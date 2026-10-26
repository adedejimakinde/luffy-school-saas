""""Add later" for the contact email and the crest on the first setup step.

Neither is needed for security. The contact email is the school's `Reply-To`
on mail Classnode sends for it and the address on its public page; nobody
signs in with it and no account is recovered through it. The crest heads the
report card, which prints the school's initials without one. So the office
may put either off, the step counts as done (`progress._is_done()`), and the
dashboard keeps a reminder card for each until it is given.

Who may: whoever may save them (`academics.services.can_set_up()`, the
principal and the administrator). Logged, like every setup change.
"""

from django.db import transaction
from django.utils import timezone

from academics.services import can_set_up
from audit import log

#: What can be put off, the `School` field that records it, and its name.
LATER = {
    "contact-email": ("contact_email_later_at", "contact email"),
    "crest": ("crest_later_at", "crest"),
}


class NotAllowedToPutOff(Exception):
    """The caller may not set this school up."""


class NothingToPutOff(Exception):
    """Not one of the things that can be added later."""


def put_off_as(actor, school, what: str):
    """Record that `school` will add `what` later. Saying it twice is one record."""
    if not can_set_up(actor, school):
        raise NotAllowedToPutOff(
            f"{actor} may not set up {school}. That is done by a principal or an administrator of the school."
        )
    if what not in LATER:
        raise NothingToPutOff(f"{what!r} is not something that can be added later.")
    column, name = LATER[what]
    from schools.models import School

    with transaction.atomic():
        now = timezone.now()
        changed = School.objects.filter(pk=school.pk, **{f"{column}__isnull": True}).update(**{column: now})
        if changed:
            setattr(school, column, now)
            log.record(
                actor, school,
                action="put-off", kind=what, item_name=school.name,
                summary=f"Chose to add the {name} later.",
            )
    return school


__all__ = ["LATER", "NotAllowedToPutOff", "NothingToPutOff", "put_off_as"]
