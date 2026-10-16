"""Make a login a writer or an editor of Classnode's blog, or stop it being one.

    python manage.py blog_account kemi@example.com --name "Kemi Oladipo" --role writer
    python manage.py blog_account tunde@example.com --role editor
    python manage.py blog_account kemi@example.com --remove

A blog account is a login of its own (`docs/blog.md`): it signs in with a code
sent to its email, has no password, and reaches the blog and nothing else.
So an address that already belongs to platform staff, or to anybody with a
membership at a school, is refused here, in a sentence, before Postgres
refuses it in a constraint. Use another address (a `+blog` one works) for the
blog.

Nothing is created by any other command or migration: the blog ships with no
writers and no posts.
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import Membership, User
from blog.models import Role


class Command(BaseCommand):
    help = "Make a login a writer or an editor of the blog, or remove it."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("--name", default="")
        parser.add_argument("--role", choices=[Role.WRITER, Role.EDITOR])
        parser.add_argument("--remove", action="store_true")

    @transaction.atomic
    def handle(self, email, name, role, remove, **options):
        email = email.strip().lower()
        user = User.objects.filter(email__iexact=email).first()

        if remove:
            if user is None or not user.blog_role:
                raise CommandError(f"{email} is not a blog account.")
            user.blog_role = ""
            user.is_active = False
            user.save(update_fields=["blog_role", "is_active"])
            self.stdout.write(f"{email} is no longer a blog account, and cannot sign in.")
            return

        if role is None:
            raise CommandError("Say --role writer or --role editor, or --remove.")

        if user is None:
            if not name.strip():
                raise CommandError("A new account needs --name.")
            user = User(username=email, email=email, full_name=name.strip(), blog_role=role)
            user.set_unusable_password()
            user.save()
            self.stdout.write(f"{name.strip()} ({email}) is now a blog {role}.")
            return

        if user.is_platform_staff or user.is_superuser:
            raise CommandError(
                f"{email} is platform staff. A blog account reaches the blog and nothing else, "
                "so use another address for it."
            )
        if Membership.objects.filter(user=user).exists():
            raise CommandError(
                f"{email} belongs to somebody at a school. A blog account reaches the blog and "
                "nothing else, so use another address for it."
            )
        user.blog_role = role
        user.is_active = True
        if name.strip():
            user.full_name = name.strip()
        user.save(update_fields=["blog_role", "is_active", "full_name"])
        self.stdout.write(f"{user.full_name} ({email}) is now a blog {role}.")
