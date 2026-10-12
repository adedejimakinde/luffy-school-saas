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
)

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
