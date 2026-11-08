"""The development-only single-host demo (`settings.DEMO_SINGLE_HOST`).

One question, asked in one place, so "is the demo mode on?" cannot be answered
two ways. It reads `DEBUG` as well as the flag: settings refuse the flag with
`DEBUG` off at start-up, and this is the second lock on the same door.

What the mode still changes: the forwarded host is trusted, and a sign-out goes
to a door on the same host. The doors themselves are on every school's host
now, demo or not (`docs/sign-in-page.md`, "A school's own door").
"""

from django.conf import settings


def single_host() -> bool:
    return bool(settings.DEBUG and getattr(settings, "DEMO_SINGLE_HOST", False))
