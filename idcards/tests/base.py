"""Two schools, every role, and a class of children: what every ID card test starts from.

Written out here rather than inherited from the report card tests' fixtures, which
build marks and releases a card has no use for. Two schools throughout, St Mary's
and Grace, because a test of one school proves nothing about tenancy: the claim
"another school's card is refused" is a claim about `TenantMainMiddleware` and the
card lookup together, and only a second school that is really built and really
used can test it.

Dates are made from today, so the suite does not start failing when a session ends.
"""

import tempfile
from datetime import timedelta
from unittest import mock

from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone

from academics.models import ClassGroup, Term, TermName
from academics.services import place_student
from accounts.models import Role, User
from accounts.services import enroll_student, grant_membership, link_guardian
from idcards import printing
from idcards.models import IdCardPrint
from idcards.tasks import build_id_cards
from schools.models import Domain, School
from schools.tests.tenants import connected_to, make_school
from tests.guardians import give_verified_channel

PASSWORD = "correct-horse-battery"
HOST = "st-marys.testserver"
THEIR_HOST = "grace.testserver"

#: The school's phone, and a parent's: the card may print the first and never the second.
SCHOOL_PHONE = "0803 123 4567"
PARENT_PHONE = "08030000001"

STAFF_ROLES = (
    Role.PRINCIPAL,
    Role.VICE_PRINCIPAL_ACADEMIC,
    Role.ADMIN,
    Role.TEACHER,
    Role.BURSAR,
)
#: Who may print, by the rule in the request. Held here as a literal, not imported from
#: `idcards.access`, so that a change to the rule has to change a test too.
MAY_PRINT = {Role.PRINCIPAL, Role.VICE_PRINCIPAL_ACADEMIC, Role.ADMIN}


def session_label(today=None) -> str:
    today = today or timezone.localdate()
    return f"{today.year}/{today.year + 1}"


def body(response) -> bytes:
    if getattr(response, "streaming", False):
        return b"".join(response.streaming_content)
    return response.content


class IdCardSetUp(TestCase):
    def setUp(self):
        today = timezone.localdate()
        self.today = today
        self.session = session_label(today)
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        settings = override_settings(FILES_ROOT=root.name, FILES_X_ACCEL=False)
        settings.enable()
        self.addCleanup(settings.disable)

        self.stmarys = self._school("St Mary's", "st-marys", "st_marys", HOST, phone=SCHOOL_PHONE, address="12 Palm Road, Abeokuta")
        self.grace = self._school("Grace Academy", "grace", "grace", THEIR_HOST, phone="0809 999 0000")

        # The portal: no schema of its own, and no cards.
        portal = School(name="Portal", slug="portal", schema_name="public")
        portal.auto_create_schema = False
        portal.save()
        Domain.objects.create(tenant=portal, domain="testserver", is_primary=True)

        self.staff = {role: self._staff(self.stmarys, role) for role in STAFF_ROLES}
        self.their_staff = {role: self._staff(self.grace, role) for role in STAFF_ROLES}
        self.principal = self.staff[Role.PRINCIPAL]

        self.terms = self._terms(self.stmarys)
        self.their_terms = self._terms(self.grace)
        self.group_id = self._group(self.stmarys)
        self.their_group_id = self._group(self.grace)

        self.ada = self._child(self.stmarys, "ada", "Ada Obi", "STM/001", self.group_id, self.terms)
        self.bola = self._child(self.stmarys, "bola", "Bola Eze", "STM/002", self.group_id, self.terms)
        self.ngozi = self._child(self.grace, "ngozi", "Ngozi Ade", "GRC/001", self.their_group_id, self.their_terms)

        self.mama = User.objects.create_user("mama", PASSWORD, full_name="Mama Ada")
        link_guardian(self.mama, self.ada)
        give_verified_channel(self.mama, PARENT_PHONE)

        self.queued = []
        enqueue = mock.patch.object(printing, "_enqueue", side_effect=lambda s, j: self.queued.append((s, j)))
        enqueue.start()
        self.addCleanup(enqueue.stop)

    def tearDown(self):
        # `TenantMainMiddleware` leaves the connection on the school's schema.
        connection.set_schema_to_public()
        super().tearDown()

    # -- fixtures --------------------------------------------------------------

    def _school(self, name, slug, schema_name, host, *, phone="", address=""):
        school = make_school(name, slug, schema_name)
        school.phone, school.address = phone, address
        school.save(update_fields=["phone", "address"])
        Domain.objects.create(tenant=school, domain=host, is_primary=True)
        return school

    def _staff(self, school, role):
        user = User.objects.create_user(f"{school.schema_name}-{role.value}", PASSWORD, full_name=f"{role.label} of {school.name}")
        grant_membership(user, school, role)
        return user

    def _terms(self, school):
        t = self.today
        spans = {
            TermName.FIRST.value: (t - timedelta(days=60), t + timedelta(days=30)),
            TermName.SECOND.value: (t + timedelta(days=60), t + timedelta(days=150)),
            TermName.THIRD.value: (t + timedelta(days=180), t + timedelta(days=270)),
        }
        with connected_to(school):
            return {
                name: Term.objects.create(
                    session=self.session, name=name, starts_on=a, ends_on=b, is_current=name == TermName.FIRST.value
                ).pk
                for name, (a, b) in spans.items()
            }

    def _group(self, school):
        with connected_to(school):
            return ClassGroup.objects.create(name="JSS 1A", level=1).pk

    def _child(self, school, username, full_name, reference, group_id, terms):
        membership = enroll_student(
            User.objects.create_user(username, PASSWORD, full_name=full_name), school, reference=reference
        )
        with connected_to(school):
            group = ClassGroup.objects.get(pk=group_id)
            for term_id in terms.values():
                place_student(group, Term.objects.get(pk=term_id), membership)
        return membership

    def more_children(self, count, school=None):
        """`count` more children in St Mary's JSS 1A, for a class that needs a second sheet."""
        school = school or self.stmarys
        made = []
        for n in range(count):
            made.append(self._child(school, f"kid{n}", f"Child {n:02d} Test", f"STM/1{n:02d}", self.group_id, self.terms))
        return made

    # -- accessors ----------------------------------------------------------------

    def host(self, school):
        return HOST if school == self.stmarys else THEIR_HOST

    def terms_of(self, school):
        return self.terms if school == self.stmarys else self.their_terms

    def group_of(self, school):
        return self.group_id if school == self.stmarys else self.their_group_id

    def as_(self, user):
        if user is None:
            self.client.logout()
        else:
            self.client.force_login(user)

    # -- the calls ------------------------------------------------------------------

    def overview(self, user, school=None, host=None, query=""):
        school = school or self.stmarys
        self.as_(user)
        return self.client.get(f"/api/id-cards/{query}", HTTP_HOST=host or self.host(school))

    def roster(self, user, school=None, host=None, group_id=None, term_id=None):
        school = school or self.stmarys
        self.as_(user)
        return self.client.get(
            f"/api/id-cards/classes/{group_id or self.group_of(school)}/{term_id or self.terms_of(school)[TermName.FIRST.value]}/",
            HTTP_HOST=host or self.host(school),
        )

    def start(self, user, school=None, ids=None, host=None, group_id=None, term_id=None):
        school = school or self.stmarys
        self.as_(user)
        return self.client.post(
            f"/api/id-cards/classes/{group_id or self.group_of(school)}/{term_id or self.terms_of(school)[TermName.FIRST.value]}/print/",
            {"student_ids": ids or []},
            content_type="application/json",
            HTTP_HOST=host or self.host(school),
        )

    def status(self, user, job_id, school=None, host=None):
        school = school or self.stmarys
        self.as_(user)
        return self.client.get(f"/api/id-cards/jobs/{job_id}/", HTTP_HOST=host or self.host(school))

    def download(self, user, job_id, school=None, host=None):
        school = school or self.stmarys
        self.as_(user)
        return self.client.get(f"/api/id-cards/jobs/{job_id}/pdf/", HTTP_HOST=host or self.host(school))

    def run_job(self, job_id, school=None):
        school = school or self.stmarys
        return build_id_cards.apply(args=[school.schema_name, job_id]).get()

    def printed(self, user, school=None, ids=None):
        """Start, run, and download. Returns `(job, pdf bytes)`."""
        school = school or self.stmarys
        response = self.start(user, school, ids)
        self.assertEqual(response.status_code, 202, response.content)
        job_id = response.json()["id"]
        self.run_job(job_id, school)
        got = self.download(user, job_id, school)
        self.assertEqual(got.status_code, 200, None if got.status_code == 200 else got.content[:300])
        with connected_to(school):
            job = IdCardPrint.objects.get(pk=job_id)
        return job, body(got)

    def token_of(self, membership, school=None):
        from idcards.models import IdCard

        with connected_to(school or self.stmarys):
            return IdCard.objects.get(student_membership_id=membership.pk, session=self.session).token

    def verify(self, token, host=HOST, user=None):
        self.as_(user)
        return self.client.get(f"/verify/{token}/", HTTP_HOST=host)
