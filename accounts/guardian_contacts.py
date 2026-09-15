"""Recording a guardian's contact channel, and proving they hold it.

`docs/parent-access.md` D9 in one sentence: a channel a school typed is not
trusted because a school typed it. Classnode sends a code to it, and the link
does not go live until the code comes back.

Three rules from that decision live here rather than in a docstring somewhere:

**Never auto-create a guardian from an inbound contact, and this is structural
rather than a check.** There is no function in this module that takes an
arbitrary value from outside and creates anything. Creation takes an actor with
authority over a school the guardian already has a child at (`record_contact_as`);
verification takes a `GuardianContact` *row* that already exists
(`request_verification`, `confirm_verification`). An unknown value therefore has
nothing to reach: no account, no enumeration, and no "we have sent you a code".
`resolve_guardians()` is the only entry point that accepts a raw value, it is a
read, and it returns an empty queryset rather than creating a guardian to match.

**Codes are stored as digests, never as codes** — the pattern
`schools.models.Invitation` established, with one deliberate departure recorded
on `GuardianContactCode`: every lookup here is scoped to a contact row, because
a global lookup by hash is only safe when the secret is 32 bytes and a
six-digit code is not.

**Normalization is PR #2's, not a second copy.** A phone reaches E.164 through
`normalize_phone()`, the same function `User` goes through, so a channel and a
`User` identifier cannot come to disagree about what "the same number" means.

**A code costs money and reaches a real handset, so sends are bounded** — per
channel and per school, in `_assert_within_send_limits()`. This is the half of
the guessing bound that `MAX_VERIFICATION_ATTEMPTS` cannot supply on its own:
without it, an attacker out of attempts simply asks for another code. It is
also the whole of the cost bound, and answers the part of OPEN-3 that names
"rate limiting per number and per school".

## Why hashing is defined here and not imported

`schools.models.hash_token()` is the same three lines, and importing it would be
the obvious move. It would also invert this project's dependency direction:
`schools` depends on `accounts` (a `School`'s invitations point at
`accounts.Membership`), so `accounts` importing `schools` at module scope is a
cycle. `accounts.throttling` already made the same call for the same reason and
recorded it on `SignInAttempts`. The duplication is three lines of stdlib; the
cycle would be structural.
"""

import hashlib
import math
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .identifiers import normalize_email, try_normalize_phone
from .models import (
    DEFAULT_VERIFICATION_TTL,
    LIVE_STATUSES,
    MAX_VERIFICATION_ATTEMPTS,
    VERIFICATION_CODE_DIGITS,
    ContactChannel,
    GuardianAccount,
    GuardianContact,
    GuardianContactCode,
    Guardianship,
    VerificationCodeStatus,
)
from .services import NotPermitted, can_grant_memberships


class GuardianContactError(Exception):
    """Something about a contact channel was refused, with a reason to read."""


class ChannelAlreadyRecorded(GuardianContactError):
    """This guardian already has a live channel.

    Replacing one is D11's change flow — revoke the old binding, verify the new
    — and that is the next slice, not this one. Refused here rather than
    silently creating a second live channel, which would leave two rows
    disagreeing about how to reach one person. `one_live_contact_per_guardian`
    refuses the same thing at the database, and the two agree by construction:
    this asks `live_contact()`, the constraint indexes `revoked_at IS NULL`.
    """


class ChannelNotVerifiable(GuardianContactError):
    """The channel is revoked, or already verified. Neither takes a new code."""


class VerificationRateLimited(GuardianContactError):
    """Too many codes have gone out already. Carries `retry_after` in seconds.

    **Counted, not locked**, on exactly the reasoning `accounts.throttling`
    sets out for sign-in: reaching the limit closes the window for a while and
    never disables a channel, a guardian or a school. A lockout on a resource
    anyone can name — and a parent's phone number is on the enrolment form — is
    a weapon the attacker picks up rather than a wall they hit.
    """

    def __init__(self, message, *, retry_after):
        super().__init__(message)
        self.retry_after = retry_after


def hash_code(raw_code: str) -> str:
    """The only representation of a code this system is allowed to keep."""
    return hashlib.sha256(raw_code.encode("utf-8")).hexdigest()


def generate_code() -> str:
    """A fresh code, zero-padded to its full width.

    `secrets.randbelow` rather than `random`, and the whole range rather than a
    "no leading zero" range: trimming 0-prefixed codes for looks would cut the
    space by a tenth and make the first digit predictable.
    """
    return str(secrets.randbelow(10**VERIFICATION_CODE_DIGITS)).zfill(
        VERIFICATION_CODE_DIGITS
    )


# -- the guardian record ----------------------------------------------------


def guardian_account_for(user) -> GuardianAccount:
    """This person's guardian record, created if this is their first time.

    Idempotent, and that is what makes D10's "two entry points, one record"
    true: the standalone admin action and the admission form both land here, so
    a guardian entered at admission and the same guardian added mid-session are
    one row with one `public_id` and one verification story, not two.

    Not authority-gated itself — `record_contact_as()` is, ahead of calling
    this, so no unauthorized caller reaches it with a user to create.
    """
    account, _ = GuardianAccount.objects.get_or_create(user=user)
    return account


def _require_authority_over_guardian(actor, guardian_user):
    """An admin may act on a guardian they share a live child with.

    Authority is per school (`can_grant_memberships`), and a guardian is not.
    The bridge is the child: an admin at St Mary's may record a channel for a
    St Mary's parent, and has no business touching a guardian whose children
    are all at Grace Academy. Only platform staff act across schools.

    A guardian with no live child anywhere is reachable by nobody but platform
    staff, which is the correct answer rather than an oversight: D10's action is
    "create guardian, attach to child", so a guardian with no link is not yet a
    guardian anyone is responsible for.

    **Returns the school id the authority was found at**, or None for platform
    staff, who act across schools and are behind no single one. That is what
    the per-school send limit counts against, so the answer to "may you?" and
    the answer to "on whose budget?" come from one pass rather than two that
    could disagree. Where a guardian has children at several schools the actor
    has authority at, the first match wins — they are equally entitled, and the
    limit is a bound on a school's own sending rather than an allocation
    anybody is owed.
    """
    # Short-circuited ahead of the loop, not inside it. `can_grant_memberships()`
    # says yes to platform staff at any school, but the loop only ever asks it
    # about schools the guardian already has a live child at — so for a guardian
    # with no live child the loop does not run, and platform staff would have
    # been refused by a function whose docstring says they are not. They are
    # behind no school, so they count against no school's send budget either.
    if getattr(actor, "is_platform_staff", False):
        return None

    schools_with_children = (
        Guardianship.objects.filter(
            guardian=guardian_user, student__status__in=LIVE_STATUSES
        )
        .values_list("student__school_id", flat=True)
        .distinct()
    )
    for school_id in schools_with_children:
        if can_grant_memberships(actor, school_id):
            return school_id
    raise NotPermitted(
        f"{actor} has no authority over a school where {guardian_user} is a guardian."
    )


@transaction.atomic
def record_contact(guardian_account, channel_type, value, *, created_by):
    """Write down a channel for a guardian. Unverified — it opens nothing yet.

    The value is normalized by `GuardianContact.clean()` before it is stored, so
    what lands in the column is E.164 or a lowercased address, never what was
    typed.
    """
    if guardian_account.live_contact() is not None:
        raise ChannelAlreadyRecorded(
            f"{guardian_account.user} already has a live contact channel."
        )
    contact = GuardianContact(
        guardian=guardian_account,
        channel_type=channel_type,
        value=value,
        created_by=created_by,
    )
    contact.full_clean(validate_constraints=False)
    contact.save()
    return contact


@transaction.atomic
def record_contact_as(actor, guardian_user, channel_type, value):
    """D10's admin action: the only way a contact channel comes into existence.

    Authority is checked **before** the guardian record is created, so a refused
    call leaves nothing behind — the same ordering `services.link_guardian()`
    uses for the same reason.
    """
    _require_authority_over_guardian(actor, guardian_user)
    account = guardian_account_for(guardian_user)
    return record_contact(account, channel_type, value, created_by=actor)


# -- how many codes may go out -----------------------------------------------


def _send_window() -> timedelta:
    """Read per call, so `override_settings` is honoured — as in `throttling`."""
    return timedelta(seconds=settings.VERIFICATION_SEND_WINDOW)


def _seconds_until_a_slot_frees(sends) -> int:
    """When the oldest send in the window falls out of it."""
    oldest = sends.order_by("created_at").values_list("created_at", flat=True).first()
    if oldest is None:
        return 0
    remaining = (oldest + _send_window() - timezone.now()).total_seconds()
    return max(1, math.ceil(remaining))


def _assert_within_send_limits(contact, school_id):
    """Refuse a send that would be one too many, per channel and per school.

    **The count is a fold over the code rows, not a counter somebody
    increments.** Every send already writes a `GuardianContactCode`, so the rows
    *are* the send log and counting them is exact — operating rule 4's
    "a balance is a fold over rows". `accounts.throttling` folds into a counter
    row instead, and for good reason there: it counts failed sign-ins, which
    would otherwise be an unbounded table written by anyone who can reach the
    login box. Codes are minted only by authorised callers and are already
    bounded by this very limit, so the row-per-send is affordable and buys an
    exact sliding window with no boundary burst.

    **Per channel, the count is keyed on the value, not the contact row.** The
    thing being protected is the handset, and a household sharing one is the
    ordinary case — two guardians hold two contact rows carrying one number, so
    counting per row would hand an attacker two windows for one phone. This is
    `throttling.key_for()`'s reasoning ("counting them as three would give an
    attacker three windows for one target") applied to the same underlying fact.

    The cost is that two guardians on one handset share a budget, so a run of
    sends to one can make the other wait. That is the trade `client_address()`
    already names: a wait for both rather than a free pass for one.
    """
    since = timezone.now() - _send_window()

    to_this_channel = GuardianContactCode.objects.filter(
        contact__channel_type=contact.channel_type,
        contact__value=contact.value,
        created_at__gte=since,
    )
    if to_this_channel.count() >= settings.MAX_VERIFICATION_SENDS_PER_CHANNEL:
        raise VerificationRateLimited(
            "Too many verification codes have been sent to this channel.",
            retry_after=_seconds_until_a_slot_frees(to_this_channel),
        )

    if school_id is None:
        return
    from_this_school = GuardianContactCode.objects.filter(
        requested_by_school_id=school_id, created_at__gte=since
    )
    if from_this_school.count() >= settings.MAX_VERIFICATION_SENDS_PER_SCHOOL:
        raise VerificationRateLimited(
            "This school has sent too many verification codes.",
            retry_after=_seconds_until_a_slot_frees(from_this_school),
        )


# -- verification -----------------------------------------------------------


@transaction.atomic
def request_verification(contact, *, school_id=None, ttl=DEFAULT_VERIFICATION_TTL):
    """Mint a code for an existing channel. Returns `(code_row, raw_code)`.

    The raw code is returned and never stored; it exists in memory for as long
    as it takes a delivery channel to put it in an SMS or an email, and after
    that only in what the guardian received. A lost code is reissued, never
    recovered.

    **Takes a row, not a value.** That is the shape of "never auto-create a
    guardian from an inbound contact": there is no argument here that could
    carry an unknown number, so there is no path from an inbound value to a
    code being sent anywhere.

    Outstanding codes for the same channel are spent first, so exactly one code
    is live at a time. Without that, every resend would add a live code and the
    attempt cap would bound guesses *per code* while the guessable surface grew
    with each one.

    `school_id` is the school whose budget this send counts against, and comes
    from the authority check in `request_verification_as()` rather than from a
    caller choosing one. None means no school is behind it — platform staff, or
    a guardian asking for their own resend once sign-in exists — and such a send
    is still counted against its channel.

    Raises `VerificationRateLimited` before minting anything, so a refused send
    neither writes a row nor spends the code already outstanding: a guardian
    still holding a good code does not lose it because somebody hit the limit.
    """
    if contact.revoked_at is not None:
        raise ChannelNotVerifiable("A revoked channel cannot be verified.")
    if contact.verified_at is not None:
        raise ChannelNotVerifiable("This channel is already verified.")

    _assert_within_send_limits(contact, school_id)

    GuardianContactCode.objects.filter(
        contact=contact, status=VerificationCodeStatus.PENDING
    ).update(status=VerificationCodeStatus.SPENT)

    raw_code = generate_code()
    code = GuardianContactCode.objects.create(
        contact=contact,
        code_hash=hash_code(raw_code),
        requested_by_school_id=school_id,
        expires_at=timezone.now() + ttl,
    )
    return code, raw_code


@transaction.atomic
def request_verification_as(actor, contact, *, ttl=DEFAULT_VERIFICATION_TTL):
    """D10's send, by a school admin: the authorised way a code goes out.

    The school the authority was found at is what the send is counted against,
    so "may you send this?" and "whose sending rate is this?" are one question
    asked once. A caller cannot name a different school than the one that
    entitled them, because they never name one at all.
    """
    school_id = _require_authority_over_guardian(actor, contact.guardian.user)
    return request_verification(contact, school_id=school_id, ttl=ttl)


@transaction.atomic
def confirm_verification(contact, raw_code) -> bool:
    """Prove control of `contact` with `raw_code`. True if the channel is now verified.

    Returns a flat `False` for a code that is wrong, expired, already used,
    superseded by a resend, or out of attempts — and for a channel that is
    revoked. The caller cannot tell which, and should not: distinguishing "wrong
    code" from "that code expired" tells whoever is guessing whether they are
    guessing in the right place at all. Same reasoning
    `Invitation.validate_token()` gives for its flat `None`.

    The wrong-code branch **counts against the code, not the channel.** A code
    out of attempts is spent the next time it is presented, right or wrong, so
    `MAX_VERIFICATION_ATTEMPTS` wrong guesses end that code and the guardian
    asks for another. Nothing here disables a guardian or a channel, on the
    reasoning `accounts.throttling` sets out at length: a lockout on a
    semi-public identifier — and a parent's phone number is on the enrolment
    form — is a weapon anyone can pick up.
    """
    if not raw_code:
        return False

    # Lock the channel, not just the code. Two codes confirming at once would
    # otherwise both find `verified_at` NULL and both try to stamp it, and the
    # second would meet the append-only trigger as an IntegrityError rather than
    # as the ordinary "already verified" it is.
    locked = (
        GuardianContact.objects.select_for_update().filter(pk=contact.pk).first()
    )
    if locked is None or locked.revoked_at is not None:
        return False

    code = (
        GuardianContactCode.objects.select_for_update()
        .filter(contact=locked, status=VerificationCodeStatus.PENDING)
        .order_by("-created_at", "-id")
        .first()
    )
    if code is None:
        return False

    if code.is_expired or code.attempts_exhausted:
        code.status = VerificationCodeStatus.SPENT
        code.save(update_fields=["status"])
        return False

    # `compare_digest` on the hexdigests. Both are already public-length values
    # of a secret, but a timing signal on the comparison is free to remove and
    # this is the one comparison in the flow an attacker can drive.
    if not secrets.compare_digest(code.code_hash, hash_code(raw_code)):
        # Count the guess and nothing else. Spending the code *here* as well,
        # once the count reached the cap, put the "this code is dead" decision
        # in two places and made the one above unreachable — a guard no control
        # run could turn red, which is operating rule 5's whole subject. The
        # count is the record; the branch above is the single place that reads
        # it.
        code.attempts += 1
        code.save(update_fields=["attempts"])
        return False

    now = timezone.now()
    code.status = VerificationCodeStatus.CONFIRMED
    code.confirmed_at = now
    code.save(update_fields=["status", "confirmed_at"])

    if locked.verified_at is None:
        locked.verified_at = now
        locked.save(update_fields=["verified_at"])
    contact.verified_at = locked.verified_at
    return True


# -- reading a typed value back ---------------------------------------------


def resolve_guardians(value):
    """Every guardian `value` could reach, as one query. Never creates anything.

    The channel-side counterpart to `User.objects.matching_identifier()`, and
    separate code for a reason worth stating: `matching_identifier()` resolves
    the `username`, `email` and `phone` columns **on `User`**, and cannot see
    this table. What the two must share is the *normalization* — both run a
    typed value through `try_normalize_phone()` and `normalize_email()` — so
    that one number typed two ways lands on one guardian here exactly as it
    lands on one account there.

    **May return more than one guardian, and callers must be built for it.**
    `value` carries no unique constraint precisely so a household sharing one
    handset can have two guardians behind one number. An empty result is the
    ordinary answer for a value no school has typed, and it is where "no
    account, no enumeration" comes from: there is nothing further to do with it.

    Only live channels — verified and unrevoked. An unverified channel has not
    yet proved anything, and a revoked one has been replaced.
    """
    value = (value or "").strip()
    if not value:
        return GuardianAccount.objects.none()

    candidates = set()
    phone = try_normalize_phone(value)
    if phone:
        candidates.add((ContactChannel.PHONE, phone))
    # `normalize_email()` lowercases; it does not decide whether something *is*
    # an address, and would hand back "08031234567" unchanged. Asking for the
    # "@" keeps a phone number from also being looked up as an email — harmless
    # today, since no such row exists, but the kind of loose match that finds
    # something the moment a school types an odd value into the wrong field.
    if "@" in value:
        email = normalize_email(value)
        if email:
            candidates.add((ContactChannel.EMAIL, email))
    if not candidates:
        return GuardianAccount.objects.none()

    query = Q()
    for channel_type, normalized in candidates:
        query |= Q(contacts__channel_type=channel_type, contacts__value=normalized)

    return GuardianAccount.objects.filter(
        query, contacts__verified_at__isnull=False, contacts__revoked_at__isnull=True
    ).distinct()
