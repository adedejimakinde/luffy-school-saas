"""Task 9: the three-term view, and the decision the school makes at the end of it.

Two things are being proved here, and they fail in different ways.

**The arithmetic**, where the failure is a wrong number on a card. The cases
that matter are not the three-terms-present one — that is a mean — but the
child who did not sit all three. An absent term must renormalise and must never
be a zero, because a zero is a failing grade the child never earned and it
propagates: it drags the session average below the pass mark and produces a
`REPEATED` *suggestion* out of arithmetic rather than out of anything that
happened. The settled decision asks for that case under both conventions a
Nigerian school uses, with the numbers shown, and
`TheTwoTermCaseTests` is it.

**The record**, where the failure is a decision nobody made. Undecided is the
absence of a row; the suggestion is frozen at the moment of the decision and
never recomputed; and a principal changing their mind writes a second row
rather than editing the first. Each of those is a way a promotion could
silently become something other than what a person decided.

Two schools throughout, and the second is used rather than merely built: a
weighting is per-school configuration, a pass mark is per-school, and every one
of those is a table living in a tenant schema. `TwoSchoolsTests` is where that
is asserted rather than assumed.
"""

from datetime import date
from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from academics.models import ClassGroup, Term, TermName
from academics.services import assign_class_teacher, move_student, place_student
from accounts.models import Role, User
from accounts.services import enroll_student, grant_membership
from gradebook.models import Assessment, Score, Subject
from results import cards, positions, sessions
from results import services as results_services
from results.models import (
    PromotionDecision,
    PromotionDecisionsAreAppendOnly,
    PromotionStatus,
    ReleasedSessionResult,
    ResultSheet,
    SessionAveraging,
    SessionResultsAreFrozenAtRelease,
    SessionSettings,
    SheetState,
    TermAbsence,
)
from results.tests.test_positions import PASSWORD, make_school
from schools.tests.tenants import connected_to
from results import unmarked

SESSION = "2025/2026"


class SessionSetUp(TestCase):
    """Two schools, each with a whole 2025/2026 session and a child in it.

    Both schools get a full set of signatures, because the approval chain wants
    three different people and the third term has to actually be released for
    anything to freeze.
    """

    #: A real Nigerian session: September to July, across the new year.
    TERM_DATES = {
        TermName.FIRST.value: (date(2025, 9, 15), date(2025, 12, 12)),
        TermName.SECOND.value: (date(2026, 1, 12), date(2026, 4, 2)),
        TermName.THIRD.value: (date(2026, 4, 27), date(2026, 7, 24)),
    }

    def setUp(self):
        self.stmarys = make_school("St Mary's", "st-marys", "st_marys")
        self.grace = make_school("Grace Academy", "grace", "grace")

        self.staff = {}
        for school, tag in ((self.stmarys, "sm"), (self.grace, "ga")):
            self.staff[school.pk] = {
                role: self._staff(school, f"{tag}-{role.value}", role)
                for role in (
                    Role.PRINCIPAL,
                    Role.ADMIN,
                    Role.TEACHER,
                    Role.VICE_PRINCIPAL_ACADEMIC,
                )
            }

        self.principal = self.staff[self.stmarys.pk][Role.PRINCIPAL]
        self.admin = self.staff[self.stmarys.pk][Role.ADMIN]
        self.teacher = self.staff[self.stmarys.pk][Role.TEACHER]
        self.vp = self.staff[self.stmarys.pk][Role.VICE_PRINCIPAL_ACADEMIC]
        self.their_principal = self.staff[self.grace.pk][Role.PRINCIPAL]

        self.terms, self.group_id, self.maths_id = {}, {}, {}
        for school in (self.stmarys, self.grace):
            (
                self.terms[school.pk],
                self.group_id[school.pk],
                self.maths_id[school.pk],
            ) = self._academics(school)

        self.ada = self.child(self.stmarys, "ada", "Ada Obi")

    # -- fixtures ------------------------------------------------------------

    def _staff(self, school, username, role):
        user = User.objects.create_user(
            username, PASSWORD, full_name=f"{role.label} of {school.name}"
        )
        grant_membership(user, school, role)
        return user

    def _academics(self, school):
        """A full session: three terms, one class, one subject."""
        with connected_to(school):
            terms = {}
            for name, (starts_on, ends_on) in self.TERM_DATES.items():
                terms[name] = Term.objects.create(
                    session=SESSION, name=name, starts_on=starts_on, ends_on=ends_on
                ).pk
            group = ClassGroup.objects.create(name="JSS 1A", level=1)
            maths = Subject.objects.create(name="Mathematics", code="MTH")

            # Every term needs a class teacher before its sheet can be
            # submitted — `_require_class_teacher_scope()` refuses otherwise,
            # and the third term has to be releasable for anything to freeze.
            teaching = self.staff[school.pk][Role.TEACHER].memberships.get(
                school=school, role=Role.TEACHER
            )
            for term_id in terms.values():
                assign_class_teacher(
                    group, Term.objects.get(pk=term_id), teaching
                )
            return terms, group.pk, maths.pk

    def child(self, school, username, full_name, terms=None):
        """A student of this school, placed in JSS 1A for the terms named.

        `terms=None` means all three; an explicit list is how a mid-session
        transfer is spelled, which is the case this module exists for.
        """
        membership = enroll_student(
            User.objects.create_user(username, PASSWORD, full_name=full_name), school
        )
        if terms is None:
            terms = [name.value for name in sessions.TERM_ORDER]
        with connected_to(school):
            for name in terms:
                place_student(self.group(school), self.term(school, name), membership)
        return membership

    def mark(self, school, term_name, membership, percentage):
        """One mark out of a hundred, so the term's average *is* `percentage`."""
        with connected_to(school):
            term = self.term(school, term_name)
            assessment, _ = Assessment.objects.get_or_create(
                term=term,
                subject_id=self.maths_id[school.pk],
                name="Exam",
                defaults={"max_score": 100},
            )
            Score.objects.create(
                assessment=assessment,
                student_membership_id=membership.pk,
                value=percentage,
            )

    def term(self, school, name):
        return Term.objects.get(pk=self.terms[school.pk][str(name)])

    def group(self, school):
        return ClassGroup.objects.get(pk=self.group_id[school.pk])

    def release_term(self, name, school=None):
        """Walk one term's sheet all the way, as a school does at the end of it."""
        school = school or self.stmarys
        people = self.staff[school.pk]
        sheet = results_services.open_sheet(
            self.group(school),
            self.term(school, str(name)),
            people[Role.PRINCIPAL],
        )
        results_services.submit(sheet, people[Role.TEACHER], unmarked=unmarked.count(sheet.class_group, sheet.term))
        results_services.check(sheet, people[Role.VICE_PRINCIPAL_ACADEMIC], unmarked=unmarked.count(sheet.class_group, sheet.term))
        results_services.approve(sheet, people[Role.PRINCIPAL], unmarked=unmarked.count(sheet.class_group, sheet.term))
        results_services.release(sheet, people[Role.PRINCIPAL])
        return sheet

    def release_terms(self, *names, school=None):
        """Release these terms in the order they are sat: all three when none is named.

        A term already released is left alone. **A year is read from the cards
        that went home** (audit G-02), so a test that wants a term to count has
        to send its card home first, exactly as a school does.
        """
        school = school or self.stmarys
        wanted = [str(n) for n in names] or [t.value for t in sessions.TERM_ORDER]
        sheets = {}
        for term in sessions.TERM_ORDER:
            if term.value not in wanted:
                continue
            already = ResultSheet.objects.filter(
                class_group=self.group(school),
                term=self.term(school, term.value),
                state=SheetState.RELEASED,
            ).first()
            sheets[term.value] = already or self.release_term(term.value, school)
        return sheets

    def release_the_third_term(self, school=None):
        """Release the third term, the first and second having gone home before it.

        Releasing the third term is what freezes the year, and the year is made
        of the earlier terms' released cards.
        """
        return self.release_terms(school=school)[TermName.THIRD.value]


class TheStraightMeanTests(SessionSetUp):
    """The default: average the terms the child sat, equally."""

    def test_a_school_that_has_configured_nothing_averages_equally(self):
        """The default is a decision, not an accident. It is what a school means."""
        with connected_to(self.stmarys):
            self.assertEqual(sessions.settings().averaging, SessionAveraging.EQUAL)

    def test_three_terms_average_to_their_mean(self):
        self.mark(self.stmarys, "first", self.ada, 60)
        self.mark(self.stmarys, "second", self.ada, 70)
        self.mark(self.stmarys, "third", self.ada, 80)

        with connected_to(self.stmarys):
            self.release_terms()
            line = sessions.session_line(self.ada, SESSION)

        self.assertEqual(line.average, Decimal("70.00"))
        self.assertEqual(
            line.weights,
            {
                "first": Decimal("33.33"),
                "second": Decimal("33.33"),
                "third": Decimal("33.34"),
            },
        )

    def test_the_mean_is_exact_and_not_the_mean_of_the_rounded_weights(self):
        """The two ways of computing this give different answers, and one is right.

        The stored weights are rounded so they add to a hundred and can be read
        off a screen; the average is computed from the exact ratios instead and
        rounded once. This is a case where that choice is visible. The child
        scored 0, 0 and 100, so the third term carries the spare hundredth:

            from the stored weights   100 * 33.34 / 100  =  33.34
            the exact mean            100 / 3            =  33.33

        A third of the year is a third, not 33.34% of it, and the session
        average is the number that decides promotions.
        """
        self.mark(self.stmarys, "first", self.ada, 0)
        self.mark(self.stmarys, "second", self.ada, 0)
        self.mark(self.stmarys, "third", self.ada, 100)

        with connected_to(self.stmarys):
            self.release_terms()
            line = sessions.session_line(self.ada, SESSION)

        # Exact mean: 100/3 = 33.333... -> 33.33
        # From the stored weights: 100 * 33.34/100 = 33.34. Different number.
        self.assertEqual(line.average, Decimal("33.33"))
        self.assertEqual(line.weights["third"], Decimal("33.34"))

    def test_the_weights_always_add_up_to_a_hundred(self):
        """Whatever the terms sat, and whichever convention is in force.

        A stored weighting that adds up to 99.99 is one every reader has to
        explain away, and a school printing it looks wrong even when the average
        beside it is right.
        """
        cases = {
            ("first", "second", "third"): "three terms",
            ("second", "third"): "joined at second term",
            ("third",): "joined at third term",
        }
        children = {}
        for terms, description in cases.items():
            child = self.child(
                self.stmarys, f"c-{len(terms)}-{description[:4]}", "A Child", list(terms)
            )
            for name in terms:
                self.mark(self.stmarys, name, child, 50)
            children[description] = child
        # One release of each term, with all three children on their rosters.
        with connected_to(self.stmarys):
            self.release_terms()
        for description, child in children.items():
            with self.subTest(description):
                with connected_to(self.stmarys):
                    line = sessions.session_line(child, SESSION)
                self.assertEqual(sum(line.weights.values()), Decimal("100.00"))


class TheTwoTermCaseTests(SessionSetUp):
    """The case the whole module exists for, under both conventions.

    A child who transferred in at second term did not score nothing in first
    term — they were not there. The settled decision asks for this proved under
    both an equal weighting and 20/20/60, with the numbers shown, because the
    two renormalise to different places and only one of them is obvious.
    """

    def setUp(self):
        super().setUp()
        # Joined at second term. First term is not hers to answer for.
        self.bisi = self.child(
            self.stmarys, "bisi", "Bisi Lawal", ["second", "third"]
        )
        self.mark(self.stmarys, "second", self.bisi, 70)
        self.mark(self.stmarys, "third", self.bisi, 80)
        with connected_to(self.stmarys):
            self.release_terms()

    def test_equal_weights_renormalise_to_fifty_fifty(self):
        """Two terms sat, so each is half the year rather than a third of it."""
        with connected_to(self.stmarys):
            line = sessions.session_line(self.bisi, SESSION)

        self.assertEqual(
            line.weights, {"second": Decimal("50.00"), "third": Decimal("50.00")}
        )
        # (70 + 80) / 2
        self.assertEqual(line.average, Decimal("75.00"))

    def test_twenty_twenty_sixty_renormalises_to_twenty_five_seventy_five(self):
        """20 and 60 of a possible 100 become 25 and 75 of the 80 actually sat."""
        with connected_to(self.stmarys):
            sessions.use_a_weighting(20, 20, 60)
            line = sessions.session_line(self.bisi, SESSION)

        self.assertEqual(
            line.weights, {"second": Decimal("25.00"), "third": Decimal("75.00")}
        )
        # (70*20 + 80*60) / 80 = (1400 + 4800) / 80 = 77.50
        self.assertEqual(line.average, Decimal("77.50"))

    def test_the_absent_term_is_not_a_zero_under_either_convention(self):
        """The failure this renormalisation exists to prevent, stated as numbers.

        Scored as a zero the same child reads 50.00 equally weighted and 62.00
        at 20/20/60 — both below a fifty pass mark on the second reading, and
        the first exactly on it. The child sat two terms and averaged 75.
        """
        with connected_to(self.stmarys):
            equal = sessions.session_line(self.bisi, SESSION).average
            sessions.use_a_weighting(20, 20, 60)
            weighted = sessions.session_line(self.bisi, SESSION).average

        as_zero_equal = Decimal("50.00")  # (0 + 70 + 80) / 3
        as_zero_weighted = Decimal("62.00")  # (0*20 + 70*20 + 80*60) / 100
        self.assertNotEqual(equal, as_zero_equal)
        self.assertNotEqual(weighted, as_zero_weighted)
        self.assertGreater(equal, as_zero_equal)
        self.assertGreater(weighted, as_zero_weighted)

    def test_a_zero_would_have_flipped_the_suggestion(self):
        """Why the arithmetic matters: it decides what the school is advised to do."""
        with connected_to(self.stmarys):
            sessions.use_a_weighting(20, 20, 60)
            sessions.set_pass_mark(70)
            line = sessions.session_line(self.bisi, SESSION)

            self.assertEqual(line.average, Decimal("77.50"))
            self.assertEqual(
                sessions.suggested_status(line.average), PromotionStatus.PROMOTED
            )
            # The same child, had the absent term been scored zero.
            self.assertEqual(
                sessions.suggested_status(Decimal("62.00")), PromotionStatus.REPEATED
            )


class WhyATermIsAbsentTests(SessionSetUp):
    """Three causes, identical arithmetic, three different things to do about it.

    Collapsing them into a bare `None` is the tempting simplification, and it
    would make a marking backlog indistinguishable from a mid-session transfer
    on the one screen a head of year uses to find both.
    """

    def test_a_child_who_was_not_enrolled_says_so(self):
        joined_late = self.child(self.stmarys, "late", "Late Joiner", ["third"])
        self.mark(self.stmarys, "third", joined_late, 80)

        with connected_to(self.stmarys):
            self.release_terms()
            line = sessions.session_line(joined_late, SESSION)

        first, second, third = line.terms
        self.assertEqual(first.absence, TermAbsence.NOT_ENROLLED)
        self.assertEqual(second.absence, TermAbsence.NOT_ENROLLED)
        self.assertEqual(third.absence, "")
        self.assertEqual(line.average, Decimal("80.00"))

    def test_a_child_who_was_enrolled_and_never_marked_says_something_different(self):
        """The data-entry gap. Same arithmetic as a transfer, opposite response."""
        self.mark(self.stmarys, "second", self.ada, 70)
        self.mark(self.stmarys, "third", self.ada, 80)
        # First term: placed, and nobody entered a mark. Its card went home
        # all the same, with no average on it.

        with connected_to(self.stmarys):
            self.release_terms()
            line = sessions.session_line(self.ada, SESSION)

        self.assertEqual(line.terms[0].absence, TermAbsence.UNMARKED)
        self.assertNotEqual(TermAbsence.UNMARKED, TermAbsence.NOT_ENROLLED)
        self.assertEqual(line.average, Decimal("75.00"))

    def test_a_term_the_school_never_created_says_that(self):
        """A session read in progress, which is what a session is for most of the year.

        The next session, two terms in: the school has not created the third
        term yet because it has not happened. Reading a running session has to
        work — a head of year looks at exactly this in February — and the
        missing term is `NO_TERM` rather than an error or a nought.
        """
        running = "2026/2027"
        with connected_to(self.stmarys):
            first = Term.objects.create(
                session=running,
                name=TermName.FIRST,
                starts_on=date(2026, 9, 14),
                ends_on=date(2026, 12, 11),
            )
            second = Term.objects.create(
                session=running,
                name=TermName.SECOND,
                starts_on=date(2027, 1, 11),
                ends_on=date(2027, 4, 1),
            )
            group = self.group(self.stmarys)
            teaching = self.teacher.memberships.get(school=self.stmarys, role=Role.TEACHER)
            for term, mark in ((first, 60), (second, 70)):
                assign_class_teacher(group, term, teaching)
                place_student(group, term, self.ada)
                assessment = Assessment.objects.create(
                    term=term,
                    subject_id=self.maths_id[self.stmarys.pk],
                    name="Exam",
                    max_score=100,
                )
                Score.objects.create(
                    assessment=assessment,
                    student_membership_id=self.ada.pk,
                    value=mark,
                )
                # Each term's card goes home: that is what the year is read from.
                sheet = results_services.open_sheet(group, term, self.principal)
                results_services.submit(sheet, self.teacher, unmarked=0)
                results_services.check(sheet, self.vp, unmarked=0)
                results_services.approve(sheet, self.principal, unmarked=0)
                results_services.release(sheet, self.principal)

            line = sessions.session_line(self.ada, running)

        self.assertEqual(line.terms[2].absence, TermAbsence.NO_TERM)
        self.assertIsNone(line.terms[2].term_id)
        self.assertEqual(line.average, Decimal("65.00"))

    def test_a_child_with_no_marks_anywhere_has_no_average_rather_than_zero(self):
        """Blank, not nought. There is nothing to average, and nought is a grade."""
        with connected_to(self.stmarys):
            line = sessions.session_line(self.ada, SESSION)

        self.assertIsNone(line.average)
        self.assertEqual(line.weights, {})
        self.assertIsNone(sessions.suggested_status(line.average))

    def test_a_weighting_that_zeroes_the_terms_sat_yields_no_average(self):
        """0/0/100 is a legal weighting, and it can leave nothing to renormalise.

        A school counting only the third term, and a child who left before it.
        No proportion of nothing is a hundred, so there is no average — which is
        the truthful answer, and it leaves the suggestion blank so that a person
        decides rather than the arithmetic inventing a REPEATED.

        **The terms sat still carry a weight, and it is nought.** Not an absent
        weight: the child sat those terms and was marked in them, and the school
        counted them for nothing. That is a different statement from "there was
        no term here", which is what a null weight beside a `*_absence` reason
        says, and the freeze has a column for each — see
        `test_a_release_survives_a_weighting_that_zeroes_the_terms_sat`, which
        is the release this distinction was costing.
        """
        left_early = self.child(self.stmarys, "early", "Early Leaver", ["first", "second"])
        self.mark(self.stmarys, "first", left_early, 90)
        self.mark(self.stmarys, "second", left_early, 90)

        with connected_to(self.stmarys):
            sessions.use_a_weighting(0, 0, 100)
            self.release_terms("first", "second")
            line = sessions.session_line(left_early, SESSION)

        self.assertIsNone(line.average)
        self.assertEqual(
            line.weights, {"first": Decimal("0.00"), "second": Decimal("0.00")}
        )
        self.assertIsNone(sessions.suggested_status(line.average))

    def test_a_child_who_sat_nothing_has_no_weights_at_all(self):
        """The other half of the pair above, and the reason they are two cases.

        Nought weight and no weight are different answers: this child sat no
        term, so there is no term to have weighted, and the frozen row's
        `*_weight_used` columns are null beside a `*_absence` reason. The child
        above sat two terms that were counted for nothing.
        """
        with connected_to(self.stmarys):
            sessions.use_a_weighting(0, 0, 100)
            line = sessions.session_line(self.ada, SESSION)

        self.assertIsNone(line.average)
        self.assertEqual(line.weights, {})


class ConfiguringTheSessionTests(SessionSetUp):
    """A weighting is three numbers adding to a hundred, in two places."""

    def test_a_weighting_that_does_not_add_up_is_refused(self):
        with connected_to(self.stmarys):
            with self.assertRaises(sessions.InvalidWeighting) as refused:
                sessions.use_a_weighting(20, 20, 50)
            self.assertIn("90", str(refused.exception))

    def test_the_database_refuses_one_too(self):
        """The import and the psql session, which never reach the service."""
        with connected_to(self.stmarys):
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    SessionSettings.objects.filter(pk=1).update(
                        averaging=SessionAveraging.WEIGHTED,
                        first_weight=Decimal(20),
                        second_weight=Decimal(20),
                        third_weight=Decimal(50),
                    )

    def test_the_database_refuses_a_weighting_with_no_weights(self):
        with connected_to(self.stmarys):
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    SessionSettings.objects.filter(pk=1).update(
                        averaging=SessionAveraging.WEIGHTED
                    )

    def test_going_back_to_a_straight_mean_clears_the_weights(self):
        """A stale 20/20/60 under a mode that says EQUAL is a field that lies."""
        with connected_to(self.stmarys):
            sessions.use_a_weighting(20, 20, 60)
            row = sessions.use_a_straight_mean()

        self.assertEqual(row.averaging, SessionAveraging.EQUAL)
        self.assertIsNone(row.first_weight)
        self.assertIsNone(row.second_weight)
        self.assertIsNone(row.third_weight)

    def test_a_pass_mark_outside_a_hundred_is_refused(self):
        with connected_to(self.stmarys):
            with self.assertRaises(sessions.InvalidPassMark):
                sessions.set_pass_mark(120)


class TheFreezeTests(SessionSetUp):
    """Release the third term and the year stops being a live calculation."""

    def setUp(self):
        super().setUp()
        self.mark(self.stmarys, "first", self.ada, 60)
        self.mark(self.stmarys, "second", self.ada, 70)
        self.mark(self.stmarys, "third", self.ada, 80)

    def test_releasing_the_third_term_writes_a_line_per_child(self):
        with connected_to(self.stmarys):
            self.release_the_third_term()
            frozen = sessions.released_session_line(self.ada, SESSION)

        self.assertIsNotNone(frozen)
        self.assertEqual(frozen.session_average, Decimal("70.00"))
        self.assertEqual(frozen.first_average, Decimal("60.00"))
        self.assertEqual(frozen.session, SESSION)

    def test_releasing_an_earlier_term_freezes_nothing(self):
        """A session average is not a thing until the year it averages is over."""
        with connected_to(self.stmarys):
            sheet = results_services.open_sheet(
                self.group(self.stmarys), self.term(self.stmarys, "first"), self.principal
            )
            results_services.submit(sheet, self.teacher, unmarked=unmarked.count(sheet.class_group, sheet.term))
            results_services.check(sheet, self.vp, unmarked=unmarked.count(sheet.class_group, sheet.term))
            results_services.approve(sheet, self.principal, unmarked=unmarked.count(sheet.class_group, sheet.term))
            results_services.release(sheet, self.principal)

            self.assertEqual(ReleasedSessionResult.objects.count(), 0)
            self.assertIsNone(sessions.released_session_line(self.ada, SESSION))

    def test_a_frozen_line_outlives_a_change_of_weighting(self):
        """The whole reason there is a table. A school may change its mind."""
        with connected_to(self.stmarys):
            self.release_the_third_term()
            before = sessions.card_session_line(self.ada, SESSION).average

            sessions.use_a_weighting(20, 20, 60)
            after = sessions.card_session_line(self.ada, SESSION).average

        self.assertEqual(before, Decimal("70.00"))
        self.assertEqual(after, Decimal("70.00"))
        # And the live computation really would have moved.
        self.assertNotEqual(before, Decimal("74.00"))  # 60*.2 + 70*.2 + 80*.6

    def test_the_live_computation_really_does_move_when_the_freeze_is_absent(self):
        """The control. Without it the test above proves only that nothing ran.

        Two terms' cards have gone home and the third has not, so no line is
        frozen and the year so far is those two cards under today's weighting.
        """
        with connected_to(self.stmarys):
            self.release_terms("first", "second")
            before = sessions.card_session_line(self.ada, SESSION).average
            sessions.use_a_weighting(20, 60, 20)
            after = sessions.card_session_line(self.ada, SESSION).average

        self.assertEqual(before, Decimal("65.00"))  # (60 + 70) / 2
        self.assertEqual(after, Decimal("67.50"))  # (60*20 + 70*60) / 80

    def test_the_frozen_line_records_why_a_term_was_absent(self):
        joined_late = self.child(self.stmarys, "late", "Late Joiner", ["third"])
        self.mark(self.stmarys, "third", joined_late, 80)

        with connected_to(self.stmarys):
            self.release_the_third_term()
            frozen = sessions.released_session_line(joined_late, SESSION)

        self.assertEqual(frozen.first_absence, TermAbsence.NOT_ENROLLED)
        self.assertIsNone(frozen.first_average)
        self.assertIsNone(frozen.first_weight_used)
        self.assertEqual(frozen.third_weight_used, Decimal("100.00"))

    def test_a_release_survives_a_weighting_that_zeroes_the_terms_sat(self):
        """The whole class's release used to fail on one school's averaging.

        `0/0/100`, and a child on the third-term roster whose third term nobody
        marked. The two terms they *did* sit have averages, so they cannot claim
        an absence reason, and `the_first_term_is_present_or_explained` demands a
        weight beside an average — while the old
        `a_session_average_has_a_term_behind_it` demanded that a null average
        carry no weights at all. There was no row the code could write, so
        `bulk_create()` raised `IntegrityError` inside the release transaction
        and took the release of **every child on the roster** down with it.

        Migration `0014` has the argument. The weight applied to a term the
        school counts for nothing is nought, and the row records it.
        """
        unmarked_third = self.child(self.stmarys, "quiet", "Quiet Third")
        self.mark(self.stmarys, "first", unmarked_third, 60)
        self.mark(self.stmarys, "second", unmarked_third, 70)
        # deliberately no third-term mark

        with connected_to(self.stmarys):
            sessions.use_a_weighting(0, 0, 100)
            self.release_the_third_term()
            frozen = sessions.released_session_line(unmarked_third, SESSION)

            # The rest of the roster froze too, rather than being rolled back
            # with it: `self.ada` is on the same sheet.
            self.assertIsNotNone(sessions.released_session_line(self.ada, SESSION))

        self.assertIsNone(frozen.session_average)
        self.assertEqual(frozen.first_average, Decimal("60.00"))
        self.assertEqual(frozen.first_weight_used, Decimal("0.00"))
        self.assertEqual(frozen.first_absence, "")
        self.assertEqual(frozen.second_weight_used, Decimal("0.00"))
        self.assertIsNone(frozen.third_weight_used)
        self.assertEqual(frozen.third_absence, TermAbsence.UNMARKED)

    def test_the_card_reads_that_line_back_the_same_way(self):
        """A nought weight has to survive the round trip through the freeze.

        `card_session_line()` reads the frozen row once one exists, and a reader
        that got `{}` back from the freeze and `{'first': 0.00}` from the live
        computation would be looking at two different answers to one question.
        """
        unmarked_third = self.child(self.stmarys, "quiet", "Quiet Third")
        self.mark(self.stmarys, "first", unmarked_third, 60)
        self.mark(self.stmarys, "second", unmarked_third, 70)

        with connected_to(self.stmarys):
            sessions.use_a_weighting(0, 0, 100)
            self.release_terms("first", "second")
            live = sessions.session_line(unmarked_third, SESSION)
            self.release_the_third_term()
            frozen = sessions.card_session_line(unmarked_third, SESSION)

        self.assertEqual(frozen.weights, live.weights)
        self.assertEqual(
            frozen.weights, {"first": Decimal("0.00"), "second": Decimal("0.00")}
        )
        self.assertIsNone(frozen.average)

    def _refusal_of(self, **row):
        """Insert a deliberately bad frozen session line; return what refused it.

        Two failures this exists to stop, and both had already happened here.

        **The row needs a card.** `0017` made `ReleasedSessionResult.card` NOT
        NULL, and Postgres tests a column's NOT NULL before it tests a CHECK, so
        a row built without one is rejected on `card_id` and never reaches the
        constraint the test is named after. All three of these went on passing
        while proving nothing about the constraint they name. The card is
        `self.ada`'s and is deliberately mismatched with the invented
        `student_membership_id` these rows carry to dodge the unique index —
        nothing ties the two columns together, and the row has to be nonsense in
        exactly one respect at a time or it is not a test of that one respect.

        **And the assertion is on the constraint's name.** `IntegrityError` is
        what a unique index, a null column and a foreign key all raise too, so
        `assertRaises(IntegrityError)` alone cannot tell the constraint under
        test from the three ways of never reaching it.
        """
        card = cards.cards_by_student(row["sheet"])[self.ada.pk]
        with self.assertRaises(IntegrityError) as refused:
            with transaction.atomic():
                ReleasedSessionResult.objects.create(card=card, **row)
        return str(refused.exception)

    def test_the_database_still_refuses_an_average_the_arithmetic_dropped(self):
        """`0014` relaxed one direction of that constraint and not the other.

        A term weighted 60 with no session average beside it is an average that
        went missing, and it is still refused — the relaxation is only that a
        weight of **nought** no longer counts as a term behind an average.
        """
        with connected_to(self.stmarys):
            sheet = self.release_the_third_term()
            refusal = self._refusal_of(
                sheet=sheet,
                student_membership_id=self.ada.pk + 9999,
                session=SESSION,
                averaging=SessionAveraging.WEIGHTED,
                first_average=Decimal("60.00"),
                first_absence="",
                first_weight_used=Decimal("60.00"),
                second_average=None,
                second_absence=TermAbsence.NOT_ENROLLED,
                second_weight_used=None,
                third_average=None,
                third_absence=TermAbsence.NOT_ENROLLED,
                third_weight_used=None,
                session_average=None,  # a term carried 60 and produced nothing
            )

        self.assertIn("a_session_average_has_a_term_behind_it", refusal)

    def test_the_database_still_refuses_an_average_with_nothing_behind_it(self):
        """The other direction, and the one the null-safety in `0014` protects.

        `weight_used > 0` is NULL for a null column and a CHECK that evaluates
        to NULL passes, so a condition written without the `IS NOT NULL` tests
        would let this row — an average invented out of no weighting at all —
        straight through.
        """
        with connected_to(self.stmarys):
            sheet = self.release_the_third_term()
            refusal = self._refusal_of(
                sheet=sheet,
                student_membership_id=self.ada.pk + 9998,
                session=SESSION,
                averaging=SessionAveraging.EQUAL,
                first_average=None,
                first_absence=TermAbsence.NOT_ENROLLED,
                first_weight_used=None,
                second_average=None,
                second_absence=TermAbsence.NOT_ENROLLED,
                second_weight_used=None,
                third_average=None,
                third_absence=TermAbsence.NOT_ENROLLED,
                third_weight_used=None,
                session_average=Decimal("70.00"),  # out of nothing
            )

        self.assertIn("a_session_average_has_a_term_behind_it", refusal)

    def test_a_frozen_line_cannot_be_edited_or_deleted(self):
        with connected_to(self.stmarys):
            self.release_the_third_term()
            frozen = sessions.released_session_line(self.ada, SESSION)

            frozen.session_average = Decimal("99.00")
            with self.assertRaises(SessionResultsAreFrozenAtRelease):
                frozen.save()
            with self.assertRaises(SessionResultsAreFrozenAtRelease):
                frozen.delete()

    def test_the_database_refuses_an_edit_that_skips_the_model(self):
        """`.update()` never calls `save()`. The import and the psql session."""
        with connected_to(self.stmarys):
            self.release_the_third_term()

            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    ReleasedSessionResult.objects.filter(
                        student_membership_id=self.ada.pk
                    ).update(session_average=Decimal("99.00"))

            self.assertEqual(
                sessions.released_session_line(self.ada, SESSION).session_average,
                Decimal("70.00"),
            )

    def test_the_database_refuses_a_term_that_is_neither_present_nor_explained(self):
        """A term that vanished with no account of itself is refused by the table."""
        with connected_to(self.stmarys):
            sheet = self.release_the_third_term()
            refusal = self._refusal_of(
                sheet=sheet,
                student_membership_id=self.ada.pk + 9999,
                session=SESSION,
                averaging=SessionAveraging.EQUAL,
                first_average=None,
                first_absence="",  # neither a number nor a reason
                first_weight_used=None,
                second_average=Decimal("70.00"),
                second_absence="",
                second_weight_used=Decimal("100.00"),
                third_average=None,
                third_absence=TermAbsence.NOT_ENROLLED,
                third_weight_used=None,
                session_average=Decimal("70.00"),
            )

        self.assertIn("the_first_term_is_present_or_explained", refusal)


class ThePromotionDecisionTests(SessionSetUp):
    """A suggestion the arithmetic makes, and a decision only a person makes."""

    def setUp(self):
        super().setUp()
        self.mark(self.stmarys, "first", self.ada, 60)
        self.mark(self.stmarys, "second", self.ada, 70)
        self.mark(self.stmarys, "third", self.ada, 80)

    def test_a_child_nobody_has_decided_about_is_undecided(self):
        """Not promoted. The absence of a row, and every reader must handle it."""
        with connected_to(self.stmarys):
            self.assertIsNone(sessions.promotion_of(self.ada, SESSION))
            self.assertEqual(PromotionDecision.objects.count(), 0)

    def test_nothing_auto_fills_a_decision_from_the_suggestion(self):
        """A principal who reviews nothing must not silently promote a school.

        The suggestion exists, is `PROMOTED`, and reading it writes nothing.
        """
        with connected_to(self.stmarys):
            self.release_terms()
            line = sessions.card_session_line(self.ada, SESSION)
            self.assertEqual(
                sessions.suggested_status(line.average), PromotionStatus.PROMOTED
            )

            self.assertEqual(PromotionDecision.objects.count(), 0)
            self.assertIsNone(sessions.promotion_of(self.ada, SESSION))

    def test_a_decision_records_the_suggestion_it_was_taken_against(self):
        with connected_to(self.stmarys):
            self.release_terms()
            decision = sessions.decide(
                self.ada, SESSION, PromotionStatus.PROMOTED, by=self.principal
            )

        self.assertEqual(decision.status, PromotionStatus.PROMOTED)
        self.assertEqual(decision.suggested, PromotionStatus.PROMOTED)
        self.assertEqual(decision.session_average, Decimal("70.00"))
        self.assertEqual(decision.pass_mark_used, Decimal("50.00"))
        self.assertFalse(decision.overrode_the_suggestion)
        self.assertEqual(decision.decided_by_id, self.principal.pk)

    def test_an_override_is_visible_as_one(self):
        """The gap between the two columns is the record that a person differed."""
        with connected_to(self.stmarys):
            self.release_terms()
            decision = sessions.decide(
                self.ada, SESSION, PromotionStatus.REPEATED, by=self.principal,
                note="Missed most of third term through illness.",
            )

        self.assertEqual(decision.suggested, PromotionStatus.PROMOTED)
        self.assertEqual(decision.status, PromotionStatus.REPEATED)
        self.assertTrue(decision.overrode_the_suggestion)
        self.assertIn("illness", decision.note)

    def test_the_suggestion_is_frozen_and_not_recomputed(self):
        """The finding this column exists for, proved by moving the config.

        The principal saw REPEATED on a 44.00 under 20/20/60 and recorded
        ON_TRIAL — an act of mercy. The school later moves to a straight mean,
        under which the same child reads 51.67 and the suggestion would be
        PROMOTED. Recomputed, the record would read "the system said promote,
        the principal said on trial" — a downgrade nobody performed, invented by
        a configuration change, on the one row kept to prove who decided what.
        """
        weak = self.child(self.stmarys, "weak", "Struggling Child")
        self.mark(self.stmarys, "first", weak, 60)
        self.mark(self.stmarys, "second", weak, 55)
        self.mark(self.stmarys, "third", weak, 40)

        with connected_to(self.stmarys):
            sessions.use_a_weighting(20, 20, 60)
            self.release_terms()
            # 60*.2 + 55*.2 + 40*.6 = 12 + 11 + 24 = 47.00
            self.assertEqual(
                sessions.card_session_line(weak, SESSION).average, Decimal("47.00")
            )
            decision = sessions.decide(
                weak, SESSION, PromotionStatus.ON_TRIAL, by=self.principal
            )
            self.assertEqual(decision.suggested, PromotionStatus.REPEATED)

            # The school changes its mind about how a year is averaged.
            sessions.use_a_straight_mean()
            # (60 + 55 + 40) / 3 = 51.67, which would suggest PROMOTED.
            self.assertEqual(
                sessions.session_line(weak, SESSION).average, Decimal("51.67")
            )

            reread = sessions.promotion_of(weak, SESSION)

        self.assertEqual(reread.suggested, PromotionStatus.REPEATED)
        self.assertEqual(reread.session_average, Decimal("47.00"))
        self.assertTrue(reread.overrode_the_suggestion)

    def test_a_second_decision_wins_and_the_first_still_stands(self):
        with connected_to(self.stmarys):
            first = sessions.decide(
                self.ada, SESSION, PromotionStatus.REPEATED, by=self.principal
            )
            second = sessions.decide(
                self.ada, SESSION, PromotionStatus.PROMOTED, by=self.principal,
                note="Appeal upheld.",
            )

            latest = sessions.promotion_of(self.ada, SESSION)
            # Evaluated *inside* the schema context. A lazy queryset carried
            # out of it runs against `public`, where these tables do not exist
            # — which is a `ProgrammingError` rather than a wrong answer, but
            # only because the table happens not to be in the public schema.
            both = list(
                PromotionDecision.objects.filter(
                    student_membership_id=self.ada.pk, session=SESSION
                )
            )

        self.assertEqual(latest.pk, second.pk)
        self.assertEqual(latest.status, PromotionStatus.PROMOTED)
        self.assertEqual(len(both), 2)
        self.assertIn(first.pk, [row.pk for row in both])

    def test_a_decision_cannot_be_edited_or_deleted(self):
        with connected_to(self.stmarys):
            decision = sessions.decide(
                self.ada, SESSION, PromotionStatus.PROMOTED, by=self.principal
            )
            decision.status = PromotionStatus.REPEATED
            with self.assertRaises(PromotionDecisionsAreAppendOnly):
                decision.save()
            with self.assertRaises(PromotionDecisionsAreAppendOnly):
                decision.delete()

    def test_the_database_refuses_an_edit_that_skips_the_model(self):
        with connected_to(self.stmarys):
            sessions.decide(
                self.ada, SESSION, PromotionStatus.PROMOTED, by=self.principal
            )
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    PromotionDecision.objects.filter(
                        student_membership_id=self.ada.pk
                    ).update(status=PromotionStatus.REPEATED)

            self.assertEqual(
                sessions.promotion_of(self.ada, SESSION).status,
                PromotionStatus.PROMOTED,
            )

    def test_a_child_with_no_average_gets_a_decision_and_no_suggestion(self):
        """Undecidable by arithmetic is exactly when a person is most needed."""
        blank = self.child(self.stmarys, "blank", "Unmarked Child")

        with connected_to(self.stmarys):
            decision = sessions.decide(
                blank, SESSION, PromotionStatus.REPEATED, by=self.principal
            )

        self.assertEqual(decision.suggested, "")
        self.assertIsNone(decision.session_average)
        self.assertIsNone(decision.pass_mark_used)
        self.assertFalse(decision.overrode_the_suggestion)

    def test_a_decision_after_release_is_about_the_number_on_the_card(self):
        """Not a live recomputation of it, which may already have moved."""
        with connected_to(self.stmarys):
            self.release_the_third_term()
            sessions.use_a_weighting(20, 20, 60)  # live would now read 74.00

            decision = sessions.decide(
                self.ada, SESSION, PromotionStatus.PROMOTED, by=self.principal
            )

        self.assertEqual(decision.session_average, Decimal("70.00"))


class WhoMayDecideTests(SessionSetUp):
    """Configuring a weighting and deciding a child's year are different acts."""

    def test_the_principal_decides(self):
        with connected_to(self.stmarys):
            decision = sessions.decide_as(
                self.principal, self.ada, SESSION, PromotionStatus.PROMOTED,
                note="Met the pass mark",
            )
        self.assertEqual(decision.decided_by_id, self.principal.pk)
        self.assertEqual(decision.note, "Met the pass mark")

    def test_an_administrator_may_configure_but_may_not_decide(self):
        """The one place these two sets are meant to disagree."""
        with connected_to(self.stmarys):
            sessions.use_a_weighting_as(self.admin, 20, 20, 60)

            with self.assertRaises(sessions.NotAllowedToDecidePromotion) as refused:
                sessions.decide_as(
                    self.admin, self.ada, SESSION, PromotionStatus.PROMOTED
                )
            self.assertIn("principal", str(refused.exception))

    def test_a_teacher_may_do_neither(self):
        with connected_to(self.stmarys):
            with self.assertRaises(sessions.NotAllowedToConfigureSessions):
                sessions.use_a_weighting_as(self.teacher, 20, 20, 60)
            with self.assertRaises(sessions.NotAllowedToDecidePromotion):
                sessions.decide_as(
                    self.teacher, self.ada, SESSION, PromotionStatus.PROMOTED
                )

    def test_a_principal_of_another_school_may_not_decide_here(self):
        """Holding the role somewhere else is not holding it here."""
        with connected_to(self.stmarys):
            with self.assertRaises(sessions.NotAllowedToDecidePromotion):
                sessions.decide_as(
                    self.their_principal, self.ada, SESSION, PromotionStatus.PROMOTED
                )

    def test_a_child_of_another_school_cannot_be_decided_about(self):
        theirs = self.child(self.grace, "grace-kid", "Their Child")
        with connected_to(self.stmarys):
            with self.assertRaises(sessions.NotThisSchoolsStudent):
                sessions.decide(
                    theirs, SESSION, PromotionStatus.PROMOTED, by=self.principal
                )

    def test_a_status_outside_the_four_is_refused(self):
        with connected_to(self.stmarys):
            with self.assertRaises(sessions.SessionsError):
                sessions.decide(self.ada, SESSION, "undecided", by=self.principal)


class TwoSchoolsTests(SessionSetUp):
    """Every table here lives in a tenant schema, and none of it may leak."""

    def test_a_weighting_is_one_schools_and_not_the_others(self):
        with connected_to(self.stmarys):
            sessions.use_a_weighting(20, 20, 60)
        with connected_to(self.grace):
            self.assertEqual(sessions.settings().averaging, SessionAveraging.EQUAL)
            self.assertIsNone(sessions.settings().first_weight)

    def test_the_same_child_reads_differently_under_two_conventions(self):
        """The point of it being configurable, shown as two numbers."""
        theirs = self.child(self.grace, "grace-kid", "Their Child")
        for term, mark in (("first", 60), ("second", 70), ("third", 80)):
            self.mark(self.stmarys, term, self.ada, mark)
            self.mark(self.grace, term, theirs, mark)

        with connected_to(self.stmarys):
            sessions.use_a_weighting(20, 20, 60)
            self.release_terms()
            ours = sessions.card_session_line(self.ada, SESSION).average
        with connected_to(self.grace):
            self.release_terms(school=self.grace)
            theirs_average = sessions.card_session_line(theirs, SESSION).average

        self.assertEqual(ours, Decimal("74.00"))
        self.assertEqual(theirs_average, Decimal("70.00"))

    def test_a_decision_at_one_school_is_invisible_at_the_other(self):
        with connected_to(self.stmarys):
            sessions.decide(
                self.ada, SESSION, PromotionStatus.PROMOTED, by=self.principal
            )
        with connected_to(self.grace):
            self.assertEqual(PromotionDecision.objects.count(), 0)
            self.assertIsNone(sessions.promotion_of(self.ada, SESSION))

    def test_a_pass_mark_is_per_school(self):
        with connected_to(self.stmarys):
            sessions.set_pass_mark(70)
        with connected_to(self.grace):
            self.assertEqual(sessions.settings().pass_mark, Decimal("50.00"))


class TheChildWhoMovedAfterReleaseTests(SessionSetUp):
    """Two releases can freeze the same child's session. The first is the card.

    Found in self-review rather than by a failing test, and it is the same shape
    that has bitten this app four times now: `ClassPlacement` holds one group
    per child per term, so "a child is on exactly one third-term roster" is true
    at any instant and false over time. Release JSS 1A, move the child, release
    JSS 3B, and two frozen rows exist for one session.

    Both are real records of releases that happened, and the table is
    append-only so neither goes away. The question is which one is the card, and
    a released card keeps saying what it said — so it is the first.

    **The two behavioural tests below pass with the `order_by()` removed**, and
    that was checked rather than assumed: Postgres with no ORDER BY returns rows
    in whatever physical order suits it, which for a freshly inserted pair is
    insertion order, so they get the right row by luck. They are kept because
    they state the property a reader cares about, and
    `test_the_card_is_chosen_by_an_explicit_order_rather_than_by_luck` pins the
    spelling that actually makes it true. `LockScopeTests` in
    `test_approval_concurrency.py` is the same pair for the same reason and says
    so at length.
    """

    def setUp(self):
        super().setUp()
        self.mark(self.stmarys, "first", self.ada, 60)
        self.mark(self.stmarys, "second", self.ada, 70)
        self.mark(self.stmarys, "third", self.ada, 80)

    def _release_a_second_class_the_child_has_moved_into(self):
        """JSS 3B, its own chain, with the child now on its roster."""
        other = ClassGroup.objects.create(name="JSS 3B", level=3)
        third = self.term(self.stmarys, "third")
        teaching = self.teacher.memberships.get(
            school=self.stmarys, role=Role.TEACHER
        )
        assign_class_teacher(other, third, teaching)
        move_student(other, third, self.ada)

        sheet = results_services.open_sheet(other, third, self.principal)
        results_services.submit(sheet, self.teacher, unmarked=unmarked.count(sheet.class_group, sheet.term))
        results_services.check(sheet, self.vp, unmarked=unmarked.count(sheet.class_group, sheet.term))
        results_services.approve(sheet, self.principal, unmarked=unmarked.count(sheet.class_group, sheet.term))
        results_services.release(sheet, self.principal)
        return sheet

    def test_the_first_release_is_the_card_the_second_does_not_overwrite_it(self):
        with connected_to(self.stmarys):
            self.release_the_third_term()
            first_line = sessions.released_session_line(self.ada, SESSION)

            self._release_a_second_class_the_child_has_moved_into()

            frozen = list(
                ReleasedSessionResult.objects.filter(
                    session=SESSION, student_membership_id=self.ada.pk
                )
            )
            still = sessions.released_session_line(self.ada, SESSION)

        # Both releases really did happen and both rows really are there.
        self.assertEqual(len(frozen), 2)
        # And the card is the one that went home first.
        self.assertEqual(still.pk, first_line.pk)

    def test_the_card_keeps_reading_the_same_after_the_second_release(self):
        """The property that matters, stated as the number a parent is holding."""
        with connected_to(self.stmarys):
            self.release_the_third_term()
            before = sessions.card_session_line(self.ada, SESSION).average

            self._release_a_second_class_the_child_has_moved_into()
            after = sessions.card_session_line(self.ada, SESSION).average

        self.assertEqual(before, Decimal("70.00"))
        self.assertEqual(after, Decimal("70.00"))

    def test_the_card_is_chosen_by_an_explicit_order_rather_than_by_luck(self):
        """The ordering is in the query, not in Postgres' good manners.

        Asserted on the SQL because it cannot be observed through behaviour —
        see the class docstring. `created_at` is named specifically: an
        `ORDER BY` that had drifted to `-created_at`, or to `id` alone, would
        satisfy a bare "is there an ORDER BY" and pick the wrong card the day
        two rows are written in one transaction.
        """
        with connected_to(self.stmarys):
            self.release_the_third_term()
            self._release_a_second_class_the_child_has_moved_into()

            with CaptureQueriesContext(connection) as captured:
                sessions.released_session_line(self.ada, SESSION)

        # **Two** queries against the frozen table since task 8, and that is
        # the rule rather than an implementation detail: the earliest release,
        # and then the highest version within it. This test asserted a single
        # statement and unpacked it, so it failed loudly the moment the second
        # half arrived — which is the behaviour wanted from it.
        #
        # The context also captures the schema-switching statement
        # `connected_to()` issues, so picking by table name rather than by
        # position is what keeps this from breaking the day another one joins.
        statements = [
            query["sql"].upper()
            for query in captured.captured_queries
            if "RESULTS_RELEASEDSESSIONRESULT" in query["sql"].upper()
        ]
        self.assertEqual(
            len(statements),
            2,
            "Expected the earliest-release query and the highest-version one.",
        )
        earliest, highest = statements

        # The ORDER BY clause specifically, not the whole statement. Two ways
        # this assertion was wrong before it was this one, both of which passed
        # against an unordered query:
        #
        #   - `assertIn("ORDER BY", sql)` — `QuerySet.first()` orders by the
        #     primary key when the queryset has no ordering of its own, so
        #     there is *always* an ORDER BY and it proves nothing;
        #   - `assertIn("created_at", sql)` — every column is in the SELECT
        #     list, `created_at` among them, so this matched the projection
        #     rather than the ordering.
        self.assertIn("ORDER BY", earliest)
        ordering = earliest.split("ORDER BY", 1)[1]
        self.assertIn("CREATED_AT", ordering)
        self.assertNotIn("DESC", ordering)

        # And the second half, asserted the same way and for the same reason.
        # Ascending here would take the superseded card: `decide()` freezes the
        # session average and the promotion suggestion off this row.
        self.assertIn("ORDER BY", highest)
        ordering = highest.split("ORDER BY", 1)[1]
        self.assertIn("VERSION", ordering)
        self.assertIn("DESC", ordering)


class TheYearIsTheCardsThatWentHomeTests(SessionSetUp):
    """Audit finding G-02: the year's summary is built from released cards only.

    Each term's figure is the average on the card that went home for that term,
    never the marks as they stand today. A subject with a paper unmarked never
    enters it, a term that was never released does not count, and the promotion
    suggestion is taken from the same figures.

    Every test here that changes a live mark was run against the old reading
    (`positions.overall_percentages()` for the earlier terms, `averages` for the
    term being released) and failed there.
    """

    def setUp(self):
        super().setUp()
        with connected_to(self.stmarys):
            self.english_id = Subject.objects.create(name="English", code="ENG").pk

    def change_the_live_mark(self, term_name, membership, value):
        """Move the child to another arm for that term, then rewrite her Exam mark.

        The database refuses to change a mark of a class whose term is released
        (`gradebook`'s guard), so a mark cannot simply be edited under a card.
        The way a live mark does move after a card went home is this one: the
        office moves the child to another arm, whose sheet is still open, and
        the mark is changed there. Her card for the term is untouched by it.
        """
        with connected_to(self.stmarys):
            term = self.term(self.stmarys, term_name)
            other, _ = ClassGroup.objects.get_or_create(name="JSS 1B", defaults={"level": 1})
            move_student(other, term, membership)
            changed = Score.objects.filter(
                assessment__term=term,
                assessment__subject_id=self.maths_id[self.stmarys.pk],
                student_membership_id=membership.pk,
            ).update(value=value)
        self.assertEqual(changed, 1, "the live mark was not there to change")
        return other

    def paper(self, term_name, name, membership=None, value=None, max_score=10):
        """An English paper for the term, marked for `membership` if a value is given."""
        with connected_to(self.stmarys):
            assessment, _ = Assessment.objects.get_or_create(
                term=self.term(self.stmarys, term_name),
                subject_id=self.english_id,
                name=name,
                defaults={"max_score": max_score},
            )
            if membership is not None and value is not None:
                Score.objects.create(
                    assessment=assessment, student_membership_id=membership.pk, value=value
                )

    def card(self, term_name, membership=None):
        return cards.card_for(membership or self.ada, self.term(self.stmarys, term_name))

    def test_a_live_mark_changed_after_its_card_went_home_does_not_move_the_year(self):
        """First and second term are read off their cards, not marked again."""
        self.mark(self.stmarys, "first", self.ada, 60)
        self.mark(self.stmarys, "second", self.ada, 70)
        self.mark(self.stmarys, "third", self.ada, 80)
        with connected_to(self.stmarys):
            self.release_terms("first", "second")
            before = sessions.session_line(self.ada, SESSION)

        self.change_the_live_mark("first", self.ada, 10)
        self.change_the_live_mark("second", self.ada, 20)

        with connected_to(self.stmarys):
            # The marks really did move: the staff's live figure says so.
            live = positions.overall_percentages(
                ClassGroup.objects.get(name="JSS 1B"), self.term(self.stmarys, "first")
            )
            self.assertEqual(live[self.ada.pk], Decimal("10.00"))

            still = sessions.session_line(self.ada, SESSION)
            self.release_the_third_term()
            frozen = sessions.released_session_line(self.ada, SESSION)
            first_card, second_card = self.card("first"), self.card("second")

        self.assertEqual(before.average, Decimal("65.00"))
        self.assertEqual(still.average, before.average)
        self.assertEqual(frozen.first_average, Decimal("60.00"))
        self.assertEqual(frozen.second_average, Decimal("70.00"))
        self.assertEqual(frozen.first_average, first_card.own_average)
        self.assertEqual(frozen.second_average, second_card.own_average)
        self.assertEqual(frozen.session_average, Decimal("70.00"))  # (60 + 70 + 80) / 3

    def test_a_live_mark_changed_after_the_year_is_released_does_not_move_it(self):
        self.mark(self.stmarys, "first", self.ada, 60)
        self.mark(self.stmarys, "second", self.ada, 70)
        self.mark(self.stmarys, "third", self.ada, 80)
        with connected_to(self.stmarys):
            self.release_the_third_term()
            before = sessions.card_session_line(self.ada, SESSION)

        self.change_the_live_mark("first", self.ada, 5)

        with connected_to(self.stmarys):
            after = sessions.card_session_line(self.ada, SESSION)
            # Nor does the unfrozen read, which is built from the same cards.
            unfrozen = sessions.session_line(self.ada, SESSION)

        self.assertEqual(before.average, Decimal("70.00"))
        self.assertEqual(after, before)
        self.assertEqual(unfrozen.average, Decimal("70.00"))

    def test_the_session_average_is_the_frozen_term_cards_under_the_schools_weighting(self):
        self.mark(self.stmarys, "first", self.ada, 61)
        self.mark(self.stmarys, "second", self.ada, 73)
        self.mark(self.stmarys, "third", self.ada, 88)
        with connected_to(self.stmarys):
            sessions.use_a_weighting(20, 30, 50)
            sheet = self.release_the_third_term()
            first, second, third = self.card("first"), self.card("second"), self.card("third")
            frozen = ReleasedSessionResult.objects.get(card=third)

        self.assertEqual(third.sheet_id, sheet.pk)
        # Each term's figure is the one at the top of that term's card.
        self.assertEqual(frozen.first_average, first.own_average)
        self.assertEqual(frozen.second_average, second.own_average)
        self.assertEqual(frozen.third_average, third.own_average)
        # And the year is those three, combined as the school weights them.
        combined = (
            first.own_average * 20 + second.own_average * 30 + third.own_average * 50
        ) / 100
        self.assertEqual(frozen.session_average, positions.round_percentage(combined))
        self.assertEqual(frozen.session_average, Decimal("78.10"))
        self.assertEqual(
            (frozen.first_weight_used, frozen.second_weight_used, frozen.third_weight_used),
            (Decimal("20.00"), Decimal("30.00"), Decimal("50.00")),
        )

    def test_a_part_marked_subject_never_enters_the_year(self):
        """English has two papers and one of them unmarked, in the first term and
        in the third. The card leaves it out of its average; so does the year."""
        for term_name, maths in (("first", 60), ("second", 70), ("third", 80)):
            self.mark(self.stmarys, term_name, self.ada, maths)
        for term_name in ("first", "third"):
            self.paper(term_name, "CA", self.ada, 10)  # 10/10, and...
            self.paper(term_name, "Exam")  # ...this one never marked
        with connected_to(self.stmarys):
            self.release_the_third_term()
            frozen = sessions.released_session_line(self.ada, SESSION)
            first_card, third_card = self.card("first"), self.card("third")
            # What the staff's figure, partial subjects included, says instead.
            with_partials = positions.overall_percentages(
                self.group(self.stmarys), self.term(self.stmarys, "third")
            )[self.ada.pk]

        self.assertEqual(with_partials, Decimal("90.00"))  # (80 + 100) / 2
        self.assertEqual(third_card.own_average, Decimal("80.00"))
        self.assertEqual(frozen.third_average, third_card.own_average)
        self.assertEqual(frozen.first_average, first_card.own_average)
        self.assertEqual(frozen.first_average, Decimal("60.00"))
        self.assertEqual(frozen.session_average, Decimal("70.00"))

    def test_a_term_that_was_never_released_does_not_count(self):
        """The first term was left in draft with marks in it."""
        self.mark(self.stmarys, "first", self.ada, 20)
        self.mark(self.stmarys, "second", self.ada, 70)
        self.mark(self.stmarys, "third", self.ada, 80)
        with connected_to(self.stmarys):
            self.release_terms("second", "third")
            frozen = sessions.released_session_line(self.ada, SESSION)

        self.assertIsNone(frozen.first_average)
        self.assertEqual(frozen.first_absence, TermAbsence.NOT_RELEASED)
        self.assertIsNone(frozen.first_weight_used)
        self.assertEqual(frozen.session_average, Decimal("75.00"))  # (70 + 80) / 2

    def test_a_term_in_progress_is_not_released_rather_than_marked_live(self):
        self.mark(self.stmarys, "first", self.ada, 60)
        self.mark(self.stmarys, "second", self.ada, 70)
        self.mark(self.stmarys, "third", self.ada, 100)
        with connected_to(self.stmarys):
            self.release_terms("first", "second")
            line = sessions.session_line(self.ada, SESSION)

        self.assertEqual(line.terms[2].absence, TermAbsence.NOT_RELEASED)
        self.assertIsNone(line.terms[2].average)
        self.assertEqual(line.average, Decimal("65.00"))

    def test_the_promotion_suggestion_is_made_on_the_figures_the_cards_showed(self):
        """48.33 on the cards: repeated. The live marks, moved since, say 65."""
        self.mark(self.stmarys, "first", self.ada, 60)
        self.mark(self.stmarys, "second", self.ada, 40)
        self.mark(self.stmarys, "third", self.ada, 45)
        with connected_to(self.stmarys):
            self.release_terms("first", "second")
        self.change_the_live_mark("first", self.ada, 100)
        self.change_the_live_mark("second", self.ada, 50)

        with connected_to(self.stmarys):
            early = sessions.decide(
                self.ada, SESSION, PromotionStatus.ON_TRIAL, by=self.principal
            )
            self.release_the_third_term()
            frozen = sessions.released_session_line(self.ada, SESSION)
            decision = sessions.decide(
                self.ada, SESSION, PromotionStatus.REPEATED, by=self.principal
            )

        # Before the third term went home the year is not frozen, and nothing
        # is suggested on a reckoning no card shows (audit finding G-04). It
        # used to suggest "promoted" here on the two cards so far.
        self.assertIsNone(early.session_average)
        self.assertEqual(early.suggested, "")
        # After: the three cards, (60 + 40 + 45) / 3, and not (100 + 50 + 45) / 3.
        self.assertEqual(frozen.session_average, Decimal("48.33"))
        self.assertEqual(decision.session_average, frozen.session_average)
        self.assertEqual(decision.suggested, PromotionStatus.REPEATED)
        self.assertFalse(decision.overrode_the_suggestion)
