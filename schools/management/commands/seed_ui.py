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
)

#: The test code and the PINs `sit.test.js` types. Fake children, DEBUG only.
SIT_CODE = "UISITQ"
SIT_TITLE = "UI Sit: Mathematics practice"

#: `screens.test.js`'s results (CBT step 5): a test JSS 1A has sat, and released, so the
#: results, the item analysis, Send to CA and both score pages have real numbers. Its code
#: and the first child's exam PIN are fixed, so the screens can open her score page.
RESULTS_CODE = "RSWKTB"
RESULTS_TITLE = "UI Results: Mathematics check"
RESULTS_PIN = "20269001"
RESULTS_SITTERS = 6


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
                results_test(school)
                self.stdout.write(f"  JSS 1A's results  code {RESULTS_CODE}, the first child's PIN {RESULTS_PIN}")
                sit_test(school, ClassGroup.objects.get(name="UI Sit"), children["UI Sit"])
                self.stdout.write(f"  UI Sit's test     code {SIT_CODE}, PINs {sit_pin(1)} to {sit_pin(6)}")


def results_test(school):
    """A test JSS 1A sat and the principal released, for `screens.test.js`'s results.

    Written, set, approved, opened by hand, sat by six of JSS 1A (`cbt.demo`), closed by
    hand and released, as a school would. Made before UI Sit's test, so the Tests list
    still opens with UI Sit's.
    """
    import random
    from datetime import timedelta
    from unittest import mock

    from django.utils import timezone

    from cbt import banks, demo, pins, release, setting, sittings
    from cbt.models import SittingControl
    from gradebook.models import Subject
    from schools.crestfield.questions import BANK

    principal = User.objects.get(username="sunrise.principal")
    maths = Subject.objects.get(code="MTH")
    group = ClassGroup.objects.get(name="JSS 1A")
    for stem, options, answer in BANK["Mathematics"]:
        banks.add_as(principal, school, maths.pk, group.level, banks.Draft(stem=stem, options=list(options), correct_index=answer, marks=1))
    opens = timezone.now() + timedelta(minutes=1)
    test = setting.create_as(
        principal, school,
        setting.TestDraft(
            title=RESULTS_TITLE, subject_id=maths.pk, level=group.level, class_group_ids=[group.pk], question_count=10,
            opens_at=opens, closes_at=opens + timedelta(days=60), duration=20,
        ),
    )
    setting.submit_as(principal, school, test.pk, rng=random.Random(RESULTS_CODE))
    setting.approve_as(principal, school, test.pk)
    sittings.set_code_as(principal, school, test.pk, code=RESULTS_CODE)
    sittings.control_as(principal, school, test.pk, group.pk, SittingControl.Kind.OPENED, "Sat in period 1")
    roster = pins.roster(school, group, pins.current_term())
    # The first child, whose score page the screens open, gets a few wrong, so it has
    # corrections to show.
    chances = (0.6, 0.9, 0.8, 0.7, 0.5, 0.85)
    demo.sit_finished(school, test, roster[:RESULTS_SITTERS], rng=random.Random(RESULTS_TITLE), ability=lambda n: chances[n])
    sittings.control_as(principal, school, test.pk, group.pk, SittingControl.Kind.CLOSED, "Period 1 is over")
    release.release_as(principal, school, test.pk, group.pk)
    with mock.patch("cbt.pins.new_pin", return_value=RESULTS_PIN):
        pins.print_student_as(principal, school, group.pk, roster[0].pk)
    return test


def sit_test(school, group, children):
    """A test "UI Sit" can sit now: written, set, approved and opened as a school would."""
    from datetime import timedelta
    from unittest import mock

    from django.utils import timezone

    from cbt import banks, pins, setting, sittings
    from cbt.models import SittingControl
    from gradebook.models import Subject
    from schools.crestfield.questions import BANK

    principal = User.objects.get(username="sunrise.principal")
    maths = Subject.objects.get(code="MTH")
    for stem, options, answer in BANK["Mathematics"]:
        banks.add_as(principal, school, maths.pk, LEVEL, banks.Draft(stem=stem, options=list(options), correct_index=answer, marks=1))
    opens = timezone.now() + timedelta(minutes=1)
    test = setting.create_as(
        principal, school,
        setting.TestDraft(
            title=SIT_TITLE, subject_id=maths.pk, level=LEVEL, class_group_ids=[group.pk], question_count=10,
            opens_at=opens, closes_at=opens + timedelta(days=60), duration=40, calculator=True,
        ),
    )
    setting.submit_as(principal, school, test.pk)
    setting.approve_as(principal, school, test.pk)
    sittings.control_as(principal, school, test.pk, group.pk, SittingControl.Kind.OPENED, "Browser tests")
    sittings.set_code_as(principal, school, test.pk, code=SIT_CODE)
    order = {child.pk: n for n, child in enumerate(children, start=1)}
    minted = iter(sit_pin(order[s.pk]) for s in pins.roster(school, group, pins.current_term()))
    with mock.patch("cbt.pins.new_pin", side_effect=lambda: next(minted)):
        pins.print_class_as(principal, school, group.pk)
    return test
