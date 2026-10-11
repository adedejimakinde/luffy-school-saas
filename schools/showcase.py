"""The showcase school: one fictional school having a good day.

What `manage.py load_demo --showcase` makes, and what the public homepage's
screenshots are taken from (`scripts/site_shots.mjs`). The other demo schools
are for clicking through every state a school can be in, the awkward ones
included: a class waiting on remarks, a child absent too often, a family in
debt. This one is for showing a school the product on a full, ordinary day, at
the size of a real private secondary school:

- **612 students** in 18 classes, JSS 1A to SS 3C, 34 to a class.
- **The Ogun State template**, so the report sheet photographed is the one an
  Ogun school prints.
- **JSS 2A and JSS 2B released**, with both remarks on every card and every
  card's attendance recorded (the registers are taken before the release, which
  is when a card freezes them). JSS 2A's broadsheet is the one photographed.
- **One strong student**, the demo parent's child, at about 78%: mostly A1 to
  B3 on the default scale.
- **Seven classes checked and waiting on the principal**: JSS 1A to 1C, JSS 2C
  and JSS 3A to 3C, marked, remarked, submitted by the class teacher and
  checked by the vice principal. The principal's home says so.
- **SS 1A to SS 3C still open**, their first test marked with healthy scores and
  the principal's remarks written, so a teacher has a marks sheet to show that
  is not locked and the principal's home asks for nothing but the approvals.
- **Every register taken**, every school day of the term so far, each child
  away one day in sixteen or so, which is about 94% a day and nobody on the
  absences list. Today's too, but for SS 1A: the screenshot script photographs
  its teacher about to take it, then submits it on the page, so the home it
  photographs next has every register in.
- **Fees**: ₦71.2m billed for the term and ₦48.6m of it paid, the strong
  student's family in full into the child's own account number.

Every name and figure is made up, and the school's name says it is a demo.
Demo data only, and only on a demo server: `load_demo` asks `DEMO_SERVER=1`
before it calls this, messages nobody, and stores no phone number. The bank and
the child's account are demo rows with made-up numbers; nothing asks Paystack.
Students get no password: nobody signs in as one.
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
NAME = "Crestfield Demo College"
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

#: The strong student's percentage in each subject, in `SUBJECTS` order: an
#: average of 78.0, every one of them A1, B2 or B3 on the default scale.
STAR = (86, 81, 79, 74, 77, 71)

#: 18 classes, three to a level. The star is the first child in JSS 2A.
CLASSES = tuple((f"{stage} {year}{arm}", level)
                for level, (stage, year) in enumerate(
                    (("JSS", 1), ("JSS", 2), ("JSS", 3), ("SS", 1), ("SS", 2), ("SS", 3)), start=1)
                for arm in "ABC")
PER_CLASS = 34
RELEASED = ("JSS 2A", "JSS 2B")
#: Submitted, checked, and waiting on the principal's approval.
WAITING = ("JSS 1A", "JSS 1B", "JSS 1C", "JSS 2C", "JSS 3A", "JSS 3B", "JSS 3C")
#: Its register for today is taken on screen by `scripts/site_shots.mjs`.
TODAYS_OPEN_REGISTER = "SS 1A"

FIRST_NAMES = (
    "Amaka", "Bolu", "Chinedu", "Damilola", "Ebuka", "Folake", "Gift", "Hauwa", "Ikenna",
    "Jumoke", "Kunle", "Lade", "Maryam", "Nkem", "Olumide", "Precious", "Rasheed", "Sade",
    "Tobi", "Uzo", "Victor", "Wuraola", "Yusuf", "Zainab", "Adaeze", "Bisola", "Chioma",
    "Dapo", "Emeka", "Fatima", "Gbemi", "Hassan", "Ifeoma", "Kelechi", "Lanre", "Mide",
)
SURNAMES = (
    "Okafor", "Adebayo", "Bello", "Nwosu", "Ogunleye", "Ibrahim", "Eze", "Afolabi", "Usman", "Okoro",
    "Adeyemi", "Chukwu", "Balogun", "Mohammed", "Olawale", "Nnamdi", "Lawal", "Obi", "Salami", "Onyeka",
)

#: The term's bill: JSS ₦112,000 and SS ₦120,700 a child, ₦71,206,200 for the
#: whole school, of which `COLLECTED` is paid.
LEVY = 7_000 * KOBO_PER_NAIRA
TUITION = {"JSS": 105_000 * KOBO_PER_NAIRA, "SS": 113_700 * KOBO_PER_NAIRA}
COLLECTED = 48_600_000 * KOBO_PER_NAIRA


def _weekdays(start, end):
    day = start
    while day <= end:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


def _name(i):
    """612 different names, and no class full of one surname."""
    return f"{FIRST_NAMES[i % len(FIRST_NAMES)]} {SURNAMES[(i + 17 * (i // len(FIRST_NAMES))) % len(SURNAMES)]}"


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

    def login(key, full_name, secret=password):
        return User.objects.create_user(f"{PREFIX}.{key}", secret, full_name=full_name)

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
            user = login(f"s{i + 1:03d}", _name(i), secret=None)
            children.append(enroll_student(user, school, reference=f"CFC/{i + 1:03d}"))
        parent = login("parent", "Mr Chukwuma Okafor")
        star = children[0]
        link_guardian(parent, star)
        activate_guardian_links(parent, school)

    with schema_context(school.schema_name), transaction.atomic():
        _term(school, staff, children, star, rng)

    labels = {"admin": "Administrator", "principal": "Principal", "vp": "Vice Principal",
              "teacher": "Teacher", "bursar": "Bursar"}
    logins = [(NAME, m.user.username, labels[key]) for key, m in staff.items()]
    logins.append((NAME, parent.username, f"Parent (of {star.name})"))
    return logins


def _term(school, staff, children, star, rng):
    from academics import details
    from results import ogun

    today = timezone.localdate()
    starts = today - timedelta(days=today.weekday()) - timedelta(weeks=5)
    term = academics.create_term(
        f"{starts.year}/{starts.year + 1}", TermName.FIRST, starts, starts + timedelta(weeks=12),
        next_term_starts_on=starts + timedelta(weeks=14),
    )
    academics.set_current_term(term)

    groups = {name: ClassGroup.objects.create(name=name, level=level) for name, level in CLASSES}
    # The star first, into JSS 2A; everyone else in order.
    order = ["JSS 2A"] + [name for name, _ in CLASSES if name != "JSS 2A"]
    placed = {groups[name]: children[n * PER_CLASS:(n + 1) * PER_CLASS] for n, name in enumerate(order)}
    teacher = staff["teacher"]
    for group, members in placed.items():
        for child in members:
            academics.place_student(group, term, child)
        academics.assign_class_teacher(group, term, teacher)
    details.record(star.pk, learner_id="CFD-2013-0001", sex="female",
                   date_of_birth=today.replace(year=today.year - 13, month=3, day=14), by=staff["admin"].user)

    # Registers first: a card freezes its attendance when it is released. Every
    # school day so far and today, whatever day today is. Each child is away on
    # one or two days, dealt round so every day is about 94%; the star never.
    days = sorted(set(_weekdays(starts, today)) | {today})
    away_on = {
        c.pk: {days[(i * 7) % len(days)]} | ({days[(i * 7 + 13) % len(days)]} if i % 5 else set())
        for i, c in enumerate(children) if c is not star
    }
    for group, members in placed.items():
        for day in days:
            if group.name == TODAYS_OPEN_REGISTER and day == today:
                continue  # its teacher takes today's on screen (`scripts/site_shots.mjs`)
            absent = [c.pk for c in members if day in away_on.get(c.pk, ())]
            attendance.take_register(group, term, on=day, absent_ids=absent, by=teacher.user)

    # The Ogun State sheet's papers (1st Test, 2nd Test, Assignment, Exam) for
    # every subject, set up the way a school's choice sets them up.
    subjects = [Subject.objects.create(name=n, code=c) for n, c in SUBJECTS]
    ogun.set_template_as(staff["principal"].user, school, "ogun")
    papers = [list(Assessment.objects.filter(term=term, subject=s).order_by("position")) for s in subjects]

    # Marks: every paper for the released and waiting classes; the first test
    # alone for the open ones, the sheet a teacher is still filling in.
    marked = [g for g in placed if g.name in RELEASED + WAITING]
    for s, assessments in enumerate(papers):
        for group in marked:
            for child in placed[group]:
                percent = STAR[s] if child is star else rng.randint(58, 88)
                for assessment in assessments:
                    score = round(assessment.max_score * percent / 100 + rng.uniform(-1, 1))
                    gradebook.set_score(assessment, child, max(0, min(assessment.max_score, score)), by=teacher.user)
        for group in placed:
            if group in marked:
                continue
            for child in placed[group]:
                gradebook.set_score(assessments[0], child, rng.randint(6, 10), by=teacher.user)

    for group in marked:
        _results(term, group, placed[group], staff, star, rng, release=group.name in RELEASED)
    # The open classes' principal's remarks are in already, so the home asks
    # the principal for nothing but the seven approvals.
    from results import comments
    from results.models import CommentAuthor

    for group in placed:
        if group not in marked:
            for child in placed[group]:
                comments.write(term, child, CommentAuthor.PRINCIPAL, "A good start to the term.",
                               by=staff["principal"].user)

    _fees(term, placed, children, star, staff["bursar"].user, days, rng)


def _results(term, group, members, staff, star, rng, *, release):
    """Both remarks on every card, then the sheet walked to checked, or on to released."""
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
        if release:
            for trait_group in TraitGroup:
                for trait in ratings.traits(trait_group):
                    ratings.rate(term, trait, child, 5 if child is star else rng.randint(3, 5), by=teacher)
    chain.submit(sheet, teacher)
    chain.check(sheet, staff["vp"].user)
    if release:
        chain.approve(sheet, principal)
        chain.release(sheet, principal)


def _fees(term, placed, children, star, bursar, days, rng):
    """Each class billed, `COLLECTED` of it paid, the star's paid in full into her account."""
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
    owed = {}
    for group, members in placed.items():
        tuition = TUITION[group.name.split()[0]]
        bill = billing.open_bill(group, term)
        billing.add_line(bill, "Tuition", tuition)
        billing.add_line(bill, "PTA levy", LEVY)
        billing.apply(bill, by=bursar)
        owed.update({child.pk: tuition + LEVY for child in members})

    # Two families in five pay in full, two half, the rest nothing yet; then
    # part-payments from those until the total is exactly `COLLECTED`.
    plan = []
    for i, child in enumerate(children):
        share = 1 if child is star or i % 5 in (0, 2) else (0.5 if i % 5 in (1, 4) else 0)
        plan.append([child, round(owed[child.pk] * share / KOBO_PER_NAIRA) * KOBO_PER_NAIRA])
    short = COLLECTED - sum(amount for _, amount in plan)
    for row in (r for r in plan if r[1] == 0):
        if short <= 0:
            break
        row[1] = min(short, 60_000 * KOBO_PER_NAIRA)
        short -= row[1]
    methods = [PaymentMethod.BANK_TRANSFER, PaymentMethod.BANK_TRANSFER, PaymentMethod.POS, PaymentMethod.CASH]
    for i, (child, amount) in enumerate(plan):
        if not amount:
            continue
        method = PaymentMethod.BANK_TRANSFER if child is star else methods[i % len(methods)]
        fees.record_payment(
            child, term, amount,
            method=method,
            narration="Paid by transfer into the child's account" if child is star else "Payment received",
            reference=f"TRF-{rng.randint(100000, 999999)}" if method == PaymentMethod.BANK_TRANSFER else "",
            effective_on=days[(i * 11) % len(days)],
            recorded_by=bursar,
        )
