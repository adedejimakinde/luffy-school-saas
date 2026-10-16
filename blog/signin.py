"""How a writer or an editor signs in: an email address, then a code sent to it.

**The platform's email-code sign-in, reused.** The code is minted by
`accounts.guardian_contacts.generate_code()`, kept only as
`hash_code()`'s SHA-256, given `MAX_VERIFICATION_ATTEMPTS` guesses and
`DEFAULT_VERIFICATION_TTL` to live, sealed on the queue (`messaging.seal`),
sent off the request by the email provider every code goes through
(`messaging.providers`), with the same words (`messaging.kinds.SIGN_IN_CODE`),
and the door is throttled by `accounts.throttling`.

**Its own table and its own door**, `blog.SignInCode` and `/write/sign-in/`,
because the guardian door's codes belong to a guardian's verified channel:
its rows are a `GuardianContact`, which goes dormant and is woken by a
school, and a session it opens is held to a parent's reach. A writer has no
school to wake anything and no child to reach. The rules carried over are the
ones that make a code safe, and they are the same numbers.

**One answer for every address.** "If that address belongs to a blog account,
a code has been sent" whether it does or not, and the send happens on a
worker after the commit, so neither the words nor the time taken say whether
an address is a writer's. Every failed code is the same one sentence.

**The throttle has a bucket of its own**, `SignInScope.BLOG_EMAIL`, counted
against the address as typed: a writer's address guessed at here must not
close a guardian's door, or the other way round (`SignInScope`'s reasoning
for CHANNEL). And the network address, shared with every door, as ever.
"""

import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth import login as start_session
from django.db import transaction
from django.utils import timezone

from accounts import throttling
from accounts.guardian_contacts import generate_code, hash_code
from accounts.models import (
    DEFAULT_VERIFICATION_TTL,
    MAX_VERIFICATION_ATTEMPTS,
    SignInScope,
)

from .models import CodeStatus, SignInCode

CODE_REQUESTED = (
    "If that address belongs to a blog account, a code has been sent to it. "
    "It lasts 15 minutes."
)
REFUSED = "That code is not one we are waiting for. Ask for a new one and try again."
THROTTLED = "Too many tries. Wait a few minutes, then try again."

#: Codes one account may be sent in an hour. The rest are not sent, and the
#: answer on the page is the same, so nobody can make the platform email a
#: writer forty times by pressing a button.
SENDS_PER_HOUR = 5


class TooManyAttempts(Exception):
    def __init__(self, retry_after: int):
        super().__init__(THROTTLED)
        self.retry_after = retry_after


class BadCode(Exception):
    pass


def _clean(value: str) -> str:
    return (value or "").strip().lower()


def _wait(email: str, address: str):
    waits = [
        wait
        for wait in (
            throttling.blocked_for(SignInScope.BLOG_EMAIL, email),
            throttling.blocked_for(SignInScope.ADDRESS, address),
        )
        if wait is not None
    ]
    return max(waits) if waits else None


def account_for(email: str):
    """The active blog account with this email, or None."""
    if not email:
        return None
    return (
        get_user_model()
        .objects.filter(email__iexact=email, is_active=True)
        .exclude(blog_role="")
        .first()
    )


@transaction.atomic
def request_code(request, value: str) -> None:
    """Send a code to `value` if it is a blog account's. Raises only `TooManyAttempts`."""
    from .tasks import deliver

    email = _clean(value)
    wait = _wait(email, throttling.client_address(request))
    if wait is not None:
        raise TooManyAttempts(wait)

    user = account_for(email)
    if user is None:
        return None
    since = timezone.now() - timedelta(hours=1)
    if SignInCode.objects.filter(user=user, created_at__gte=since).count() >= SENDS_PER_HOUR:
        return None

    # One live code at a time: a resend ends the one before it.
    SignInCode.objects.filter(user=user, status=CodeStatus.PENDING).update(
        status=CodeStatus.SPENT
    )
    raw_code = generate_code()
    code = SignInCode.objects.create(
        user=user,
        code_hash=hash_code(raw_code),
        expires_at=timezone.now() + DEFAULT_VERIFICATION_TTL,
    )
    deliver(code, raw_code)
    return None


@transaction.atomic
def _spend(user, raw_code: str) -> bool:
    code = (
        SignInCode.objects.select_for_update()
        .filter(user=user, status=CodeStatus.PENDING)
        .order_by("-created_at", "-id")
        .first()
    )
    if code is None:
        return False
    if code.is_expired or code.attempts >= MAX_VERIFICATION_ATTEMPTS:
        code.status = CodeStatus.SPENT
        code.save(update_fields=["status"])
        return False
    if not secrets.compare_digest(code.code_hash, hash_code(raw_code)):
        code.attempts += 1
        code.save(update_fields=["attempts"])
        return False
    code.status = CodeStatus.CONFIRMED
    code.save(update_fields=["status"])
    return True


def sign_in_with_code(request, value: str, raw_code: str):
    """Answer the code and open a session. Returns the user, or raises `BadCode`."""
    email = _clean(value)
    address = throttling.client_address(request)
    wait = _wait(email, address)
    if wait is not None:
        raise TooManyAttempts(wait)

    raw_code = (raw_code or "").strip()
    user = account_for(email)
    if user is None or not raw_code or not _spend(user, raw_code):
        throttling.record_failure(SignInScope.BLOG_EMAIL, email)
        throttling.record_failure(SignInScope.ADDRESS, address)
        raise BadCode(REFUSED)

    throttling.clear(SignInScope.BLOG_EMAIL, email)
    start_session(request, user)
    return user
