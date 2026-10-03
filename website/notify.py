"""Telling platform staff a school asked for a demo."""

import logging
import smtplib

from django.conf import settings
from django.core.mail import EmailMessage

from accounts.models import User

logger = logging.getLogger(__name__)

#: As `schools.delivery.EmailChannel.NETWORK_BACKENDS`: the one backend that
#: needs `EMAIL_HOST` to point somewhere before it can send anything.
_NETWORK_BACKENDS = ("django.core.mail.backends.smtp.EmailBackend",)


def staff_addresses():
    """Every active platform staff login with an email address."""
    return sorted(
        User.objects.filter(is_platform_staff=True, is_active=True, email__isnull=False)
        .exclude(email="")
        .values_list("email", flat=True)
    )


def demo_requested(request_id):
    """Email platform staff one demo request. Run after the row has committed.

    Never raises: the request is saved, and the admin lists it whether or not
    this arrives. A send that fails is logged with its cause, for the reason
    `schools.delivery.EmailChannel.send()` gives for catching only `OSError`
    and `SMTPException`.
    """
    from .models import DemoRequest

    demo = DemoRequest.objects.filter(pk=request_id).first()
    if demo is None:
        return
    to = staff_addresses()
    if not to:
        logger.warning("Demo request %s saved; no platform staff has an email address.", demo.pk)
        return
    if settings.EMAIL_BACKEND in _NETWORK_BACKENDS and not getattr(settings, "EMAIL_HOST", ""):
        logger.warning("Demo request %s saved; no EMAIL_HOST to send it with.", demo.pk)
        return
    lines = [
        f"Name: {demo.name}",
        f"School: {demo.school}",
        f"Phone: {demo.phone}",
        f"Email: {demo.email or 'not given'}",
        f"Students: {demo.students}",
        f"Sent: {demo.created_at:%Y-%m-%d %H:%M} UTC",
    ]
    message = EmailMessage(
        subject=f"Demo request: {demo.school}",
        body="\n".join(lines) + "\n",
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        to=to,
        reply_to=[demo.email] if demo.email else None,
    )
    try:
        message.send(fail_silently=False)
    except (OSError, smtplib.SMTPException):
        logger.exception("Demo request %s saved; emailing platform staff failed.", demo.pk)
