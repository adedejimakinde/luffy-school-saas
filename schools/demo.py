"""The development-only single-host demo (`settings.DEMO_SINGLE_HOST`).

One question, asked in one place, so "is the demo mode on?" cannot be answered
two ways. It reads `DEBUG` as well as the flag: settings refuse the flag with
`DEBUG` off at start-up, and this is the second lock on the same door.
"""

from functools import wraps

from django.conf import settings
from django.http import Http404


def single_host() -> bool:
    return bool(settings.DEBUG and getattr(settings, "DEMO_SINGLE_HOST", False))


def only_in_the_single_host_demo(view):
    """A view that is a 404 unless the demo mode is on, decided per request.

    Per request rather than per urlconf so that the answer is the setting's at
    the time, and a test can show both without reloading routes.
    """

    @wraps(view)
    def guarded(request, *args, **kwargs):
        if not single_host():
            raise Http404("Sign in on the portal host.")
        return view(request, *args, **kwargs)

    return guarded
