"""`manage.py create_school <slug> "<name>" --admin-email … --operator …`

Builds the school's schema, gives it `<slug>.PLATFORM_DOMAIN`, and invites its
first administrator. All of it or none of it — see `schools/onboarding.py`.
"""

from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from schools.onboarding import OnboardingError, create_school


class Command(BaseCommand):
    help = "Create a school, its schema and host, and invite its first administrator."

    def add_arguments(self, parser):
        parser.add_argument("slug", help="The school's subdomain, e.g. stmarys")
        parser.add_argument("name", help="The school's name, as it prints")
        parser.add_argument("--admin-email", required=True)
        parser.add_argument("--admin-name", default="")
        parser.add_argument(
            "--operator",
            required=True,
            help="Username of the platform-staff account the invitation is sent from",
        )

    def handle(self, *args, **options):
        operator = User.objects.filter(username=options["operator"]).first()
        if operator is None:
            raise CommandError(f"No account {options['operator']!r}.")
        try:
            school, host, invitation = create_school(
                slug=options["slug"],
                name=options["name"],
                admin_email=options["admin_email"],
                admin_name=options["admin_name"],
                operator=operator,
            )
        except OnboardingError as exc:
            raise CommandError(str(exc)) from exc
        except invitations_errors() as exc:
            raise CommandError(f"Nothing was created: {exc}") from exc
        self.stdout.write(
            f"{school.name} answers on https://{host}/ ; its administrator was "
            f"invited at {invitation.sent_to}."
        )


def invitations_errors():
    from schools.delivery import DeliveryFailed, DeliveryNotConfigured, NoDeliveryAddress
    from schools.models import InvitationError

    return (DeliveryNotConfigured, DeliveryFailed, NoDeliveryAddress, InvitationError)
