"""The background job that closes attempts nobody reads after their time is over.

`docs/cbt.md`, "Offline": the server closes an attempt at `deadline + late_window`
whatever the device does. Until step 5 that close was written only when something read
or wrote the attempt (`sitting.settle()`, asked by every sync, door, log read and send),
so an attempt whose computer never came back stayed open in the table until somebody
looked. This walks every school and settles every approved test's overdue attempts.

**Each close is stamped when it was due**, not when the job ran (`settle()` closes at
`closes_for_good_at()`), so a run an hour late writes the same rows a run on time would
have. Running it twice writes nothing the second time: an attempt is closed once (the
database's `an_attempt_is_closed_once`).
"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone


def close_overdue(now=None) -> int:
    """Close every school's attempts whose time and late window are over. How many."""
    from django_tenants.utils import get_public_schema_name, tenant_context

    from schools.models import School

    from . import sitting
    from .models import Attempt, Test

    now = now or timezone.now()
    closed = 0
    for school in School.objects.exclude(schema_name=get_public_schema_name()).order_by("pk"):
        with tenant_context(school):
            # The earliest any attempt can be due is its base deadline plus the shortest
            # window, so this reads only tests with an attempt that might be.
            tests = Test.objects.filter(
                state=Test.State.PUBLISHED, attempts__submitted_at__isnull=True, attempts__base_deadline__lte=now
            ).distinct()
            for test in tests:
                with transaction.atomic():
                    before = Attempt.objects.filter(test=test, submitted_at__isnull=True).count()
                    sitting.settle_all(test, now)
                    closed += before - Attempt.objects.filter(test=test, submitted_at__isnull=True).count()
    return closed


__all__ = ["close_overdue"]
