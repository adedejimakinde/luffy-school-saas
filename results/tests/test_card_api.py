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
from datetime import date

from django.db import connection
from django.test import TestCase

from academics.models import ClassGroup, Term, TermName
from academics.services import assign_class_teacher, place_student
from accounts.models import Role, User
from accounts.services import enroll_student, grant_membership, link_guardian
from tests.guardians import give_verified_channel
from gradebook.models import Assessment, Score, Subject
from results import cards, revision, sessions
from results import services as results_services
from results.models import (
    PromotionStatus,
    ReleasedCard,
    ReleasedSessionResult,
    ReleasedSubjectResult,
    TraitGroup,
)
from schools.models import Domain, School
from schools.tests.tenants import connected_to, make_school

PASSWORD = "correct-horse-battery"
SESSION = "2025/2026"

HOST = "st-marys.testserver"
THEIR_HOST = "grace.testserver"

TERM_DATES = {
    TermName.FIRST.value: (date(2025, 9, 15), date(2025, 12, 12)),
    TermName.SECOND.value: (date(2026, 1, 12), date(2026, 4, 2)),
    TermName.THIRD.value: (date(2026, 4, 27), date(2026, 7, 24)),
}


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
        # D9's gate: a PARENT membership is INVITED until the guardian's contact
        # channel is verified, and an invited member is refused at the school's
        # host. Every guardian who fetches anything below needs a live channel,
        # or the 403 that arrives is the middleware's and not this app's.
        give_verified_channel(self.mama, "08030000001")
        give_verified_channel(self.bolas_father, "08030000002")

    # -- fixtures ------------------------------------------------------------

    def _school(self, name, slug, schema_name, host):
        # Two of these per test, thirty tests. Migrating them was ~1.65s each;
        # `make_school()` copies the template instead. `School` is still used
        # directly in `setUp` for the portal, which has no schema of its own.
        school = make_school(name, slug, schema_name)
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

    def test_a_bursar_may(self):
        """This assertion was inverted by the fee gate, and that is ruled.

        It read "a bursar keeps the books" and asserted 404, which was right
        for as long as there was no reason for a bursar to open a card. The
        withholding design gives one: a bursar deciding whether to hold a card
        back cannot do the job without seeing the document they are holding, and
        the narrower alternative — a staff screen showing only *that* a card
        exists and is withheld — is a second surface answering a question the
        first one already answers. That shape produced four answers to "did a
        card go home" and the PR #35 bug with them.

        `card_api.CARD_VIEWING_ROLES` carries the widening's full reasoning,
        including what it must not imply: a bursar must never be added to
        `results.api.POSITION_VIEWING_ROLES`, and nothing in this module has a
        slot for a position for this to reach.
        """
        self.assertEqual(self.fetch(self.bursar, self.stmarys, self.ada).status_code, 200)

    def test_the_bursar_widening_did_not_reach_positions(self):
        """The other half of the ruling, and the one worth a test of its own.

        The two constants are deliberately not imported from one another so
        that a widening of one is not a widening of the other. This is that
        widening, and it stops here.
        """
        from results.api import POSITION_VIEWING_ROLES

        self.assertNotIn(Role.BURSAR.value, POSITION_VIEWING_ROLES)

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


class TheRevisedMarkerIsOnThePayload(ReportCardApiSetUp):
    """Task 8. "Revised" is a word on the page, so it has to be in the JSON.

    The exclusion tests above are all about fields a family must **not** see.
    This is the opposite claim about the same payload, and it needs its own
    control: a card that is not a revision must say `false` rather than omit the
    key, because a client reading a missing key as falsey is a client that will
    read a missing key as falsey the day the key is dropped by accident.
    """

    def test_a_first_release_says_it_is_not_revised(self):
        self.release()

        response = self.fetch(self.mama, self.stmarys, self.ada)

        self.assertEqual(response.status_code, 200)
        self.assertIn("is_revised", response.json())
        self.assertFalse(response.json()["is_revised"])
        self.assertEqual(response.json()["version"], 1)

    def test_a_revised_card_says_so_to_the_family_as_well_as_to_staff(self):
        """Both callers, because the payload does not branch on who is asking.

        `position` is staff-only and is excluded for everyone; this is the field
        that goes the other way, and asserting it for the parent alone would
        leave it free to be a staff-only field that the parent's serializer
        happened to include.
        """
        self.release()
        with connected_to(self.stmarys):
            revision.revise(
                self.ada,
                self.term_of(self.stmarys, TermName.FIRST.value),
                self.principal,
                "Surname misspelled on the first printing.",
            )

        for who in (self.mama, self.principal):
            with self.subTest(reader=who.username):
                payload = self.fetch(who, self.stmarys, self.ada).json()
                self.assertTrue(payload["is_revised"])
                self.assertEqual(payload["version"], 2)

    def test_the_reason_and_the_reviser_are_not_on_the_page(self):
        """The audit is the school's. A child carries home the card, not the file.

        `CardRevision` holds who asked and why, and neither has a slot in any
        schema here — the same rule task 6 applied to `position` and the
        promotion *suggestion*, for the same reason: a field omitted from the
        rendered page but sitting in the JSON has not been omitted.
        """
        self.release()
        with connected_to(self.stmarys):
            revision.revise(
                self.ada,
                self.term_of(self.stmarys, TermName.FIRST.value),
                self.principal,
                "A reason nobody outside the office should read.",
            )

        response = self.fetch(self.mama, self.stmarys, self.ada)
        payload = response.json()

        self.assertNotIn(
            "A reason nobody outside the office should read",
            response.content.decode(),
        )
        for absent in ("reason", "revised_by", "by_platform_staff", "previous_card"):
            with self.subTest(field=absent):
                self.assertNotIn(absent, payload)

    def test_a_revision_at_one_school_does_not_mark_the_others_card(self):
        """Grace releases and is asked in Grace's own schema, through its own host."""
        self.release()
        self.release(self.grace)
        with connected_to(self.stmarys):
            revision.revise(
                self.ada,
                self.term_of(self.stmarys, TermName.FIRST.value),
                self.principal,
                "St Mary's correction.",
            )

        theirs = self.fetch(self.their_principal, self.grace, self.ngozi).json()

        self.assertFalse(theirs["is_revised"])
        self.assertEqual(theirs["version"], 1)


class TheIndexIsHowAFamilyReachesACardAtAll(ReportCardApiSetUp):
    """Without this route there is no path from signing in to a card.

    The gap this closes is not a missing convenience. Both card routes are keyed
    on `(student_membership_id, term_id)`; sign-in answers with a list of
    *schools*; and until this change `ReportCardOut` carried `term_name` and
    `term_label` but no `term_id`. So nothing the API ever said to a family
    contained either number, and the only way to open a card was to type
    integers into a URL bar and hope.

    `test_a_guardian_can_go_from_the_index_to_a_card_with_no_other_knowledge`
    is the one that holds that claim, and it is written to use **nothing** but
    what the two responses contain — no `self.ada.pk`, no `self.terms`.

    ## The control runs first

    Every scoping test here asserts that somebody sees *less* than everything,
    and an index that returned an empty list for every caller would pass all of
    them. `test_the_index_really_lists_a_card` pins that shut before any of the
    exclusions are asserted, against the same fixture.
    """

    def setUp(self):
        super().setUp()
        self.release()

    def index(self, user, school=None, host=None):
        school = school or self.stmarys
        if user is not None:
            self.client.force_login(user)
        else:
            self.client.logout()
        return self.client.get(
            "/api/results/cards/",
            HTTP_HOST=host or (HOST if school == self.stmarys else THEIR_HOST),
        )

    def children_in(self, response):
        return {child["student_name"]: child for child in response.json()["children"]}

    # -- the control ---------------------------------------------------------

    def test_the_index_really_lists_a_card(self):
        """First, so that no exclusion below can pass against an empty index."""
        body = self.children_in(self.index(self.mama))

        self.assertEqual(
            list(body),
            ["Ada Obi"],
            "the guardian's own child is not in the index, so every assertion "
            "about who is *not* in it would be checking an empty list",
        )
        self.assertEqual(len(body["Ada Obi"]["cards"]), 1)
        card = body["Ada Obi"]["cards"][0]
        self.assertEqual(card["term_label"], "First term")
        self.assertEqual(card["academic_session"], SESSION)
        self.assertFalse(card["is_withheld"])

    # -- the gap it closes ---------------------------------------------------

    def test_a_guardian_can_go_from_the_index_to_a_card_with_no_other_knowledge(self):
        """The whole point, driven using only what the responses themselves say.

        Deliberately does not touch `self.ada` or `self.terms`. A test that
        reached for the fixture's ids would prove the card route works, which
        was never in doubt; what was in doubt is whether a family holding only a
        session cookie can *find* the two numbers, and reaching past the payload
        to get them is exactly the step a parent cannot take.
        """
        listed = self.index(self.mama).json()["children"][0]
        membership_id = listed["student_membership_id"]
        term_id = listed["cards"][0]["term_id"]

        card = self.client.get(
            f"/api/results/cards/{membership_id}/{term_id}/", HTTP_HOST=HOST
        )

        self.assertEqual(card.status_code, 200, "the index named a card that 404s")
        self.assertEqual(card.json()["student_name"], "Ada Obi")

    def test_the_card_payload_carries_the_term_id_it_was_fetched_with(self):
        """`term_name` and `term_label` are labels; this is the identity.

        Round-tripped rather than compared to the fixture, because the claim is
        that a client holding a card can ask for another one — which needs the
        id the card carries to be usable as the id the route takes.
        """
        first = self.fetch(self.mama, self.stmarys, self.ada).json()

        again = self.client.get(
            f"/api/results/cards/{self.ada.pk}/{first['term_id']}/", HTTP_HOST=HOST
        )

        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["term_id"], first["term_id"])
        self.assertEqual(
            first["term_id"],
            self.terms_of(self.stmarys)[str(TermName.FIRST.value)],
        )

    # -- who is in it --------------------------------------------------------

    def test_a_guardian_sees_their_own_child_and_not_another_families(self):
        """Bola is at the same school, in the same class, released in the same run."""
        body = self.children_in(self.index(self.mama))

        self.assertIn("Ada Obi", body)
        self.assertNotIn(
            "Bola Eze",
            body,
            "a guardianship links a login to one child; holding PARENT at a "
            "school says nothing about whose",
        )

    def test_a_child_sees_their_own_card(self):
        """The `SELF` claim, which is a different branch of `_may_read()`."""
        body = self.children_in(self.index(self.ada.user))

        self.assertEqual(list(body), ["Ada Obi"])
        self.assertEqual(len(body["Ada Obi"]["cards"]), 1)

    def test_staff_get_an_index_of_their_own_children_and_not_the_roll(self):
        """A principal is not a parent here, so her index is empty — not the school.

        The refusal to build a staff index off `CardClaim.STAFF` is a design
        decision rather than an omission: that claim reaches every card at the
        school, and an index built from it would be a staff directory grown onto
        a family router by accident. `_children_of()` carries the argument.
        """
        body = self.index(self.principal).json()

        self.assertEqual(body["children"], [])

    def test_a_guardian_at_another_school_never_reaches_this_route(self):
        """403 from the middleware, and **not** an empty index from this view.

        Written to assert what actually happens rather than what this route
        would have done, because the difference is the tenancy guarantee.
        `SchoolAccessMiddleware` refuses any authenticated caller with no active
        membership at the host's school before a view runs, so Ada's mother is
        turned away at Grace Academy's door and `_children_of()` is never asked.

        `WhoMayReadACard.test_the_other_schools_principal_may_not_reach_across`
        records the same refusal for the card route, including why that 403 is
        not the disclosure hole a 403 usually is: the middleware's answer
        depends only on the caller's own membership and never on what they
        asked for.

        The first draft of this test asserted an empty `children` list and
        errored on a `text/html` body — the middleware's page. Keeping the
        weaker assertion would have meant this file claimed `_children_of()`
        scopes by school on the evidence of a request that never reached it.
        """
        self.release(self.grace)

        response = self.index(self.mama, self.grace, host=THEIR_HOST)

        self.assertEqual(response.status_code, 403)
        self.assertNotIn(
            b"children",
            response.content,
            "the refusal carried this route's payload shape, so the view ran",
        )

    def test_the_index_is_scoped_to_the_host_school_for_a_caller_who_is_a_member(self):
        """The scoping claim the test above cannot make, driven by somebody inside.

        A guardian with children at **both** schools is the case that separates
        "the middleware refused you" from "this view scoped its query". She is a
        member at each, so she reaches the route on both hosts and must be
        handed a different child on each.
        """
        self.release(self.grace)
        # No second channel: `link_guardian()` grants the PARENT membership
        # ACTIVE outright when the guardian already holds a verified one, and
        # `one_live_contact_per_guardian` refuses a second. One channel reaches
        # every school a guardian has a child at, which is D5's whole point.
        link_guardian(self.mama, self.ngozi)

        here = self.children_in(self.index(self.mama, self.stmarys, host=HOST))
        there = self.children_in(self.index(self.mama, self.grace, host=THEIR_HOST))

        self.assertEqual(list(here), ["Ada Obi"])
        self.assertEqual(list(there), ["Ngozi Ade"])

    def test_an_unreleased_term_is_not_listed(self):
        """The index lists artefacts, never a calendar.

        Second and third term exist as `Term` rows for this child — `_child()`
        places her in all three — and neither has been released. An index built
        from placements rather than from `ReleasedCard` would list them, and a
        parent would tap a card that does not exist.
        """
        cards_listed = self.index(self.mama).json()["children"][0]["cards"]

        self.assertEqual([card["term_name"] for card in cards_listed], ["first"])

    def test_an_unauthenticated_caller_is_refused(self):
        response = self.index(None)

        self.assertEqual(response.status_code, 401)
