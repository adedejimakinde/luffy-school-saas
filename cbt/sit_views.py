"""`/sit/` on a school's own host: the exam door, the exam screen and its small API.

`docs/cbt.md`, "Student sign-in" and "Offline". The services are `cbt.sitting`; this
module is HTTP and the cookie.

## The cookie

The door makes **no account session**. Starting an attempt sets one cookie, `sit`,
scoped to `/sit/` (the browser sends it nowhere else), `HttpOnly`, `SameSite=Strict`,
`Secure` on HTTPS, holding a random token whose digest names one `AttemptSession`, so it
opens one attempt and nothing else. No other route reads it: every staff route
authenticates the account session (`accounts.session.session_auth`), and none of them is
under `/sit/`. It is cleared at submit and at "This is not me".

## The device's cookie

The page also gives each browser a second cookie, `sit_device`: a random id, scoped to
`/sit/`, `HttpOnly`, `SameSite=Strict`, kept a year. It names no student, no test and no
attempt, and opens nothing. It is what wrong tries at the door are counted against (audit
F-09): a computer that has guessed too often waits, and so does its address, but the
student whose admission number was typed does not. It is set by the page, or by the door
if a request comes without it. Anyone can get a fresh one, which is why the address
keeps its own, wider limit.

## Writes without a CSRF token

The routes are exempt from Django's CSRF check because there is no account session to
ride on: the only credential is the `sit` cookie, which `SameSite=Strict` keeps off any
request another site starts. Every write must also be `application/json`, which a form on
another site cannot send without the browser asking this host first.

## A guardian never reaches it

`docs/parent-access.md` D2: exam surfaces do not render for a guardian. A request whose
account session is a parent's here gets the page's refusal and the API's 403.
"""

import json
import re
import secrets

import pages
from django.db import transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from accounts.models import Role, STAFF_ROLES
from accounts.throttling import client_address
from schools import brand

from . import sitting

COOKIE = "sit"
PATH = "/sit/"
#: The browser's own id for the door's throttle (audit F-09). Opens nothing.
DEVICE_COOKIE = "sit_device"
DEVICE_SECONDS = 365 * 24 * 3600
_DEVICE_ID = re.compile(r"[0-9a-f]{32}")

#: The exam screen's modules, entry point last.
SIT_MODULES = (
    "web/html.js",
    "sit/clock.js",
    "sit/outbox.js",
    "sit/calculator.js",
    "sit/api.js",
    "sit/states.js",
    "sit/app.js",
)
SIT_STYLES = ("web/design.css", "sit/sit.css")


def _school(request):
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("The exam door is on each school's own address.")
    return school


def device_of(request):
    """(this browser's device id, whether it was made just now)."""
    kept = request.COOKIES.get(DEVICE_COOKIE, "")
    if _DEVICE_ID.fullmatch(kept):
        return kept, False
    return secrets.token_hex(16), True


def keep_device(response, request, device, made, path=PATH):
    """Give the browser its device id, if it came without one."""
    if made:
        response.set_cookie(
            DEVICE_COOKIE, device, max_age=DEVICE_SECONDS, path=path, httponly=True, samesite="Strict",
            secure=request.is_secure(),
        )
    return response


def _a_guardian(request, school) -> bool:
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return False
    roles = set(user.roles_at(school))
    staff = {r.value if hasattr(r, "value") else r for r in STAFF_ROLES}
    return Role.PARENT.value in roles and not roles & (staff | {Role.STUDENT.value})


@never_cache
def sit_page(request):
    """The frame for `/sit/`: the door, the exam screen and the finished screen.

    Holds no test, no student and no question. Wears the school's crest and name, as
    its public website does (`brand.for_request(door=True)`).
    """
    school = _school(request)
    response = render(
        request,
        "cbt/sit_page.html",
        {
            "import_map": pages.import_map(*SIT_MODULES),
            "door": True,
            "school_brand": brand.for_request(request, door=True),
            "guardian": _a_guardian(request, school),
        },
    )
    response["Cache-Control"] = "no-cache"
    device, made = device_of(request)
    return keep_device(response, request, device, made)


def worker_config() -> dict:
    """What `/sit/sw.js` keeps: the page, and the static files the page itself names."""
    import hashlib

    from sync.views import STYLES as SHARED

    fonts = [p for p in SHARED if p.startswith("web/fonts/")]
    shell = [static(p) for p in (*SIT_MODULES, *SIT_STYLES, *fonts)]
    source = (pages_dir() / "sit_worker.js").read_text()
    version = hashlib.sha256((source + "\n".join(shell)).encode()).hexdigest()[:12]
    return {"version": version, "page": PATH, "shell": shell, "pictures": f"{PATH}pictures/"}


def pages_dir():
    from pathlib import Path

    return Path(__file__).parent


@require_GET
def sit_worker(request):
    """The exam page's own service worker, scoped to `/sit/` and nothing above it."""
    source = (pages_dir() / "sit_worker.js").read_text()
    body = f"const CONFIG = {json.dumps(worker_config(), indent=2)};\n\n{source}"
    response = HttpResponse(body, content_type="text/javascript; charset=utf-8")
    response["Cache-Control"] = "no-cache"
    response["Service-Worker-Allowed"] = PATH
    return response


# -- the API -------------------------------------------------------------------------


def _json(request):
    if request.content_type != "application/json":
        return None
    try:
        body = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return None
    return body if isinstance(body, dict) else None


def _said(status, detail, **more):
    response = JsonResponse({"detail": detail, **more}, status=status)
    response["Cache-Control"] = "no-store, private"
    return response


def _ok(body, status=200):
    response = JsonResponse(body, status=status)
    response["Cache-Control"] = "no-store, private"
    return response


def _with_device(response, request, exc):
    kept = getattr(exc, "device", None)
    if kept:
        keep_device(response, request, *kept, path=getattr(exc, "device_path", PATH))
    return response


def _api(view):
    """Every route: a school's host, no guardian, a JSON body for a write."""

    @csrf_exempt
    def wrapped(request, *args, **kwargs):
        school = getattr(request, "school", None)
        if school is None:
            return _said(404, "The exam door is on each school's own address.")
        if _a_guardian(request, school):
            return _said(403, sitting.NOT_FROM_A_PARENT)
        body = {}
        if request.method == "POST":
            body = _json(request)
            if body is None:
                return _said(415, "Send the answer as JSON.")
        try:
            return view(request, school, body, *args, **kwargs)
        except sitting.TooManyAttempts as exc:
            return _with_device(_said(429, str(exc), retry_after=exc.retry_after), request, exc)
        except sitting.NotOpened as exc:
            return _with_device(_said(404, str(exc)), request, exc)
        except sitting.NoSession as exc:
            response = _said(401, str(exc))
            response.delete_cookie(COOKIE, path=PATH)
            return response
        except sitting.Replaced as exc:
            return _said(409, str(exc), replaced=True)
        except sitting.Closed as exc:
            return _with_device(_said(409, str(exc)), request, exc)

    wrapped.__name__ = view.__name__
    wrapped.__doc__ = view.__doc__
    return wrapped


def _token(request):
    return request.COOKIES.get(COOKIE, "")


@require_POST
@_api
def door(request, school, body):
    """The three: code, admission number, PIN. One refusal for every failure of them, counted
    against this browser and its address, never against the number typed."""
    device, made = device_of(request)
    try:
        found = sitting.door(
            school,
            code=str(body.get("code") or ""),
            admission_number=str(body.get("admission_number") or ""),
            pin=str(body.get("pin") or ""),
            address=client_address(request),
            device=device,
        )
    except sitting.SitError as exc:
        # The refusal still gives the browser the id its wrong try was counted against.
        exc.device = (device, made)
        raise
    test = found.test
    return keep_device(_ok(
        {
            "ticket": found.ticket,
            "student": {
                "name": sitting.name_of(found.student),
                "admission_number": " ".join((found.student.reference or "").split()),
                "class_name": found.class_group.name,
            },
            "test": {
                "title": test.title,
                "duration": test.duration,
                "questions": test.items.count(),
                "calculator": test.calculator,
            },
            "resuming": found.resuming,
            "minutes_left": found.minutes_left,
        }
    ), request, device, made)


@require_POST
@_api
def not_me(request, school, body):
    """"This is not me": logged, nothing started."""
    sitting.not_me(school, str(body.get("ticket") or ""))
    response = _ok({"detail": "Nothing has started. Tell your teacher."})
    response.delete_cookie(COOKIE, path=PATH)
    return response


@require_POST
@_api
def start(request, school, body):
    """The clock starts (or carries on): the attempt, this computer's session, the paper."""
    started = sitting.start(
        school,
        str(body.get("ticket") or ""),
        seat=str(body.get("seat") or "")[:80],
        sync_offset_ms=body.get("sync_offset_ms") or 0,
    )
    response = _ok({**sitting.payload_for(started.session), "resumed": started.resumed})
    ends = sitting.closes_for_good_at(started.attempt)
    age = max(60, int((ends - timezone.now()).total_seconds()) + 3600)
    response.set_cookie(
        COOKIE, started.token, max_age=age, path=PATH, httponly=True, samesite="Strict", secure=request.is_secure()
    )
    return response


@require_GET
@_api
def attempt(request, school, body):
    """The attempt this computer holds, for a reload: paper, answers held, the clock."""
    with transaction.atomic():
        session = sitting.session_for(school, _token(request), lock=True)
        sitting.settle(session.attempt)
        session.refresh_from_db(fields=["ended_at", "ended_by"])
        return _ok(sitting.payload_for(session))


@require_POST
@_api
def sync(request, school, body):
    """The outbox and the heartbeat."""
    return _ok(sitting.sync(school, _token(request), answers=body.get("answers") or [], events=body.get("events") or []))


@require_POST
@_api
def submit(request, school, body):
    """The outbox, then the close. No score: the teacher releases scores (step 5)."""
    out = sitting.submit(
        school, _token(request), answers=body.get("answers") or [], events=body.get("events") or [],
        by_clock=bool(body.get("by_clock")),
    )
    response = _ok(out)
    response.delete_cookie(COOKIE, path=PATH)
    return response


@require_GET
def picture(request, key, variant):
    """A picture in the paper this cookie's attempt holds, and no other."""
    school = getattr(request, "school", None)
    if school is None or variant not in ("full.webp", "small.webp") or len(key) != 32:
        raise Http404("No such picture.")
    try:
        session = sitting.session_for(school, _token(request))
    except sitting.NoSession:
        raise Http404("No such picture.")
    from files import service, views
    from files.kinds import Kind

    from .models import TestItem

    if not TestItem.objects.filter(test_id=session.attempt.test_id, image_key=key).exists():
        raise Http404("No such picture.")
    stored = service.find(key)
    if stored is None or stored.kind != Kind.QUESTION_IMAGE:
        raise Http404("No such picture.")
    return views.send(stored, variant, cache_control=views.PRIVATE)


__all__ = ["COOKIE", "DEVICE_COOKIE", "PATH", "device_of", "keep_device", "SIT_MODULES", "SIT_STYLES", "attempt", "door", "not_me", "picture", "sit_page",
           "sit_worker", "start", "submit", "sync", "worker_config"]
