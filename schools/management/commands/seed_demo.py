"""`manage.py seed_demo` — two fake schools to click through. Development only.

Each school gets a current term and the one before it, two classes of ten
children, three subjects with first-CA marks, two weeks of registers, a term's
fees with payments, a discount and one family in credit, and one login per
role: administrator, principal, vice principal (academic), teacher, bursar and
parent (of two children). Everybody's password is the one printed at the end.

**Refuses unless `DEBUG` is on.** Fake children with a published password have
no business in a real deployment, and `DEBUG` is the one switch this project
already ties "this is not production" to (`settings.py`).

**Refuses to run twice** rather than guessing what a second run should do to
the first run's data. Reset a development database to start again.

Each school's host is `<slug>.<--domain-suffix>` — `localhost` unless given.
Pointing a school at a forwarded address is a change to its `Domain` row made
where the demo is served, not something this command knows about.
"""

import random
from datetime import date, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django_tenants.utils import schema_context

from academics import services as academics
from academics.models import ClassGroup, Term, TermName
from accounts.models import Role, User
from accounts.services import (
    activate_guardian_links,
    enroll_student,
    grant_membership,
    link_guardian,
)
from attendance import services as attendance
from fees import services as fees
from fees.models import KOBO_PER_NAIRA, PaymentMethod
from gradebook import services as gradebook
from gradebook.models import Assessment, Subject
from schools.models import Domain, School

SCHOOLS = (
    ("sunrise-demo", "Sunrise Demo Academy"),
    ("harbour-demo", "Harbour Demo College"),
)

#: The staff logins, one per role, per school: `<school prefix>.<key>`.
STAFF = (
    ("admin", Role.ADMIN, "Administrator"),
    ("principal", Role.PRINCIPAL, "Principal"),
    ("vp", Role.VICE_PRINCIPAL_ACADEMIC, "Vice Principal"),
    ("teacher", Role.TEACHER, "Teacher"),
    ("bursar", Role.BURSAR, "Bursar"),
)

FIRST_NAMES = (
    "Ada", "Bayo", "Chidi", "Dayo", "Efe", "Funmi", "Gbenga", "Halima", "Ife", "Jide",
    "Kemi", "Lola", "Musa", "Ngozi", "Obi", "Pelumi", "Rukky", "Segun", "Tolu", "Uche",
)
SURNAMES = ("Adeyemi", "Bello", "Chukwu", "Danjuma", "Eze", "Falana", "Garba", "Hassan", "Ibe", "Johnson")

SUBJECTS = (("Mathematics", "MTH"), ("English Language", "ENG"), ("Basic Science", "BSC"))
TUITION = 150_000 * KOBO_PER_NAIRA
DEFAULT_PASSWORD = "demo-pass-2026"


def _weekdays(start, end):
    day = start
    while day <= end:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


class Command(BaseCommand):
    help = "Create two fake schools with a term's worth of data. Development only."

    def add_arguments(self, parser):
        parser.add_argument("--password", default=DEFAULT_PASSWORD)
        parser.add_argument(
            "--domain-suffix",
            default=settings.PLATFORM_DOMAIN or "localhost",
            help="Each school answers on <slug>.<suffix>.",
        )

    def handle(self, *args, password, domain_suffix, **options):
        if not settings.DEBUG:
            raise CommandError(
                "seed_demo only runs with DEBUG on: it writes fake children and "
                "a published password."
            )
        taken = [slug for slug, _ in SCHOOLS if School.objects.filter(slug=slug).exists()]
        if taken:
            raise CommandError(
                f"The demo is already here ({', '.join(taken)}). Reset the "
                f"development database to seed it again."
            )

        logins = []
        for slug, name in SCHOOLS:
            logins += self._school(slug, name, password, domain_suffix)

        self.stdout.write(f"\nEvery password: {password}\n")
        for school, username, role in logins:
            self.stdout.write(f"  {school:<22} {role:<28} {username}")

    # -------------------------------------------------------------------------

    def _school(self, slug, name, password, suffix):
        prefix = slug.split("-")[0]
        rng = random.Random(slug)
        school = School(name=name, slug=slug, schema_name=slug.replace("-", "_"))
        school.save()  # CREATE SCHEMA and migrate, the real way
        host = f"{slug}.{suffix}"
        Domain.objects.create(tenant=school, domain=host, is_primary=True)
        self.stdout.write(f"{name}: http://{host}/  (schema {school.schema_name})")

        def login(key, full_name):
            return User.objects.create_user(f"{prefix}.{key}", password, full_name=full_name)

        with transaction.atomic():
            staff = {
                key: grant_membership(login(key, f"{label} {name.split()[0]}"), school, role)
                for key, role, label in STAFF
            }
            children = []
            for i in range(20):
                user = login(f"s{i + 1:02d}", f"{FIRST_NAMES[i]} {rng.choice(SURNAMES)}")
                children.append(enroll_student(user, school, reference=f"{prefix[:3].upper()}/{i + 1:03d}"))
            parent = login("parent", f"Parent {name.split()[0]}")
            for child in children[:2]:
                link_guardian(parent, child)
            # `link_guardian()` grants INVITED until the guardian answers the
            # school's code, and this is what answering does. A demo parent has
            # no phone to answer with, and an INVITED one can open nothing.
            activate_guardian_links(parent, school)

        logins = [(name, u.user.username, label) for (key, _, label), u in zip(STAFF, staff.values())]
        logins.append((name, parent.username, f"Parent (of {children[0].name}, {children[1].name})"))

        with schema_context(school.schema_name), transaction.atomic():
            self._term_data(staff, children, rng)
        return logins

    def _term_data(self, staff, children, rng):
        today = timezone.localdate()
        # The term is the one running today, so every "current term" screen has
        # something to show; the previous one exists so a copy has a source.
        starts = today - timedelta(days=today.weekday()) - timedelta(weeks=2)
        academics.create_term(
            f"{starts.year - 1}/{starts.year}", TermName.THIRD,
            starts - timedelta(weeks=20), starts - timedelta(weeks=8),
        )
        term = academics.create_term(
            f"{starts.year}/{starts.year + 1}", TermName.FIRST, starts, starts + timedelta(weeks=12),
        )
        academics.set_current_term(term)

        groups = [ClassGroup.objects.create(name=n, level=1) for n in ("JSS 1A", "JSS 1B")]
        placed = {groups[0]: children[:10], groups[1]: children[10:]}
        for group, members in placed.items():
            for child in members:
                academics.place_student(group, term, child)
        academics.assign_class_teacher(groups[0], term, staff["teacher"])

        # Marks: a first CA in every subject, and an exam nobody has sat yet.
        for position, (subject_name, code) in enumerate(SUBJECTS):
            subject = Subject.objects.create(name=subject_name, code=code)
            ca = Assessment.objects.create(term=term, subject=subject, name="First CA", max_score=20, position=0)
            Assessment.objects.create(term=term, subject=subject, name="Exam", max_score=60, position=1)
            for child in children:
                gradebook.set_score(ca, child, rng.randint(6, 20), by=staff["teacher"].user)

        # Two weeks of registers. Children 3 and 14 are away often enough to be
        # on the principal's absence list.
        days = [d for d in _weekdays(starts, today)][:10]
        for group, members in placed.items():
            for day in days:
                away = [c.pk for c in members if (c in (children[2], children[13]) and rng.random() < 0.5)
                        or rng.random() < 0.05]
                attendance.take_register(group, term, on=day, absent_ids=away, by=staff["teacher"].user)

        # The term's fees: everybody charged; a spread of payments; one discount
        # with its reason; and one family that overpaid, so "In credit" shows.
        bursar = staff["bursar"].user
        methods = [PaymentMethod.CASH, PaymentMethod.BANK_TRANSFER, PaymentMethod.POS, PaymentMethod.CHEQUE]
        for i, child in enumerate(children):
            fees.charge(child, term, TUITION, narration="First term tuition", recorded_by=bursar)
            if i % 3 == 2:
                continue  # owes the lot
            method = methods[i % len(methods)]
            amount = TUITION if i % 3 == 0 else TUITION // 2
            if i == 0:
                amount = TUITION + 20_000 * KOBO_PER_NAIRA  # in credit
            fees.record_payment(
                child, term, amount,
                method=method,
                reference=f"TRF-{rng.randint(100000, 999999)}" if method == PaymentMethod.BANK_TRANSFER else "",
                effective_on=days[min(i, len(days) - 1)] if days else None,
                recorded_by=bursar,
            )
        fees.discount(children[1], term, 25_000 * KOBO_PER_NAIRA, narration="Second child in the school", recorded_by=bursar)
