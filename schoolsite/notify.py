"""Telling a school's principal that its website draft is ready for them. `docs/school-sites.md` §2.4.

When the administrator the principal has let edit marks the draft "Ready for the
principal", every active principal of that school with an email address is sent
a link to the preview on the school's own address. Only that school's: the
principals are read from its memberships, and the link is its own host's. Sent
after the mark commits (`services.mark_ready_as`), so a mark that rolls back
sends nothing, and never raises: the mark is saved and shown in the editor
whether or not the email arrives.
"""

import logging
import smtplib

from django.conf import settings
from django.core.mail import EmailMessage

from accounts.models import Membership, Role
from schools.models import Domain, School

logger = logging.getLogger(__name__)

#: As `website.notify`: the one backend that needs `EMAIL_HOST` before it can send.
_NETWORK_BACKENDS = ("django.core.mail.backends.smtp.EmailBackend",)

#: The draft's preview, on the school's own host (`schoolsite.views.preview`).
PREVIEW_PATH = "/website/preview/"


def principal_addresses(school) -> list:
    """The email addresses of this school's principals whose membership gives access today."""
    return sorted(
        {
            email
            for email in Membership.objects.with_access()
            .filter(school=school, role=Role.PRINCIPAL, user__is_active=True)
            .values_list("user__email", flat=True)
            if email
        }
    )


def preview_url(school) -> str:
    """The preview on the school's own primary address, or "" if it has none."""
    host = (
        Domain.objects.filter(tenant=school, is_primary=True).values_list("domain", flat=True).first()
        or Domain.objects.filter(tenant=school).values_list("domain", flat=True).first()
    )
    return f"https://{host}{PREVIEW_PATH}" if host else ""


def ready(school_id, by_name, note=""):
    """Email this school's principals that the draft is ready. Run after the mark has committed."""
    school = School.objects.filter(pk=school_id).first()
    if school is None:
        return
    to = principal_addresses(school)
    link = preview_url(school)
    if not to or not link:
        logger.warning("Website draft of %s marked ready; no principal address or no host to send to.", school.pk)
        return
    if settings.EMAIL_BACKEND in _NETWORK_BACKENDS and not getattr(settings, "EMAIL_HOST", ""):
        logger.warning("Website draft of %s marked ready; no EMAIL_HOST to send it with.", school.pk)
        return
    lines = [
        f"{by_name} has marked {school.name}'s website draft ready for you to check and publish.",
        "",
        f"See it as it will look: {link}",
        "",
        "Nothing changes on the website until you press Publish.",
    ]
    if note:
        lines[1:1] = ["", f"Their note: {note}"]
    # One message each, so a school with two principals does not hand each the other's address.
    for address in to:
        message = EmailMessage(
            subject=f"{school.name}: the website draft is ready for you",
            body="\n".join(lines) + "\n",
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            to=[address],
        )
        try:
            message.send(fail_silently=False)
        except (OSError, smtplib.SMTPException):
            logger.exception("Website draft of %s marked ready; emailing a principal failed.", school.pk)


__all__ = ["PREVIEW_PATH", "principal_addresses", "preview_url", "ready"]
