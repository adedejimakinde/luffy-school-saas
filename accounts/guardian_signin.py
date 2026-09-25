"""Exchanging a handset and six digits for a session.

The guardian half of `accounts/signin.py`. That module trades an identifier and
a password; D3 removes the password for guardians — "passwords for infrequent
use become forgotten passwords, which become support load on a school
secretary" — so what is traded here is control of a verified contact channel,
proved by a code sent to it.

Almost everything this module needs already exists. `guardian_contacts` mints
and spends the codes and owns the three doors; `throttling` counts failures in
Postgres and explains at length why it counts rather than locks;
`signin.sign_in()` fixes the order those two are used in. What is left is the
part neither of them can do from where they sit: deciding what a caller is
told, and making sure that answer is the same one however the attempt failed.

## One refusal, and here it is not only a convention

`signin.py` already answers "no account", "wrong password", "deactivated" and
"two accounts matched" with one sentence, because splitting them turns a login
route into an account-existence oracle. The same rule holds here and carries
more weight, because D9 states it as a requirement rather than leaving it to
be inferred: *no account creation, no enumeration, and no "we have sent you a
code" for an unknown value.*

So a value nobody holds, a channel that was never verified
(`ChannelNotLive`), a channel that has gone dormant (`ChannelDormant`), a wrong
code, an expired code, a code already spent, and a code out of attempts all
produce the same answer. The dormant case is the one a careless implementation
leaks, and it leaks for a sympathetic reason — a school-facing caller genuinely
needs to tell it apart, which is why `request_sign_in_code()` raises it with
`last_authenticated_at` attached instead of returning a flag. `ChannelDormant`'s
own docstring names this module as the thing that swallows it. This is that.

**What the request door says is conditional, and deliberately.** D9 forbids
"we have sent you a code" for an unknown value; it does not ask for a denial,
which would be the same oracle wearing the other face. `CODE_REQUESTED` claims
nothing about whether anything was sent — it states what follows *if* the value
is on a guardian record — so the sentence is true whoever types it.

## The throttle, and why it is a third scope rather than the identifier one

`SignInScope` counts against IDENTIFIER and ADDRESS. ADDRESS is reused
unchanged: one machine working through six-digit codes across many channels is
exactly the credential-stuffing shape that limit exists to see, and it does not
care which door the guesses arrive at.

IDENTIFIER is **not** reused, and the reason is a lockout risk rather than
tidiness. `key_for()` normalises through `canonical_username()`, so a phone
number typed at this door and the same number typed at the password door would
share a bucket — and a parent's number is on the enrolment form, which is the
semi-public identifier `throttling.py` refuses to let anyone weaponise. Folding
them would mean anyone who could read a number off a form could close a
teacher's password door by guessing codes at it, and close a parent's code door
by guessing passwords. Two doors, two buckets.

CHANNEL is counted against **the value as typed**, not against the contact row
it resolves to, and that is what keeps the throttle outside the one-refusal
rule without breaking it. A key that existed only for values which resolve
would make a 429 mean "this number is known here" — the oracle the neutral
answer exists to prevent. Counted as typed, it says only that this caller has
been getting things wrong.

## Two steps, and a third case between them

Step one asks for a code. Step two answers it and opens a session.

The case between the two is the shared handset, which is not an edge:
`GuardianContact.value` carries no unique constraint precisely because one
household has one phone and two parents, and `resolve_guardians()` says in so
many words that callers must be built for more than one answer.

The choice cannot be offered at step one — listing who holds a number, to
anybody who types it, is the enumeration this whole module is arranged around.
It can only be offered **after** control of the handset is proved, which is
what makes it a third case rather than a parameter on the first. So a correct
code against a shared value returns the chooser and opens no session; the pick
comes back to the same door, carried across by the session cookie the browser
already has. There is no new token type, and the thing carried is a spent code
row rather than a credential.

**The pick is self-asserted, and that is not a hole — it is the shape of the
credential.** The handset is what D3 makes the credential, and it belongs to
both parents equally. Nothing at sign-in can tell which of them is holding it,
so nothing here pretends to. What the design owes instead is a record of the
choice, which is `GuardianSignIn` — who was offered, who was picked, and which
answered code proved the handset.
"""

from django.contrib.auth import login as start_session

from . import guardian_contacts, signin, throttling
from .models import (
    ContactChannel,
    GuardianAccount,
    GuardianContact,
    GuardianContactCode,
    GuardianSignIn,
    SignInScope,
)

#: What every failed guardian sign-in says, whichever failure it was. Names no
#: channel, no guardian and no reason: see the module docstring.
REFUSED = (
    "That code is not one we are waiting for. Ask for a new one, or call the "
    "school if this keeps happening."
)

#: What the request door says, to everybody. Conditional on purpose — it makes
#: no claim that anything was sent, so it is equally true for a number on a
#: guardian record and one that is not.
CODE_REQUESTED = (
    "If that number is on a guardian record, a code has been sent to it. It "
    "lasts a few minutes."
)

BAD_CODE = "bad_code"

#: The session key holding a proved handset that has not yet been claimed. Only
#: ever set on the shared-handset path, and removed the moment it is spent.
PENDING_PICK = "guardian_pending_pick"

#: Set on every session this module opens, and read by `SchoolAccessMiddleware`
#: to hold it to what a six-digit code is allowed to reach. It carries the
#: `GuardianSignIn` row id rather than `True`, so a request that turns out to
#: have escalated can be traced to the handset proof that opened it without a
#: second lookup deciding which sign-in it was.
#:
#: **Written after `start_session()`, never before.** Django's `login()` cycles
#: the session key, and flushes outright when a different user was signed in
#: there — a marker written first would be gone exactly when it matters, on the
#: session that had somebody else in it a moment ago.
OPENED_BY_CODE = "guardian_sign_in_id"


class GuardianSignInError(Exception):
    """Guardian sign-in was refused.

    One base class for the module, as `SignInError` is for the password half,
    so a caller catches every refusal rather than the half it remembered.
    """


class BadCode(GuardianSignInError):
    """The value and code did not open anything.

    Carries no detail about which part was wrong, because there is none to
    carry: the caller is told `REFUSED` and nothing else.
    """


class TooManyAttempts(GuardianSignInError):
    """The throttle is closed for this channel or this address."""

    def __init__(self, retry_after: int):
        super().__init__(signin.THROTTLED)
        #: Whole seconds until another attempt is worth making.
        self.retry_after = retry_after


class MustChooseGuardian(GuardianSignInError):
    """The handset is proved and more than one guardian is behind it.

    Not a failure, and it is an exception only because it is the one outcome
    that is neither "refused" nor "signed in". The route renders it as a 200
    with a chooser; nothing is counted against the throttle, because nothing was
    got wrong.
    """

    def __init__(self, offered):
        super().__init__("Choose which guardian to continue as.")
        #: `GuardianAccount`s, in a stable order. Opaque `public_id` and the
        #: person's name — never the channel value, which the caller typed and
        #: which says nothing about who else is behind it.
        self.offered = list(offered)


def _wait_before_retrying(value: str, address: str):
    """Seconds this attempt must wait, or None if it may go ahead.

    The longer of the two windows, so a client that waits exactly as long as it
    was told is not refused a second time by the other limit —
    `signin.wait_before_retrying()`'s reasoning, for this door's two scopes.
    """
    open_windows = [
        wait
        for wait in (
            throttling.blocked_for(SignInScope.CHANNEL, value),
            throttling.blocked_for(SignInScope.ADDRESS, address),
        )
        if wait is not None
    ]
    return max(open_windows) if open_windows else None


def _note_failure(value: str, address: str) -> None:
    """Count one wrong answer against both keys."""
    throttling.record_failure(SignInScope.CHANNEL, value)
    throttling.record_failure(SignInScope.ADDRESS, address)


def _note_success(value: str) -> None:
    """Forgive the channel's failures, and deliberately not the address's.

    `throttling.clear()` explains the asymmetry: one correct answer says this
    handset is in the right hands, and says nothing at all about the machine
    that has been guessing at forty other numbers through the same window.
    """
    throttling.clear(SignInScope.CHANNEL, value)


def _contacts_typed(value: str):
    """The unrevoked contact rows whose value **is** what was typed, oldest first.

    **The row typed, never "every row of the guardians behind it"** (#111). A
    guardian may hold a live email and a live phone, and a code goes to the one
    they typed: through the other, a guardian typing their phone would be sent
    the code by email and wait for an SMS that never comes, and a dormant phone
    would open the door through the email, which is never dormant — D9's
    reactivation step skipped without anyone deciding to skip it. Matching the
    typed value is what makes both impossible rather than unlikely.

    Normalised the way every contact is stored (`read_contact()`), so one
    number typed two ways is one row. Ordered so that a shared handset produces
    the same offer twice running.
    """
    read = guardian_contacts.read_contact(value)
    if read is None:
        return []
    channel_type, normalized = read
    return list(
        GuardianContact.objects.select_related("guardian")
        .filter(channel_type=channel_type, value=normalized, revoked_at__isnull=True)
        .order_by("created_at", "id")
    )


def _live_contacts_for(value: str):
    """The verified rows among `_contacts_typed(value)`: the ones a sign-in code may be minted for."""
    return [contact for contact in _contacts_typed(value) if contact.verified_at is not None]


def _eligible_for_a_code(contacts):
    """Those a sign-in code may actually be minted for.

    Dormancy is per row and not per value — `is_dormant()` argues that at
    length — so on a shared handset where one parent signs in monthly and the
    other has not in a year, only the first is eligible. The second needs the
    school-mediated reactivation step D9 puts in front of a reassigned number,
    and gets it by talking to the school rather than by being told anything
    here.
    """
    return [
        contact
        for contact in contacts
        if contact.channel_type != ContactChannel.PHONE
        or not guardian_contacts.is_dormant(contact)
    ]


def request_code(request, value: str) -> None:
    """Send a sign-in code to `value`, if there is anything there to send to.

    Returns nothing, raises only `TooManyAttempts`, and the caller says
    `CODE_REQUESTED` either way. Every other outcome — no such value, never
    verified, dormant, revoked — is indistinguishable from success by design.

    Order is `signin.sign_in()`'s, for its reasons:

    1. **The throttle is asked first**, before any lookup or send. A closed
       window has to be closed to everybody, including a caller whose next
       request happens to be for a real channel.
    2. A value that resolves to nothing is **not** counted as a failure. It is
       not a wrong guess at a code; it is a typo or a stranger, and counting it
       would make the window itself say whether the value was real. The send
       limits in `guardian_contacts` are what bound this door's traffic, and
       they are already per value and per school.

    On a shared handset this mints **one** code, against the oldest eligible
    row. Two sends to one phone would burn two metered messages and two rate
    limit slots to deliver the same six digits to the same person, and
    `sign_in_with_code()` is built to spend a code against whichever row is
    holding it.
    """
    address = throttling.client_address(request)
    wait = _wait_before_retrying(value, address)
    if wait is not None:
        raise TooManyAttempts(wait)

    eligible = _eligible_for_a_code(_live_contacts_for(value))
    if not eligible:
        return None

    try:
        guardian_contacts.request_sign_in_code(eligible[0])
    except guardian_contacts.GuardianContactError:
        # Swallowed whole, and this is the module's whole subject: a channel
        # that went dormant between the filter above and the mint, one out of
        # sends, one revoked a moment ago. Every one of them is a fact about
        # who holds this number, and the caller is told none of them.
        return None
    return None


def _spend(contacts, raw_code):
    """The code row `raw_code` answers, or None if it answers none of `contacts`.

    Tried in order rather than resolved up front, because the caller does not
    know which row holds the pending code and must not be told. A row with no
    pending code costs nothing and counts nothing — `_confirm_code()` returns
    before it increments anything — so this cannot spend one channel's attempt
    budget guessing at another's.

    **Every code a guardian can be sent is answered here** (`docs/messaging.md`
    D8): a sign-in code, and the three a school sends. A channel check answers
    an unverified row, through `confirm_verification_code()`, which stamps it
    verified in the same transaction, so no session ever opens on a channel
    whose `verified_at` is NULL. A reactivation code answers a dormant row: none
    other can be pending there, because `request_sign_in_code()` refuses a
    dormant channel, and answering it is what D9 calls reactivation. A school's
    code answers a live row and turns that school's links live.

    The code row alone, not the pair it was found by: it carries `contact`
    itself, and a second name for the same thing is a second thing to keep in
    step.
    """
    for contact in contacts:
        if contact.verified_at is None:
            code = guardian_contacts.confirm_verification_code(contact, raw_code)
        else:
            code = guardian_contacts.confirm_sign_in_code(contact, raw_code)
        if code is not None:
            return code
    return None



def sign_in_with_code(request, value: str, raw_code: str, *, guardian_public_id=None):
    """Answer a code and open a session. Returns the `User` signed in.

    Raises `TooManyAttempts` when the window is closed, `BadCode` for every
    other failure, and `MustChooseGuardian` when the handset is proved and more
    than one guardian is behind it.

    `guardian_public_id` is the pick, and it is checked against the offer rather
    than trusted: a caller naming a guardian who is not behind this handset gets
    the ordinary refusal, not a different one. D9's opaque identifier is what is
    passed, never the row pk and never the channel value.

    `start_session()` is Django's `login()`, which cycles the session key — so a
    key fixed by an attacker beforehand is not the one the guardian ends up
    holding — and rotates the CSRF token with it. It runs **after** the pick is
    resolved, so a session never exists as the wrong guardian even briefly.
    """
    address = throttling.client_address(request)
    wait = _wait_before_retrying(value, address)
    if wait is not None:
        raise TooManyAttempts(wait)

    # A code on the request means this is the first call, always — even when a
    # pick is parked on the session. Reading the parked one first would let an
    # abandoned shared-handset attempt swallow the next genuine code for the
    # same number, which is the ordinary case rather than a rare one: the
    # guardian who gives up half way through is the same guardian who tries
    # again. No code and something parked is the second call.
    pending = request.session.get(PENDING_PICK)
    if pending is not None and not raw_code:
        return _finish_pick(request, value, pending, guardian_public_id)
    if raw_code:
        request.session.pop(PENDING_PICK, None)

    code = _spend(_contacts_typed(value), raw_code)
    if code is None:
        _note_failure(value, address)
        raise BadCode(REFUSED)

    _note_success(value)
    # Asked **after** the spend, and that is the point: answering a channel
    # check makes a row verified, and answering a reactivation code makes a
    # dormant row current — `is_dormant()` is a fold over the `confirmed_at`
    # the spend just wrote. Who is behind this handset now is the offer. A
    # dormant guardian on a shared handset whose code was not answered stays out
    # of it, as D9 requires.
    #
    # **Each guardian once, and by construction rather than by folding** (#111).
    # These rows share one typed value, and a guardian holds at most one live
    # row of a type (`one_live_contact_per_guardian_per_channel`), so a guardian
    # holding a phone and an email is one offer: the email was never in this
    # list. Two offers means two people on one handset, which is the only case
    # the chooser is for.
    offered = [contact.guardian for contact in _eligible_for_a_code(_live_contacts_for(value))]
    return _open(request, value, offered, code, guardian_public_id)


def _open(request, value, offered, code, guardian_public_id):
    """Open the session, or hold the proof and ask who is holding the phone."""
    picked = _pick(offered, guardian_public_id)
    if picked is None:
        # The proof is parked on the session rather than handed back, so the
        # second call carries nothing a caller could have invented. The code is
        # already spent, so this is not a credential — it is a receipt for one.
        request.session[PENDING_PICK] = {
            "code_id": code.pk,
            "offered": [str(g.public_id) for g in offered],
            "value": value,
        }
        raise MustChooseGuardian(offered)

    request.session.pop(PENDING_PICK, None)
    return _start(request, offered, picked, code)


def _finish_pick(request, value, pending, guardian_public_id):
    """The second half of a shared-handset sign-in. No code is spent here.

    The handset was proved on the first call and the code row is spent; what is
    left is the choice. It is refused with the same `BadCode` as everything
    else if the pick is not one of the guardians that call offered, so a caller
    poking at public_ids learns nothing from the difference.
    """
    if value != pending.get("value"):
        raise BadCode(REFUSED)

    offered = list(
        GuardianAccount.objects.filter(public_id__in=pending.get("offered", []))
    )
    picked = _pick(offered, guardian_public_id)
    if picked is None:
        raise BadCode(REFUSED)

    code = GuardianContactCode.objects.filter(pk=pending.get("code_id")).first()
    if code is None:
        raise BadCode(REFUSED)

    request.session.pop(PENDING_PICK, None)
    return _start(request, offered, picked, code)


def _start(request, offered, picked, code):
    """Record the choice, then open the session. Never the other way round.

    `record()` returns None when this code has already opened a session —
    `one_session_per_answered_code` refusing a replay — and that has to be found
    out *before* `start_session()`, or the replay would be signed in and the row
    saying who they are would be the one written for somebody else's pick.

    The refusal is the module's ordinary one, so a replayed pick is
    indistinguishable from a wrong code.
    """
    row = GuardianSignIn.record(offered=offered, picked=picked, proof=code)
    if row is None:
        raise BadCode(REFUSED)

    start_session(request, picked.user)
    request.session[OPENED_BY_CODE] = row.pk
    return picked.user


def _pick(offered, guardian_public_id):
    """Which guardian this session is for, or None if that is still open.

    One offer and no pick resolves itself: there is nothing to choose between,
    and asking would be a round trip to tell somebody their own name. A pick
    that names somebody outside the offer returns None rather than raising, so
    the caller above answers it with the module's one refusal.
    """
    if guardian_public_id is None:
        return offered[0] if len(offered) == 1 else None
    for guardian in offered:
        if str(guardian.public_id) == str(guardian_public_id):
            return guardian
    return None
