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
            created = create_school(
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
        self.stdout.write(f"{created.school.name} answers on https://{created.host}/")
        if created.link_to_hand_over is None:
            self.stdout.write(
                f"Its administrator was invited by email at {created.invitation.sent_to}."
            )
            return
        # No email provider: the operator is the delivery. The link is a
        # credential — it makes whoever opens it this school's administrator —
        # so it is written here, to the terminal of the person who ran this, and
        # nowhere else: not to a log, not to a file.
        self.stdout.write(
            "No email provider is configured, so nothing was sent.\n"
            f"Give this link to {created.invitation.sent_to} yourself. Until it is "
            f"used it makes whoever opens it {created.school.name}'s administrator, "
            f"and it stops working at {created.invitation.expires_at:%Y-%m-%d %H:%M %Z}:\n\n"
            f"  {created.link_to_hand_over}\n"
        )


def invitations_errors():
    from schools.delivery import DeliveryFailed, DeliveryNotConfigured, NoDeliveryAddress
    from schools.models import InvitationError

    return (DeliveryNotConfigured, DeliveryFailed, NoDeliveryAddress, InvitationError)
