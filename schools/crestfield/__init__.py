"""Crestfield College, Abeokuta (Demo): Classnode's sales demo, on the production server.

`manage.py crestfield create` makes it once and `manage.py crestfield reset`
puts it back to exactly this state before each visit. A made-up day secondary
school in Abẹ́òkúta at the end of its first term:

- **JSS 1A to SS 3B**, twelve classes of 25, 300 students with Yorùbá, Igbo and
  Hausa names (`people.py`), each with a guardian, some with a brother or
  sister in another class.
- **Staff**: a principal, a vice principal (academic), an administrator, a
  bursar and fifteen teachers, each with a class to keep or subjects to teach.
  Who teaches what is set per class (`SUBJECT_TEACHERS`), so marking is narrowed
  the way a school that has set it is.
- **The first term, finished**: twelve weeks of registers but for two days of
  mid-term, every paper of the Ogun State sheet marked in every subject a class
  takes, both halves of the conduct section rated, both remarks written.
- **Results at every stage**: JSS 1A, JSS 2A and SS 1A released; six classes
  submitted and checked, waiting on the principal; JSS 2B, SS 3A and SS 3B
  still with their class teachers, so the teacher's marking sheet is open.
- **Fees**: each class billed, about half the families paid in full, a third
  part-paid, the rest owing.
- **CBT**: the vice principal named exam officer and JSS 3A's exam slips
  printed. The question bank (`questions.py`) waits for CBT step 3.
- **Its website**, the starter theme with the school's details, published.

## What keeps it apart from real schools

- **A name that is not a demo name.** `schools.demo_slugs` refuses `*-demo` on
  production and is not loosened: the slug is `crestfield`, and what marks the
  school is `School.sales_demo`, which only this slug may carry (a constraint).
- **It sends nothing** (`schools.quiet`): no invitation, notice, receipt, alert,
  summary or code leaves for it. Its staff have `example.com` addresses and its
  guardians 555-01xx numbers, which are reserved for fiction.
- **It is never indexed or listed** (`schoolsite.views._may_be_indexed`).
- **Reset touches this school and nothing else.** It refuses unless the school
  called `crestfield` carries the flag and the schema it names is `crestfield`,
  drops that one schema and builds it again, and in the shared tables changes
  only rows whose school is this one (`_public_side`).

## Why reset rebuilds the schema rather than deleting rows

Much of a school is append-only on purpose: released cards, the fee ledger, the
setup log and a guardian's contacts refuse DELETE in Postgres. A wiped school is
therefore a new schema, not an emptied one. The shared rows (the people, their
memberships and their guardian links) are kept and put back as they were: a
membership is never deleted, and ending the ones a demo added is what a school
would do. Tenant rows name memberships by id, so the same people keep the same
ids and nothing dangles.

Sign-ins: only the principal, a teacher and the parent can sign in
(`cfc.principal`, `cfc.teacher`, `cfc.parent`). Their passwords are read from
the environment of the command (`SIGN_INS`), are never printed, and are kept
only where the operator keeps them on the server (`docs/demo-school.md`).
"""

import io
import random
from datetime import timedelta

from django.db import connection, transaction
from django.utils import timezone
from django_tenants.utils import schema_context, schema_exists

from . import people as cast

SLUG = "crestfield"
SCHEMA = "crestfield"
NAME = "Crestfield College, Abeokuta (Demo)"
#: Logins are `cfc.<key>`.
PREFIX = "cfc"
#: The three logins that can sign in, and the variables their passwords come from.
SIGN_INS = {
    "principal": "CRESTFIELD_PRINCIPAL_PASSWORD",
    "teacher": "CRESTFIELD_TEACHER_PASSWORD",
    "parent": "CRESTFIELD_PARENT_PASSWORD",
}
MIN_PASSWORD = 12
CONTACT_EMAIL = "office.crestfield@example.com"
ABOUT = (
    "Crestfield College is a day secondary school in Abẹ́òkúta, JSS 1 to SS 3. "
    "It is not a real school: Classnode uses it to show schools what Classnode does."
)
ADDRESS = "Ìbàrà, Abẹ́òkúta, Ogun State"
LGA = "Abeokuta South"

PER_CLASS = 25
CLASSES = tuple(
    (f"{stage} {year}{arm}", level)
    for level, (stage, year) in enumerate(
        (("JSS", 1), ("JSS", 2), ("JSS", 3), ("SS", 1), ("SS", 2), ("SS", 3)), start=1
    )
    for arm in "AB"
)
RELEASED = ("JSS 1A", "JSS 2A", "SS 1A")
#: With their class teachers: marks in, remarks partly written, not submitted.
OPEN = ("JSS 2B", "SS 3A", "SS 3B")
#: Every other class is submitted and checked, and waits on the principal.
SLIPS_FOR = "JSS 3A"

SUBJECTS = (
    ("English Language", "ENG"),
    ("Mathematics", "MTH"),
    ("Civic Education", "CVE"),
    ("Basic Science", "BSC"),
    ("Basic Technology", "BTE"),
    ("Social Studies", "SOS"),
    ("Yorùbá", "YOR"),
    ("Business Studies", "BUS"),
    ("Computer Studies", "CMP"),
    ("Biology", "BIO"),
    ("Economics", "ECO"),
    ("Physics", "PHY"),
    ("Chemistry", "CHM"),
    ("Government", "GOV"),
    ("Literature in English", "LIT"),
)
JSS_SUBJECTS = ("ENG", "MTH", "BSC", "BTE", "SOS", "CVE", "YOR", "BUS", "CMP")
#: Senior arm A is the science stream, arm B the arts.
SS_SUBJECTS = {"A": ("ENG", "MTH", "CVE", "BIO", "ECO", "PHY", "CHM"),
               "B": ("ENG", "MTH", "CVE", "BIO", "ECO", "GOV", "LIT")}
#: `subject code -> (teacher key for JSS, teacher key for SS)`; None where the
#: subject is not taught at that stage.
SUBJECT_TEACHERS = {
    "MTH": ("teacher", "t02"),
    "ENG": ("t03", "t04"),
    "BSC": ("t05", None),
    "BTE": ("t06", None),
    "CMP": ("t14", None),
    "SOS": ("t07", None),
    "CVE": ("t07", "t08"),
    "GOV": (None, "t08"),
    "YOR": ("t09", None),
    "BUS": ("t10", None),
    "ECO": (None, "t10"),
    "BIO": (None, "t11"),
    "PHY": (None, "t12"),
    "CHM": (None, "t13"),
    "LIT": (None, "t15"),
}

KOBO = 100
#: Each term's bill, in naira: JSS and SS tuition, and the two levies everybody pays.
TUITION = {"JSS": 85_000, "SS": 95_000}
LEVIES = (("Development levy", 10_000), ("PTA levy", 5_000))


class Refused(Exception):
    """The command would not do this. The message says why and that nothing changed."""


def subjects_of(class_name):
    stage, rest = class_name.split()
    return JSS_SUBJECTS if stage == "JSS" else SS_SUBJECTS[rest[-1]]


def username(key):
    return f"{PREFIX}.{key}"


# -- finding it -------------------------------------------------------------------


def find():
    """The demo school, or None. Refuses a `crestfield` that is not the demo."""
    from schools.models import School

    school = School.objects.filter(slug=SLUG).first()
    if school is None:
        return None
    if not school.sales_demo or school.schema_name != SCHEMA:
        raise Refused(
            f"A school called {SLUG!r} is here and it is not Classnode's demo school "
            "(it does not carry the sales_demo flag). Nothing was touched."
        )
    return school


def check_passwords(passwords, *, required):
    """`passwords` is `key -> password or ""`. Refuses a short one, and a missing one if required."""
    for key, variable in SIGN_INS.items():
        value = passwords.get(key) or ""
        if not value and not required:
            continue
        if len(value) < MIN_PASSWORD:
            raise Refused(
                f"Set {variable} to a password of at least {MIN_PASSWORD} characters. "
                "Nothing was changed."
            )


# -- making it, and putting it back --------------------------------------------------


def create(passwords, suffix, *, write=print, per_class=PER_CLASS):
    """Make the school, its schema, its host and everything in it. Refuses if any of it is here."""
    from accounts.models import User
    from schools.models import Domain, School

    check_passwords(passwords, required=True)
    if find() is not None:
        raise Refused(f"{NAME} is already here. To put it back as it was, run: manage.py crestfield reset")
    if School.objects.filter(schema_name=SCHEMA).exists() or schema_exists(SCHEMA):
        raise Refused(f"A schema called {SCHEMA!r} is already here. Nothing was created.")
    host = f"{SLUG}.{suffix}"
    if Domain.objects.filter(domain=host).exists():
        raise Refused(f"{host} already belongs to a school. Nothing was created.")
    taken = sorted(User.objects.filter(username__startswith=f"{PREFIX}.").values_list("username", flat=True)[:5])
    if taken:
        raise Refused(
            f"Logins starting {PREFIX}. are already here ({', '.join(taken)}). They would "
            "become the demo's. Nothing was created."
        )

    school = School(name=NAME, slug=SLUG, schema_name=SCHEMA, sales_demo=True)
    school.save()  # CREATE SCHEMA and migrate, the real way
    Domain.objects.create(tenant=school, domain=host, is_primary=True)
    write(f"{NAME}: https://{host}/  (schema {SCHEMA})")
    build(school, passwords, write=write, per_class=per_class)
    return school


def rebuild_schema(school):
    """Drop the demo's schema and make it again, empty and migrated. Its own and no other."""
    from schools.models import School

    assert school.sales_demo and school.slug == SLUG and school.schema_name == SCHEMA
    # Asked of the database again, not of the row in hand.
    assert School.objects.filter(pk=school.pk, sales_demo=True, schema_name=SCHEMA).exists()
    connection.set_schema_to_public()
    with connection.cursor() as cursor:
        # Inside a transaction that wrote to the schema (the tests' own), the
        # deferred foreign keys must be checked before its tables can go.
        cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        cursor.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
    school.create_schema(check_if_exists=True, verbosity=0)


def reset(passwords, *, write=print, schema=rebuild_schema, per_class=PER_CLASS):
    """Put the demo back to its starting state. Passwords given are set; the others are kept."""
    check_passwords(passwords, required=False)
    school = find()
    if school is None:
        raise Refused(f"{NAME} is not here. Make it first: manage.py crestfield create")
    write(f"Rebuilding {NAME} (schema {SCHEMA}).")
    schema(school)
    build(school, passwords, write=write, per_class=per_class)
    return school


# -- what is in it -------------------------------------------------------------------


def build(school, passwords, *, write=print, per_class=PER_CLASS):
    """Everything in the school. `per_class` is smaller only in the tests."""
    rng = random.Random(SLUG)
    by_class, guardians = cast.roll([name for name, _ in CLASSES], per_class, SLUG)
    with transaction.atomic():
        staff, children, parents = _public_side(school, passwords, by_class, guardians)
    write(f"  {len(staff)} staff, {len(children)} students, {len(parents)} guardians.")
    with schema_context(school.schema_name), transaction.atomic():
        _school(school, staff, children, parents, by_class, rng, write)
    from onboarding.progress import progress_for

    progress_for(school)  # every step holds, so it is written down as finished
    for key in SIGN_INS:
        write(f"  sign-in: {username(key)}")


def _user(key, full_name, *, email=None, password=None):
    from accounts.models import User

    user = User.objects.filter(username=username(key)).first()
    if user is None:
        user = User.objects.create_user(username(key), None, full_name=full_name, email=email)
    user.full_name, user.is_active = full_name, True
    if email is not None:
        user.email = email
    if password:
        user.set_password(password)
    user.save()
    return user


def _public_side(school, passwords, by_class, guardians):
    """The people, their memberships and their guardian links, as they were.

    Every write names this school, or a `cfc.` login that belongs only to it.
    """
    from accounts import services as accounts
    from accounts.models import (
        ContactChannel,
        GuardianAccount,
        GuardianContact,
        Guardianship,
        Membership,
        MembershipStatus,
        Role,
    )

    school.name, school.is_active = NAME, True
    school.contact_email = school.about = school.address = school.phone = ""
    school.lga = school.school_code = ""
    school.setup_completed_at = school.contact_email_later_at = school.crest_later_at = None
    school.save()

    def member(user, role, **fields):
        membership = accounts.grant_membership(user, school, role, **fields)
        if membership.status != MembershipStatus.ACTIVE or any(
            getattr(membership, k) != v for k, v in fields.items()
        ):
            membership.status, membership.ended_on = MembershipStatus.ACTIVE, None
            for k, v in fields.items():
                setattr(membership, k, v)
            membership.save()
        return membership

    staff = {}
    for key, role, full_name in cast.OFFICE:
        user = _user(key, full_name, email=cast.staff_email(key), password=passwords.get(key))
        staff[key] = member(user, role)
    for key, full_name, _keeps in cast.TEACHERS:
        user = _user(key, full_name, email=cast.staff_email(key), password=passwords.get(key))
        staff[key] = member(user, Role.TEACHER)

    children = {}
    number = 0
    this_year = int(session_of(term_dates(timezone.localdate())[0])[:4])
    for level, (class_name, _) in enumerate(CLASSES):
        entered = this_year - (level // 2)
        for child in by_class[class_name]:
            number += 1
            user = _user(f"s{number:03d}", child.name)
            reference = f"CFC/{entered}/{number:03d}"
            children[id(child)] = member(user, Role.STUDENT, reference=reference)

    admin = staff["admin"].user
    parents = []
    for n, family in enumerate(guardians):
        key = "parent" if n == 0 else f"g{n:03d}"
        user = _user(key, family.full_name, password=passwords.get("parent") if n == 0 else None)
        for child in family.children:
            accounts.link_guardian(
                user, children[id(child)], relationship=family.relationship, is_primary_contact=True,
            )
        accounts.activate_guardian_links(user, school)
        account, _ = GuardianAccount.objects.get_or_create(user=user)
        if not GuardianContact.objects.filter(guardian=account, channel_type=ContactChannel.PHONE,
                                              revoked_at__isnull=True).exists():
            GuardianContact.objects.create(
                guardian=account, channel_type=ContactChannel.PHONE, value=cast.guardian_phone(n),
                created_by=admin, verified_at=timezone.now(),
            )
        parents.append(user)

    # What a demo added: a guardian typed against one of our children, and
    # anybody given a place here who is not one of ours. Unlinked and ended,
    # as the school would; a membership is never deleted.
    ours = {m.pk for m in staff.values()} | {m.pk for m in children.values()}
    our_parents = {u.pk for u in parents}
    for link in Guardianship.objects.filter(student__school=school).exclude(guardian_id__in=our_parents):
        accounts.unlink_guardian(link.guardian, link.student)
    extra = Membership.objects.filter(school=school).exclude(status=MembershipStatus.ENDED).exclude(pk__in=ours)
    extra = extra.exclude(role=Role.PARENT, user_id__in=our_parents)
    for membership in extra:
        membership.end()
    return staff, children, parents


def _crest_png():
    """A plain shield with the school's initials, drawn here rather than kept as a file."""
    from PIL import Image, ImageDraw, ImageFont

    side = 512
    image = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    shield = [(64, 48), (448, 48), (448, 260), (256, 470), (64, 260)]
    draw.polygon(shield, fill=(21, 61, 107, 255))
    draw.line(shield + [shield[0]], fill=(212, 166, 52, 255), width=18)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 150)
    except OSError:
        font = ImageFont.load_default()
    draw.text((256, 230), "CC", font=font, fill=(255, 255, 255, 255), anchor="mm")
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _weekdays(start, end):
    day = start
    while day <= end:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


def term_dates(today):
    """`(first day, last day, next term's first day, the school days)` for a term finished by `today`.

    Twelve weeks to the last weekday on or before today, less a Thursday and
    Friday of mid-term in week seven.
    """
    ends = today - timedelta(days=max(0, today.weekday() - 4))
    starts = ends - timedelta(days=ends.weekday()) - timedelta(weeks=11)
    midterm = {starts + timedelta(weeks=6, days=3), starts + timedelta(weeks=6, days=4)}
    days = [d for d in _weekdays(starts, ends) if d not in midterm]
    next_starts = ends - timedelta(days=ends.weekday()) + timedelta(weeks=3)
    return starts, ends, next_starts, days


def session_of(starts):
    year = starts.year if starts.month >= 8 else starts.year - 1
    return f"{year}/{year + 1}"


def _school(school, staff, children, parents, by_class, rng, write):
    from academics import services as academics
    from academics.models import TermName
    from cbt import officers, pins
    from gradebook import assignments
    from gradebook.models import Assessment, Subject
    from results import look, ogun
    from schools import contact

    from . import site

    principal, admin = staff["principal"].user, staff["admin"].user

    # School details first, through the services the setup steps use, so the
    # setup log says who set them.
    contact.set_contact_email_as(admin, school, CONTACT_EMAIL)
    contact.set_public_details_as(admin, school, about=ABOUT, address=ADDRESS, phone="")
    contact.set_lga_as(admin, school, LGA)
    look.set_crest_as(principal, school, _crest_png())

    starts, ends, next_starts, days = term_dates(timezone.localdate())
    term = academics.create_term(session_of(starts), TermName.FIRST, starts, ends, next_term_starts_on=next_starts)
    academics.set_current_term(term)
    academics.set_school_days(term, len(days))

    groups = {name: academics.create_class_group(name, level) for name, level in CLASSES}
    subjects = {code: Subject.objects.create(name=name, code=code) for name, code in SUBJECTS}
    # The Ogun State sheet, chosen as a school chooses it: it sets every
    # subject's papers for this term and the conduct section's traits.
    ogun.set_template_as(principal, school, "ogun")
    papers = {
        code: list(Assessment.objects.filter(term=term, subject=subject).order_by("position"))
        for code, subject in subjects.items()
    }

    placed = {name: [children[id(c)] for c in by_class[name]] for name in groups}
    keeps = {class_name: key for key, _name, class_name in cast.TEACHERS if class_name}
    for name, group in groups.items():
        for child in placed[name]:
            academics.place_student(group, term, child)
        academics.assign_class_teacher(group, term, staff[keeps[name]])
        stage = 0 if name.startswith("JSS") else 1
        for code in subjects_of(name):
            teacher = SUBJECT_TEACHERS[code][stage]
            assignments.assign_as(principal, school, term, group, subjects[code], staff[teacher])

    _learners(by_class, children, admin, rng)
    write("  registers ...")
    _registers(groups, placed, term, days, staff, keeps, rng)
    write("  marks ...")
    ability = _marks(groups, placed, papers, term, staff, rng, by_class, children)
    write("  ratings, remarks and the chain ...")
    _results(groups, placed, term, staff, keeps, ability, rng)
    write("  fees ...")
    _fees(groups, placed, term, days, staff["bursar"].user, rng)

    officers.name_as(principal, school, staff["vp"].pk, note="Runs the CBT room")
    pins.print_class_as(admin, school, groups[SLIPS_FOR].pk)
    site.publish(principal, school)


def _learners(by_class, children, by, rng):
    """The learner's ID, sex and date of birth the Ogun sheet prints. Made up."""
    from academics import details

    today = timezone.localdate()
    number = 0
    for level, (class_name, _) in enumerate(CLASSES):
        age = 10 + level // 2
        for child in by_class[class_name]:
            number += 1
            born = today.replace(year=today.year - age - 1, month=rng.randint(1, 12), day=rng.randint(1, 28))
            details.record(
                children[id(child)].pk, learner_id=f"OG-CFC-{number:04d}", sex=child.sex,
                date_of_birth=born, by=by,
            )


def _registers(groups, placed, term, days, staff, keeps, rng):
    """Every school day. About one child in twenty away on any day; three away often."""
    from attendance import services as attendance

    often = {placed[name][seat % len(placed[name])].pk for name, seat in (("JSS 3B", 7), ("SS 2A", 12), ("JSS 1B", 19))}
    for name, group in groups.items():
        by = staff[keeps[name]].user
        for day in days:
            absent = [c.pk for c in placed[name] if rng.random() < (0.3 if c.pk in often else 0.035)]
            attendance.take_register(group, term, on=day, absent_ids=absent, by=by)


def _marks(groups, placed, papers, term, staff, rng, by_class, children):
    """Every paper of every subject each class takes. Returns `membership pk -> average %`."""
    from gradebook import services as gradebook

    strong = {children[id(c)].pk for c in by_class["JSS 2A"] + by_class["SS 1A"]
              if c.name in {full for _, full, _ in cast.PARENT_CHILDREN}}
    ability = {}
    for name in groups:
        stage = 0 if name.startswith("JSS") else 1
        for child in placed[name]:
            base = 81 if child.pk in strong else min(92, max(38, rng.gauss(63, 12)))
            got = []
            for code in subjects_of(name):
                teacher = staff[SUBJECT_TEACHERS[code][stage]].user
                percent = min(97, max(25, base + rng.gauss(0, 7)))
                for paper in papers[code]:
                    value = round(paper.max_score * min(1, max(0, percent / 100 + rng.uniform(-0.06, 0.06))))
                    gradebook.set_score(paper, child, value, by=teacher)
                got.append(percent)
            ability[child.pk] = sum(got) / len(got)
    return ability


TEACHER_SAYS = (
    (75, ("An excellent term. Works with care and helps others in class.",
          "Outstanding effort. Leads by example and never misses homework.")),
    (60, ("A good term. Works steadily and takes part in class.",
          "Good progress. More practice at home will lift the next grade.")),
    (48, ("A fair term. Must ask for help early when a topic is hard.",
          "Can do better. Needs to finish classwork and revise every week.")),
    (0, ("A difficult term. Needs close support at home and at school.",
         "Must attend extra lessons and complete every assignment.")),
)
PRINCIPAL_SAYS = (
    (75, "Excellent result. Keep it up next term."),
    (60, "A good result. Aim higher next term."),
    (48, "Fair. More effort is needed next term."),
    (0, "See the class teacher with your parents early next term."),
)


def _said(table, average, rng):
    for floor, said in table:
        if average >= floor:
            return rng.choice(said) if isinstance(said, tuple) else said
    return table[-1][1]


def _results(groups, placed, term, staff, keeps, ability, rng):
    """Ratings and both remarks, then each class walked as far as its stage."""
    from results import checker, comments, ratings
    from results import services as chain
    from results.models import CommentAuthor, TraitGroup

    principal, vp = staff["principal"].user, staff["vp"].user
    for group in TraitGroup:
        ratings.set_group_enabled(group, True)
    traits = [trait for group in TraitGroup for trait in ratings.traits(group)]
    for name, group in groups.items():
        teacher = staff[keeps[name]].user
        sheet = chain.open_sheet(group, term, principal)
        still_open = name in OPEN
        for n, child in enumerate(placed[name]):
            average = ability[child.pk]
            for trait in traits:
                score = rng.choice((4, 5, 5) if average >= 78 else (3, 4, 4, 5) if average >= 55 else (2, 3, 3, 4))
                ratings.rate(term, trait, child, score, by=teacher)
            # An open class has its remarks half written: the teacher's last
            # few and every one of the principal's still to come.
            if not still_open or n < len(placed[name]) * 3 // 5:
                comments.write(term, child, CommentAuthor.CLASS_TEACHER, _said(TEACHER_SAYS, average, rng), by=teacher)
            if not still_open:
                comments.write(term, child, CommentAuthor.PRINCIPAL, _said(PRINCIPAL_SAYS, average, rng), by=principal)
        if still_open:
            continue
        chain.submit(sheet, teacher)
        chain.check(sheet, vp)
        if name in RELEASED:
            chain.approve(sheet, principal)
            chain.release(sheet, principal)
            # The result checker's slips, printed as the office prints them
            # after a release. The PINs are on paper only, so a salesperson
            # who wants to show the checker prints a lost slip on the page.
            checker.print_slips(sheet, actor=principal)


def _paid_on(days, rng):
    """Most families pay in the first weeks, and a few are still paying this week."""
    if rng.random() < 0.06:
        return days[-1]
    return days[min(len(days) - 1, int(rng.triangular(0, len(days), 0)))]


def _fees(groups, placed, term, days, bursar, rng):
    """Each class billed; about half paid in full, a third part-paid, the rest owing."""
    from fees import billing
    from fees import services as fees
    from fees.models import PaymentMethod

    methods = (PaymentMethod.BANK_TRANSFER, PaymentMethod.BANK_TRANSFER, PaymentMethod.POS, PaymentMethod.CASH)
    for name, group in groups.items():
        tuition = TUITION[name.split()[0]]
        bill = billing.open_bill(group, term)
        billing.add_line(bill, "Tuition", tuition * KOBO)
        for line, amount in LEVIES:
            billing.add_line(bill, line, amount * KOBO)
        billing.apply(bill, by=bursar)
        owed = tuition + sum(amount for _, amount in LEVIES)
        for child in placed[name]:
            roll = rng.random()
            if roll < 0.5:
                paid = owed
            elif roll < 0.82:
                paid = rng.choice((0.4, 0.5, 0.6, 0.75)) * owed // 1000 * 1000
            else:
                continue
            method = rng.choice(methods)
            fees.record_payment(
                child, term, int(paid) * KOBO, method=method,
                reference=f"TRF{rng.randint(10**9, 10**10 - 1)}" if method == PaymentMethod.BANK_TRANSFER else "",
                effective_on=_paid_on(days, rng), recorded_by=bursar,
            )


__all__ = ["NAME", "SIGN_INS", "SLUG", "Refused", "create", "find", "reset"]
