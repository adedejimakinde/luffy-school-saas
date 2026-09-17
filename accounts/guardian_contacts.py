"""Recording a guardian's contact channel, and proving they hold it.

`docs/parent-access.md` D9 in one sentence: a channel a school typed is not
trusted because a school typed it. Classnode sends a code to it, and the link
does not go live until the code comes back.

Three rules from that decision live here rather than in a docstring somewhere:

**Never auto-create a guardian from an inbound contact, and this is structural
rather than a check.** There is no function in this module that takes an
arbitrary value from outside and creates anything. Creation takes an actor with
authority over a school the guardian already has a child at (`record_contact_as`);
every door that sends a code takes a `GuardianContact` *row* that already
exists. An unknown value therefore has nothing to reach: no account, no
enumeration, and no "we have sent you a code". `resolve_guardians()` is the only
entry point that accepts a raw value, it is a read, and it returns an empty
queryset rather than creating a guardian to match.

## Three doors, and the channel's own state is which one you are at

There is exactly one reason a code is ever minted, and three situations it is
minted in. They share `_mint_code()` — the rate limit, the supersede sweep, the
digest — and differ only in what state they require the channel to be in:

| door | channel must be | who may ask | counted against |
|---|---|---|---|
| `request_verification` | unverified | a school admin | their school |
| `request_sign_in_code`  | verified, not dormant | the guardian, unauthenticated | no school |
| `request_reactivation`  | verified, **dormant** | a school admin | their school |

**A code carries no purpose column, deliberately.** The channel is verified or
it is not, so at any moment at most one of these doors can have a pending code,
and the state is a better answer than a column that could disagree with it.
`_confirm_code()`'s `expect_verified` is what turns "at most one" from likely
into true: without it a verification code could be spent at the sign-in door and
open a session on a channel whose `verified_at` was still NULL.

**Codes are stored as digests, never as codes** — the pattern
`schools.models.Invitation` established, with one deliberate departure recorded
on `GuardianContactCode`: every lookup here is scoped to a contact row, because
a global lookup by hash is only safe when the secret is 32 bytes and a
six-digit code is not.

**Normalization is PR #2's, not a second copy.** A phone reaches E.164 through
`normalize_phone()`, the same function `User` goes through, so a channel and a
`User` identifier cannot come to disagree about what "the same number" means.

**A phone channel goes dormant, and dormancy is a fold rather than a sweep.**
D9 suspends a phone link after 180 days without a successful authentication. No
cron job stamps anything: `last_authenticated_at()` is the maximum `confirmed_at`
over the channel's own codes, read at the moment a code is asked for — the lazy
shape `Invitation.validate_token()` argues for, so a channel cannot sit live past
its date because a scheduled job is broken. Reactivation writes no row either;
it is a school admin causing one code to go out, and the guardian answering it
*is* the reactivation.

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
from django.db.models import Max, Q
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
from .services import (
    NotPermitted,
    activate_guardian_links,
    can_grant_memberships,
)


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


class ChannelNotLive(GuardianContactError):
    """The channel is not verified, or has been revoked. It opens nothing.

    The counterpart of `ChannelNotVerifiable`, and the two are opposites on
    purpose: that one refuses a channel that has *already* proved itself, this
    one refuses a channel that has *not yet*. Every door in this module wants
    one state or the other, and none of them wants both.
    """


class ChannelDormant(GuardianContactError):
    """A phone channel with no successful authentication inside the window.

    D9: a Nigerian number is reassigned after a total of 360 days of
    inactivity, and the new holder inherits everything sent to it. Finishing at
    180 puts a human at the school in front of that — somebody who can notice
    the person on the line is not the person on the record — while the number
    is still not even eligible for churning.

    **Not a refusal a guardian is ever shown.** `accounts.guardian_signin`
    swallows it into the same neutral answer an unknown value gets, because
    telling a caller "that number is known to us but dormant" is the
    enumeration D9 forbids. It is raised for the school-facing caller, and
    carries `last_authenticated_at` so that caller can say when.
    """

    def __init__(self, message, *, last_authenticated_at):
        super().__init__(message)
        #: When this channel last answered a code, or None if it never has.
        self.last_authenticated_at = last_authenticated_at


class ChannelNotDormant(GuardianContactError):
    """Reactivation was asked for a channel that is working.

    This is a guard rather than tidiness. Without it, `reactivate_as()` would
    be a way for any school admin to put a code on any guardian's live handset
    whenever they liked — the one send path in this module that is not already
    bounded by the channel's state, since `request_verification_as()` refuses a
    verified channel and the sign-in door is not theirs to knock on.
    """


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


# -- how long a channel may sit unused --------------------------------------


def _dormancy_window() -> timedelta:
    """Read per call, so `override_settings` is honoured — as in `throttling`."""
    return timedelta(days=settings.GUARDIAN_DORMANCY_DAYS)


def last_authenticated_at(contact):
    """When this channel last answered a code, or None if it never has.

    **A fold over the code rows, not a column somebody stamps.** Every
    successful answer already writes `confirmed_at`, so the rows *are* the
    authentication log and the maximum of them is exact — operating rule 4's
    "a balance is a fold over rows", and the same argument
    `_assert_within_send_limits()` makes for counting sends. A
    `last_authenticated_at` column would be a second copy of this with its own
    way of going wrong, and it could not be added to `GuardianContact` anyway:
    that table is append-only by trigger.

    `confirmed_at`, deliberately, and **not** `created_at`. D9 says the window
    runs from a successful *authentication*, so asking for codes and never
    answering them must not hold a dormant channel open — which is exactly what
    somebody holding a reassigned number would be doing.

    The first verification is itself a confirmed code, so the clock starts at
    `verified_at` with no special case for a channel that has only ever been
    verified.
    """
    return contact.codes.filter(status=VerificationCodeStatus.CONFIRMED).aggregate(
        last=Max("confirmed_at")
    )["last"]


def is_dormant(contact) -> bool:
    """Has this channel gone quiet for longer than D9 allows?

    **Phone only.** Email addresses are not churned and reassigned, so the
    failure this rule exists to catch cannot happen to one; applying it anyway
    would suspend email guardians for no reason and cost a school-side step to
    undo.

    **Per contact row, not per value** — and this is the one place that
    deliberately parts company with `_assert_within_send_limits()`, which counts
    per value. The two protect different things. The send limit protects a
    *handset* from traffic, and two guardians on one handset are one handset.
    Dormancy protects a *record* from going stale, and on a shared handset where
    one guardian signs in every month and the other has not in a year, the
    second record is exactly the stale one — a parent who has left the household
    while the number stayed. Folding per value would keep that record alive on
    the other parent's activity, which is the case the school-mediated step is
    for.

    A channel that has never authenticated at all is not dormant; it is
    unverified, which is a different door with its own refusal.
    """
    if contact.channel_type != ContactChannel.PHONE:
        return False
    last = last_authenticated_at(contact)
    if last is None:
        return False
    return timezone.now() - last >= _dormancy_window()


# -- minting a code ----------------------------------------------------------


def _mint_code(contact, *, school_id, ttl):
    """Put one code on this channel. Returns `(code_row, raw_code)`.

    The body every door shares, with none of the preconditions. There are three
    doors and they differ *only* in what state they require the channel to be
    in, so the rate limit, the supersede sweep and the digest live here once
    rather than three times drifting apart.

    The raw code is returned and never stored; it exists in memory for as long
    as it takes a delivery channel to put it in an SMS or an email, and after
    that only in what the guardian received. A lost code is reissued, never
    recovered.

    Outstanding codes for the same channel are spent first, so exactly one code
    is live at a time. Without that, every resend would add a live code and the
    attempt cap would bound guesses *per code* while the guessable surface grew
    with each one.

    `school_id` is the school whose budget this send counts against, and comes
    from an authority check in the `_as` wrappers rather than from a caller
    choosing one. None means no school is behind it — platform staff, or a
    guardian asking for their own sign-in code — and such a send is still
    counted against its channel.

    Raises `VerificationRateLimited` before minting anything, so a refused send
    neither writes a row nor spends the code already outstanding: a guardian
    still holding a good code does not lose it because somebody hit the limit.
    """
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
def request_verification(contact, *, school_id=None, ttl=DEFAULT_VERIFICATION_TTL):
    """Door one: prove a channel a school has just typed. Channel must be unverified.

    **Takes a row, not a value.** That is the shape of "never auto-create a
    guardian from an inbound contact": there is no argument here that could
    carry an unknown number, so there is no path from an inbound value to a
    code being sent anywhere. The same is true of the other two doors.
    """
    if contact.revoked_at is not None:
        raise ChannelNotVerifiable("A revoked channel cannot be verified.")
    if contact.verified_at is not None:
        raise ChannelNotVerifiable("This channel is already verified.")
    return _mint_code(contact, school_id=school_id, ttl=ttl)


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
def request_sign_in_code(contact, *, ttl=DEFAULT_VERIFICATION_TTL):
    """Door two: a guardian signing in. Channel must be live and not dormant.

    The only door a caller who is nobody yet can reach, and the only one with no
    school behind it — `school_id` is not a parameter, because there is nothing
    a guardian could be asked that would name one honestly. The send is still
    counted against the channel, which is the limit that protects the handset.

    Both refusals are swallowed by `accounts.guardian_signin` into the neutral
    answer an unknown value gets. They are raised rather than returned as a flag
    so that a school-facing caller — which is what `reactivate_as()` is — can
    tell the two apart and say something useful.
    """
    if not contact.is_live:
        raise ChannelNotLive("This channel is not verified, so it opens nothing.")
    if is_dormant(contact):
        raise ChannelDormant(
            "This channel has not been used inside the dormancy window.",
            last_authenticated_at=last_authenticated_at(contact),
        )
    return _mint_code(contact, school_id=None, ttl=ttl)


@transaction.atomic
def request_reactivation(contact, *, school_id=None, ttl=DEFAULT_VERIFICATION_TTL):
    """Door three: waking a dormant channel. Channel must be live and dormant.

    **Reactivation is not a stamp, and there is no row that records one.** D9
    asks for "school-side reactivation before any further code is sent", and
    that is what this is: a school admin who has checked out of band that the
    person on the number is the person on the record causes one code to go out.
    The guardian answering it writes a fresh `confirmed_at`, and *that* is the
    reactivation — the fold in `last_authenticated_at()` sees it and the channel
    is no longer dormant.

    Which means a reactivation nobody answers does not reactivate anything. That
    is the correct behaviour and it falls out of the shape rather than needing a
    rule: the clock is a record of the guardian answering, so only the guardian
    answering can move it.
    """
    if not contact.is_live:
        raise ChannelNotLive("This channel is not verified, so it opens nothing.")
    if not is_dormant(contact):
        raise ChannelNotDormant("This channel is not dormant; nothing to reactivate.")
    return _mint_code(contact, school_id=school_id, ttl=ttl)


@transaction.atomic
def request_reactivation_as(actor, contact, *, ttl=DEFAULT_VERIFICATION_TTL):
    """D9's school-side reactivation, by an admin with authority over the guardian.

    Same authority check and same budget as `request_verification_as()`, for the
    same reason: the school that was entitled to act is the school the send is
    counted against.
    """
    school_id = _require_authority_over_guardian(actor, contact.guardian.user)
    return request_reactivation(contact, school_id=school_id, ttl=ttl)


# -- answering a code --------------------------------------------------------


def _confirm_code(contact, raw_code, *, expect_verified: bool):
    """Spend `raw_code` against `contact`. Returns `(locked_contact, code)` or None.

    The body both confirm doors share. Every refusal is the same `None`: a code
    that is wrong, expired, already used, superseded by a resend, or out of
    attempts, and a channel that is revoked or in the wrong state for this door.
    The caller cannot tell which, and should not — distinguishing "wrong code"
    from "that code expired" tells whoever is guessing whether they are guessing
    in the right place at all. Same reasoning `Invitation.validate_token()`
    gives for its flat `None`.

    **`expect_verified` is which door this is, and it is load-bearing.** A code
    carries no purpose column, because the channel's own state is a better
    answer: `request_verification()` mints only for an unverified channel and
    `request_sign_in_code()` only for a verified one, so at any moment only one
    door can have a pending code. This parameter is what makes that "only one"
    true rather than merely likely — without it, a verification code minted for
    a channel that has never proved itself could be spent at the sign-in door,
    and a session would open on a channel whose `verified_at` was still NULL.

    It is checked **under the lock**, not before it, for the same reason the
    lock is taken at all.

    The wrong-code branch **counts against the code, not the channel.** A code
    out of attempts is spent the next time it is presented, right or wrong, so
    `MAX_VERIFICATION_ATTEMPTS` wrong guesses end that code and the guardian
    asks for another. Nothing here disables a guardian or a channel, on the
    reasoning `accounts.throttling` sets out at length: a lockout on a
    semi-public identifier — and a parent's phone number is on the enrolment
    form — is a weapon anyone can pick up.
    """
    if not raw_code:
        return None

    # Lock the channel, not just the code. Two codes confirming at once would
    # otherwise both find `verified_at` NULL and both try to stamp it, and the
    # second would meet the append-only trigger as an IntegrityError rather than
    # as the ordinary "already verified" it is.
    locked = GuardianContact.objects.select_for_update().filter(pk=contact.pk).first()
    if locked is None or locked.revoked_at is not None:
        return None
    if (locked.verified_at is not None) != expect_verified:
        return None

    code = (
        GuardianContactCode.objects.select_for_update()
        .filter(contact=locked, status=VerificationCodeStatus.PENDING)
        .order_by("-created_at", "-id")
        .first()
    )
    if code is None:
        return None

    if code.is_expired or code.attempts_exhausted:
        code.status = VerificationCodeStatus.SPENT
        code.save(update_fields=["status"])
        return None

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
        return None

    code.status = VerificationCodeStatus.CONFIRMED
    code.confirmed_at = timezone.now()
    code.save(update_fields=["status", "confirmed_at"])
    return locked, code


@transaction.atomic
def confirm_verification(contact, raw_code) -> bool:
    """Prove control of `contact` with `raw_code`. True if the channel is now verified.

    The `verified_at` stamp is the whole of what this adds to `_confirm_code()`,
    and it is unconditional: `expect_verified=False` has already refused a
    channel that carries one, so the `if locked.verified_at is None` this used to
    guard the write with was a branch no control run could turn red. Operating
    rule 5 — the shorter path is the one whose behaviour can be demonstrated.

    **This is where D9's link goes live.** `services.link_guardian()` grants a
    PARENT membership INVITED while the guardian has no verified channel, and
    this is the moment that changes — so the stamp and the access it unlocks are
    written in one transaction and cannot come apart. Every school the guardian
    is waiting at is promoted at once, because one person has one channel.

    **There is no matching demotion here, and the gap is deliberate rather than
    forgotten.** D11 revokes a channel when a new one is entered and says the
    link is suspended until the new one verifies; nothing stamps `revoked_at`
    yet, so there is no event to hang a demotion on. Building the demotion
    before the revocation that triggers it would be a guard with no path to it —
    which is the shape operating rule 5 spends its time removing. When D11's
    change flow lands, the revocation is where the demotion goes.
    """
    result = _confirm_code(contact, raw_code, expect_verified=False)
    if result is None:
        return False

    locked, code = result
    locked.verified_at = code.confirmed_at
    locked.save(update_fields=["verified_at"])
    contact.verified_at = locked.verified_at
    activate_guardian_links(locked.guardian.user)
    return True


@transaction.atomic
def confirm_sign_in_code(contact, raw_code):
    """Prove control of a live channel again. Returns the confirmed code, or None.

    The code row rather than a bare `True`, because it is the handset proof: it
    carries `confirmed_at`, which is the fold `last_authenticated_at()` reads,
    and it is what the sign-in audit points at to say *which* answered code
    opened a session.

    Writes no stamp. The channel was already verified — that is this door's
    precondition — and `verified_at` does not move twice; the append-only
    trigger would refuse it if this tried.
    """
    result = _confirm_code(contact, raw_code, expect_verified=True)
    if result is None:
        return None
    _, code = result
    return code


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
