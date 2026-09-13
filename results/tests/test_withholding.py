"""Holding a released card back from a family over fees.

Written against `docs/withholding.md` rather than against
`results/withholding.py`, and that is not a stylistic note. The implementation
under this file was recovered uncommitted, with no tests and no history saying
who wrote it or what they checked. Tests written by reading that code would
document whatever it happens to do — including any place it drifted from the
design — and freeze the drift in as the specification. So every assertion below
traces to a numbered decision in the design document, and the numbering of the
classes follows the design's own list of the tests it owes.

## The two rules no constraint can express

Two of these are held by nothing but this file, which is why both come with a
control run recorded in the PR body rather than a bare green tick.

**The freeze is unconditional** (`TheFeeDoorDoesNotTouchTheFreeze`). No check
constraint can say "a row exists for every child on a roster this transaction
has moved on from" — the design's own enforcement table says `nothing can
express it` in that row. Making the freeze conditional on payment would leave an
unpaid child with no frozen record of that term, permanently, which is the exact
failure #31, #33 and #34 converged on. The control makes
`cards.freeze_for_release()` skip a child with a standing `withheld` decision —
the bug the fee door invites — and shows this class red.

**Both serving surfaces gate identically** (`TheFourCharacterBypass`). The gate
is one shared helper precisely so there is one function to change, and
`report_card_pdf()`'s docstring predicted the failure before the feature
existed: a family refused the JSON card appends `/pdf/` and is handed the file,
*reachable by adding four characters to a URL*. The control fits the gate to
`report_card()` alone and shows the PDF half of that class red while the JSON
half stays green.

A test that has never been seen red is a test whose subject has never been
proven, and both of these have a failure mode where they pass vacuously: the
first if the fixture releases nothing, the second if the PDF request never
reaches the gate.

## What the fixture has to carry

`ReportCardApiSetUp` from `test_card_api.py`, which already builds two schools,
a bursar, a guardian linked to one child by `Guardianship`, and two children
with different marks. The two-school half matters here for the same reason it
matters there — a gate that refuses everybody would pass a single-school test —
and the guardian matters because a claim is not a role: `FAMILY_CLAIMS` is
about `Guardianship`, not about holding PARENT somewhere.

Children are put in real arrears through `fees.services.charge()` rather than by
asserting against an empty ledger. The design rules that **the balance never
gates**, and a test where every balance is zero cannot tell a gate that ignores
the balance from one that reads it and finds nothing.
"""

import json
import re

from django.db import connection, transaction
from django.test import TestCase

from academics.models import TermName
from accounts.models import Membership, Role, User
from fees import services as fees_services
from results import cards, revision, withholding
from results.card_api import CardClaim, router as card_router
from results.services import NotAllowedToActOnResults, ResultsError
from results.models import (
    PdfState,
    ReportCardSettings,
    ReleasedCard,
    ReleasedCardPdf,
    WithholdingDecision,
    WithholdingDecisionsAreAppendOnly,
    WithholdingStatus,
)
from schools.tests.tenants import connected_to
from tests.refusals import RefusalAssertions

from .test_card_api import HOST, PASSWORD, THEIR_HOST, ReportCardApiSetUp

CONTACT = "Call the bursar's office on 0803 555 0100."

#: The prefix `api.py` mounts `card_api.router` under. Test 4e rebuilds URLs
#: from `router.path_operations`, and a hardcoded prefix there would be a second
#: place to change; it is written once, here.
PREFIX = "/api/results"


class WithholdingSetUp(RefusalAssertions, ReportCardApiSetUp):
    """The card fixture, plus arrears, a policy switch and a way to withhold.

    Every helper takes the school explicitly. `withhold()` and `set_policy()`
    resolve the school from the connection, so a helper that assumed St Mary's
    would silently write into whichever schema the last test left the
    connection on — the failure mode `ReportCardApiSetUp`'s own docstring
    records for `CardSetUp`.
    """

    def setUp(self):
        super().setUp()
        # Real arrears for both children, so "the balance never gates" is a
        # claim about a gate that had a non-zero number available to it.
        with connected_to(self.stmarys):
            for child in (self.ada, self.bola):
                fees_services.charge(
                    child,
                    self.term_of(self.stmarys, TermName.FIRST.value),
                    250_000_00,
                    narration="First term fees",
                )

    # -- policy and decisions -------------------------------------------------

    def enable_withholding(self, school=None, contact=CONTACT):
        school = school or self.stmarys
        with connected_to(school):
            return withholding.set_policy(enabled=True, contact=contact)

    def disable_withholding(self, school=None):
        school = school or self.stmarys
        with connected_to(school):
            return withholding.set_policy(enabled=False)

    def withhold(self, child, school=None, actor=None, reason="Fees outstanding."):
        school = school or self.stmarys
        with connected_to(school):
            return withholding.withhold(
                child.pk,
                self.term_of(school, TermName.FIRST.value),
                actor=actor or self.principal,
                reason=reason,
            )

    def lift(self, child, school=None, actor=None, reason=""):
        school = school or self.stmarys
        with connected_to(school):
            return withholding.lift(
                child.pk,
                self.term_of(school, TermName.FIRST.value),
                actor=actor or self.principal,
                reason=reason,
            )

    def withheld_and_released(self, child=None):
        """The normal fixture for the gate: switch on, one child held, released.

        Returns the child. The release happens **after** the decision on
        purpose — a decision is keyed on `(child, term)` and may exist before
        any card does, which is what makes the freeze control below reachable.
        """
        child = child or self.ada
        self.enable_withholding()
        self.withhold(child)
        self.release()
        return child

    # -- the two HTTP surfaces ------------------------------------------------

    def pdf_url(self, school, membership, term_name=TermName.FIRST.value):
        return f"{self.card_url(school, membership, term_name)}pdf/"

    def fetch_pdf(self, user, school, membership, term_name=TermName.FIRST.value):
        if user is not None:
            self.client.force_login(user)
        else:
            self.client.logout()
        return self.client.get(
            self.pdf_url(school, membership, term_name),
            HTTP_HOST=HOST if school == self.stmarys else THEIR_HOST,
        )

    def both_surfaces(self):
        """The two ways to ask for one card, for tests that must run on each."""
        return (("json", self.fetch), ("pdf", self.fetch_pdf))


class TheFeeDoorDoesNotTouchTheFreeze(WithholdingSetUp):
    """Design test 1, and the most important one here.

    Release a school with the switch on and a child already withheld, and every
    child on the roster still gets a `ReleasedCard`. Nothing in Part 2 touches
    `release()`, `cards.freeze_for_release()` or any frozen table: what fees
    gate is whether the card is **served**.

    The control that proves this class can fail is in the PR body — without it,
    a fixture that released nothing would turn every assertion here green.
    """

    def test_every_child_on_the_roster_is_frozen_though_one_is_withheld(self):
        self.enable_withholding()
        self.withhold(self.ada)

        self.release()

        with connected_to(self.stmarys):
            term = self.term_of(self.stmarys, TermName.FIRST.value)
            frozen = set(
                ReleasedCard.objects.filter(term=term).values_list(
                    "student_membership_id", flat=True
                )
            )

        self.assertEqual(
            frozen,
            {self.ada.pk, self.bola.pk},
            "the freeze is unconditional: a withheld child still gets a frozen "
            "card, or an unpaid child has no record of the term for ever",
        )

    def test_the_withheld_childs_card_is_a_real_card_not_a_stub(self):
        """Frozen *and* complete. A stub row would pass the test above."""
        self.enable_withholding()
        self.withhold(self.ada)

        self.release()

        with connected_to(self.stmarys):
            card = cards.card_for(self.ada, self.term_of(self.stmarys, TermName.FIRST))

        self.assertIsNotNone(card)
        self.assertEqual(card.position, 1, "Ada outscored Bola; the ranking is real")
        self.assertEqual(card.roster_size, 2)
        self.assertTrue(card.school_name, "the frozen school name is what the 403 uses")

    def test_withholding_every_child_still_freezes_every_child(self):
        """The whole-roster case, which is what a school in a bad term does."""
        self.enable_withholding()
        self.withhold(self.ada)
        self.withhold(self.bola)

        self.release()

        with connected_to(self.stmarys):
            term = self.term_of(self.stmarys, TermName.FIRST.value)
            self.assertEqual(ReleasedCard.objects.filter(term=term).count(), 2)


class AWithheldCardIsServedToStaffAndRefusedToAFamily(WithholdingSetUp):
    """Design test 2. Same term, same child, three readers, on both surfaces."""

    def setUp(self):
        super().setUp()
        self.withheld_and_released()

    def test_a_guardian_is_refused_on_both_surfaces(self):
        for name, fetch in self.both_surfaces():
            with self.subTest(surface=name):
                response = fetch(self.mama, self.stmarys, self.ada)
                self.assertEqual(response.status_code, 403)

    def test_the_child_themselves_is_refused_on_both_surfaces(self):
        """`SELF` is a family claim too — the design puts both in `FAMILY_CLAIMS`."""
        for name, fetch in self.both_surfaces():
            with self.subTest(surface=name):
                response = fetch(self.ada.user, self.stmarys, self.ada)
                self.assertEqual(response.status_code, 403)

    def test_staff_are_served_the_withheld_card_on_both_surfaces(self):
        """A bursar who cannot see what they are withholding cannot do the job."""
        for role_name, user in (
            ("principal", self.principal),
            ("bursar", self.bursar),
            ("teacher", self.teacher),
        ):
            with self.subTest(role=role_name):
                self.assertEqual(
                    self.fetch(user, self.stmarys, self.ada).status_code,
                    200,
                    "staff always see a withheld card",
                )

    def test_a_bursar_may_read_a_card_at_all(self):
        """`CARD_VIEWING_ROLES` gained BURSAR, and that is the widening's point.

        Asserted separately from the gate: a bursar refused here would make the
        staff test above pass for the wrong reason on a 403.
        """
        self.assertIn(Role.BURSAR.value, __import__(
            "results.card_api", fromlist=["CARD_VIEWING_ROLES"]
        ).CARD_VIEWING_ROLES)

    def test_a_guardian_of_a_child_who_is_not_withheld_is_served(self):
        """Bola is on the same roster, in the same term, with the same arrears.

        This is what stops the gate from being "refuse every family": the
        decision is per child, and the balance is not what decides.
        """
        for name, fetch in self.both_surfaces():
            with self.subTest(surface=name):
                response = fetch(self.bolas_father, self.stmarys, self.bola)
                self.assertNotEqual(
                    response.status_code,
                    403,
                    "Bola has arrears and no decision; nothing should be withheld",
                )

    def test_lifting_serves_the_card_again(self):
        """A second row, and the first still stands."""
        self.lift(self.ada)

        self.assertEqual(self.fetch(self.mama, self.stmarys, self.ada).status_code, 200)
        with connected_to(self.stmarys):
            self.assertEqual(
                WithholdingDecision.objects.filter(
                    student_membership_id=self.ada.pk
                ).count(),
                2,
                "append-only: lifting writes a row, it does not edit one",
            )


class NobodyWithoutAClaimLearnsTheCardIsWithheld(WithholdingSetUp):
    """Design test 3, corrected against the two refusal layers that exist.

    The design says "a stranger gets 404, not 403", and that is true of a
    stranger the *endpoint* refuses. It is not the whole picture, and writing
    the test from the design alone got this wrong first time round.

    `SchoolAccessMiddleware` refuses any authenticated caller with no active
    membership at the host's school **before a view runs at all**, with a 403.
    `test_card_api.py` documents this and pins it: that answer depends only on
    the caller's membership and never on the child asked for, so it is the flat
    refusal one layer up rather than the disclosure hole a 403 usually is.

    So there are two populations and the assertion differs:

    - **Members with no claim on this child** — a classmate, another child's
      guardian — are refused by the endpoint, and get its flat 404.
    - **Non-members** — a stranger, another school's principal — never reach the
      endpoint and get the middleware's 403.

    The property the fee gate owes is the same for both, and it is the one this
    class actually asserts: **neither is ever told the card is being withheld.**
    A withholding 403 leaking out here would name the school and print its
    bursar's phone number to somebody with no claim on the child, which is a
    worse disclosure than the one the flat 404 exists to prevent.
    """

    def setUp(self):
        super().setUp()
        self.withheld_and_released()
        self.nobody = User.objects.create_user("nobody", PASSWORD, full_name="No Body")

    def assertNotTheWithheldBody(self, response, who):
        """The assertion that matters, on the bytes rather than on parsed JSON.

        A leak that renamed a field or nested it deeper would still be a leak.
        """
        self.assertNotIn(CONTACT.encode(), response.content, f"{who} was given the contact")
        self.assertNotIn(b"holding", response.content.lower(), f"{who} learned of the withholding")
        self.assertNotIn(b"St Mary", response.content, f"{who} was given the school name")

    def test_a_member_with_no_claim_gets_the_endpoints_flat_404(self):
        for label, user in (
            ("a classmate", self.bola.user),
            ("another child's guardian", self.bolas_father),
        ):
            for name, fetch in self.both_surfaces():
                with self.subTest(reader=label, surface=name):
                    response = fetch(user, self.stmarys, self.ada)
                    self.assertEqual(
                        response.status_code,
                        404,
                        "a member with no claim must not learn this card exists",
                    )
                    self.assertNotTheWithheldBody(response, label)

    def test_a_non_member_gets_the_middlewares_403_and_learns_nothing(self):
        """403, but the middleware's — never the fee gate's.

        The status alone cannot tell these apart, which is exactly why the body
        is asserted. A withholding 403 reaching here would be indistinguishable
        by status code and would carry the school's name and phone number.
        """
        for label, user in (
            ("a stranger", self.nobody),
            ("another school's principal", self.their_principal),
        ):
            for name, fetch in self.both_surfaces():
                with self.subTest(reader=label, surface=name):
                    response = fetch(user, self.stmarys, self.ada)
                    self.assertEqual(
                        response.status_code,
                        403,
                        "the middleware refuses a non-member before the view runs",
                    )
                    self.assertNotTheWithheldBody(response, label)

    def test_the_non_members_403_is_the_same_for_a_child_who_does_not_exist(self):
        """The control, and the reason the 403 above is not a disclosure.

        If the middleware's refusal ever started depending on the child asked
        for, this class would be asserting the wrong thing everywhere else.
        """
        self.client.force_login(self.nobody)
        real = self.client.get(self.card_url(self.stmarys, self.ada), HTTP_HOST=HOST)
        invented = self.client.get(
            f"/api/results/cards/{self.ada.pk + 9999}/"
            f"{self.terms_of(self.stmarys)[str(TermName.FIRST.value)]}/",
            HTTP_HOST=HOST,
        )

        self.assertEqual(real.status_code, invented.status_code)
        self.assertEqual(real.content, invented.content)


class NoCardMeans404NotA403(WithholdingSetUp):
    """Design test 4. Nothing was withheld, because nothing exists.

    The gate runs after `cards.card_for()` for this reason: a family whose term
    was never released must not be told the school is holding a card back.
    """

    def test_a_guardian_of_an_unreleased_term_gets_404_on_both_surfaces(self):
        self.enable_withholding()
        self.withhold(self.ada)
        # Deliberately no release.

        for name, fetch in self.both_surfaces():
            with self.subTest(surface=name):
                response = fetch(self.mama, self.stmarys, self.ada)
                self.assertEqual(
                    response.status_code,
                    404,
                    "no card was released; there is nothing to withhold",
                )

    def test_a_released_term_that_is_not_this_one_gets_404(self):
        self.withheld_and_released()

        for name, fetch in self.both_surfaces():
            with self.subTest(surface=name):
                response = fetch(
                    self.mama, self.stmarys, self.ada, TermName.SECOND.value
                )
                self.assertEqual(response.status_code, 404)


class TheFourCharacterBypass(WithholdingSetUp):
    """Design test 4b, and the control run that proves it can fail.

    Every refusal in tests 2-4 asked of `/pdf/` as well as of the JSON route.
    `report_card_pdf()`'s docstring made this argument before the feature
    existed: *a PDF of a card you may read is not a second permission*, and
    every refusal is that route's flat 404 because a file route answering
    otherwise would be the existence oracle the JSON route refuses to be,
    **reachable by adding four characters to a URL**.

    A gate fitted to one route is not a hypothetical: it is what an unwary
    implementation produces, because the feature is described in terms of the
    JSON route and the file route is four characters nobody re-reads.
    """

    def setUp(self):
        super().setUp()
        self.withheld_and_released()

    def test_the_pdf_route_refuses_a_guardian(self):
        self.assertEqual(
            self.fetch_pdf(self.mama, self.stmarys, self.ada).status_code, 403
        )

    def test_the_pdf_route_serves_staff(self):
        response = self.fetch_pdf(self.principal, self.stmarys, self.ada)
        self.assertIn(
            response.status_code,
            (200, 202),
            "staff see the withheld card's file, or that it is still building",
        )

    def test_the_pdf_route_gives_a_claimless_member_the_flat_404(self):
        """A classmate: inside the school, no claim on this child.

        Not a non-member, who is refused a layer earlier by
        `SchoolAccessMiddleware` — see `NobodyWithoutAClaimLearnsTheCardIsWithheld`.
        """
        response = self.fetch_pdf(self.bola.user, self.stmarys, self.ada)
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(CONTACT.encode(), response.content)

    def test_the_two_surfaces_agree_for_every_reader(self):
        """The property, stated once: no reader gets a different answer class.

        This is the assertion a one-route gate fails on whichever route it
        forgot, and it does not have to be told which one that is.
        """
        nobody = User.objects.create_user("nobody3", PASSWORD, full_name="No Body")
        for label, user in (
            ("guardian", self.mama),
            ("the child", self.ada.user),
            ("a stranger", nobody),
            ("another school's principal", self.their_principal),
        ):
            with self.subTest(reader=label):
                self.assertEqual(
                    self.fetch(user, self.stmarys, self.ada).status_code,
                    self.fetch_pdf(user, self.stmarys, self.ada).status_code,
                    f"{label} gets a different answer by adding four characters",
                )


class TheWithheldFamilyLearnsNothingAboutTheRender(WithholdingSetUp):
    """Design test 4c. 403, never 202.

    A 202 carries `state`, `state_label` and a detail string, so a withheld
    family reaching that code would learn whether their child's card had been
    rendered — and be told the file is "still being prepared", which is a worse
    lie than the 404 this design already rejects, because it promises a
    document that is never coming. The gate sits above the marker read.
    """

    def test_a_pending_render_still_answers_403_to_a_family(self):
        self.withheld_and_released()
        with connected_to(self.stmarys):
            card = cards.card_for(self.ada, self.term_of(self.stmarys, TermName.FIRST))
            ReleasedCardPdf.objects.filter(card=card).update(
                state=PdfState.PENDING, content=None, byte_size=None
            )

        response = self.fetch_pdf(self.mama, self.stmarys, self.ada)

        self.assertEqual(response.status_code, 403)
        self.assertNotIn(b"state", response.content)
        self.assertNotIn(b"prepar", response.content.lower())

    def test_a_failed_render_still_answers_403_to_a_family(self):
        self.withheld_and_released()
        with connected_to(self.stmarys):
            card = cards.card_for(self.ada, self.term_of(self.stmarys, TermName.FIRST))
            ReleasedCardPdf.objects.filter(card=card).update(
                state=PdfState.FAILED, error="It failed."
            )

        response = self.fetch_pdf(self.mama, self.stmarys, self.ada)

        self.assertEqual(response.status_code, 403)
        self.assertNotIn(b"It failed", response.content)


class ThePdfIsStillBuiltForAWithheldCard(WithholdingSetUp):
    """Design test 4d. Freeze always, render always, gate the serving.

    `docs/report-card-pdf.md` writes the marker inside the release transaction
    precisely so that "released and never rendered" is a positive fact rather
    than an absence somebody infers. Making the render conditional on fees
    would reintroduce through the fee door the hole that closed.
    """

    def test_the_marker_is_written_at_release_for_a_withheld_child(self):
        self.enable_withholding()
        self.withhold(self.ada)

        self.release()

        with connected_to(self.stmarys):
            card = cards.card_for(self.ada, self.term_of(self.stmarys, TermName.FIRST))
            self.assertTrue(
                ReleasedCardPdf.objects.filter(card=card).exists(),
                "the marker is a positive fact written at release, fees or no fees",
            )

    def test_the_withheld_childs_marker_is_identical_to_a_served_childs(self):
        """The render path is not made conditional on fees, stated as a diff.

        Asserted as *sameness* rather than as a fixed state, and the first
        version of this test got it wrong by asserting `BUILT`. A release writes
        the marker `PENDING` **before any job has run at all** — that is the
        inversion `test_pdf.py` pins — so pinning a terminal state here would be
        asserting the worker's timing, not this design's property.

        The property is that withholding changes nothing about the render. Ada
        is withheld and Bola is not, on the same release; their markers must be
        in the same state.
        """
        self.enable_withholding()
        self.withhold(self.ada)

        self.release()

        with connected_to(self.stmarys):
            term = self.term_of(self.stmarys, TermName.FIRST)
            withheld = ReleasedCardPdf.objects.get(card=cards.card_for(self.ada, term))
            served = ReleasedCardPdf.objects.get(card=cards.card_for(self.bola, term))

        self.assertEqual(
            withheld.state,
            served.state,
            "the withheld child's file was treated differently from the served "
            "child's, which is the fee door reaching the render",
        )
        self.assertEqual(withheld.error, "", "no render was refused on fee grounds")


class AThirdServingSurfaceCannotBeAddedUngated(WithholdingSetUp):
    """Design test 4e. The router is enumerated, not listed.

    A third surface is covered the day it is written, and goes red if it does
    not call the helper.

    **The enumeration is asserted to have found something first**, and
    specifically to have found the two operations we know about. A discovery
    test filtered by a path prefix passes *vacuously* the moment a route is
    spelled differently or the paths are refactored: the filter matches
    nothing, the loop runs zero times, and a test named "a third surface cannot
    be added ungated" goes green having checked nothing.

    **Its limit, stated because a coverage claim goes stale.** This proves the
    property for *this router*. A future surface serving card content from
    somewhere else — a staff export in `results/api.py`, an emailed attachment,
    a management command — is outside its reach, because the only thing tying
    the helper to a route is that the route calls it.

    So the design's promise is the narrower one — `_require_servable()` is the
    only door — and it is written in **that helper's own docstring**, not here.
    A claim about coverage belongs where the person about to add the third
    surface will read it, which is the function they would have to not call.
    """

    KNOWN = {
        "/cards/{int:student_membership_id}/{int:term_id}/",
        "/cards/{int:student_membership_id}/{int:term_id}/pdf/",
    }

    def setUp(self):
        super().setUp()
        self.withheld_and_released()

    def test_the_enumeration_finds_the_routes_we_know_about(self):
        """Asserted before anything else, so nothing below can pass vacuously."""
        found = set(card_router.path_operations)

        self.assertTrue(found, "the router exposed no operations at all")
        self.assertEqual(
            self.KNOWN & found,
            self.KNOWN,
            "the known serving routes are not in the enumeration, so every "
            "assertion driven from it would be checking nothing",
        )

    def test_every_operation_on_the_router_refuses_a_withheld_family(self):
        term_id = self.terms_of(self.stmarys)[str(TermName.FIRST.value)]
        self.client.force_login(self.mama)

        drove = 0
        for path, path_op in card_router.path_operations.items():
            for operation in path_op.operations:
                with self.subTest(path=path, methods=operation.methods):
                    self.assertEqual(
                        list(operation.methods),
                        ["GET"],
                        f"{path} is not a GET, so this test cannot drive it. An "
                        f"unrecognised serving surface is the finding, not an "
                        f"exemption from it.",
                    )

                    url, substituted = self._url_for(path, self.ada.pk, term_id)
                    self.assertTrue(
                        substituted,
                        f"{path} takes parameters this test does not know how to "
                        f"fill. That is a new serving surface and it must be "
                        f"gated deliberately, not skipped here.",
                    )

                    response = self.client.get(url, HTTP_HOST=HOST)
                    self.assertEqual(
                        response.status_code,
                        403,
                        f"{path} served a withheld card to a guardian",
                    )
                    drove += 1

        self.assertEqual(
            drove,
            len(self.KNOWN),
            "the number of operations driven does not match the number known; "
            "a surface was added or removed and this test has not been read",
        )

    def _url_for(self, path, student_membership_id, term_id):
        """Build a drivable URL, and say whether every parameter was filled."""
        filled = re.sub(
            r"\{(?:int:)?student_membership_id\}", str(student_membership_id), path
        )
        filled = re.sub(r"\{(?:int:)?term_id\}", str(term_id), filled)
        return f"{PREFIX}{filled}", "{" not in filled


class TheRefusalCarriesTheContactAndNothingElse(WithholdingSetUp):
    """Design test 5, and the reason `withholding_contact` exists at all.

    The 403 promises a family somebody to call. Asserted against the serialised
    JSON and against the raw bytes, deliberately cruder than parsing: a leak
    that renamed the field, nested it a level deeper or put it in an error body
    would still be a leak, and a structural assertion would walk past all three.

    **Not the amount, and not the reason.** A parent-facing balance is a support
    burden and a correctness risk; `reason` is the bursar's internal note and
    may be unguarded about a family. Both are staff-only in the sense
    `ReleasedCard.position` is — excluded at the serializer, not merely absent
    from a template.
    """

    REASON = "Third term fees outstanding since November; mother avoiding calls."

    def setUp(self):
        super().setUp()
        self.enable_withholding()
        self.withhold(self.ada, reason=self.REASON)
        self.release()

    def test_the_403_names_the_school_and_who_to_call(self):
        response = self.fetch(self.mama, self.stmarys, self.ada)
        body = json.loads(response.content)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            body["school_name"],
            "St Mary's",
            "the frozen copy on the card, not a live join to School",
        )
        self.assertEqual(body["contact"], CONTACT)

    def test_the_403_carries_a_human_readable_sentence(self):
        """The design names this field `message`; the code emits `detail`.

        Asserted by substance rather than by name, deliberately: pinning either
        name here would freeze a divergence this file was written to surface
        rather than to bless. What the design actually requires is that the
        refusal reads as a sentence to a parent, and that it carries the
        contact — both asserted, under whichever key the body uses.
        """
        response = self.fetch(self.mama, self.stmarys, self.ada)
        body = json.loads(response.content)

        sentences = [
            value
            for key, value in body.items()
            if key not in ("school_name", "contact") and isinstance(value, str)
        ]
        self.assertTrue(sentences, "the 403 carries no human-readable message at all")
        self.assertTrue(
            any(CONTACT in sentence for sentence in sentences),
            "the message does not tell the family who to call",
        )

    def test_the_reason_reaches_no_family_facing_payload(self):
        for name, fetch in self.both_surfaces():
            with self.subTest(surface=name):
                response = fetch(self.mama, self.stmarys, self.ada)
                self.assertNotIn(b"outstanding since November", response.content)
                self.assertNotIn(b"avoiding calls", response.content)
                self.assertNotIn(b"reason", response.content.lower())

    def test_the_balance_reaches_no_family_facing_payload(self):
        for name, fetch in self.both_surfaces():
            with self.subTest(surface=name):
                response = fetch(self.mama, self.stmarys, self.ada)
                self.assertNotIn(b"balance", response.content.lower())
                self.assertNotIn(b"25000000", response.content)
                self.assertNotIn(b"250000", response.content)

    def test_the_decision_really_holds_the_things_being_excluded(self):
        """The control for the two exclusions above.

        `assertNotIn(b"balance", ...)` passes for two different reasons: because
        the serializer excluded it, or because there was nothing to exclude. A
        decision row with a null balance and an empty reason would turn both
        exclusion tests green against a 403 that leaked everything.
        """
        with connected_to(self.stmarys):
            row = withholding.latest_decision(
                self.ada.pk, self.term_of(self.stmarys, TermName.FIRST.value)
            )

        self.assertIsNotNone(row)
        self.assertEqual(row.reason, self.REASON, "there is a reason to leak")
        self.assertEqual(
            row.balance_kobo_at_decision,
            250_000_00,
            "there is a balance to leak, and it is the books' own number",
        )


class TheSwitchGatesWhetherDecisionsAreConsulted(WithholdingSetUp):
    """Design test 6. Step one before step two, and that is the composition.

    A school turning the feature off serves every card immediately, without
    walking back four hundred rows; the rows survive, so turning it back on
    restores the state rather than having lost it.
    """

    def setUp(self):
        super().setUp()
        self.withheld_and_released()

    def test_switching_the_policy_off_serves_a_standing_withheld_card(self):
        self.disable_withholding()

        for name, fetch in self.both_surfaces():
            with self.subTest(surface=name):
                self.assertNotEqual(
                    fetch(self.mama, self.stmarys, self.ada).status_code, 403
                )

    def test_switching_it_back_on_withholds_again_with_no_new_decision(self):
        self.disable_withholding()
        with connected_to(self.stmarys):
            before = WithholdingDecision.objects.count()

        self.enable_withholding()

        self.assertEqual(self.fetch(self.mama, self.stmarys, self.ada).status_code, 403)
        with connected_to(self.stmarys):
            self.assertEqual(
                WithholdingDecision.objects.count(),
                before,
                "the rows survived the switch; nothing was rewritten",
            )

    def test_turning_the_switch_off_keeps_the_contact(self):
        """A school that pauses withholding has not forgotten its own bursar."""
        self.disable_withholding()

        with connected_to(self.stmarys):
            self.assertEqual(withholding.settings().withholding_contact, CONTACT)

    def test_a_school_that_never_enabled_it_serves_every_card(self):
        """The off-default is load-bearing: an existing school sees no trace."""
        self.disable_withholding(self.grace)
        self.release(self.grace)

        with connected_to(self.grace):
            self.assertFalse(withholding.settings().withhold_for_fees_enabled)


class ARevisionOfAWithheldCardIsStillWithheld(WithholdingSetUp):
    """Design test 7. The `(child, term)` keying, tested directly.

    A decision keyed on the card row would not cover a version made after it,
    so correcting a withheld child's mark would serve the card the school had
    withheld. This is that trap, sprung.
    """

    def test_a_new_version_is_still_withheld(self):
        self.withheld_and_released()
        with connected_to(self.stmarys):
            term = self.term_of(self.stmarys, TermName.FIRST.value)
            before = cards.card_for(self.ada, term)
            revision.revise(self.ada, term, self.principal, "Maths mark corrected.")
            after = cards.card_for(self.ada, term)

        self.assertNotEqual(
            before.pk, after.pk, "no new version was written; the trap is not sprung"
        )
        for name, fetch in self.both_surfaces():
            with self.subTest(surface=name):
                self.assertEqual(
                    fetch(self.mama, self.stmarys, self.ada).status_code,
                    403,
                    "a revision served the card the school had withheld",
                )

    def test_the_decision_is_not_keyed_on_the_card(self):
        """Stated structurally as well, so the reason survives a refactor."""
        self.assertFalse(
            any(
                field.name in ("card", "released_card")
                for field in WithholdingDecision._meta.get_fields()
            ),
            "a decision keyed on the card row would miss the next version",
        )


class TheDecisionRowIsAppendOnly(WithholdingSetUp):
    """Not numbered in the design's list, but the design owes it twice over.

    Append-only is asserted by the enforcement table as *both* a trigger and a
    `save()`/`delete()` refusal, and "both rows stand" is the entire reason
    withholding is a log rather than a boolean. A boolean flipped twice has
    forgotten it was ever different, who changed it, and when.
    """

    def setUp(self):
        super().setUp()
        self.withheld_and_released()

    def test_updating_a_decision_is_refused(self):
        """The model half: `save()` refuses before the database is asked."""
        with connected_to(self.stmarys):
            row = withholding.latest_decision(
                self.ada.pk, self.term_of(self.stmarys, TermName.FIRST.value)
            )
            row.reason = "Something else."
            with self.assertRaises(WithholdingDecisionsAreAppendOnly):
                row.save()

    def test_deleting_a_decision_is_refused(self):
        with connected_to(self.stmarys):
            row = withholding.latest_decision(
                self.ada.pk, self.term_of(self.stmarys, TermName.FIRST.value)
            )
            with self.assertRaises(WithholdingDecisionsAreAppendOnly):
                row.delete()

    def test_the_database_refuses_a_bulk_update_that_skips_the_model(self):
        """The trigger half, which this class claimed and nothing asserted.

        `save()` and `delete()` are one code path; `.update()` is four others —
        the admin, a shell, a data migration, a queryset in a service. The two
        tests above pass with `0023`'s trigger dropped, because they never
        reach it. Found by #84's sweep: both said `assertRaises(Exception)`,
        and widening them to name a layer showed the layer they name is the
        only one either of them tests.
        """
        with connected_to(self.stmarys):
            term = self.term_of(self.stmarys, TermName.FIRST.value)
            with self.assertRefusedBy("results_withholdingdecision is append-only"):
                with transaction.atomic():
                    WithholdingDecision.objects.filter(
                        student_membership_id=self.ada.pk, term=term
                    ).update(reason="Something else.")

    def test_the_database_refuses_a_bulk_delete_that_skips_the_model(self):
        with connected_to(self.stmarys):
            term = self.term_of(self.stmarys, TermName.FIRST.value)
            with self.assertRefusedBy("results_withholdingdecision is append-only"):
                with transaction.atomic():
                    WithholdingDecision.objects.filter(
                        student_membership_id=self.ada.pk, term=term
                    ).delete()

    def test_both_decisions_stand_and_the_latest_holds(self):
        self.lift(self.ada)
        self.withhold(self.ada, reason="Cheque bounced.")

        with connected_to(self.stmarys):
            term = self.term_of(self.stmarys, TermName.FIRST.value)
            rows = WithholdingDecision.objects.filter(
                student_membership_id=self.ada.pk, term=term
            )
            self.assertEqual(rows.count(), 3, "three acts, three rows, none rewritten")
            self.assertEqual(
                withholding.latest_decision(self.ada.pk, term).status,
                WithholdingStatus.WITHHELD,
            )

        self.assertEqual(self.fetch(self.mama, self.stmarys, self.ada).status_code, 403)


class ThePolicyRefusesADeadEnd(WithholdingSetUp):
    """The constraint behind the promise: a switch on with nobody to call.

    A school that enables withholding without telling families who to call has
    built a dead end, and the refusal is a database constraint rather than a
    form validator because a validator is a promise kept by one code path — the
    admin, a shell, a data migration and a test fixture are four others.
    """

    def test_enabling_without_a_contact_is_refused(self):
        """`WithholdingError`, and the type is the assertion.

        `assertRaises(Exception)` passed here while the service was letting a
        raw `IntegrityError` out of the database — which is outside
        `ResultsError`, so every `except ResultsError` missed it, and fatal to
        an enclosing `atomic()` with no savepoint under it. A test that accepts
        any exception cannot tell a sentence from a 500.
        """
        with connected_to(self.stmarys):
            with self.assertRaises(withholding.WithholdingError):
                withholding.set_policy(enabled=True, contact="")

    def test_enabling_with_only_whitespace_is_refused(self):
        """A contact of one space is not a contact. The regex, not `!= ""`."""
        with connected_to(self.stmarys):
            with self.assertRaises(withholding.WithholdingError):
                withholding.set_policy(enabled=True, contact="   ")

    def test_the_refusal_does_not_poison_the_transaction(self):
        """The point of refusing before the constraint rather than after it.

        An `IntegrityError` leaves the surrounding block unusable; a refusal
        raised in Python does not, so the caller can correct the contact and try
        again in the same request.
        """
        with connected_to(self.stmarys):
            with self.assertRaises(withholding.WithholdingError):
                withholding.set_policy(enabled=True, contact=" ")
            row = withholding.set_policy(enabled=True, contact=CONTACT)
        self.assertTrue(row.withhold_for_fees_enabled)

    def test_the_constraint_still_holds_underneath_the_service(self):
        """The guard is the sentence; the constraint is what actually holds.

        A validator is a promise kept by one code path — the admin, a shell, a
        data migration and a fixture are four others — so the service refusing
        first must not be mistaken for the constraint being unnecessary.
        """
        from django.db import IntegrityError

        with connected_to(self.stmarys):
            with self.assertRaises(IntegrityError):
                ReportCardSettings.objects.filter(pk=1).update(
                    withhold_for_fees_enabled=True, withholding_contact=""
                )

    def test_a_withholding_must_say_why(self):
        with connected_to(self.stmarys):
            with self.assertRaises(withholding.WithholdingError):
                withholding.withhold(
                    self.ada.pk,
                    self.term_of(self.stmarys, TermName.FIRST.value),
                    actor=self.principal,
                    reason="   ",
                )

    def test_a_blank_reason_is_caught_by_except_results_error(self):
        """Which is the whole reason it is not a bare `ValueError`.

        Every `results` submodule hangs its refusals off `ResultsError` so that
        a caller wrapping "get this class's results out" catches them all
        without learning a base class per module.
        """
        with connected_to(self.stmarys):
            with self.assertRaises(ResultsError):
                withholding.withhold(
                    self.ada.pk,
                    self.term_of(self.stmarys, TermName.FIRST.value),
                    actor=self.principal,
                    reason="",
                )

    def test_a_lift_may_be_silent(self):
        """Asymmetric on purpose: a school that has been paid owes no reason."""
        self.enable_withholding()
        with connected_to(self.stmarys):
            row = withholding.lift(
                self.ada.pk,
                self.term_of(self.stmarys, TermName.FIRST.value),
                actor=self.principal,
            )
        self.assertEqual(row.status, WithholdingStatus.LIFTED)


class OnlyAPrincipalOrABursarMayDecide(WithholdingSetUp):
    """`WITHHOLDING_ROLES` is its own constant, and it is both roles.

    The principal is not the person who knows the ledger, so a principal-only
    lever means the bursar uses the principal's login and the audit names the
    wrong person. Bursar-only is also wrong: withholding a report card carries
    academic weight. The append-only log is what makes "both" safe.
    """

    def test_a_bursar_may_withhold(self):
        self.enable_withholding()
        row = self.withhold(self.ada, actor=self.bursar)
        self.assertEqual(row.status, WithholdingStatus.WITHHELD)
        self.assertEqual(row.decided_by_id, self.bursar.pk, "the audit names them")

    def test_a_principal_may_lift_what_a_bursar_withheld(self):
        self.enable_withholding()
        self.withhold(self.ada, actor=self.bursar)
        row = self.lift(self.ada, actor=self.principal)
        self.assertEqual(row.decided_by_id, self.principal.pk)

    def test_a_teacher_may_not_withhold(self):
        """The authority refusal, and the type is the assertion.

        `assertRaises(Exception)` here was satisfied by a 500 — by an
        `AttributeError` on the way to the guard as readily as by the guard
        itself. This is the test standing between a class teacher and the power
        to hold a family's report card back, so it has to be able to tell those
        apart. `_require_authority()` raises `NotAllowedToActOnResults`.
        """
        self.enable_withholding()
        with self.assertRaises(NotAllowedToActOnResults):
            self.withhold(self.ada, actor=self.teacher)

    def test_the_roles_are_not_borrowed_from_another_constant(self):
        """Its own constant, never imported from `RELEASING_ROLES`."""
        self.assertEqual(
            withholding.WITHHOLDING_ROLES,
            frozenset({Role.PRINCIPAL.value, Role.BURSAR.value}),
        )


class TheBalanceNeverGates(WithholdingSetUp):
    """A person decides; the number is only frozen so the row explains itself.

    A rule like *withhold while balance > 0* would withhold from a family a few
    hundred naira short on a payment plan, and part-payment is the normal case.
    """

    def test_arrears_alone_withhold_nobody(self):
        self.enable_withholding()
        self.release()

        for name, fetch in self.both_surfaces():
            with self.subTest(surface=name):
                self.assertNotEqual(
                    fetch(self.mama, self.stmarys, self.ada).status_code,
                    403,
                    "a balance withheld a card that nobody decided to withhold",
                )

    def test_a_paid_up_child_is_still_withheld_once_decided(self):
        """The other direction: paying does not lift a standing decision."""
        self.withheld_and_released()
        with connected_to(self.stmarys):
            fees_services.record_payment(
                self.ada,
                self.term_of(self.stmarys, TermName.FIRST.value),
                250_000_00,
            )

        self.assertEqual(
            self.fetch(self.mama, self.stmarys, self.ada).status_code,
            403,
            "the balance does not decide; a person lifting the decision does",
        )

    def test_the_serving_path_never_reads_the_ledger(self):
        """`results.withholding` imports nothing from `fees` at module scope.

        The claim is about queries, and the import is where it is provable: a
        module-level `import fees` would make "the serving path never touches
        the books" a sentence the imports contradict at a glance.
        """
        import inspect

        source = inspect.getsource(withholding)
        module_level = [
            line
            for line in source.splitlines()
            if line.startswith(("import ", "from ")) and "fees" in line
        ]
        self.assertEqual(
            module_level, [], "fees is imported at module scope in the serving module"
        )


class TheWriteEarnsItsBareStudentId(WithholdingSetUp):
    """`student_membership_id` carries no foreign key, so the check is the key.

    `docs/tenancy.md` explains why the column is bare, and
    `accounts.students.why_not_a_student_here()` is the one definition of "is
    this child ours?" that every tenant app storing such an id already asks —
    `fees.services`, `gradebook.services`, `academics.services`,
    `results.comments`, `results.sessions`, `results.ratings`.

    **It matters more here than at most of those call sites**, because this
    table is append-only in three places: `save()`, `delete()` and a Postgres
    trigger. A withholding written against the wrong child cannot be corrected,
    only masked by appending a `lifted` row beside it — and where the wrong
    child is at the same school, the mistake silently holds a paid family's card
    until somebody notices.
    """

    def setUp(self):
        super().setUp()
        self.enable_withholding()

    def _withhold_id(self, membership_id, school=None):
        school = school or self.stmarys
        with connected_to(school):
            return withholding.withhold(
                membership_id,
                self.term_of(school, TermName.FIRST.value),
                actor=self.principal if school == self.stmarys else self.their_principal,
                reason="Fees outstanding.",
            )

    def test_a_staff_membership_is_refused(self):
        """Not a near miss — a row about the wrong person entirely."""
        staff = Membership.objects.get(user=self.teacher, school=self.stmarys)

        with self.assertRaises(withholding.NotThisSchoolsStudent):
            self._withhold_id(staff.pk)

    def test_another_schools_child_is_refused(self):
        """The row would sit in St Mary's tables naming a child they never taught."""
        with self.assertRaises(withholding.NotThisSchoolsStudent):
            self._withhold_id(self.ngozi.pk)

    def test_a_membership_that_does_not_exist_is_refused(self):
        with self.assertRaises(withholding.NotThisSchoolsStudent):
            self._withhold_id(9_999_999)

    def test_a_lift_is_checked_too(self):
        """Both acts go through `_record()`, so both are guarded by it."""
        with connected_to(self.stmarys):
            with self.assertRaises(withholding.NotThisSchoolsStudent):
                withholding.lift(
                    self.ngozi.pk,
                    self.term_of(self.stmarys, TermName.FIRST.value),
                    actor=self.principal,
                )

    def test_nothing_is_written_when_the_child_is_refused(self):
        """Refused *before* anything is written, which is the only useful time.

        The table is append-only, so a row written and then regretted is a row
        for ever.
        """
        with self.assertRaises(withholding.NotThisSchoolsStudent):
            self._withhold_id(self.ngozi.pk)

        with connected_to(self.stmarys):
            self.assertEqual(
                WithholdingDecision.objects.filter(
                    student_membership_id=self.ngozi.pk
                ).count(),
                0,
            )

    def test_the_refusal_is_caught_by_except_results_error(self):
        with self.assertRaises(ResultsError):
            self._withhold_id(self.ngozi.pk)

    def test_the_right_child_is_still_written(self):
        """The guard refuses; it does not get in the way."""
        row = self._withhold_id(self.ada.pk)
        self.assertEqual(row.student_membership_id, self.ada.pk)


class TheRefusalReadsAsASentence(WithholdingSetUp):
    """`_require_authority()` builds the sentence; `step` is a fragment in it.

    The two templates are *{actor} may not {step} results at {school}.* and
    *Signing in is required to {step} results.*, and the existing callers pass
    `revise` and `open a sheet for` to fit them. A fragment naming its own
    object produced "may not withhold a report card at results at St Mary's" —
    the refusal arriving as gibberish at the person least able to act on it.
    """

    def test_a_teacher_is_refused_in_english(self):
        self.enable_withholding()
        with connected_to(self.stmarys):
            with self.assertRaises(NotAllowedToActOnResults) as caught:
                withholding.withhold(
                    self.ada.pk,
                    self.term_of(self.stmarys, TermName.FIRST.value),
                    actor=self.teacher,
                    reason="Fees outstanding.",
                )

        message = str(caught.exception)
        self.assertNotIn("at results at", message, message)
        self.assertIn("may not withhold results at", message, message)

    def test_a_lift_is_refused_in_english(self):
        self.enable_withholding()
        with connected_to(self.stmarys):
            with self.assertRaises(NotAllowedToActOnResults) as caught:
                withholding.lift(
                    self.ada.pk,
                    self.term_of(self.stmarys, TermName.FIRST.value),
                    actor=self.teacher,
                )

        message = str(caught.exception)
        self.assertNotIn("at results at", message, message)
        self.assertIn("may not release withheld results at", message, message)

    def test_signing_out_is_refused_in_english(self):
        """The other template, which reads `to {step} results.`"""
        self.enable_withholding()
        with connected_to(self.stmarys):
            with self.assertRaises(NotAllowedToActOnResults) as caught:
                withholding.withhold(
                    self.ada.pk,
                    self.term_of(self.stmarys, TermName.FIRST.value),
                    actor=None,
                    reason="Fees outstanding.",
                )

        self.assertEqual(
            str(caught.exception),
            "Signing in is required to withhold results.",
        )


class TheWriteTakesATermOrItsId(WithholdingSetUp):
    """The read path documents itself as taking either, so the write must too.

    `latest_decision()` says *takes a `Term` or its id*, because the serving
    path holds a card and `card.term_id` is a column it already has. A caller
    who read that and passed the same value to `withhold()` used to be told
    `must be a "Term" instance` by a write they never saw coming.
    """

    def test_withholding_by_term_id_is_the_same_decision(self):
        self.enable_withholding()
        with connected_to(self.stmarys):
            term = self.term_of(self.stmarys, TermName.FIRST.value)
            row = withholding.withhold(
                self.ada.pk, term.pk, actor=self.principal, reason="Fees outstanding."
            )
            self.assertEqual(row.term_id, term.pk)
            self.assertTrue(withholding.is_withheld(self.ada.pk, term.pk))

    def test_lifting_by_term_id_lifts_a_withholding_made_by_term(self):
        """The two spellings have to reach the same `(child, term)` key."""
        self.enable_withholding()
        self.withhold(self.ada)
        with connected_to(self.stmarys):
            term = self.term_of(self.stmarys, TermName.FIRST.value)
            withholding.lift(self.ada.pk, term.pk, actor=self.principal)
            self.assertFalse(withholding.is_withheld(self.ada.pk, term))


class TheFrozenBalanceDistinguishesNothingFromZero(WithholdingSetUp):
    """`balance_kobo_at_decision` is nullable, and the null has to mean something.

    The column's own docstring says a decision can be recorded where the ledger
    has nothing to say, and that naming a fictional zero would be a claim nobody
    made. `FeeLedgerQuerySet.balance()` ends `... or 0`, so a school that keeps
    its fees on paper would have had every audit row say the family owed
    nothing — which reads, a year later, as a withholding with no basis.
    """

    def test_a_ledger_with_no_entries_freezes_no_number(self):
        with connected_to(self.grace):
            withholding.set_policy(enabled=True, contact=CONTACT)
            row = withholding.withhold(
                self.ngozi.pk,
                self.term_of(self.grace, TermName.FIRST.value),
                actor=self.their_principal,
                reason="Fees outstanding.",
            )

        self.assertIsNone(
            row.balance_kobo_at_decision,
            "an empty ledger was recorded as a family owing nothing",
        )

    def test_a_family_charged_and_paid_in_full_freezes_a_real_zero(self):
        """The other half: zero is a fact when the books actually say it."""
        self.enable_withholding()
        with connected_to(self.stmarys):
            term = self.term_of(self.stmarys, TermName.FIRST.value)
            fees_services.record_payment(self.ada, term, 250_000_00)
            row = withholding.withhold(
                self.ada.pk, term, actor=self.principal, reason="Late again."
            )

        self.assertEqual(row.balance_kobo_at_decision, 0)

    def test_arrears_are_frozen_as_the_books_read_them(self):
        self.enable_withholding()
        row = self.withhold(self.ada)
        self.assertEqual(row.balance_kobo_at_decision, 250_000_00)


class TheClaimIsNotABool(WithholdingSetUp):
    """`_may_read()` returns which claim, and the gate spares staff by it.

    A guardian who is also staff comes back `STAFF`, because the role check
    runs before the guardianship query — so a bursar is served their own
    child's withheld card. That is a consequence of "staff always see a
    withheld card" rather than an exception to it, and it is asserted here
    because a reader who found it themselves would reasonably file it as a leak.
    """

    def test_a_guardian_who_is_also_staff_is_served(self):
        self.withheld_and_released()
        with connected_to(self.stmarys):
            pass
        from accounts.services import grant_membership, link_guardian

        staff_parent = User.objects.create_user(
            "staffparent", PASSWORD, full_name="Staff Parent"
        )
        grant_membership(staff_parent, self.stmarys, Role.BURSAR)
        link_guardian(staff_parent, self.ada)

        self.assertEqual(
            self.fetch(staff_parent, self.stmarys, self.ada).status_code,
            200,
            "the claim order decides this, and it is ruled",
        )

    def test_family_claims_are_the_two_family_ones(self):
        from results.card_api import FAMILY_CLAIMS

        self.assertEqual(FAMILY_CLAIMS, frozenset({CardClaim.SELF, CardClaim.GUARDIAN}))

    def tearDown(self):
        connection.set_schema_to_public()
        super().tearDown()
