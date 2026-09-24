"""`manage.py setup_portal` — make the portal answer on PORTAL_HOST. Safe to re-run."""

from django.core.management.base import BaseCommand, CommandError

from schools.onboarding import OnboardingError, setup_portal


class Command(BaseCommand):
    help = "Create the portal's tenant row and its Domain on PORTAL_HOST."

    def handle(self, *args, **options):
        try:
            _, host = setup_portal()
        except OnboardingError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"The portal answers on https://{host}/")
