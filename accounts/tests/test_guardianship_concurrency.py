"""Two parents linked to one child at the same moment, and what refuses.

`link_guardian()` reaches `Guardianship.objects.get_or_create()`, which is only
safe under concurrency because it catches `IntegrityError` from the unique index
and re-reads. PR #93 put a `full_clean()` inside `Guardianship.save()`, and a
`full_clean()` that refused a duplicate in Python would raise `ValidationError`
before the insert ever reached the database — taking the row out of
`get_or_create()`'s hands and turning a survivable race into an exception.

It does not, and the reason is **not** the one it looks like. Measured here
rather than reasoned about, because the obvious reading is wrong:

    validate_unique=True   validate_constraints=True   -> ValidationError ['__all__']
    validate_unique=True   validate_constraints=False  -> no error
    validate_unique=False  validate_constraints=True   -> ValidationError ['__all__']
    validate_unique=False  validate_constraints=False  -> no error

`validate_unique` makes no difference either way. `Guardianship._meta.unique_together`
is empty — the pair's uniqueness lives only in `Meta.constraints` as a
`UniqueConstraint`, and `validate_unique()` has never looked at those.
`validate_constraints()` does, and that is the flag `save()` passes `False`.

So the window is held open by `validate_constraints=False`, not by
`validate_unique=False`, and a future edit that "tidies up" the wrong one of the
two would change nothing while the other would close the path silently. Both
halves are asserted below.

`TransactionTestCase` and real threads, because this needs two connections whose
commits are visible to each other. The interleaving is driven by a barrier, not
by sleeps, so both calls are provably in flight together — the idiom
`test_transfer_concurrency.py` established.
"""

import threading

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connections, transaction
from django.test import TransactionTestCase

from accounts import services
from accounts.models import Guardianship, Membership, Role, User
from schools.models import School

PASSWORD = "correct-horse-battery"


def make_school(name, slug, schema_name):
    school = School(name=name, slug=slug, schema_name=schema_name)
    school.auto_create_schema = False
    school.save()
    return school


def make_user(username, full_name, **extra):
    return User.objects.create_user(username, PASSWORD, full_name=full_name, **extra)


class TheRaceWindowIsStillTheDatabasesTests(TransactionTestCase):
    def setUp(self):
        self.school = make_school("St Mary's", "st-marys", "st_marys")
        self.parent = make_user("08031234567", "Bisi Ade", phone="08031234567")
        self.child = services.enroll_student(make_user("STM/1", "Ada Ade"), self.school)

    def test_a_duplicate_is_refused_by_the_index_and_not_by_validate_unique(self):
        """The decisive one: which layer refuses a duplicate pair.

        If `save()` ever starts running `validate_unique()`, this flips to
        `ValidationError` and `get_or_create()` — which catches `IntegrityError`
        and nothing else — stops being able to recover from a lost race.

        The `atomic()` block is deliberate: an `IntegrityError` with no savepoint
        under it breaks the transaction for every statement after it, which is
        issue #90.
        """
        Guardianship.objects.create(guardian=self.parent, student=self.child)
        duplicate = Guardianship(guardian=self.parent, student=self.child)

        with self.assertRaises(IntegrityError) as caught:
            with transaction.atomic():
                duplicate.save()

        # Name the index, not the word "duplicate" — `accounts` has two unique
        # constraints on this table and five more on `Membership`, and #89 is
        # about exactly the assertion that cannot tell them apart.
        self.assertIn("uniq_guardianship_guardian_student", str(caught.exception))
        self.assertEqual(Guardianship.objects.count(), 1)

    def test_it_is_validate_constraints_and_not_validate_unique_holding_it_open(self):
        """Which flag actually guards the window — the two are not interchangeable.

        Pinned because the natural reading of `save()`'s call is that
        `validate_unique=False` is what keeps the duplicate reaching the index,
        and that reading is wrong. Uniqueness here is a `UniqueConstraint` in
        `Meta.constraints`, which `validate_unique()` does not inspect; only
        `validate_constraints()` does.
        """
        Guardianship.objects.create(guardian=self.parent, student=self.child)

        # The flag that does nothing: asking for unique validation still lets it past.
        Guardianship(guardian=self.parent, student=self.child).full_clean(
            exclude=None, validate_unique=True, validate_constraints=False
        )

        # The flag that would close the path, with unique validation switched off.
        with self.assertRaises(ValidationError) as caught:
            Guardianship(guardian=self.parent, student=self.child).full_clean(
                exclude=None, validate_unique=False, validate_constraints=True
            )
        self.assertEqual(list(caught.exception.error_dict), ["__all__"])

        # And the model's own uniqueness really is constraint-borne, which is
        # why the split above falls that way round.
        self.assertEqual(Guardianship._meta.unique_together, ())
        self.assertEqual(
            [c.name for c in Guardianship._meta.total_unique_constraints],
            ["uniq_guardianship_guardian_student"],
        )

    def test_two_concurrent_links_of_one_pair_leave_one_row(self):
        """Both callers succeed and both get the same row.

        The PARENT membership is granted first, so `grant_membership()` finds a
        row to `select_for_update()` and the two calls serialise there rather
        than colliding. See the module note below for the cold-start case, which
        is a different and pre-existing defect.
        """
        services.grant_membership(self.parent, self.school, Role.PARENT)

        ready = threading.Barrier(2, timeout=15)
        results = []
        guard = threading.Lock()

        def run(tag):
            try:
                ready.wait()
                link = services.link_guardian(self.parent, self.child)
                with guard:
                    results.append((tag, "ok", link.pk))
            except Exception as exc:  # noqa: BLE001 — the tag is the assertion
                with guard:
                    results.append((tag, type(exc).__name__, str(exc)[:90]))
            finally:
                connections.close_all()

        threads = [threading.Thread(target=run, args=(t,)) for t in ("A", "B")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(20)

        self.assertEqual([r[1] for r in results], ["ok", "ok"], results)
        self.assertEqual(len({r[2] for r in results}), 1, results)
        self.assertEqual(Guardianship.objects.count(), 1)
        self.assertEqual(
            Membership.objects.filter(user=self.parent, role=Role.PARENT).count(), 1
        )
