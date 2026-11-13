"""Who may print ID cards: asked on the server, on every route, for every role.

The principal, the vice principal (academic) and the administrator, and nobody
else. A teacher (class teacher included), a bursar, a parent and a student are
each refused on the overview, the roll, the start, the status and the download:
the rule is in the request, not in a button that is or is not drawn.
`test_a_principal_elsewhere_who_is_a_parent_here_cannot_print` is the one that
fails when the rule asks for roles anywhere rather than roles here.
"""

from academics.models import ClassGroup, Term
from academics.services import assign_class_teacher
from accounts.models import Role, User
from accounts.services import grant_membership, link_guardian
from schools.tests.tenants import connected_to
from tests.guardians import give_verified_channel

from idcards.models import IdCardPrint

from .base import MAY_PRINT, PASSWORD, STAFF_ROLES, IdCardSetUp


class EveryRoleOnEveryRouteTests(IdCardSetUp):
    def test_the_three_roles_may_and_the_others_may_not_on_each_route(self):
        for role in STAFF_ROLES:
            user = self.staff[role]
            allowed = role in MAY_PRINT
            with self.subTest(role=role.value):
                self.assertEqual(self.overview(user).status_code, 200 if allowed else 403)
                self.assertEqual(self.roster(user).status_code, 200 if allowed else 403)
                self.assertEqual(self.start(user).status_code, 202 if allowed else 403)

    def test_a_refused_start_makes_no_job_and_queues_nothing(self):
        with connected_to(self.stmarys):
            before = IdCardPrint.objects.count()
        for role in STAFF_ROLES:
            if role in MAY_PRINT:
                continue
            self.assertEqual(self.start(self.staff[role]).status_code, 403)
        self.assertEqual(self.queued, [])
        with connected_to(self.stmarys):
            self.assertEqual(IdCardPrint.objects.count(), before)

    def test_a_class_teacher_may_not_print_even_their_own_class(self):
        teacher = self.staff[Role.TEACHER]
        with connected_to(self.stmarys):
            membership = teacher.memberships.get(school=self.stmarys, role=Role.TEACHER)
            for term in Term.objects.all():
                assign_class_teacher(ClassGroup.objects.get(pk=self.group_id), term, membership)
        self.assertEqual(self.overview(teacher).status_code, 403)
        self.assertEqual(self.start(teacher).status_code, 403)

    def test_a_parent_and_a_student_may_not(self):
        child = User.objects.get(username="ada")
        for user in (self.mama, child):
            with self.subTest(user=user.username):
                self.assertEqual(self.overview(user).status_code, 403)
                self.assertEqual(self.roster(user).status_code, 403)
                self.assertEqual(self.start(user).status_code, 403)

    def test_signed_out_is_refused(self):
        self.assertEqual(self.overview(None).status_code, 401)
        self.assertEqual(self.start(None).status_code, 401)
        self.assertEqual(self.status(None, 1).status_code, 401)
        self.assertEqual(self.download(None, 1).status_code, 401)

    def test_the_refusal_comes_before_any_lookup(self):
        """A class that does not exist answers 403 to somebody who may not print, not 404."""
        self.assertEqual(self.roster(self.staff[Role.TEACHER], group_id=9999).status_code, 403)
        self.assertEqual(self.start(self.staff[Role.BURSAR], group_id=9999).status_code, 403)
        self.assertEqual(self.roster(self.principal, group_id=9999).status_code, 404)


class TheJobBelongsToWhoAskedTests(IdCardSetUp):
    def test_only_the_person_who_asked_may_watch_or_download(self):
        job, _ = self.printed(self.principal)
        for other in (self.staff[Role.VICE_PRINCIPAL_ACADEMIC], self.staff[Role.ADMIN]):
            with self.subTest(other=other.username):
                self.assertEqual(self.status(other, job.pk).status_code, 404)
                self.assertEqual(self.download(other, job.pk).status_code, 404)
        self.assertEqual(self.status(self.principal, job.pk).status_code, 200)

    def test_someone_who_loses_the_role_loses_the_file(self):
        job, _ = self.printed(self.staff[Role.ADMIN])
        membership = self.staff[Role.ADMIN].memberships.get(school=self.stmarys, role=Role.ADMIN)
        membership.end()
        # Refused: by the school's door for somebody with no place here, or by the route.
        self.assertIn(self.status(self.staff[Role.ADMIN], job.pk).status_code, (403, 404))
        self.assertIn(self.download(self.staff[Role.ADMIN], job.pk).status_code, (403, 404))

    def test_a_suspended_principal_may_not_print(self):
        membership = self.principal.memberships.get(school=self.stmarys, role=Role.PRINCIPAL)
        membership.status = "suspended"
        membership.save(update_fields=["status"])
        self.assertEqual(self.start(self.principal).status_code, 403)

    def test_the_generic_file_route_never_sends_it(self):
        job, _ = self.printed(self.principal)
        self.as_(self.principal)
        response = self.client.get(f"/files/{job.file_key}/id-cards.pdf", HTTP_HOST=self.host(self.stmarys))
        self.assertEqual(response.status_code, 404)


class TwoSchoolsTests(IdCardSetUp):
    def test_a_principal_elsewhere_who_is_a_parent_here_cannot_print(self):
        """Signed in here (as a parent), so past the middleware: only the rule's own
        question, "roles at *this* school", stands between them and the class."""
        both = User.objects.create_user("both", PASSWORD, full_name="Both Ways")
        grant_membership(both, self.grace, Role.PRINCIPAL)
        link_guardian(both, self.bola)
        give_verified_channel(both, "08030000099")
        job, _ = self.printed(self.principal)

        self.assertEqual(self.start(both, self.stmarys).status_code, 403)
        self.assertEqual(self.overview(both, self.stmarys).status_code, 403)
        self.assertEqual(self.roster(both, self.stmarys).status_code, 403)
        self.assertEqual(self.status(both, job.pk).status_code, 404)
        self.assertEqual(self.download(both, job.pk).status_code, 404)
        # The control: at Grace, where they are principal, they may.
        self.assertEqual(self.start(both, self.grace).status_code, 202)

    def test_another_schools_principal_cannot_use_this_schools_host(self):
        for call in (self.overview, self.roster, self.start):
            with self.subTest(call=call.__name__):
                self.assertIn(call(self.their_staff[Role.PRINCIPAL], self.stmarys).status_code, (403, 404))
        with connected_to(self.stmarys):
            self.assertFalse(IdCardPrint.objects.exists())

    def test_the_portal_has_no_cards(self):
        self.as_(self.principal)
        self.assertEqual(self.client.get("/api/id-cards/", HTTP_HOST="testserver").status_code, 404)
