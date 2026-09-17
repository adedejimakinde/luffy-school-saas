"""Deployment checks for things that are only wrong on the second host.

Registered with `deploy=True`, so these run under `manage.py check --deploy`
and stay out of the way of ordinary development and the test suite — which is
the right trade for a rule about production hostnames.
"""

from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.security, deploy=True)
def session_cookie_spans_every_host(app_configs, **kwargs):
    """`SESSION_COOKIE_DOMAIN` must be set once there is more than one host.

    Sign-in happens on the portal host and the work happens on a school's host.
    A cookie set without a Domain attribute goes back only to the host that set
    it, so leaving this unset produces the most expensive kind of bug: sign-in
    succeeds, returns 200, sets a cookie, and the very next request — to the
    school the person was signing in to reach — arrives unauthenticated. Every
    part of that looks like it worked.

    Refused at deploy rather than caught at runtime because the platform cannot
    tell the two situations apart from inside a single request: "no cookie yet"
    and "cookie that will never be sent here" are the same absence.
    """
    if settings.SESSION_COOKIE_DOMAIN:
        return []
    return [
        Error(
            "SESSION_COOKIE_DOMAIN is not set, so a session opened on the "
            "portal host will not be sent to any school's host.",
            hint=(
                "Set it to the parent domain of every host this platform "
                "answers on, with a leading dot — for example '.luffy.school'. "
                "A deployment that genuinely serves one host only may set it to "
                "that host."
            ),
            id="accounts.E001",
        )
    ]


@register(Tags.security)
def a_guardian_session_cannot_outlive_the_dormancy_window(app_configs, **kwargs):
    """`GUARDIAN_SESSION_AGE` must be shorter than `GUARDIAN_DORMANCY_DAYS`.

    Dormancy is read lazily, at the moment a code is asked for — the same shape
    `Invitation.validate_token()` argues for, and the reason this rule needs no
    cron job. The consequence is that it binds *new codes* and not sessions
    already open, so a dormant guardian keeps whatever session they are holding
    until it lapses on its own.

    With the defaults that is harmless: a thirty-day sliding session cannot
    survive a hundred and eighty idle days, so by the time a channel is dormant
    there is no session left to suspend. But that is a coincidence of two
    numbers rather than a guard, and each of them is an environment variable
    somebody can raise on a Friday. Written down here, it becomes a guard.

    Not `deploy=True`, unlike `accounts.E001`. That one is a fact about
    production hostnames and has nothing to say in development; this is a
    relationship between two settings, and it is wrong in every environment
    where it is wrong.
    """
    dormancy = settings.GUARDIAN_DORMANCY_DAYS * 24 * 60 * 60
    if settings.GUARDIAN_SESSION_AGE < dormancy:
        return []
    return [
        Error(
            f"GUARDIAN_SESSION_AGE ({settings.GUARDIAN_SESSION_AGE}s) is not "
            f"shorter than GUARDIAN_DORMANCY_DAYS "
            f"({settings.GUARDIAN_DORMANCY_DAYS} days = {dormancy}s), so a "
            "session opened before a channel went dormant outlives the "
            "suspension that dormancy is supposed to be.",
            hint=(
                "Lower GUARDIAN_SESSION_AGE, or raise GUARDIAN_DORMANCY_DAYS. "
                "Dormancy is read when a code is requested, so it cannot reach "
                "a session that is already open — the session has to expire "
                "first, and that only happens if it is the shorter of the two."
            ),
            id="accounts.E002",
        )
    ]
