"""List admission numbers shared by more than one child at a school, changing nothing.

The check `accounts/migrations/0021_...` runs before it adds the unique index,
runnable on its own so a server can be looked at before a deploy. Exits 1 when
any number is shared, so a script can stop on it.
"""

from django.core.management.base import BaseCommand

from accounts import admission_numbers


class Command(BaseCommand):
    help = "List admission numbers shared by more than one child at one school."

    def handle(self, *args, **options):
        found = admission_numbers.clashes()
        if not found:
            self.stdout.write("No admission number is shared by two children at any school.")
            return
        self.stdout.write(admission_numbers.clash_report(found))
        raise SystemExit(1)
