"""Two schools whose classes can be walked along the approval chain.

Subclasses `gradebook.tests.fixtures.MarkingSetUp`, which is itself
`attendance.tests.fixtures.RegisterSetUp` — so this inherits St Mary's *and*
Grace Academy as real schemas, with class groups, placements, staff and an
assessment already in place. Building a fourth copy of that would be the
fourteen-copies-of-`make_school` problem (#67) starting again.

What it adds is the chain's own cast: a vice principal (academic) and a
principal at each school, and a `ClassTeacher` assignment — without which
nobody can submit anything, because `_require_class_teacher_scope()` narrows
TEACHER to their own group and answers False when nobody is assigned.

The current term is set here too. The chain's list is keyed on
`Term.is_current`, so a fixture that left it unset would make every test read
an empty page for a reason unrelated to what it was asserting.
"""

from academics import services as academics
from academics.models import Term
from accounts.models import Role, User
from accounts.services import grant_membership
from gradebook.tests.fixtures import PASSWORD, MarkingSetUp
from schools.models import Domain, School
from schools.tests.tenants import connected_to

HOST = "st-marys.testserver"
THEIR_HOST = "grace.testserver"
PORTAL = "testserver"


class ChainSetUp(MarkingSetUp):
    """Both schools, both hosts, and everyone the chain needs."""

    def setUp(self):
        super().setUp()

        Domain.objects.create(tenant=self.stmarys, domain=HOST, is_primary=True)
        Domain.objects.create(tenant=self.grace, domain=THEIR_HOST, is_primary=True)
        portal = School(name="Portal", slug="portal", schema_name="public")
        portal.auto_create_schema = False
        portal.save()
        Domain.objects.create(tenant=portal, domain=PORTAL, is_primary=True)

        self.vp = grant_membership(
            User.objects.create_user("vera", PASSWORD, full_name="Vera Okoro"),
            self.stmarys,
            Role.VICE_PRINCIPAL_ACADEMIC,
        )
        # `self.head` is already the PRINCIPAL at St Mary's, from RegisterSetUp.

        self.their_vp = grant_membership(
            User.objects.create_user("vidal", PASSWORD, full_name="Vidal Ada"),
            self.grace,
            Role.VICE_PRINCIPAL_ACADEMIC,
        )
        self.their_head = grant_membership(
            User.objects.create_user("hope", PASSWORD, full_name="Hope Eze"),
            self.grace,
            Role.PRINCIPAL,
        )

        with connected_to(self.stmarys):
            Term.objects.filter(pk=self.term_id).update(is_current=True)
            # Without this nobody may submit: the scope answers False when no
            # class teacher is assigned, which is a school configuration
            # problem rather than an authorisation hole.
            academics.assign_class_teacher(
                self.jss1a, Term.objects.get(pk=self.term_id), self.teacher,
                by=self.head,
            )

        with connected_to(self.grace):
            Term.objects.filter(pk=self.grace_term_id).update(is_current=True)
            academics.assign_class_teacher(
                self.grace_group,
                Term.objects.get(pk=self.grace_term_id),
                self.grace_teacher,
                by=self.their_head,
            )


__all__ = ["ChainSetUp", "HOST", "THEIR_HOST", "PORTAL", "PASSWORD"]
