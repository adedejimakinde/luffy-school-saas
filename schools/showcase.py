"""The showcase school: one fictional school having a good day.

What `manage.py load_demo --showcase` makes, and what the public homepage's
screenshots are taken from (`scripts/site_shots.mjs`). The other demo schools
are for clicking through every state a school can be in, the awkward ones
included: a class waiting on remarks, a child absent too often, a family in
debt. This one is for showing a school the product on its best day, so it holds
nothing that is waiting, flagged or owed past the ordinary:

- **JSS 2A and JSS 2B released**, with both remarks on every card and every
  card's attendance recorded (the registers are taken before the release, which
  is when a card freezes them). JSS 2A's broadsheet is the one photographed.
- **One strong student**, the demo parent's child, at about 78%: mostly A1 to
  B3 on the default scale.
- **SS 1A still open**, its first CA marked with healthy scores and no sheet
  opened, so a teacher has a marks sheet to show that is not locked. It is the
  one class still to go on the principal's home, and it raises no row there:
  a class with no sheet is waiting on nobody (`home.summary.waiting()`).
- **Every register taken**, every school day of the term so far, with absences
  rare enough that the absences list is empty. Today's too, but for SS 1A: the
  screenshot script photographs its teacher about to take it, then submits it
  on the page, so the home it photographs next has every register in.
- **Fees mostly paid**, and the strong student's family paid in full into the
  child's own account number.

Demo data only, and only on a demo server: `load_demo` asks `DEMO_SERVER=1`
before it calls this, messages nobody, and stores no phone number. The bank and
the child's account are demo rows with made-up numbers; nothing asks Paystack.
"""

import random
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django_tenants.utils import schema_context

from academics import services as academics
from academics.models import ClassGroup, TermName
from accounts.models import Role, User
from accounts.services import (
    activate_guardian_links,
    enroll_student,
    grant_membership,
    link_guardian,
)
from attendance import services as attendance
from fees import billing
from fees import services as fees
from fees.models import KOBO_PER_NAIRA, PaymentMethod, SchoolBank, VirtualAccount
from gradebook import services as gradebook
from gradebook.models import Assessment, Subject
from schools.models import Domain, School

SLUG = "showcase-demo"
NAME = "Crestfield College"
#: Logins are `<PREFIX>.<key>`, as in `seed_demo`.
PREFIX = "crestfield"
CONTACT_EMAIL = "office@crestfield.example"

SUBJECTS = (
    ("Mathematics", "MTH"),
    ("English Language", "ENG"),
    ("Basic Science", "BSC"),
    ("Social Studies", "SOS"),
    ("Civic Education", "CVE"),
    ("Computer Studies", "CMP"),
)

#: First CA, second CA and exam: a hundred marks between them.
ASSESSMENTS = (("First CA", 20), ("Second CA", 20), ("Exam", 60))

#: The strong student's percentage in each subject, in `SUBJECTS` order: an
#: average of 78.0, every one of them A1, B2 or B3 on the default scale.
STAR = (86, 81, 79, 74, 77, 71)

CLASSES = (("JSS 2A", 2), ("JSS 2B", 2), ("SS 1A", 4))
PER_CLASS = 12

FIRST_NAMES = (
    "Amaka", "Bolu", "Chinedu", "Damilola", "Ebuka", "Folake", "Gift", "Hauwa", "Ikenna",
    "Jumoke", "Kunle", "Lade", "Maryam", "Nkem", "Olumide", "Precious", "Rasheed", "Sade",
    "Tobi", "Uzo", "Victor", "Wuraola", "Yusuf", "Zainab", "Adaeze", "Bisola", "Chioma",
    "Dapo", "Emeka", "Fatima", "Gbemi", "Hassan", "Ifeoma", "Kelechi", "Lanre", "Mide",
)
SURNAMES = ("Okafor", "Adebayo", "Bello", "Nwosu", "Ogunleye", "Ibrahim", "Eze", "Afolabi", "Usman", "Okoro")

TUITION = 120_000 * KOBO_PER_NAIRA
LEVY = 10_000 * KOBO_PER_NAIRA


def _weekdays(start, end):
    day = start
    while day <= end:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


def exists():
    return School.objects.filter(slug=SLUG).exists()


def make(password, suffix, write=print):
    """Create the showcase school. Returns `(school, username, role)` rows for each login."""
    rng = random.Random(SLUG)
    school = School(name=NAME, slug=SLUG, schema_name=SLUG.replace("-", "_"), contact_email=CONTACT_EMAIL)
    school.save()  # CREATE SCHEMA and migrate, the real way
    host = f"{SLUG}.{suffix}"
    Domain.objects.create(tenant=school, domain=host, is_primary=True)
    write(f"{NAME}: http://{host}/  (schema {school.schema_name})")

    def login(key, full_name):
        return User.objects.create_user(f"{PREFIX}.{key}", password, full_name=full_name)

    with transaction.atomic():
        staff = {
            "admin": grant_membership(login("admin", "Mrs Funke Adewale"), school, Role.ADMIN),
            "principal": grant_membership(login("principal", "Dr Ngozi Okonkwo"), school, Role.PRINCIPAL),
            "vp": grant_membership(
                login("vp", "Mr Tunde Bakare"), school, Role.VICE_PRINCIPAL_ACADEMIC
            ),
            "teacher": grant_membership(login("teacher", "Mrs Aisha Danladi"), school, Role.TEACHER),
            "bursar": grant_membership(login("bursar", "Mr Segun Oyelaran"), school, Role.BURSAR),
        }
        children = []
        for i in range(PER_CLASS * len(CLASSES)):
            name = f"{FIRST_NAMES[i]} {SURNAMES[(i * 7) % len(SURNAMES)]}"
            user = login(f"s{i + 1:02d}", name)
            children.append(enroll_student(user, school, reference=f"CFC/{i + 1:03d}"))
        parent = login("parent", "Mr Chukwuma Okafor")
        star = children[0]
        link_guardian(parent, star)
        activate_guardian_links(parent, school)

    with schema_context(school.schema_name), transaction.atomic():
        _term(staff, children, star, rng)

    labels = {"admin": "Administrator", "principal": "Principal", "vp": "Vice Principal",
              "teacher": "Teacher", "bursar": "Bursar"}
    logins = [(NAME, m.user.username, labels[key]) for key, m in staff.items()]
    logins.append((NAME, parent.username, f"Parent (of {star.name})"))
    return logins


def _term(staff, children, star, rng):
    today = timezone.localdate()
    starts = today - timedelta(days=today.weekday()) - timedelta(weeks=5)
    term = academics.create_term(
        f"{starts.year}/{starts.year + 1}", TermName.FIRST, starts, starts + timedelta(weeks=12),
        next_term_starts_on=starts + timedelta(weeks=14),
    )
    academics.set_current_term(term)

    groups = [ClassGroup.objects.create(name=name, level=level) for name, level in CLASSES]
    placed = {g: children[n * PER_CLASS:(n + 1) * PER_CLASS] for n, g in enumerate(groups)}
    for group, members in placed.items():
        for child in members:
            academics.place_student(group, term, child)
    teacher = staff["teacher"]
    for group in groups:
        academics.assign_class_teacher(group, term, teacher)
    released, still_open = groups[:2], groups[2]

    # Registers first: a card freezes its attendance when it is released. Every
    # school day so far and today, whatever day today is, so the home has a
    # register for today. A child misses at most one day, which keeps everyone
    # under the absences list's 10%.
    days = sorted(set(_weekdays(starts, today)) | {today})
    away_on = {c.pk: rng.choice(days[:-1]) for c in children if rng.random() < 0.35 and c is not star}
    for group, members in placed.items():
        for day in days:
            if group is still_open and day == today:
                continue  # SS 1A's teacher takes today's on screen (`scripts/site_shots.mjs`)
            absent = [c.pk for c in members if away_on.get(c.pk) == day]
            attendance.take_register(group, term, on=day, absent_ids=absent, by=teacher.user)

    # Marks. The released classes have every assessment; SS 1A only its first
    # CA, which is the sheet a teacher is still filling in.
    by_subject = []
    for subject_name, code in SUBJECTS:
        subject = Subject.objects.create(name=subject_name, code=code)
        made = [
            Assessment.objects.create(term=term, subject=subject, name=n, max_score=m, position=p)
            for p, (n, m) in enumerate(ASSESSMENTS)
        ]
        by_subject.append(made)
    for s, assessments in enumerate(by_subject):
        for group in released:
            for child in placed[group]:
                percent = STAR[s] if child is star else rng.randint(58, 88)
                for assessment in assessments:
                    score = round(assessment.max_score * percent / 100 + rng.uniform(-1, 1))
                    score = max(0, min(assessment.max_score, score))
                    gradebook.set_score(assessment, child, score, by=teacher.user)
        first_ca = assessments[0]
        for child in placed[still_open]:
            gradebook.set_score(first_ca, child, rng.randint(12, 19), by=teacher.user)

    for group in released:
        _release(term, group, placed[group], staff, star, rng)

    _fees(term, groups, children, star, staff["bursar"].user, days, rng)


def _release(term, group, members, staff, star, rng):
    """Both remarks on every card, conduct rated, and the sheet walked to released."""
    from results import comments, ratings
    from results import services as chain
    from results.models import CommentAuthor, TraitGroup

    principal = staff["principal"].user
    teacher = staff["teacher"].user
    sheet = chain.open_sheet(group, term, principal)
    for trait_group in TraitGroup:
        ratings.set_group_enabled(trait_group, True)
    for child in members:
        if child is star:
            teacher_says = "An excellent term. Leads her group well and never misses homework."
            principal_says = "Outstanding work. Keep it up next term."
        else:
            teacher_says = "A good term. Works hard and takes part in class."
            principal_says = "Well done. Keep reading every evening."
        comments.write(term, child, CommentAuthor.CLASS_TEACHER, teacher_says, by=teacher)
        comments.write(term, child, CommentAuthor.PRINCIPAL, principal_says, by=principal)
        for trait_group in TraitGroup:
            for trait in ratings.traits(trait_group):
                ratings.rate(term, trait, child, 5 if child is star else rng.randint(3, 5), by=teacher)
    chain.submit(sheet, teacher)
    chain.check(sheet, staff["vp"].user)
    chain.approve(sheet, principal)
    chain.release(sheet, principal)


def _fees(term, groups, children, star, bursar, days, rng):
    """Each class billed, most families paid, the star's paid in full into her account."""
    SchoolBank.objects.create(
        bank_code="035", bank_name="Wema Bank", account_number="0123456789",
        account_name=NAME, subaccount_code="ACCT_showcase", split_code="SPL_showcase",
        connected_by_id=bursar.pk, connected_by_name=bursar.full_name,
    )
    VirtualAccount.objects.create(
        student_membership_id=star.pk, customer_code="CUS_showcase",
        account_number="8123450001", account_name=f"{NAME} / {star.name}",
        bank_name="Wema Bank", split_code="SPL_showcase",
        created_by_id=bursar.pk, created_by_name=bursar.full_name,
    )
    for group in groups:
        bill = billing.open_bill(group, term)
        billing.add_line(bill, "Tuition", TUITION)
        billing.add_line(bill, "PTA levy", LEVY)
        billing.apply(bill, by=bursar)
    methods = [PaymentMethod.BANK_TRANSFER, PaymentMethod.BANK_TRANSFER, PaymentMethod.POS, PaymentMethod.CASH]
    for i, child in enumerate(children):
        if child is not star and i % 6 == 5:
            continue  # a few families still to pay
        method = PaymentMethod.BANK_TRANSFER if child is star else methods[i % len(methods)]
        amount = TUITION + LEVY if child is star or i % 3 else TUITION
        fees.record_payment(
            child, term, amount,
            method=method,
            narration="Paid by transfer into the child's account" if child is star else "Payment received",
            reference=f"TRF-{rng.randint(100000, 999999)}" if method == PaymentMethod.BANK_TRANSFER else "",
            effective_on=days[min(i % 10, len(days) - 1)],
            recorded_by=bursar,
        )
