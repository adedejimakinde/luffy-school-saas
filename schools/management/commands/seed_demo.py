"""`manage.py seed_demo` — two fake schools to click through. Development only.

Each school gets a current term, the one before it and an empty one after it
(for "copy last term"), two classes of ten children, three subjects with
first-CA marks, a week's timetable with a double period, a combined lesson and
a free period, two weeks of registers, and a term's fees: each class's bill
applied, one line added since that nobody has been charged yet, a standing
concession and a revoked one, payments, a discount and one family in credit.
JSS 1B's first-CA results are walked through the chain and released, with a
principal's remark on each card, so a parent has a card to open; JSS 1A's stay
in draft, so a teacher has a sheet left to mark. Result notices are turned on
and told for JSS 1B's release, to a verified phone the demo parent already
holds, so the fake outbox (`/dev/outbox/`) has a real message in it too.
One login per role — administrator, principal, vice principal (academic),
teacher, bursar and parent (of two children, one in each class, so the parent
page shows one child with a card and one without) — and two more teachers, so
each subject has its own. Everybody's password is the one printed at the end.

**Refuses unless `DEBUG` is on.** Fake children with a published password have
no business in a real deployment, and `DEBUG` is the one switch this project
already ties "this is not production" to (`settings.py`).

**Refuses unless the phone channel's provider is the fake one.** The parent's
phone number is a real number's shape (`messaging.fake` is the one place that
is safe), and this command calls `tell_families()`: a deploy whose
`MESSAGING_PHONE_PROVIDER` points at Termii, `DEBUG` on or not, must never be
handed a real send to a number nobody here asked for.

**Refuses to run twice** rather than guessing what a second run should do to
the first run's data. Reset a development database to start again.

Each school's host is `<slug>.<--domain-suffix>` — `localhost` unless given.
Pointing a school at a forwarded address is a change to its `Domain` row made
where the demo is served, not something this command knows about.
"""

import random
import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from django_tenants.utils import schema_context

from academics import services as academics
from academics.models import ClassGroup, Term, TermName
from accounts.models import ContactChannel, GuardianAccount, GuardianContact, Role, User
from accounts.services import (
    activate_guardian_links,
    enroll_student,
    grant_membership,
    link_guardian,
)
from attendance import services as attendance
from fees import billing
from fees import services as fees
from fees.models import KOBO_PER_NAIRA, PaymentMethod
from gradebook import services as gradebook
from gradebook.models import Assessment, Subject
from messaging.fake import FakeProvider
from messaging.providers import provider_for
from schools.models import Domain, School
from timetable import services as timetable
from timetable.models import Weekday

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

#: Two more teachers, so the timetable has a teacher per subject: the one in
#: `STAFF` teaches mathematics, these the other two. `<school prefix>.<key>`.
MORE_TEACHERS = (
    ("english", "English Teacher"),
    ("science", "Science Teacher"),
)

FIRST_NAMES = (
    "Ada", "Bayo", "Chidi", "Dayo", "Efe", "Funmi", "Gbenga", "Halima", "Ife", "Jide",
    "Kemi", "Lola", "Musa", "Ngozi", "Obi", "Pelumi", "Rukky", "Segun", "Tolu", "Uche",
)
SURNAMES = ("Adeyemi", "Bello", "Chukwu", "Danjuma", "Eze", "Falana", "Garba", "Hassan", "Ibe", "Johnson")

SUBJECTS = (("Mathematics", "MTH"), ("English Language", "ENG"), ("Basic Science", "BSC"))
TUITION = 150_000 * KOBO_PER_NAIRA
LEVY = 15_000 * KOBO_PER_NAIRA
DEFAULT_PASSWORD = "demo-pass-2026"

#: The demo parent's phone, already verified: nobody clicks through code
#: delivery to seed a demo. A real number's shape, `identifiers.normalize_phone`
#: stores it as E.164.
PARENT_PHONE = "08031234567"

LAGOS = ZoneInfo("Africa/Lagos")


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
        if not isinstance(provider_for("phone"), FakeProvider):
            raise CommandError(
                "seed_demo only runs with the fake message provider on the phone "
                "channel: it tells families about a release, to a real-shaped "
                "phone number, and this deploy's MESSAGING_PHONE_PROVIDER is "
                "something else. That number could belong to somebody; the demo "
                "must never hand it to a real provider."
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
            teachers = {
                key: grant_membership(login(key, f"{label} {name.split()[0]}"), school, Role.TEACHER)
                for key, label in MORE_TEACHERS
            }
            children = []
            for i in range(20):
                user = login(f"s{i + 1:02d}", f"{FIRST_NAMES[i]} {rng.choice(SURNAMES)}")
                children.append(enroll_student(user, school, reference=f"{prefix[:3].upper()}/{i + 1:03d}"))
            parent = login("parent", f"Parent {name.split()[0]}")
            # One child in each class: JSS 1B's results are released below and
            # JSS 1A's are not, so the parent page shows both a card and a
            # child with none yet.
            for child in (children[0], children[10]):
                link_guardian(parent, child)
            # `link_guardian()` grants INVITED until the guardian answers the
            # school's code, and this is what answering does. A demo parent has
            # no phone to answer with, and an INVITED one can open nothing.
            activate_guardian_links(parent, school)
            # A verified channel too, written directly rather than clicked
            # through code delivery, so "tell families" below has somewhere
            # real to land: `GuardianContact` only refuses a channel changing
            # after it is written, not a verified one arriving with it.
            account, _ = GuardianAccount.objects.get_or_create(user=parent)
            GuardianContact.objects.create(
                guardian=account,
                channel_type=ContactChannel.PHONE,
                value=PARENT_PHONE,
                created_by=staff["admin"].user,
                verified_at=timezone.now(),
            )

        logins = [(name, u.user.username, label) for (key, _, label), u in zip(STAFF, staff.values())]
        logins += [(name, u.user.username, label) for (key, label), u in zip(MORE_TEACHERS, teachers.values())]
        logins.append((name, parent.username, f"Parent (of {children[0].name}, {children[10].name})"))

        with schema_context(school.schema_name), transaction.atomic():
            self._term_data(staff, teachers, children, rng)
        return logins

    def _term_data(self, staff, teachers, children, rng):
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
        # Next term, empty, so "copy last term" on the timetable has somewhere
        # to copy to.
        academics.create_term(
            f"{starts.year}/{starts.year + 1}", TermName.SECOND,
            starts + timedelta(weeks=14), starts + timedelta(weeks=26),
        )

        groups = [ClassGroup.objects.create(name=n, level=1) for n in ("JSS 1A", "JSS 1B")]
        placed = {groups[0]: children[:10], groups[1]: children[10:]}
        for group, members in placed.items():
            for child in members:
                academics.place_student(group, term, child)
        academics.assign_class_teacher(groups[0], term, staff["teacher"])

        # Marks: a first CA in every subject, and an exam nobody has sat yet.
        subjects = []
        for position, (subject_name, code) in enumerate(SUBJECTS):
            subject = Subject.objects.create(name=subject_name, code=code)
            subjects.append(subject)
            ca = Assessment.objects.create(term=term, subject=subject, name="First CA", max_score=20, position=0)
            Assessment.objects.create(term=term, subject=subject, name="Exam", max_score=60, position=1)
            for child in children:
                gradebook.set_score(ca, child, rng.randint(6, 20), by=staff["teacher"].user)

        self._timetable(term, groups, subjects, staff, teachers)
        self._release(term, groups[1], placed[groups[1]], staff)

        # Two weeks of registers. Children 3 and 14 are away often enough to be
        # on the principal's absence list.
        days = [d for d in _weekdays(starts, today)][:10]
        for group, members in placed.items():
            for day in days:
                away = [c.pk for c in members if (c in (children[2], children[13]) and rng.random() < 0.5)
                        or rng.random() < 0.05]
                attendance.take_register(group, term, on=day, absent_ids=away, by=staff["teacher"].user)

        # The term's fees. Two concessions first — child 5 a staff child, whose
        # standing concession each bill gives; child 8 a bursary since revoked,
        # which the bill does not give and the account still shows, with who
        # revoked it and why. Then each class's bill, applied as the bursar's
        # "Charge the class" applies it, so every charge names its line; then a
        # line added to JSS 1B's bill since, which nobody has been charged, so
        # pressing "Charge the class" there has something to do. Then a spread
        # of payments, one discount given by hand, and one family that overpaid,
        # so "In credit" shows.
        bursar = staff["bursar"].user
        billing.grant_concession(
            children[4], TUITION, reason="Staff child", form_key=uuid.uuid4(), by=bursar
        )
        bursary, _ = billing.grant_concession(
            children[7], 30_000 * KOBO_PER_NAIRA, reason="Bursary 2025", form_key=uuid.uuid4(), by=bursar
        )
        billing.revoke_concession(bursary, reason="The bursary ended with last session", by=bursar)
        for group in groups:
            bill = billing.open_bill(group, term)
            billing.add_line(bill, "Tuition", TUITION)
            billing.add_line(bill, "PTA levy", LEVY)
            billing.apply(bill, by=bursar)
        billing.add_line(billing.bill_for(groups[1], term), "Excursion", 5_000 * KOBO_PER_NAIRA)

        methods = [PaymentMethod.CASH, PaymentMethod.BANK_TRANSFER, PaymentMethod.POS, PaymentMethod.CHEQUE]
        for i, child in enumerate(children):
            if i % 3 == 2 or i == 4:
                continue  # owes the lot, or (the staff child) only the levy
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

    def _release(self, term, group, members, staff):
        """JSS 1B's results, walked the whole chain and released, and told.

        The ordinary way, one step per role, so the demo holds what a real
        release leaves behind: the frozen card, the transitions, and a render
        owed for each card. The render is queued after the commit and a
        broker that is not there is logged rather than raised
        (`results.renders._enqueue()`), so the demo seeds without Redis and
        the card page still opens — just without a PDF to download yet.

        JSS 1B has no class teacher (only JSS 1A does — see `_term_data()`),
        so the administrator submits it: the other role `SUBMITTING_ROLES`
        admits, and the one that is not scoped to a class.

        "Tell families" (D9) is its own step after release, off by default per
        school, so the demo turns it on and presses it itself: otherwise the
        fake outbox would never show a release notice at all. `now` is a fixed
        Lagos daytime moment rather than the real clock, so the notice always
        sends at once (`notices.hours.send_after()`) whatever time the seed
        happens to be run at.
        """
        from notices import services as notices_service
        from results import comments
        from results import services as chain
        from results.models import CommentAuthor

        principal = staff["principal"].user
        for child in members:
            comments.write(
                term, child, CommentAuthor.PRINCIPAL,
                "A steady term. Keep reading every evening.", by=principal,
            )
        sheet = chain.open_sheet(group, term, principal)
        chain.submit(sheet, staff["admin"].user)
        chain.check(sheet, staff["vp"].user)
        chain.approve(sheet, principal)
        chain.release(sheet, principal)

        notices_service.set_offered_as(principal, result_notices=True)
        now = datetime.combine(term.starts_on, time(9, 0), tzinfo=LAGOS)
        notices_service.tell_families(sheet, actor=principal, now=now)

    def _timetable(self, term, groups, subjects, staff, teachers):
        """Five periods and a break, and this term's week for both classes.

        One teacher per subject, and the two classes take the subjects out of
        step, so no teacher is in two rooms at once — except Friday's last
        period, one Basic Science lesson for both classes together, which the
        clash rule allows because it is the same subject. JSS 1A has a double
        period of mathematics on Tuesday (two slots); JSS 1B is free on
        Wednesday's last period (no slot). `set_lesson()` refuses a clash, so a
        mistake here fails the seed rather than the demo.
        """
        bell = [
            timetable.add_period(time(8, 0), time(8, 40), "Period 1"),
            timetable.add_period(time(8, 40), time(9, 20), "Period 2"),
            timetable.add_period(time(9, 20), time(10, 0), "Period 3"),
            timetable.add_period(time(10, 20), time(11, 0), "Period 4"),
            timetable.add_period(time(11, 0), time(11, 40), "Period 5"),
        ]
        maths, english, science = subjects
        teacher_of = {maths: staff["teacher"], english: teachers["english"], science: teachers["science"]}
        junior, other = groups
        last = len(bell) - 1
        for day in Weekday:
            for p, period in enumerate(bell):
                for offset, group in enumerate(groups):
                    subject = subjects[(day + p + offset) % len(subjects)]
                    if day == Weekday.FRIDAY and p == last:
                        subject = science
                    elif day == Weekday.TUESDAY and p == 2 and group is junior:
                        subject = maths
                    elif day == Weekday.WEDNESDAY and p == last and group is other:
                        continue
                    timetable.set_lesson(
                        term, group, day, period, subject, teacher_of[subject], by=staff["admin"].user
                    )
