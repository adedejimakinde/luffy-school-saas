"""`manage.py load_demo` — the fictional demo schools, on a demo server.

The same two schools, children, terms, fees and logins as `seed_demo` (this is
its code, `_school()` and all), for a server that is not a development machine
and so runs with `DEBUG` off.

**Refuses unless `DEMO_SERVER=1` is set.** That is the one thing that says "this
server holds nothing real and is meant to": without it a production deploy that
somebody ran this on by mistake would get twenty fake children per school and
logins for every role. It is not read from a flag, so it cannot be typed into a
command by accident; it is set in the environment the demo server's containers
get (`docs/demo-server.md`).

**The password comes from `LOAD_DEMO_PASSWORD`, and there is no default.** The
development default is published in this repository, which makes it no password
at all on a server anyone can reach. It must be at least 12 characters, is
never taken from an argument (it would sit in shell history and the process
list) and is never printed.

**No family is told and no phone number is stored.** `seed_demo` releases JSS
1B's results and sends the notice through the fake provider to a real-shaped
phone number; with `DEBUG` off there is no fake provider (`messaging.E001`),
and a real one must never be handed that number. Here the release is made and
nobody is messaged, and the demo parent has no phone on file, so the parent
page is shown from the staff side rather than signed into by code.

**Refuses to run twice**, as `seed_demo` does.
"""

import os

from django.core.management.base import CommandError

from .seed_demo import Command as SeedDemo

MIN_PASSWORD = 12


class Command(SeedDemo):
    help = "Create the two fictional demo schools on a demo server (DEMO_SERVER=1, LOAD_DEMO_PASSWORD)."
    tell_families = False

    def add_arguments(self, parser):
        parser.add_argument(
            "--domain-suffix",
            default=None,
            help="Each school answers on <slug>.<suffix>. Defaults to PLATFORM_DOMAIN.",
        )

    def handle(self, *args, domain_suffix, **options):
        from django.conf import settings

        if os.environ.get("DEMO_SERVER") != "1":
            raise CommandError(
                "load_demo only runs on a demo server: set DEMO_SERVER=1 in its "
                "environment. It writes fake children and logins for every role."
            )
        password = os.environ.get("LOAD_DEMO_PASSWORD", "")
        if len(password) < MIN_PASSWORD:
            raise CommandError(
                f"Set LOAD_DEMO_PASSWORD to a password of at least {MIN_PASSWORD} "
                "characters. There is no default: a published one is no password."
            )
        suffix = domain_suffix or settings.PLATFORM_DOMAIN
        if not suffix:
            raise CommandError("Set PLATFORM_DOMAIN, or pass --domain-suffix.")
        self.seed(password, suffix)

    def password_line(self, password):
        return "\nEvery login has the password you set in LOAD_DEMO_PASSWORD.\n"
