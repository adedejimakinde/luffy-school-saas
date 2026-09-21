"""Two schools with real rosters, plus the subject and assessment to mark.

**Subclasses `attendance.tests.fixtures.RegisterSetUp` rather than building a
third copy of the same thing.** That fixture already has what a marking sheet
needs and what a single-school one cannot test: St Mary's *and* Grace Academy,
each a real schema, with class groups and `ClassPlacement` rows behind them.
Copying it here would be the fourteen-copies-of-`make_school` problem (issue
#67) starting again in a new app, and the reason its docstring gives for two
schools is the reason this module needs them too — "a single-tenant fixture
cannot fail for any of the reasons a roster query is most likely to be got
wrong: a missing `term` filter, a uniqueness that should be per-schema, a write
on the wrong connection."

Two gaps in it are filled here, and both are about being able to *fail*:

- `RegisterSetUp` places all four children in **JSS 1A**, leaving JSS 1B empty.
  A class-scoped sheet tested against that passes whether or not the scope
  works, because there is nothing in the other group to leak. So a fifth child
  is placed in JSS 1B.
- Grace has schools, staff and a schema but no group, child or assessment. "A
  sheet at one school cannot answer for the other" asserted against an empty
  school is a claim about emptiness, not about scoping.

`Subject`'s unique constraints are per-schema, so both schools hold their own
"Mathematics"/"MTH" without colliding — which is itself one of the things a
two-school fixture is here to keep true.
"""

from academics import services as academics
from academics.models import ClassGroup
from accounts.models import Role, User
from accounts.services import enroll_student, grant_membership
from attendance.tests.fixtures import PASSWORD, RegisterSetUp, a_term
from gradebook.models import Assessment, Subject
from schools.tests.tenants import connected_to


class MarkingSetUp(RegisterSetUp):
    """St Mary's with two marked-up groups, and a Grace that can disagree."""

    def setUp(self):
        super().setUp()

        # The fifth child, in the group the register fixture leaves empty. This
        # is what gives the class scope two groups to tell apart.
        self.bimpe = enroll_student(
            User.objects.create_user("bimpe", PASSWORD, full_name="Bimpe Ojo"),
            self.stmarys,
        )

        with connected_to(self.stmarys):
            academics.place_student(self.jss1b, self.term, self.bimpe)
            self.maths = Subject.objects.create(name="Mathematics", code="MTH")
            self.first_ca = Assessment.objects.create(
                term=self.term, subject=self.maths, name="First CA", max_score=20
            )
            self.first_ca_id = self.first_ca.pk
            self.maths_id = self.maths.pk

        # Grace's own everything. Its ids are deliberately *not* reused from
        # St Mary's: two schemas number their rows independently, and a test
        # that borrowed an id would be asserting against a coincidence.
        self.grace_teacher = grant_membership(
            User.objects.create_user("dupe", PASSWORD, full_name="Dupe Ade"),
            self.grace,
            Role.TEACHER,
        )
        self.grace_child = enroll_student(
            User.objects.create_user("chidi", PASSWORD, full_name="Chidi Eze"),
            self.grace,
        )

        with connected_to(self.grace):
            self.grace_term = a_term()
            self.grace_group = ClassGroup.objects.create(name="JSS 1A", level=1)
            academics.place_student(self.grace_group, self.grace_term, self.grace_child)
            grace_maths = Subject.objects.create(name="Mathematics", code="MTH")
            self.grace_ca = Assessment.objects.create(
                term=self.grace_term,
                subject=grace_maths,
                name="First CA",
                max_score=20,
            )
            self.grace_ca_id = self.grace_ca.pk
            self.grace_group_id = self.grace_group.pk
            self.grace_term_id = self.grace_term.pk


__all__ = ["MarkingSetUp", "PASSWORD"]
