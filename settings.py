import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# The three settings a deploy is most likely to forget
#
# All three used to have a *convenient* default, which meant a deployment that
# set none of them started successfully and was wrong in three ways at once.
# They now fail the way the email backend does (see DEFAULT_EMAIL_BACKEND
# below): closed, loudly, and with development opting in explicitly rather than
# production opting out by accident.
# ---------------------------------------------------------------------------

# **Off unless something says otherwise.** This used to default to on, so a
# deploy that never set it served tracebacks — settings, environment and all —
# to anybody who could provoke one. Development turns it on in
# docker-compose.yml, beside EMAIL_BACKEND, for the same reason and in the same
# place.
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"

# **No usable default outside development.** A `SECRET_KEY` is what signs
# session cookies and CSRF tokens, so a known one is not a weaker key — it is no
# key at all: anybody holding this repository could mint a session for any
# account on the platform. That was survivable while sessions only ever came
# from `force_login()` in tests. It stopped being survivable the moment
# `/api/login/` could mint one from a password.
_DEVELOPMENT_SECRET_KEY = "dev-only-not-for-production"
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY") or (
    _DEVELOPMENT_SECRET_KEY if DEBUG else ""
)
if not SECRET_KEY:
    raise ImproperlyConfigured(
        "DJANGO_SECRET_KEY is not set. Refusing to start with a known key: it "
        "signs every session cookie and CSRF token on the platform. Set it, or "
        "set DJANGO_DEBUG=1 for local development."
    )

# **The `Domain` table is the real allowlist**, which is why this could be `*`
# for as long as it was. `TenantMainMiddleware` resolves every request's host
# against `schools.Domain` and raises `Http404` for one it does not recognise,
# before any view runs — so an invented `Host` header is already refused, by
# data rather than by a list somebody has to remember to update.
#
# Kept overridable anyway, for defence in depth and for the paths that do not go
# through that middleware. `*` remains the default because narrowing it here
# without narrowing `Domain` buys nothing and would silently break a school the
# day it is added.
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")
    if host.strip()
]

# ---------------------------------------------------------------------------
# Tenancy layout
#
# SHARED_APPS live in the `public` schema, once for the whole platform.
# TENANT_APPS are created per school schema.
#
# Identity and access control are deliberately SHARED, not per-tenant:
# a parent may have children at more than one school and must reach all of
# them from a single login, so `accounts.User` and `accounts.Membership`
# cannot be duplicated per schema. Academic and financial records — the data
# a school owns — belong in TENANT_APPS.
# ---------------------------------------------------------------------------
SHARED_APPS = [
    "django_tenants",
    "schools",
    "accounts",
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.admin",
]

TENANT_APPS = [
    # Each school gets its own copy of these tables, in its own schema.
    # Attendance and report cards land here alongside these three.
    "django.contrib.contenttypes",
    "academics",
    # A school's own books. Separate from `academics` rather than a module
    # inside it because the two answer to different people and change on
    # different schedules — a bursar's ledger and a calendar of terms share only
    # the fact that both belong to one school.
    "fees",
    # What a teacher enters: subjects, assessments and marks. Separate from
    # both of the above on the same reasoning — a teacher's sheet and a
    # bursar's ledger have different readers and different release schedules,
    # and neither should have to migrate because the other changed.
    "gradebook",
    # What a school *publishes*: the approval chain a term's results go
    # through, and the snapshot frozen when they are released. Separate from
    # `gradebook` for the reason `gradebook` is separate from `fees` — a
    # teacher's working sheet is edited daily by the person who owns it, while
    # a released result is read by parents years later and may not change at
    # all. Two tables with opposite relationships to time do not belong in one
    # app.
    "results",
]

INSTALLED_APPS = SHARED_APPS + [app for app in TENANT_APPS if app not in SHARED_APPS]

TENANT_MODEL = "schools.School"
TENANT_DOMAIN_MODEL = "schools.Domain"

# Builds one migrated tenant schema per test database and lets `make_school()`
# clone it, instead of running `migrate_schemas` once per test method — which
# was about 90% of the suite's wall clock. It subclasses Django's own runner and
# changes nothing about discovery, selection or reporting; the only thing it
# adds is *when* that schema is built, which has to be after the test database
# exists and before Django clones it for the `--parallel` workers.
# `schools/tests/runner.py` says why that window is the only one that works.
TEST_RUNNER = "schools.tests.runner.TenantTemplateRunner"

MIDDLEWARE = [
    # First, as Django asks: it is the one that can end a request before the
    # rest of the stack has done any work. What it buys here is the header set
    # — nosniff, referrer policy, and HSTS once a deployment turns it on.
    "django.middleware.security.SecurityMiddleware",
    # Second, and **above the tenant middleware on purpose**. A stylesheet is
    # not a school's: it is the same bytes on thirty hostnames, and resolving a
    # tenant to serve one would mean a database query and a `search_path` set
    # per asset, on requests that touch no school's data at all. Placed here,
    # `/static/...` is answered and returned before `TenantMainMiddleware` is
    # ever asked which school this is — which also means a request for an asset
    # on a hostname that is not a school's cannot 404 as "no such tenant".
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django_tenants.middleware.main.TenantMainMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # Enforces that whoever is signed in actually belongs to the school whose
    # domain they are on. Must come after AuthenticationMiddleware.
    "accounts.middleware.SchoolAccessMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # Last, so the header lands on whatever the stack finally produced. There is
    # nothing on this platform that belongs in somebody else's frame, and the
    # admin — a form that performs privileged writes on submit — is the exact
    # thing clickjacking is for.
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# ---------------------------------------------------------------------------
# Transport and header hardening
#
# Set here where the answer is the same everywhere, and deliberately left unset
# where it is a fact about a deployment's topology rather than about this
# application.
#
# `SECURE_HSTS_SECONDS` and `SECURE_SSL_REDIRECT` are the two left out. Both
# depend on where TLS is terminated and whether the load balancer already
# redirects; turning on the redirect in a process that is *behind* a terminator
# that does not set `X-Forwarded-Proto` produces an infinite redirect, and HSTS
# is close to irreversible for the length of its own max-age. `manage.py check
# --deploy` reports both as warnings, which is the right loudness for a decision
# somebody has to make with the infrastructure in front of them.
# ---------------------------------------------------------------------------
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"

AUTH_USER_MODEL = "accounts.User"

# Django ships no validators by default, which meant the one path in this
# codebase that sets a password on somebody's behalf — Invitation.accept() —
# would take a single character. What it writes is a *global* credential: it
# signs the person in at every school they hold a membership at, so it is worth
# a floor. Add the rest of Django's stock validators here if the policy grows.
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
]

# Staff, parents and students all sign in through the same door. They just
# reach for different identifiers, so accept any of username / email / phone.
AUTHENTICATION_BACKENDS = ["accounts.backends.IdentifierBackend"]

# ---------------------------------------------------------------------------
# Sessions
#
# Both settings below are Django defaults being overridden deliberately, so both
# say why. The case that decides them is a teacher marking a class of thirty:
# each cell saves as it loses focus, so a marking session is a long stretch of
# steady small writes rather than one form and one submit.
#
# **The window is idle time, not total time.** Django's default,
# `SESSION_SAVE_EVERY_REQUEST = False`, runs the clock from the moment of login
# and never extends it however hard the person is working. A teacher who signed
# in near the end of the window gets logged out mid-sheet, cursor still in a
# cell, having saved marks successfully seconds earlier. Sliding the expiry on
# every request is what makes "expired" mean "went away", which is the only
# meaning anybody expects.
#
# The cost is a session write per request, and with one request per blur that is
# thirty writes for one register rather than none. Accepted: the row is small and
# keyed by primary key, and the alternative is losing a teacher's work. If it
# ever shows up in the database's load, the fix is a cached session backend, not
# turning this back off.
#
# **Twelve hours, down from Django's two weeks.** A school day plus room either
# side, so a normal working day never trips it and a session left open on a
# shared staff-room computer is gone by the next morning. Two weeks of *idle*
# time on a machine several teachers use is a long time to leave a signed-in
# gradebook lying around; two weeks of idle time was never the intent, it was
# simply the default nobody had chosen.
#
# Not `SESSION_EXPIRE_AT_BROWSER_CLOSE`: half of marking is done in a browser
# that is never deliberately closed, and it would put the teacher back where this
# started — logged out at a moment they did not choose.
SESSION_SAVE_EVERY_REQUEST = True
SESSION_COOKIE_AGE = 60 * 60 * 12

# **A session belongs to the person, not to one school.** That is not a new
# decision here; it is the one this project already made and has been relying
# on. `accounts.Membership` is shared rather than per-tenant precisely so a
# parent with children at three schools has one login, and
# `SchoolAccessMiddleware` re-derives what they may do from the host on every
# request rather than from anything stored in the session. Writing the school
# into the session would put the same fact in two places, and make the copy in
# the session the stale one the moment a membership is suspended.
#
# What that costs is this setting. Sign-in happens on the portal host (see
# `/api/login/`), and a cookie with no Domain attribute is returned only to the
# exact host that set it — so without a domain spanning the portal and every
# school, a teacher would sign in successfully on the portal and arrive at their
# own school's host as a stranger. Set it to the parent of every host the
# platform answers on, with a leading dot: `.luffy.school`.
#
# Left unset it is not merely unconfigured, it is wrong in a way that only shows
# up on the second host, which is why `accounts/checks.py` refuses a production
# deploy without it rather than letting it be discovered by a teacher. Unset is
# still right for local single-host development, where it means "this host".
SESSION_COOKIE_DOMAIN = os.environ.get("SESSION_COOKIE_DOMAIN") or None

# The CSRF cookie has to travel exactly as far as the session it protects.
CSRF_COOKIE_DOMAIN = SESSION_COOKIE_DOMAIN

# A session cookie is a credential from the moment `/api/login/` can mint one,
# so it should never cross a plain-HTTP hop. Tied to DEBUG rather than given its
# own switch: a deployment with DEBUG on has a larger problem than this setting.
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

# ---------------------------------------------------------------------------
# Sign-in throttling
#
# The reasoning — counted rather than locked, failures rather than attempts,
# Postgres rather than the cache — is in `accounts/throttling.py`. These are the
# numbers, which are the part worth arguing about separately.
#
# Ten failures per identifier per quarter-hour: generous for somebody who has
# genuinely forgotten which of their two passwords this is, and against a
# ten-character minimum it leaves an attacker roughly a thousand guesses a day
# against a space where that is nothing.
#
# Fifty per address, because a staff room is one NAT address and a limit that a
# school trips by arriving in the morning would be turned off within a week.
# Only failures count, so ordinary arrivals never approach it.
# ---------------------------------------------------------------------------
SIGN_IN_THROTTLE_WINDOW = int(os.environ.get("SIGN_IN_THROTTLE_WINDOW", 15 * 60))
SIGN_IN_MAX_FAILURES_PER_IDENTIFIER = int(
    os.environ.get("SIGN_IN_MAX_FAILURES_PER_IDENTIFIER", 10)
)
SIGN_IN_MAX_FAILURES_PER_ADDRESS = int(
    os.environ.get("SIGN_IN_MAX_FAILURES_PER_ADDRESS", 50)
)

# Ten wrong codes per handset per quarter-hour. The same number as the
# identifier limit above and not for the same reason, which is worth saying so
# that changing one does not read as a reason to change the other.
#
# What bounds guessing *one* code is `MAX_VERIFICATION_ATTEMPTS` — five against
# a million, inside a fifteen-minute expiry. This bounds the *sequence*: a
# caller who burns a code, asks for another and keeps going. Ten leaves a
# guardian who mistypes twice, asks for a fresh code and mistypes again well
# inside it, and leaves an attacker two dead codes rather than an afternoon.
#
# It is a separate scope from the identifier on purpose — see
# `accounts.models.SignInScope.CHANNEL`. Sharing the bucket would let a number
# read off an enrolment form close a teacher's password door.
SIGN_IN_MAX_FAILURES_PER_CHANNEL = int(
    os.environ.get("SIGN_IN_MAX_FAILURES_PER_CHANNEL", 10)
)

# ---------------------------------------------------------------------------
# How many guardian verification codes may be SENT, and this counts successes
# rather than failures — which is the opposite of the sign-in throttle above
# and is why it is a separate set of numbers.
#
# A code is a metered SMS to a real handset (docs/parent-access.md, OPEN-4 and
# OPEN-5), so an unbounded send path is two problems at once: a bill, and a way
# to make a stranger's phone buzz all afternoon from a school's account. It also
# multiplies guesses — every resend is another MAX_VERIFICATION_ATTEMPTS.
#
# Five per channel per hour. A guardian who did not receive the first one asks
# again, maybe twice if the network is slow; five is past anything honest and
# holds total guessing to 25 tries an hour against a million codes.
#
# Two hundred per school per hour. D10 admits guardians one at a time, typed by
# a human, so a school cannot approach this by working normally even on a heavy
# intake day — but a runaway loop or a stolen admin session reaches it in
# seconds, which is the whole point of having it.
# ---------------------------------------------------------------------------
VERIFICATION_SEND_WINDOW = int(os.environ.get("VERIFICATION_SEND_WINDOW", 60 * 60))
MAX_VERIFICATION_SENDS_PER_CHANNEL = int(
    os.environ.get("MAX_VERIFICATION_SENDS_PER_CHANNEL", 5)
)
MAX_VERIFICATION_SENDS_PER_SCHOOL = int(
    os.environ.get("MAX_VERIFICATION_SENDS_PER_SCHOOL", 200)
)

# ---------------------------------------------------------------------------
# How long a phone channel may go unused before the guardian link is suspended,
# and how long a session opened by a one-time code lasts. The two are read
# together on purpose — see `accounts.checks`, which refuses a deployment where
# the session outlives the window.
#
# 180 days, phone only (docs/parent-access.md, D9). Nigerian operators churn a
# number after a total of 360 days of inactivity and reassign it, so finishing
# at 180 puts a school-mediated step in front of a reassignment while the number
# is still not even eligible for it. It never touches an active guardian: three
# terms a year means a natural sign-in roughly every four months, and the
# longest natural gap — the long vacation — is about two. Email is not churned
# and is not subject to it.
#
# Thirty days for the session, sliding (SESSION_SAVE_EVERY_REQUEST). OPEN-4 asks
# how long is acceptable "on a device that may be shared or lost" and no school
# has answered; this is reasoning, not a school, and OPEN-4 records which. A
# guardian opens this a handful of times a term, so thirty days means checking
# in monthly never costs a second metered send, while a lost handset is exposed
# for at most a month.
#
# **The other half of that trade is what makes thirty days the number it is, and
# it is enforced rather than asserted.** What a code-opened session reaches is a
# parent-scoped read of that guardian's own children and nothing else:
# `SchoolAccessMiddleware` sets `parent_scoped_credential` on a session carrying
# `guardian_signin.OPENED_BY_CODE`, and `User.roles_at()` — the one call every
# guard on the platform makes — narrows to PARENT when it is set. A guardian who
# is also a bursar is an ordinary person rather than a corner case
# (`results.tests.test_withholding.TheClaimIsNotABool` is about exactly her); on
# this session she reads her own child's card as a parent rather than as staff
# the fee gate spares, and cannot hold a card back. She gets her staff powers
# again by signing in with her password.
#
# So raising this number lengthens a parent-scoped exposure. It does not lengthen
# a staff one, and that is the only reason thirty days is tolerable at all — the
# comment here said so for one commit before the code did, and said that it was
# saying it.
# ---------------------------------------------------------------------------
GUARDIAN_DORMANCY_DAYS = int(os.environ.get("GUARDIAN_DORMANCY_DAYS", 180))
GUARDIAN_SESSION_AGE = int(os.environ.get("GUARDIAN_SESSION_AGE", 30 * 24 * 60 * 60))

# How many entries at the right-hand end of `X-Forwarded-For` this deployment's
# own proxies wrote. Zero — believe nothing, use REMOTE_ADDR — is the only safe
# default: every hop trusted beyond the ones we actually run is one the caller
# gets to forge, and forging it is exactly how the per-address limit is escaped.
# See `accounts.throttling.client_address()`.
TRUSTED_PROXY_COUNT = int(os.environ.get("TRUSTED_PROXY_COUNT", 0))

# Parsing default only, not a restriction: a number typed with no country
# code is read as Nigerian, but any other country's numbers are still valid.
# See accounts/identifiers.py.
PHONE_DEFAULT_REGION = os.environ.get("PHONE_DEFAULT_REGION", "NG")

# Two urlconfs, chosen by schema rather than by anything a view has to check.
# `urls` is what a school's host serves; `urls_public` replaces it on the public
# schema — the portal — and is the only one carrying the admin. See both files.
ROOT_URLCONF = "urls"
PUBLIC_SCHEMA_URLCONF = "urls_public"

# ---------------------------------------------------------------------------
# Invitations
#
# The channel is a dotted path rather than a hard-coded class so that adding
# WhatsApp for parents later is a settings change and a new class beside
# EmailChannel, not an edit to the Invitation model. See schools/delivery.py.
# ---------------------------------------------------------------------------
INVITATION_CHANNEL = os.environ.get(
    "INVITATION_CHANNEL", "schools.delivery.EmailChannel"
)

#: Where the accept page lives, as a template containing `{token}`.
#:
#: This used to be built with `request.build_absolute_uri()` at the two API call
#: sites, which made the origin of a live credential a property of *whichever
#: host the issuing admin happened to be signed in on*. `TenantMainMiddleware`
#: resolves the portal host and a school's own host differently, so the same
#: flow emitted `http://testserver/invitations/...` or
#: `http://stmarys.luffy.school/invitations/...` depending on where the admin was
#: standing — for a page that is meant to live on a frontend which may be on
#: neither of them, and which no urlconf in this project serves.
#:
#: There is deliberately **no default**. Every candidate default is wrong
#: somewhere: a hard-coded origin is wrong for every deploy that is not ours, and
#: falling back to the request host is the bug this setting exists to remove. So
#: an unset value is a misconfiguration and is refused — see
#: `invitations.configured_accept_url()`, which raises *before* the transaction
#: commits, so a deploy that never sets this creates no orphaned placeholder
#: accounts while failing.
INVITATION_ACCEPT_URL = os.environ.get("INVITATION_ACCEPT_URL")

#: Not the console backend, which is what this used to default to. An invite
#: link is a live credential, and the console backend writes the whole message
#: — accept URL, token and all — to stdout, which in a container is the
#: application log, readable by anyone who can read logs. It failed open in the
#: other direction too: nothing was delivered and nothing raised, so a
#: production deploy that never set this looked exactly like a working one.
#:
#: SMTP is Django's own default and fails closed on both counts: no silent
#: non-delivery, and no credential in the logs. Local development opts into the
#: console backend explicitly — see docker-compose.yml. (Django's test runner
#: substitutes the locmem backend regardless of what is set here.)
DEFAULT_EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", DEFAULT_EMAIL_BACKEND)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "no-reply@luffy.school")

#: Where that SMTP backend connects. Django's own defaults are `localhost:25`
#: with no credentials, which is not a mail server anywhere this runs — so the
#: deploy that sets `EMAIL_BACKEND` nowhere (the intended path, since SMTP is the
#: default above) got `ConnectionRefusedError` on every single invitation.
#:
#: Which host and which credentials is a deployment decision and stays one:
#: these are read from the environment and have no in-repo values. What is *not*
#: left to the deploy is what happens when they are missing — `EmailChannel`
#: refuses to accept an invitation it has nowhere to send, before the
#: transaction commits, rather than raising from inside an `on_commit` callback
#: where nothing can be undone. See `delivery.EmailChannel.check_configured()`.
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "1") == "1"
EMAIL_USE_SSL = os.environ.get("EMAIL_USE_SSL", "0") == "1"
#: Bounded on purpose. `send()` runs in the request/response cycle via
#: `on_commit`, so an unreachable mail host with no timeout holds the worker for
#: as long as the OS lets the connection hang.
EMAIL_TIMEOUT = int(os.environ.get("EMAIL_TIMEOUT", "10"))

DATABASES = {
    "default": {
        "ENGINE": "django_tenants.postgresql_backend",
        "NAME": os.environ.get("POSTGRES_DB", "luffy_db"),
        "USER": os.environ.get("POSTGRES_USER", "luffy_admin"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "changeme"),
        "HOST": os.environ.get("POSTGRES_HOST", "db"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

DATABASE_ROUTERS = ["django_tenants.routers.TenantSyncRouter"]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

# ---------------------------------------------------------------------------
# Logging
#
# Every line says which school it is about. On a platform whose entire shape is
# one schema per customer, "IntegrityError on membership save" is the same line
# from St Mary's and from Grace Academy, and the log could not tell them apart —
# so the first question anybody asks of an incident was the one question it
# could not answer.
#
# `SchoolContextFilter` reads the *connection*, not the request, so this is
# still right in a management command, a migration and an `on_commit` callback,
# where there is no request to read. It is attached to every handler rather than
# to the loggers, because a filter on a logger does not apply to records that
# propagate up from its children — and the lines worth labelling most are
# Django's own (`django.request`) and third-party ones, which nobody can go and
# edit a call site for.
#
# See schools/logging.py.
# ---------------------------------------------------------------------------
LOGGING = {
    "version": 1,
    # Emphatically not True. Django configures `django` and `django.server`
    # before this runs, and disabling existing loggers silences them for the
    # life of the process — including the request logger this section exists to
    # label.
    "disable_existing_loggers": False,
    "filters": {
        "school": {"()": "schools.logging.SchoolContextFilter"},
        "require_debug_false": {"()": "django.utils.log.RequireDebugFalse"},
    },
    "formatters": {
        "school_aware": {
            "format": "{levelname} {asctime} [{school}] {name} {message}",
            "style": "{",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "filters": ["school"],
            "formatter": "school_aware",
        },
        # The error report. Subclassed so the school reaches the *subject*,
        # which is the part visible in a mailbox list of forty of them.
        "mail_admins": {
            "class": "schools.logging.SchoolAdminEmailHandler",
            "level": "ERROR",
            "filters": ["require_debug_false", "school"],
            "include_html": True,
        },
    },
    "root": {
        "handlers": ["console"],
        "level": os.environ.get("LOG_LEVEL", "INFO"),
    },
    "loggers": {
        "django.request": {
            "handlers": ["console", "mail_admins"],
            "level": "ERROR",
            # False: the root handler would otherwise print every 500 twice.
            "propagate": False,
        }
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("TIME_ZONE", "Africa/Lagos")
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"

# ---------------------------------------------------------------------------
# Static files
#
# One server process serves the assets, through WhiteNoise, because this
# platform has no CDN and no separate web server in front of Django. The
# alternative is `runserver`'s static handler, which exists for development and
# says so.
#
# `STATIC_ROOT` is where `collectstatic` gathers them and the only directory
# WhiteNoise reads in production. It is deliberately outside the app tree, so a
# stale collected copy can never be mistaken for a source file.
STATIC_ROOT = BASE_DIR / "staticfiles"

# **One project-level tree, and this reverses what this comment said a change
# ago.** The report card page's assets started per-app, under
# `results/static/results/card/`, on the argument that an asset belongs to the
# app whose page loads it the way its template does. Two pages broke that:
#
# 1. The sign-in page and the card page share `esc()`. Two copies of an HTML
#    escaper is two places to fix an XSS and one of them will be missed, which
#    is the drift this codebase spends its review effort removing.
# 2. Per-app static makes the URL space and the disk layout diverge — the
#    finders merge `results/static/` and `accounts/static/` into one `/static/`
#    — so a relative `import` that is correct in a browser resolves to nothing
#    on disk. That breaks `node --test`, which has no finders and reads files.
#    The page's premise is ES modules with no build step, and that premise only
#    holds while one relative path means the same thing in both places.
#
# So `static/` mirrors what is served: `static/web/` for what every page shares,
# `static/card/`, `static/signin/`, `static/index/` for each page's own.
# `STATICFILES_DIRS` is what makes that tree visible to the finders.
STATICFILES_DIRS = [BASE_DIR / "static"]
#
# ## The hashed manifest, and why it is off in development
#
# `CompressedManifestStaticFilesStorage` renames every file to include a hash of
# its contents — `card.7f3c1e.js` — and rewrites `{% static %}` to match. That
# is what makes a far-future cache header safe: a changed file is a changed
# name, so no browser can hold yesterday's script against today's payload. It
# also pre-compresses, so the bytes on the wire are gzip/brotli without asking
# the CPU per request.
#
# It refuses to serve any file that is not in the manifest, and the manifest is
# written by `collectstatic` — which a test run and a `runserver` have not run.
# Under that storage `{% static %}` raises `ValueError: Missing staticfiles
# manifest entry` in development and in the test suite, and the failure looks
# like a broken template rather than an uncollected asset. So the manifest is
# conditioned on `DEBUG`: hashed and compressed where it is deployed, plain
# where nothing has collected anything.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

# ---------------------------------------------------------------------------
# Background work
#
# The reasoning — why a worker needs to be told which school it is working for,
# and what happens when it is not — is in `schools/tasks.py` and
# `docs/background.md`. These are the settings, which are the part a deployment
# changes.
#
# Everything Celery reads is namespaced `CELERY_` and comes from here rather
# than from a config file of its own, so a worker and a web process cannot
# disagree about the platform they are part of. See `celery_app.py`.
# ---------------------------------------------------------------------------

#: The broker. Defaults to the compose service name for the same reason
#: `POSTGRES_HOST` defaults to `db`: inside docker-compose that is the address,
#: and anywhere else this has to be set anyway.
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")

#: **Deliberately off.** A result backend is where `AsyncResult.get()` reads a
#: return value from, and nothing on this platform asks a task what it returned:
#: the PDF job's answer is a file plus a row recording it, which is in Postgres
#: where a parent's next request can find it. A backend would put the same
#: answer in a second place, in a key that expires, and make a task's success
#: something the broker remembers rather than something the database does.
#:
#: Turning it on is a deployment's call — `flower` and any other tool that
#: watches task states needs one — and **the switch is the environment variable
#: rather than this line.** Celery reads `CELERY_RESULT_BACKEND` from the
#: environment itself and that value outranks anything configured here, so this
#: assignment cannot override a set variable and evaluates to `None` when the
#: variable is unset, which is already the default. It is kept because it is
#: where a reader looks for the decision, not because it is the mechanism.
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND") or None

#: JSON only, in both directions. Celery 5 already defaults to this, and it is
#: pinned anyway because the failure it prevents is not a bug — it is remote
#: code execution: `pickle` in `accept_content` means anybody who can write to
#: the broker can hand the worker an object that runs on unpickling, and the
#: worker runs as the process that can reach every school's schema.
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_ACCEPT_CONTENT = ["json"]

CELERY_TIMEZONE = TIME_ZONE
CELERY_ENABLE_UTC = True

#: Acknowledge a job when it is *finished*, not when it is picked up, so a
#: worker killed mid-render — a deploy, an OOM kill — leaves the job on the
#: queue for another worker instead of silently dropping it. The price is that
#: a task must be safe to run twice, which for "render this frozen snapshot to
#: a file" it is: the snapshot cannot have changed, so the second run writes
#: the same bytes over the first. A task that is *not* idempotent must not be
#: written under this setting without saying so in its docstring.
CELERY_TASK_ACKS_LATE = True

#: **`acks_late` alone does not deliver the sentence above, and this is the
#: half that makes it true.** When the *child process* running a task is killed
#: by a signal — which is what an OOM kill and most deploy stops actually do —
#: Celery acknowledges the message anyway, marks the task `WorkerLostError`, and
#: the job is gone. `task_reject_on_worker_lost` is what sends it back to the
#: queue instead. It is a separate switch precisely because redelivering a task
#: whose process died is only safe when the task is idempotent, which is the
#: condition already stated above.
CELERY_TASK_REJECT_ON_WORKER_LOST = True

#: The other half. Redis has no broker-side notion of an unacknowledged
#: delivery, so kombu emulates one: a message reserved and not acked comes back
#: only after `visibility_timeout`, whose default is 3600 seconds. With that
#: default a parent waiting for a re-rendered card waits an hour, which is not
#: "another worker picks it up" in any sense a school would recognise. Five
#: minutes is longer than task 7's measured render by a wide margin and short
#: enough to be a retry rather than an outage.
#:
#: It must stay comfortably *above* the longest task runtime: a task still
#: running when its visibility timeout expires is redelivered to a second
#: worker while the first is still going, which is the duplicate-execution
#: failure the idempotence rule above is what saves us from.
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": 300}

#: With `acks_late` on, a worker that reserved ten long jobs and died would
#: hand all ten back at once. One at a time, so a redelivery is one job.
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

#: A worker started before Redis is accepting connections — which is the normal
#: order in docker-compose and in most orchestrators — should wait rather than
#: exit. Celery 6 makes this the default and warns when it is unset; setting it
#: here is what silences the warning as well as choosing the behaviour.
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
