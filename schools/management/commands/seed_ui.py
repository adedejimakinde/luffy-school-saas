"""`manage.py seed_ui` — a class of its own for each file in `tests/ui/`. After `seed_demo`.

The browser tests run side by side, one process a file, against one demo
(`tests/ui/screens.test.js` says how). Two files that write to the same class
race each other: the register taken on a phone in `offline.test.js` was held
for review whenever `roll_import_gap.test.js` admitted three children into the
same class between the phone's copy and the send. So each file that writes
gets a class nobody else touches, with children nobody else marks, takes a
register for or imports beside:

- `offline.test.js`: **UI Offline**, six children (its marks and two registers);
- `marking_clear.test.js`: **UI Marking Clear**, six children (its Mathematics exam);
- `marking_focus.test.js`: **UI Marking Focus**, six children (its English exam);
- `roll_import_gap.test.js`: **UI Import**, empty (it admits its own three);
- `teaching.test.js`: **UI Teaching**, empty (it gives it a class teacher and takes it back).
- `sit.test.js`: **UI Sit**, six children who sit a test (CBT step 4): a Mathematics bank
  at the class's level, one approved test for the class, its sitting opened by hand
  now, a known test code (`SIT_CODE`) and known exam PINs (`sit_pin(n)`), so the browser
  can sign in at `/sit/` as each child in turn. A PIN is otherwise random and shown only
  on a slip; here, with DEBUG on and for fake children, it is fixed so a test can type it.
- `pwa.test.js`: **UI PWA**, two children who sit a test of their own (`PWA_CODE`, the same
  paper and the same fixed PINs): the installed app's worker beside the exam's, in a browser
  that has signed in, with a child no other file sits as (`docs/pwa.md`).

`screens.test.js` keeps `seed_demo`'s JSS 1A and JSS 1B, the classes it
photographs. Each file names its class, never "the first", and
`schools/tests/test_seed_demo.py` checks that no two files name the same one.

The classes sit at level 9, after JSS 1A and JSS 1B, so every list the screens
photograph starts as it always has. Sunrise's, in this term; the children have
no password, as nobody signs in as one.

**Refuses unless `DEBUG` is on**, as `seed_demo` does, **unless Sunrise is
there**, and **twice**: a second run has nothing to add.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django_tenants.utils import schema_context

from academics import services as academics
from academics.models import ClassGroup, Term
from accounts.models import User
from accounts.services import enroll_student
from schools.models import School

SLUG = "sunrise-demo"
LEVEL = 9

#: Each file's class: (name, the short tag its children's logins and
#: references carry, how many children).
CLASSES = (
    ("UI Offline", "off", 6),
    ("UI Marking Clear", "clr", 6),
    ("UI Marking Focus", "foc", 6),
    ("UI Import", "imp", 0),
    ("UI Teaching", "tch", 0),
    ("UI Sit", "sit", 6),
    ("UI PWA", "pwa", 2),
)

#: The test code and the PINs `sit.test.js` types. Fake children, DEBUG only.
SIT_CODE = "UISITQ"
SIT_TITLE = "UI Sit: Mathematics practice"
#: The same paper for `pwa.test.js`'s class, under a code and a title of its own.
PWA_CODE = "UIPWAQ"
PWA_TITLE = "UI PWA: Mathematics practice"


def sit_pin(n: int) -> str:
    return f"2026{n:04d}"

FIRST_NAMES = ("Ada", "Bayo", "Chidi", "Dayo", "Efe", "Funmi")


class Command(BaseCommand):
    help = "Give each browser test file its own class and children in Sunrise. After seed_demo."

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError("seed_ui only runs with DEBUG on: it adds fake children.")
        school = School.objects.filter(slug=SLUG).first()
        if school is None:
            raise CommandError("Sunrise is not here. Run seed_demo first.")
        with schema_context(school.schema_name):
            if ClassGroup.objects.filter(name__in=[name for name, _, _ in CLASSES]).exists():
                raise CommandError("The browser tests' classes are already here. Reset the database to seed again.")

        with transaction.atomic():
            children = {}
            for name, tag, count in CLASSES:
                children[name] = [
                    enroll_student(
                        User.objects.create_user(f"sunrise.ui{tag}{n:02d}", None, full_name=f"{FIRST_NAMES[n - 1]} {name.split()[-1]}"),
                        school,
                        reference=f"SUN/UI-{tag.upper()}-{n:02d}",
                    )
                    for n in range(1, count + 1)
                ]
            with schema_context(school.schema_name):
                term = Term.objects.get(is_current=True)
                for name, _, _ in CLASSES:
                    group = ClassGroup.objects.create(name=name, level=LEVEL)
                    for child in children[name]:
                        academics.place_student(group, term, child)
                    self.stdout.write(f"  {name:<18} {len(children[name])} children")
                sit_test(school, ClassGroup.objects.get(name="UI Sit"), children["UI Sit"])
                self.stdout.write(f"  UI Sit's test     code {SIT_CODE}, PINs {sit_pin(1)} to {sit_pin(6)}")
                sit_test(
                    school, ClassGroup.objects.get(name="UI PWA"), children["UI PWA"],
                    title=PWA_TITLE, code=PWA_CODE, bank=False,
                )
                self.stdout.write(f"  UI PWA's test     code {PWA_CODE}, PINs {sit_pin(1)} and {sit_pin(2)}")


def sit_test(school, group, children, *, title=SIT_TITLE, code=SIT_CODE, bank=True):
    """A test the class can sit now: written, set, approved and opened as a school would.

    `bank=False` for a second class at the same level, which sits from the same bank.
    """
    from datetime import timedelta
    from unittest import mock

    from django.utils import timezone

    from cbt import banks, pins, setting, sittings
    from cbt.models import SittingControl
    from gradebook.models import Subject
    from schools.crestfield.questions import BANK

    principal = User.objects.get(username="sunrise.principal")
    maths = Subject.objects.get(code="MTH")
    for stem, options, answer in BANK["Mathematics"] if bank else ():
        banks.add_as(principal, school, maths.pk, LEVEL, banks.Draft(stem=stem, options=list(options), correct_index=answer, marks=1))
    opens = timezone.now() + timedelta(minutes=1)
    test = setting.create_as(
        principal, school,
        setting.TestDraft(
            title=title, subject_id=maths.pk, level=LEVEL, class_group_ids=[group.pk], question_count=10,
            opens_at=opens, closes_at=opens + timedelta(days=60), duration=40, calculator=True,
        ),
    )
    setting.submit_as(principal, school, test.pk)
    setting.approve_as(principal, school, test.pk)
    sittings.control_as(principal, school, test.pk, group.pk, SittingControl.Kind.OPENED, "Browser tests")
    sittings.set_code_as(principal, school, test.pk, code=code)
    order = {child.pk: n for n, child in enumerate(children, start=1)}
    minted = iter(sit_pin(order[s.pk]) for s in pins.roster(school, group, pins.current_term()))
    with mock.patch("cbt.pins.new_pin", side_effect=lambda: next(minted)):
        pins.print_class_as(principal, school, group.pk)
    return test
