"""`manage.py crestfield create` and `manage.py crestfield reset`: Classnode's demo school.

Crestfield College, Abeokuta (Demo), on the production server beside real
schools, for sales visits. What is in it and what keeps it apart from the real
schools is `schools.crestfield`; how to run this on the server is
`docs/demo-school.md`.

- **`create`** makes it once: the school, its schema, `crestfield.<domain>`,
  its people and its first term. Refuses if any of that is already here.
- **`reset`** puts it back exactly as `create` left it, today's dates, before a
  visit. It drops and rebuilds the demo's own schema and nothing else, and
  refuses unless the school called `crestfield` is the one `create` made.

**Passwords come from the environment, never from an argument** (shell history
and the process list keep arguments) and are never printed: `CRESTFIELD_PRINCIPAL_PASSWORD`,
`CRESTFIELD_TEACHER_PASSWORD`, `CRESTFIELD_PARENT_PASSWORD`, twelve characters or
more. `create` needs all three; `reset` sets the ones given and keeps the rest.
Nobody else at the school can sign in.
"""

import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from schools import crestfield


class Command(BaseCommand):
    help = "Create Crestfield College, Classnode's demo school, or reset it to its starting state."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("create", "reset"))
        parser.add_argument(
            "--domain-suffix",
            default=None,
            help="It answers on crestfield.<suffix>. Defaults to PLATFORM_DOMAIN. create only.",
        )

    def handle(self, *args, action, domain_suffix, **options):
        passwords = {key: os.environ.get(variable, "") for key, variable in crestfield.SIGN_INS.items()}
        write = self.stdout.write
        try:
            if action == "create":
                suffix = domain_suffix or settings.PLATFORM_DOMAIN
                if not suffix:
                    raise CommandError("Set PLATFORM_DOMAIN, or pass --domain-suffix.")
                crestfield.create(passwords, suffix, write=write)
            else:
                crestfield.reset(passwords, write=write)
        except crestfield.Refused as exc:
            raise CommandError(str(exc)) from exc
        write(
            "\nDone. The sign-ins above take the passwords in CRESTFIELD_*_PASSWORD. "
            "No email or text leaves for this school."
        )
        write(
            "The question bank (30 questions in schools/crestfield/questions.py) is not loaded: "
            "the bank is CBT step 3, which is not built yet."
        )
