"""The first sign-in, recorded once.

`User.first_signed_in_at` is what the first-day cards count their fourteen
days from (`onboarding.first`) and what the handover page reads as "signed in
once" (`onboarding.handover`). Django's own `last_login` moves on every
sign-in, so it cannot answer either question.

One conditional UPDATE per sign-in, on the row Django's `update_last_login`
has just written: it matches nothing once the column is set.
"""

from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver
from django.utils import timezone


@receiver(user_logged_in, dispatch_uid="onboarding.first_sign_in")
def note_first_sign_in(sender, request, user, **kwargs):
    if getattr(user, "first_signed_in_at", None) is not None:
        return
    now = timezone.now()
    type(user).objects.filter(pk=user.pk, first_signed_in_at__isnull=True).update(first_signed_in_at=now)
    user.first_signed_in_at = now
