"""The report card over HTTP: what a family gets, and what must never be in it.

The rule this file exists to hold is not a rendering preference and cannot be
enforced in a template:

> Position is **staff-only**. It must not reach a parent or a student, in a card
> *or in a payload*. Excluded at the serializer, because omitting a field from a
> page while leaving it in the JSON is the same leak with an extra step.

`results/tests/test_positions_api.py` asks that question of the broadsheet. This
file asks it of the card, where the answer is harder to be sure of: the
broadsheet's staff-only numbers are its whole subject and a family has no route
to it at all, whereas the card is *designed* for a family and is assembled from
six frozen tables that each carry a staff-only column.

## The control is the point of this file

`assertNotIn(b"position", response.content)` passes for two completely different
reasons: because the serializer excluded it, or because there was no position to
exclude. A card for the only child in a class, or for a child with no marks, has
`position` null and `subject_position` null, and every exclusion test in this
file would pass green against a serializer that leaked all of them.

So `TheSnapshotReallyHoldsTheStaffOnlyNumbers` runs first and asserts the frozen
rows **do** carry a position, a roster size and a subject position — against the
same fixture the exclusion tests use. Two children with different marks, so the
ranking is real and the numbers are not one.

Assertions are on the **bytes**, deliberately cruder than parsing. A leak that
renamed the field, nested it one level deeper, or put it in an error body would
still be a leak, and a structural assertion on parsed JSON would walk past all
three.

## Two schools, and Grace is used

Grace Academy releases a card of its own and its principal is a real signed-in
caller in `WhoMayReadACard`. A second school built and never exercised proves
nothing about tenancy — it is `#38`'s finding 10, and this file would be
vulnerable to exactly it, because "can Grace's principal read Ada's card" is a
question about `TenantMainMiddleware` and the authority check together and
neither one alone answers it.

Not `RequestFactory`: these are tenant tables and the schema is chosen from the
hostname. A test that skipped the middleware would query whichever schema the
connection happened to be left on.
"""

import json
from contextlib import contextmanager
from datetime import date

from django.db import connection
from django.test import TestCase
from django_tenants.utils import schema_context

from academics.models import ClassGroup, Term, TermName
from academics.services import assign_class_teacher, place_student
from accounts.models import Role, User
from accounts.services import enroll_student, grant_membership, link_guardian
from gradebook.models import Assessment, Score, Subject
from results import cards, sessions
from results import services as results_services
from results.models import (
    PromotionStatus,
    ReleasedCard,
    ReleasedSessionResult,
    ReleasedSubjectResult,
    TraitGroup,
)
from schools.models import Domain, School

PASSWORD = "correct-horse-battery"
SESSION = "2025/2026"

HOST = "st-marys.testserver"
THEIR_HOST = "grace.testserver"

TERM_DATES = {
    TermName.FIRST.value: (date(2025, 9, 15), date(2025, 12, 12)),
    TermName.SECOND.value: (date(2026, 1, 12), date(2026, 4, 2)),
    TermName.THIRD.value: (date(2026, 4, 27), date(2026, 7, 24)),
}


@contextmanager
def connected_to(school):
    with schema_context(school.schema_name):
        yield


class ReportCardApiSetUp(TestCase):
    """Two schools, each with a full session, a class, two subjects, children.

    Written out here rather than inherited from `CardSetUp` in `test_cards.py`,
    and the reason is a bug this project has hit before. That fixture is
    single-school: `term()` and `group()` take a `school` argument and then read
    `self.terms` and `self.group_id`, which are always St Mary's. Because each
    tenant schema has its own sequences, `Term.objects.get(pk=...)` inside
    Grace's schema resolves to a *different, existing* Grace term rather than
    raising — so a two-school test built on it would quietly assert against the
    wrong school and stay green. Everything below branches on the school.
    """

    def setUp(self):
        self.stmarys = self._school("St Mary's", "st-marys", "st_marys", HOST)
        self.grace = self._school("Grace Academy", "grace", "grace", THEIR_HOST)

        # The portal. No schema of its own; it is the public one.
        portal = School(name="Portal", slug="portal", schema_name="public")
        portal.auto_create_schema = False
        portal.save()
        Domain.objects.create(tenant=portal, domain="testserver", is_primary=True)

        self.staff = self._staff_for(self.stmarys)
        self.principal = self.staff[Role.PRINCIPAL]
        self.teacher = self.staff[Role.TEACHER]
        self.vp = self.staff[Role.VICE_PRINCIPAL_ACADEMIC]
        self.bursar = self._one_staff(self.stmarys, "bursar", Role.BURSAR)

        self.their_staff = self._staff_for(self.grace)
        self.their_principal = self.their_staff[Role.PRINCIPAL]

        self.terms, self.group_id, self.subjects = self._academics(
            self.stmarys, self.teacher
        )
        self.their_terms, self.their_group_id, self.their_subjects = self._academics(
            self.grace, self.their_staff[Role.TEACHER]
        )

        # Two children with *different* marks, so a position is a real ranking
        # rather than a tie or a one-child class where every rank is 1.
        self.ada = self._child(self.stmarys, "ada", "Ada Obi")
        self.bola = self._child(self.stmarys, "bola", "Bola Eze")
        self._mark(self.stmarys, TermName.FIRST.value, self.ada, "maths", "Exam", 88)
        self._mark(self.stmarys, TermName.FIRST.value, self.bola, "maths", "Exam", 61)
        self._mark(self.stmarys, TermName.FIRST.value, self.ada, "english", "Exam", 74)
        self._mark(self.stmarys, TermName.FIRST.value, self.bola, "english", "Exam", 55)

        # Grace has a child and marks of her own, and releases a term below, so
        # that "Grace is untouched" is a claim about the release rather than
        # about an empty school.
        self.ngozi = self._child(self.grace, "ngozi", "Ngozi Ade")
        self._mark(self.grace, TermName.FIRST.value, self.ngozi, "maths", "Exam", 90)

        self.mama = User.objects.create_user("mama", PASSWORD, full_name="Mama Ada")
        link_guardian(self.mama, self.ada)
        self.bolas_father = User.objects.create_user(
            "papa", PASSWORD, full_name="Papa Bola"
        )
        link_guardian(self.bolas_father, self.bola)

    # -- fixtures ------------------------------------------------------------

    def _school(self, name, slug, schema_name, host):
        school = School(name=name, slug=slug, schema_name=schema_name)
        school.save()
        Domain.objects.create(tenant=school, domain=host, is_primary=True)
        return school

    def _one_staff(self, school, tag, role):
        user = User.objects.create_user(
            f"{school.schema_name}-{tag}", PASSWORD, full_name=f"{role.label} {tag}"
        )
        grant_membership(user, school, role)
        return user

    def _staff_for(self, school):
        return {
            role: self._one_staff(school, role.value, role)
            for role in (
                Role.PRINCIPAL,
                Role.ADMIN,
                Role.TEACHER,
                Role.VICE_PRINCIPAL_ACADEMIC,
            )
        }

    def _academics(self, school, teacher):
        with connected_to(school):
            terms = {
                name: Term.objects.create(
                    session=SESSION, name=name, starts_on=starts, ends_on=ends
                ).pk
                for name, (starts, ends) in TERM_DATES.items()
            }
            group = ClassGroup.objects.create(name="JSS 1A", level=1)
            subjects = {
                "maths": Subject.objects.create(name="Mathematics", code="MTH").pk,
                "english": Subject.objects.create(name="English", code="ENG").pk,
            }
            teaching = teacher.memberships.get(school=school, role=Role.TEACHER)
            for term_id in terms.values():
                assign_class_teacher(group, Term.objects.get(pk=term_id), teaching)
            return terms, group.pk, subjects

    # -- per-school accessors, which is the whole point of writing this out ---

    def terms_of(self, school):
        return self.terms if school == self.stmarys else self.their_terms

    def group_of(self, school):
        return ClassGroup.objects.get(
            pk=self.group_id if school == self.stmarys else self.their_group_id
        )

    def term_of(self, school, name):
        return Term.objects.get(pk=self.terms_of(school)[str(name)])

    def subjects_of(self, school):
        return self.subjects if school == self.stmarys else self.their_subjects

    def staff_of(self, school):
        return self.staff if school == self.stmarys else self.their_staff

    def _child(self, school, username, full_name):
        membership = enroll_student(
            User.objects.create_user(username, PASSWORD, full_name=full_name), school
        )
        with connected_to(school):
            for name in TermName:
                place_student(
                    self.group_of(school), self.term_of(school, name.value), membership
                )
        return membership

    def _mark(self, school, term_name, membership, subject_key, name, value, out_of=100):
        with connected_to(school):
            assessment, _ = Assessment.objects.get_or_create(
                term=self.term_of(school, term_name),
                subject_id=self.subjects_of(school)[subject_key],
                name=name,
                defaults={"max_score": out_of},
            )
            Score.objects.create(
                assessment=assessment,
                student_membership_id=membership.pk,
                value=value,
            )

    def release(self, school=None, term_name=TermName.FIRST.value):
        school = school or self.stmarys
        people = self.staff_of(school)
        with connected_to(school):
            sheet = results_services.open_sheet(
                self.group_of(school),
                self.term_of(school, term_name),
                people[Role.PRINCIPAL],
            )
            results_services.submit(sheet, people[Role.TEACHER])
            results_services.check(sheet, people[Role.VICE_PRINCIPAL_ACADEMIC])
            results_services.approve(sheet, people[Role.PRINCIPAL])
            results_services.release(sheet, people[Role.PRINCIPAL])
            return sheet

    # -- the HTTP call --------------------------------------------------------

    def card_url(self, school, membership, term_name=TermName.FIRST.value):
        return f"/api/results/cards/{membership.pk}/{self.terms_of(school)[str(term_name)]}/"

    def fetch(self, user, school, membership, term_name=TermName.FIRST.value, host=None):
        if user is not None:
            self.client.force_login(user)
        else:
            self.client.logout()
        return self.client.get(
            self.card_url(school, membership, term_name),
            HTTP_HOST=host or (HOST if school == self.stmarys else THEIR_HOST),
        )

    def tearDown(self):
        # `TenantMainMiddleware` leaves the connection on the school's schema.
        connection.set_schema_to_public()
        super().tearDown()


class TheSnapshotReallyHoldsTheStaffOnlyNumbers(ReportCardApiSetUp):
    """The control for every exclusion test below, and it runs first on purpose.

    Each of those tests asserts a field is *absent* from a payload, and absence
    has two causes: excluded, or never there. This class pins the second one
    shut by showing the frozen rows carry all three staff-only numbers for
    exactly the child and term the exclusion tests fetch.

    Without this, a serializer that leaked every one of them would still turn
    the rest of this file green the day somebody changed the fixture to a
    one-child class.
    """

    def setUp(self):
        super().setUp()
        self.release()

    def test_the_frozen_card_carries_a_position_and_a_roster_size(self):
        with connected_to(self.stmarys):
            card = cards.card_for(self.ada, self.term_of(self.stmarys, TermName.FIRST))

        self.assertIsNotNone(card, "nothing was released, so nothing is being excluded")
        self.assertEqual(card.position, 1, "Ada outscored Bola and should rank first")
        self.assertEqual(card.roster_size, 2)

    def test_the_frozen_subject_lines_carry_a_subject_position(self):
        with connected_to(self.stmarys):
            card = cards.card_for(self.ada, self.term_of(self.stmarys, TermName.FIRST))
            ranks = sorted(
                ReleasedSubjectResult.objects.filter(card=card).values_list(
                    "subject_position", flat=True
                )
            )

        self.assertTrue(ranks, "no subject lines were frozen")
        self.assertNotIn(
            None, ranks, "a null subject_position would make the leak test vacuous"
        )
        self.assertEqual(ranks, [1, 1], "Ada is first in both subjects")


class TheStaffOnlyFieldsAreNotInThePayload(ReportCardApiSetUp):
    """The rule, asked of the bytes, as each kind of caller who may read a card."""

    def setUp(self):
        super().setUp()
        self.release()

    def test_the_parents_payload_never_says_position(self):
        """Covers `position`, `subject_position` and `roster_size` at once.

        A substring assertion rather than a parsed one: `subject_position`
        contains `position`, so this single check catches the class rank, the
        subject rank and any future field whose name carries the word — which is
        the direction a leak would most likely arrive from.
        """
        response = self.fetch(self.mama, self.stmarys, self.ada)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"position", response.content)
        self.assertNotIn(b"roster_size", response.content)

    def test_the_students_own_payload_never_says_position(self):
        response = self.fetch(self.ada.user, self.stmarys, self.ada)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"position", response.content)
        self.assertNotIn(b"roster_size", response.content)

    def test_staff_get_the_same_bytes_as_the_parent(self):
        """No role branch, which is the design and not an accident.

        A payload that differed by caller would be a second shape of this
        response exercised only by staff, and that is where a leak survives
        review. What staff read here is *what went home*; position lives on the
        broadsheet behind its own authority check.
        """
        parents = self.fetch(self.mama, self.stmarys, self.ada)
        self.client.logout()
        staff = self.fetch(self.principal, self.stmarys, self.ada)

        self.assertEqual(parents.status_code, 200)
        self.assertEqual(staff.status_code, 200)
        self.assertEqual(json.loads(staff.content), json.loads(parents.content))

    def test_the_card_still_carries_the_numbers_a_family_is_owed(self):
        """The other half. A serializer returning `{}` would pass every test above."""
        body = json.loads(self.fetch(self.mama, self.stmarys, self.ada).content)

        self.assertEqual(body["student_name"], "Ada Obi")
        self.assertEqual(body["school_name"], "St Mary's")
        self.assertEqual(body["class_group_name"], "JSS 1A")
        self.assertEqual(body["own_average"], "81.00")
        self.assertEqual(
            sorted(line["subject_name"] for line in body["subjects"]),
            ["English", "Mathematics"],
        )
        maths = next(l for l in body["subjects"] if l["subject_code"] == "MTH")
        self.assertEqual(maths["percentage"], "88.00")
        self.assertEqual(
            [cell["assessment_name"] for cell in maths["assessments"]], ["Exam"]
        )


class TheCardIsTheSnapshotAndNotTheLiveTables(ReportCardApiSetUp):
    """A released card keeps saying what it said, whatever the school edits after.

    This is the requirement that the page reads only from the snapshot. It is
    tested by moving the live tables *after* release and asking the endpoint
    again: a page assembled from live configuration would follow the edit, and
    one assembled from frozen rows cannot.
    """

    def setUp(self):
        super().setUp()
        self.release()

    def test_renaming_a_subject_does_not_relabel_a_released_line(self):
        with connected_to(self.stmarys):
            subject = Subject.objects.get(pk=self.subjects["maths"])
            subject.name = "Further Mathematics"
            subject.save(update_fields=["name"])
            live_now = Subject.objects.get(pk=self.subjects["maths"]).name

        body = json.loads(self.fetch(self.mama, self.stmarys, self.ada).content)
        names = [line["subject_name"] for line in body["subjects"]]

        # The control: the live table really did move.
        self.assertEqual(live_now, "Further Mathematics")
        self.assertIn("Mathematics", names)
        self.assertNotIn("Further Mathematics", names)

    def test_renaming_the_class_does_not_rename_it_on_a_released_card(self):
        with connected_to(self.stmarys):
            group = ClassGroup.objects.get(pk=self.group_id)
            group.name = "JSS 1 Alpha"
            group.save(update_fields=["name"])
            live_now = ClassGroup.objects.get(pk=self.group_id).name

        body = json.loads(self.fetch(self.mama, self.stmarys, self.ada).content)

        self.assertEqual(live_now, "JSS 1 Alpha")
        self.assertEqual(body["class_group_name"], "JSS 1A")

    def test_a_conduct_group_switched_on_after_release_adds_no_section(self):
        """The frozen section is the section, including when it was empty.

        `ratings.card_sections()` would compose a live one here, which is right
        for a draft card on the school's screen and wrong for a card in a
        parent's hand. This is the test that would fail if this module ever
        reached for that reader.
        """
        before = json.loads(self.fetch(self.mama, self.stmarys, self.ada).content)

        with connected_to(self.stmarys):
            from results import ratings

            ratings.set_group_enabled(TraitGroup.AFFECTIVE, True)

        self.client.logout()
        after = json.loads(self.fetch(self.mama, self.stmarys, self.ada).content)

        self.assertEqual(before["sections"], [])
        self.assertEqual(after["sections"], [], "a live section reached a frozen card")


class WhoMayReadACard(ReportCardApiSetUp):
    """The child, a guardian of theirs, or staff at that school. Everyone else 404s."""

    def setUp(self):
        super().setUp()
        self.release()
        self.release(school=self.grace)

    def test_the_child_may_read_their_own_card(self):
        self.assertEqual(self.fetch(self.ada.user, self.stmarys, self.ada).status_code, 200)

    def test_a_guardian_may_read_their_own_childs_card(self):
        self.assertEqual(self.fetch(self.mama, self.stmarys, self.ada).status_code, 200)

    def test_staff_may_read_a_card_at_their_school(self):
        self.assertEqual(
            self.fetch(self.principal, self.stmarys, self.ada).status_code, 200
        )

    def test_another_childs_guardian_may_not(self):
        """A PARENT membership says somebody is a parent here, not whose.

        Without the `Guardianship` lookup, every parent at a school could read
        every child's card, and the role check alone would let them.
        """
        self.assertEqual(
            self.fetch(self.bolas_father, self.stmarys, self.ada).status_code, 404
        )

    def test_a_classmate_may_not_read_another_childs_card(self):
        self.assertEqual(self.fetch(self.bola.user, self.stmarys, self.ada).status_code, 404)

    def test_the_other_schools_principal_may_not_reach_across(self):
        """Grace's principal, at St Mary's host, asking for a St Mary's child.

        **403 and not this endpoint's flat 404**, because the refusal happens
        earlier than this endpoint: `SchoolAccessMiddleware` refuses any
        authenticated caller with no active membership at the host's school
        before a view runs at all.

        That is not the disclosure hole a 403 usually is. The middleware's
        answer depends only on the *caller's* membership and never on the child
        asked for, so Grace's principal gets this identical 403 for Ada, for a
        membership id that belongs to nobody, and for a term never released. It
        is the flat refusal, one layer up. The endpoint's own 404 is what covers
        callers who *are* members here — see the two tests above it.
        """
        self.assertEqual(
            self.fetch(self.their_principal, self.stmarys, self.ada, host=HOST).status_code,
            403,
        )

    def test_that_403_says_nothing_about_whether_the_child_exists(self):
        """The control for the reasoning above, rather than a restatement of it."""
        real = self.fetch(self.their_principal, self.stmarys, self.ada, host=HOST)
        self.client.logout()
        self.client.force_login(self.their_principal)
        invented = self.client.get(
            f"/api/results/cards/{self.ada.pk + 9999}/{self.terms['first']}/",
            HTTP_HOST=HOST,
        )

        self.assertEqual(real.status_code, invented.status_code)
        self.assertEqual(real.content, invented.content)

    def test_grace_reads_its_own_card_perfectly_well(self):
        """The control for the test above: Grace's principal is not simply broken."""
        response = self.fetch(self.their_principal, self.grace, self.ngozi, host=THEIR_HOST)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["school_name"], "Grace Academy")

    def test_a_bursar_may_not(self):
        """Staff, but not this kind. A bursar keeps the books."""
        self.assertEqual(self.fetch(self.bursar, self.stmarys, self.ada).status_code, 404)

    def test_signing_out_is_a_401_rather_than_a_card(self):
        self.assertEqual(self.fetch(None, self.stmarys, self.ada).status_code, 401)

    def test_an_unreleased_term_has_no_card_even_for_its_own_child(self):
        self.assertEqual(
            self.fetch(
                self.ada.user, self.stmarys, self.ada, term_name=TermName.SECOND.value
            ).status_code,
            404,
        )


class TheThirdTermCard(ReportCardApiSetUp):
    """The session line and the promotion decision, and what neither may carry."""

    def setUp(self):
        super().setUp()
        self._mark(self.stmarys, TermName.THIRD.value, self.ada, "maths", "Exam", 80)
        self._mark(self.stmarys, TermName.THIRD.value, self.bola, "maths", "Exam", 50)
        self.release(term_name=TermName.THIRD.value)

    def test_the_session_line_is_there_with_its_averages(self):
        body = json.loads(
            self.fetch(
                self.mama, self.stmarys, self.ada, term_name=TermName.THIRD.value
            ).content
        )

        self.assertIsNotNone(body["session"], "a third-term card should carry one")
        self.assertEqual(body["session"]["session"], SESSION)
        self.assertEqual(body["session"]["third_average"], "80.00")

    def test_the_frozen_session_row_really_does_record_an_absence_reason(self):
        """The control for the exclusion below.

        Ada is marked in first and third term and never in second, so the
        second-term column carries an `UNMARKED` reason and the other two carry
        none. If no column carried one, asserting the payload lacks one would
        prove nothing.
        """
        with connected_to(self.stmarys):
            card = cards.card_for(self.ada, self.term_of(self.stmarys, TermName.THIRD))
            row = ReleasedSessionResult.objects.get(card=card)

        self.assertEqual(row.second_absence, "unmarked")
        # And the terms she *was* marked in carry no reason, which is what makes
        # the one above a real value rather than a default sitting in every row.
        self.assertEqual(row.first_absence, "")
        self.assertEqual(row.third_absence, "")

    def test_the_payload_never_says_why_a_term_averaged_nothing(self):
        response = self.fetch(
            self.mama, self.stmarys, self.ada, term_name=TermName.THIRD.value
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"absence", response.content)
        self.assertNotIn(b"unmarked", response.content)

    def test_a_first_term_card_carries_no_session_line_at_all(self):
        self.release(term_name=TermName.FIRST.value)
        body = json.loads(self.fetch(self.mama, self.stmarys, self.ada).content)

        self.assertIsNone(body["session"])
        self.assertIsNone(body["promotion"])

    def test_a_recorded_promotion_shows_its_status_and_never_its_suggestion(self):
        with connected_to(self.stmarys):
            decision = sessions.decide(
                self.ada, SESSION, PromotionStatus.REPEATED, by=self.principal
            )

        response = self.fetch(
            self.mama, self.stmarys, self.ada, term_name=TermName.THIRD.value
        )
        body = json.loads(response.content)

        # The control: the row really does carry a suggestion, and it differs
        # from the decision — so this is a row where the gap is visible and a
        # leak would be meaningful.
        self.assertEqual(decision.suggested, PromotionStatus.PROMOTED)
        self.assertEqual(decision.status, PromotionStatus.REPEATED)

        self.assertEqual(body["promotion"]["status"], "repeated")
        self.assertNotIn(b"suggested", response.content)
        self.assertNotIn(b"promoted", response.content)

    def test_an_undecided_year_has_no_promotion_object(self):
        body = json.loads(
            self.fetch(
                self.mama, self.stmarys, self.ada, term_name=TermName.THIRD.value
            ).content
        )

        self.assertIsNone(body["promotion"], "undecided is the absence of a row")
