"""Forgot password: an emailed link that sets a new one. `docs/sign-in-page.md`, "Forgot password".

Staff sign in with a password (`accounts/signin.py`), and until this existed a
forgotten one was a call to an administrator, who could only invite the person
again. A parent signs in with a code and needs none of this, but may hold a
password too, and asks here the same way.

Two steps, each on the host the person is already on:

1. **`request_reset()`**: somebody types an email address or a phone number.
   If it is an account that may be reset on this host, a link is emailed to the
   account's own address. Whatever happened, the page says one sentence.
2. **`complete()`**: the link opens "Choose a new password". The password is
   held to `AUTH_PASSWORD_VALIDATORS`, every session the person has is signed
   out, and they are told by email that it changed.

## One answer, whatever was typed

`signin.py`'s rule, for its reason. No such account, a deactivated one, one
that is not a member of the school whose host this is, one with no email
address, a throttled request and a request that worked all get the **same
status and the same words** (`SENT`): otherwise this page would say, one guess
at a time and with no credential, who has an account and where. The throttle is
inside that rule here, unlike sign-in's 429: a 429 would be harmless (it is
counted against what was typed, real or not), but the page has no use for it,
and "the same sentence, always" is a rule nobody has to reason about.

The email is sent **off the request** (`messaging.codes`'s reason): a provider
call takes hundreds of milliseconds and happens only for a real account, so on
the request it would make response time say what the words do not.

## The link

- **Random, and kept only as a hash.** 32 bytes from `secrets`, SHA-256 in
  `PasswordReset.token_hash`. The raw token is in the email and nowhere else;
  it crosses the broker sealed (`messaging.seal`), as a sign-in code does.
- **Thirty minutes** (`settings.PASSWORD_RESET_TTL`).
- **Once.** Spent in the transaction that changes the password, under a row
  lock, so two clicks cannot both use it.
- **Only the newest.** Asking again kills every earlier link the person holds,
  on every host: the one in the inbox is always the last one asked for.
- **Only on the host it was asked for from.** A link asked for on Sunrise's
  host is Sunrise's: Harbour's host and the portal answer it exactly as they
  answer a token nobody ever made. A school's door signs in its own members and
  nobody else (`signin.belongs_at`), and its reset is the same door.

A dead link is one page, whatever killed it (unknown, used, replaced, expired,
another host's, or its holder since deactivated or removed from the school):
telling them apart would say which guessed tokens were real.

## Who may be sent one

An **active** account, with an **email address**, that is:

- on a school's host, an active member of that school (any role);
- on the portal, anybody else with an account, as at the portal's door.

And never platform staff or a blog account, on any host. A blog account has no
password by design (`blog.signin`); an operator's reaches every school, and its
password is changed by somebody with the server (`manage.py changepassword`),
not by whoever can read one mailbox.

**An account with only a phone number is sent nothing.** The link goes by
email, and there is no SMS version yet; the page says its one sentence, and the
school office is who to ask. A school that sends nothing (`schools.quiet`)
sends no link either.

## The throttle counts requests

`SignInScope.RESET_ACCOUNT` and `RESET_ADDRESS`, over an hour
(`settings.PASSWORD_RESET_*`). The account's bucket is keyed on the account
when what was typed resolves to one, so its email and its phone number are one
bucket and not two, and on what was typed otherwise. Because the answer is the
same sentence either way, the key says nothing to the caller.

## Every request and every reset is written down

`PasswordResetLog`: what happened to each request (`Result`), and each password
changed, with the address it came from. And one line each in the log stream.
"""

import hashlib
import logging
import secrets
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection, transaction
from django.utils import timezone

from . import throttling
from .identifiers import canonical_username
from .models import (
    PasswordReset,
    PasswordResetEvent,
    PasswordResetLog,
    SignInScope,
    User,
)

logger = logging.getLogger(__name__)

#: What the page says after every request, whatever came of it.
SENT = "If an account matches, we've sent a link to its email address."

#: What the page says for every link that cannot be used, whatever killed it.
LINK_NOT_VALID = "This link no longer works."


class Result:
    """What came of a request, as `PasswordResetLog.result` keeps it. Never shown."""

    SENT = "sent"
    THROTTLED = "throttled"
    NO_ACCOUNT = "no_account"
    #: What was typed matches more than one account (`IdentifierBackend` refuses it too).
    AMBIGUOUS = "ambiguous"
    DEACTIVATED = "deactivated"
    #: Platform staff or a blog account: never reset by email.
    NOT_ELIGIBLE = "not_eligible"
    #: Not an active member of the school whose host this is.
    NOT_A_MEMBER = "not_a_member"
    #: A phone number and no email address: the link has nowhere to go.
    NO_EMAIL = "no_email"
    #: A school that sends nothing (`schools.quiet`).
    SWITCHED_OFF = "switched_off"
    CHANGED = "changed"


class PasswordResetError(Exception):
    """A reset was refused. One base class, as `SignInError` is for sign-in."""


class LinkNotValid(PasswordResetError):
    """The link cannot be used. Carries no reason, because the caller is told none."""

    def __init__(self):
        super().__init__(LINK_NOT_VALID)


class WeakPassword(PasswordResetError):
    """The new password failed `AUTH_PASSWORD_VALIDATORS`. `messages` is what to fix."""

    def __init__(self, messages):
        self.messages = list(messages)
        super().__init__(" ".join(self.messages))


def _ttl() -> timedelta:
    """The link's lifetime, read per call so `override_settings` is honoured."""
    return timedelta(seconds=settings.PASSWORD_RESET_TTL)


def minutes() -> int:
    """The lifetime in whole minutes, for the page and the email."""
    return max(1, round(settings.PASSWORD_RESET_TTL / 60))


def hash_token(raw_token: str) -> str:
    """The only form of a link's token this platform keeps (`schools.models.hash_token`)."""
    return hashlib.sha256((raw_token or "").encode("utf-8")).hexdigest()


def _digest(identifier: str) -> str:
    """What was typed, as the log keeps it: normalised, then hashed."""
    normalized = canonical_username((identifier or "").strip()).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _account_key(matches, identifier: str) -> str:
    """One throttle key for one account, however it was named; what was typed, for nobody."""
    if len(matches) == 1:
        return f"account:{matches[0].pk}"
    return "typed:" + canonical_username((identifier or "").strip()).casefold()


def _may_be_reset_here(user, school) -> str | None:
    """Why `user` is sent nothing on this host, as a `Result`, or None: send it."""
    from schools import quiet

    from .signin import belongs_at

    if not user.is_active:
        return Result.DEACTIVATED
    if user.is_platform_staff or user.is_superuser or user.blog_role:
        return Result.NOT_ELIGIBLE
    if school is not None and not belongs_at(user, school):
        return Result.NOT_A_MEMBER
    if not user.email:
        return Result.NO_EMAIL
    if quiet.is_quiet(school) or (school is None and quiet.only_at_quiet_schools(user.pk)):
        return Result.SWITCHED_OFF
    return None


def _log(event, result, *, address="", identifier="", user=None, school=None, reset=None):
    PasswordResetLog.objects.create(
        event=event,
        result=result,
        address=(address or "")[:64],
        identifier_digest=_digest(identifier) if identifier else "",
        account_id=user.pk if user is not None else None,
        host_school_id=school.pk if school is not None else None,
        reset_id=reset.pk if reset is not None else None,
    )
    logger.info(
        "password reset %s: %s (account=%s host_school=%s address=%s)",
        event,
        result,
        user.pk if user is not None else "-",
        school.pk if school is not None else "portal",
        address or "-",
    )


def link_origin(request) -> str:
    """`https://<host>`: where this request came in, which is where its link goes back to.

    The request's own host, never a setting: a link asked for on a school's
    host opens on that host (`schools.hosts.sign_in_host` says why that is
    safe: the tenant middleware has already matched the host to a `Domain`
    row, and an unknown one was a 404 before any view ran).
    """
    return f"{request.scheme}://{request.get_host()}"


def request_reset(request, identifier: str, *, school=None) -> str:
    """Email a reset link for `identifier`, if there is an account here to send one to.

    Returns the `Result`, for the log and the tests. **The caller shows `SENT`
    whatever it is**, with the same status (the module says why).

    Order is `signin.sign_in()`'s. What was typed is resolved first, only to
    name its bucket (`_account_key`). Then the throttle is asked, before
    anything is decided, so a closed window is closed to everybody; then the
    request is counted, whoever it was for; and only then is the account asked
    whether it may be sent a link here.

    Anything `User.matching_identifier()` knows finds the account, as at the
    staff door: an email address, a phone number in any spelling, or a staff
    ID. The link goes to the account's email address whichever was typed.
    """
    identifier = (identifier or "").strip()
    address = throttling.client_address(request)
    # Two at most: one is the account, two is "more than one" and nobody's.
    matches = list(User.objects.matching_identifier(identifier)[:2])
    user = matches[0] if len(matches) == 1 else None
    account_key = _account_key(matches, identifier)

    def done(result, reset=None):
        _log(
            PasswordResetEvent.REQUESTED, result, address=address, identifier=identifier,
            user=user, school=school, reset=reset,
        )
        return result

    if (
        throttling.blocked_for(SignInScope.RESET_ACCOUNT, account_key) is not None
        or throttling.blocked_for(SignInScope.RESET_ADDRESS, address) is not None
    ):
        return done(Result.THROTTLED)
    throttling.record_request(SignInScope.RESET_ACCOUNT, account_key)
    throttling.record_request(SignInScope.RESET_ADDRESS, address)

    if user is None:
        return done(Result.AMBIGUOUS if matches else Result.NO_ACCOUNT)
    refused = _may_be_reset_here(user, school)
    if refused is not None:
        return done(refused)

    with transaction.atomic():
        reset, raw_token = _mint(user, school)
        _deliver(reset, raw_token, link_origin(request))
        return done(Result.SENT, reset)


def _mint(user, school):
    """A new link for `user` on this host, and the end of every earlier one. `(row, raw_token)`.

    The account's row is locked first, so two requests for one person cannot
    both read "no live link" and leave two.
    """
    User.objects.select_for_update().filter(pk=user.pk).first()
    now = timezone.now()
    PasswordReset.objects.live().filter(user=user).update(superseded_at=now)
    raw_token = secrets.token_urlsafe(32)
    reset = PasswordReset.objects.create(
        user=user,
        school=school,
        token_hash=hash_token(raw_token),
        created_at=now,
        expires_at=now + _ttl(),
    )
    return reset, raw_token


def holder(raw_token: str, *, school=None, lock=False):
    """`(row, user)` for a link that may be used on this host now, or None.

    None for a token that is unknown, used, replaced by a newer one, expired,
    another host's, or whose holder has since been deactivated or is no longer
    a member of this school. The caller cannot tell which (the module says why).
    """
    from .signin import belongs_at

    if not raw_token:
        return None
    rows = PasswordReset.objects.filter(token_hash=hash_token(raw_token))
    if lock:
        rows = rows.select_for_update()
    reset = rows.first()
    if reset is None or not reset.is_live:
        return None
    if reset.school_id != (school.pk if school is not None else None):
        return None
    user = User.objects.filter(pk=reset.user_id).first()
    if user is None or _may_be_reset_here(user, school) in (
        Result.DEACTIVATED, Result.NOT_ELIGIBLE, Result.NOT_A_MEMBER,
    ):
        return None
    return reset, user


@transaction.atomic
def complete(request, raw_token: str, password: str, *, school=None):
    """Spend the link and set `password`. Returns the user, or raises.

    `LinkNotValid` for any link `holder()` refuses; `WeakPassword` for a
    password `AUTH_PASSWORD_VALIDATORS` refuses, which leaves the link unspent.

    **Every session the person has ends here, and nothing has to find them.**
    A session carries a hash of the password it was signed in with
    (`User.get_session_auth_hash()`), and Django refuses and flushes one whose
    hash no longer matches, on its next request, on every host and in either
    cookie (`schools.sessions`). Changing the password is what signs them out;
    a session opened with a parent's code carries the same hash and ends too.
    """
    found = holder(raw_token, school=school, lock=True)
    if found is None:
        raise LinkNotValid()
    reset, user = found
    try:
        validate_password(password, user)
    except DjangoValidationError as exc:
        raise WeakPassword(exc.messages) from exc

    now = timezone.now()
    user.set_password(password)
    user.save(update_fields=["password"])
    reset.used_at = now
    reset.save(update_fields=["used_at"])
    # Wrong passwords typed before the reset are forgiven with it: the person
    # is about to sign in, and a window they closed by guessing would refuse
    # the right password for another quarter of an hour.
    for value in filter(None, {user.username, user.email, user.phone}):
        throttling.clear(SignInScope.IDENTIFIER, value)

    _log(
        PasswordResetEvent.COMPLETED, Result.CHANGED,
        address=throttling.client_address(request), user=user, school=school, reset=reset,
    )
    _tell(reset, request.get_host())
    return user


# -- the two emails ------------------------------------------------------------


def _deliver(reset, raw_token, origin):
    """Queue the link for sending once the minting transaction commits (`messaging.codes`)."""
    from messaging.seal import seal

    sealed = seal(raw_token)
    reset_id = reset.pk
    transaction.on_commit(lambda: _publish(send_reset_link, [reset_id, sealed, origin]))


def _tell(reset, host):
    """Queue the "your password was changed" email, after the commit."""
    reset_id = reset.pk
    transaction.on_commit(lambda: _publish(send_password_changed, [reset_id, host]))


def _publish(task, args):
    """Hand a send to the queue. A failure here never fails the page (`messaging.codes`)."""
    try:
        task.apply_async(args=args, retry=False)
    except Exception:  # noqa: BLE001, the request has committed and answered already
        logger.exception("Could not queue %s for password reset %s", task.name, args[0])


def _place(school) -> str:
    return school.name if school is not None else "Classnode"


def _send(outbound):
    """Hand `outbound` to the email provider. Returns a `messaging.models.Outcome` value."""
    from messaging import providers
    from messaging.models import Outcome

    provider = providers.provider_for("email")
    try:
        provider.check_configured()
        provider.send(outbound)
    except providers.NotConfigured:
        logger.error("No email provider: %s was not sent", outbound.reference)
        return str(Outcome.NOT_CONFIGURED)
    except providers.Refused:
        return str(Outcome.REFUSED)
    except providers.Unavailable:
        logger.exception("The email provider is unavailable: %s", outbound.reference)
        return str(Outcome.UNAVAILABLE)
    return str(Outcome.ACCEPTED)


@shared_task
def send_reset_link(reset_id, sealed, origin):
    """Claim the link, email it, and write down what the provider said. At most once."""
    from messaging import kinds, providers
    from messaging.kinds import Kind
    from messaging.models import Outcome
    from messaging.seal import open_sealed

    connection.set_schema_to_public()
    claimed = PasswordReset.objects.filter(pk=reset_id, claimed_at__isnull=True).update(
        claimed_at=timezone.now()
    )
    if not claimed:
        return None
    reset = PasswordReset.objects.select_related("user", "school").get(pk=reset_id)

    lifetime = int((reset.expires_at - reset.created_at).total_seconds())
    raw_token = open_sealed(sealed, ttl_seconds=lifetime)
    if raw_token is None or not reset.is_live or not reset.user.email:
        return _record(reset, str(Outcome.EXPIRED))

    host = origin.partition("://")[2]
    params = {
        "place": _place(reset.school),
        "link": f"{origin}/reset-password/{raw_token}/",
        "minutes": max(1, round(lifetime / 60)),
        "host": host,
    }
    outbound = providers.Outbound(
        channel_type="email",
        address=reset.user.email,
        kind=str(Kind.PASSWORD_RESET),
        # The link is a credential: `params` carries it only to a provider, as a
        # code's do, and nothing of ours writes an `Outbound` down.
        params=params,
        text=kinds.render(Kind.PASSWORD_RESET, channel_type="email", **params),
        reference=f"password-reset-{reset.pk}",
        reply_to=reset.school.contact_email if reset.school is not None else "",
    )
    return _record(reset, _send(outbound))


def _record(reset, outcome):
    reset.outcome = outcome
    reset.save(update_fields=["outcome"])
    return outcome


@shared_task
def send_password_changed(reset_id, host):
    """Tell the account's own address that its password was changed. At most once."""
    from messaging import kinds, providers
    from messaging.kinds import Kind
    from schools import quiet

    connection.set_schema_to_public()
    claimed = PasswordReset.objects.filter(
        pk=reset_id, used_at__isnull=False, told_at__isnull=True
    ).update(told_at=timezone.now())
    if not claimed:
        return None
    reset = PasswordReset.objects.select_related("user", "school").get(pk=reset_id)
    user, school = reset.user, reset.school
    if not user.email:
        return None
    if quiet.is_quiet(school) or (school is None and quiet.only_at_quiet_schools(user.pk)):
        return None

    contact = school.contact_email if school is not None else ""
    params = {
        "place": _place(school),
        "when": timezone.localtime(reset.used_at).strftime("%d %B %Y at %H:%M"),
        "host": host,
        "who": f"your school ({contact})" if contact else "your school office",
    }
    outbound = providers.Outbound(
        channel_type="email",
        address=user.email,
        kind=str(Kind.PASSWORD_CHANGED),
        params=params,
        text=kinds.render(Kind.PASSWORD_CHANGED, channel_type="email", **params),
        reference=f"password-changed-{reset.pk}",
        reply_to=contact,
    )
    return _send(outbound)


__all__ = [
    "LINK_NOT_VALID",
    "LinkNotValid",
    "PasswordResetError",
    "Result",
    "SENT",
    "WeakPassword",
    "complete",
    "hash_token",
    "holder",
    "link_origin",
    "minutes",
    "request_reset",
    "send_password_changed",
    "send_reset_link",
]
