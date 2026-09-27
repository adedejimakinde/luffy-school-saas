"""The result checker: an admission number and a PIN open one card. D11.

`docs/messaging.md` D11, and correctness requirements 8, 9, 10 and 12.

Two schools in every test, and **Ada at St Mary's and Ngozi at Grace have the
same admission number, SM/001, on purpose**: an admission number means nothing
outside the school that issued it, and a checker that forgot the school would
open the wrong child's card rather than fail. Bola is SM/002 at St Mary's.

The card fixture is `ReportCardApiSetUp`'s, through `WithholdingSetUp`: Ada is
marked in two subjects and ranks first over Bola, so `position` really is on her
frozen card and its absence from the checker's answer is an exclusion rather
than an empty snapshot (`TheSnapshotReallyHoldsTheStaffOnlyNumbers` pins that).
"""

from datetime import timedelta

from django.db import connection, transaction
from django.test import override_settings
from django.utils import timezone

from academics.models import Term, TermName
from accounts.models import Membership, Role, SignInAttempts, SignInScope
from messaging.models import FakeMessage
from notices.models import Notice
from results import checker, pdf
from results import services as results_services
from results.models import CheckerPin, CheckerPinsAreAppendOnly
from schools.models import hash_token
from schools.tests.tenants import connected_to

from .test_card_api import HOST, THEIR_HOST
from .test_withholding import CONTACT, WithholdingSetUp

CHECK = "/api/results/check/"
ADA_NO = "SM/001"
BOLA_NO = "SM/002"
NGOZI_NO = "SM/001"

#: Where the tests' guesses come from, unless a test is about the address.
HERE = "10.0.0.1"


class CheckerSetUp(WithholdingSetUp):
    """Both schools released, with admission numbers. Slips are printed by the tests."""

    def setUp(self):
        super().setUp()
        Membership.objects.filter(pk=self.ada.pk).update(reference=ADA_NO)
        Membership.objects.filter(pk=self.bola.pk).update(reference=BOLA_NO)
        Membership.objects.filter(pk=self.ngozi.pk).update(reference=NGOZI_NO)
        self.sheet = self.release()
        self.their_sheet = self.release(self.grace)

    def slips(self, school=None, *, actor=None, number=None):
        school = school or self.stmarys
        sheet = self.sheet if school == self.stmarys else self.their_sheet
        with connected_to(school):
            return checker.print_slips(
                sheet,
                actor=actor or self.staff_of(school)[Role.PRINCIPAL],
                admission_number=number,
            )

    def pins(self, school=None, **kwargs):
        """`{child's name: raw PIN}` for one press."""
        return {slip.student_name: slip.pin for slip in self.slips(school, **kwargs).slips}

    def check(self, number, pin, *, host=HOST, address=HERE):
        self.client.logout()
        return self.client.post(
            CHECK,
            {"admission_number": number, "pin": pin},
            content_type="application/json",
            HTTP_HOST=host,
            REMOTE_ADDR=address,
        )

    def assertOpened(self, response, name):
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["student_name"], name)

    def assertNotOpened(self, response, who="the caller"):
        """The one refusal: its status and its exact bytes."""
        self.assertEqual(response.status_code, 404, f"{who}: {response.content!r}")
        self.assertEqual(response.json(), {"detail": checker.NOT_OPENED, "retry_after": None})

    def assertWaits(self, response, who="the caller"):
        self.assertEqual(response.status_code, 429, f"{who}: {response.content!r}")
        self.assertEqual(response.json()["detail"], checker.WAIT)
        self.assertGreater(response.json()["retry_after"], 0)


class PrintingSlipsTests(CheckerSetUp):
    """Minting: who may, for which class, and what is kept."""

    def test_each_child_gets_twelve_digits_printed_in_three_groups_of_four(self):
        slips = self.slips()

        self.assertEqual(
            sorted(slip.student_name for slip in slips.slips), ["Ada Obi", "Bola Eze"]
        )
        for slip in slips.slips:
            self.assertRegex(slip.pin, r"^\d{12}$")
            self.assertRegex(slip.printed_pin, r"^\d{4} \d{4} \d{4}$")
            self.assertEqual(slip.printed_pin.replace(" ", ""), slip.pin)
        self.assertNotEqual(slips.slips[0].pin, slips.slips[1].pin)

    def test_only_the_digest_is_kept(self):
        """No column anywhere in the row holds the PIN itself."""
        pins = self.pins()

        with connected_to(self.stmarys):
            rows = list(CheckerPin.objects.values())
        self.assertEqual(len(rows), 2)
        kept = repr(rows)
        for name, pin in pins.items():
            self.assertNotIn(pin, kept, f"{name}'s PIN is at rest")
        self.assertEqual(
            {row["pin_hash"] for row in rows}, {hash_token(pin) for pin in pins.values()}
        )

    def test_only_the_principal_or_an_administrator_prints_slips(self):
        for role in (Role.TEACHER, Role.VICE_PRINCIPAL_ACADEMIC):
            with self.subTest(role=role):
                with self.assertRaises(checker.NotAllowed):
                    self.slips(actor=self.staff[role])
        with self.assertRaises(checker.NotAllowed):
            self.slips(actor=self.bursar)
        with connected_to(self.stmarys):
            self.assertFalse(CheckerPin.objects.exists(), "a refused press minted a PIN")

        self.assertEqual(len(self.slips(actor=self.staff[Role.ADMIN]).slips), 2)

    def test_a_principal_prints_nothing_for_another_schools_class(self):
        """Authority is asked at the school whose schema this is, not the actor's."""
        with self.assertRaises(checker.NotAllowed):
            self.slips(self.grace, actor=self.principal)

    def test_a_class_not_yet_released_has_no_slips(self):
        with connected_to(self.stmarys):
            second = results_services.open_sheet(
                self.group_of(self.stmarys),
                self.term_of(self.stmarys, TermName.SECOND.value),
                self.principal,
            )
            with self.assertRaises(checker.NotReleased):
                checker.print_slips(second, actor=self.principal)
            self.assertFalse(CheckerPin.objects.exists())

    def test_a_second_press_prints_only_the_children_without_a_slip(self):
        first = self.pins()

        self.assertEqual(self.slips().slips, [], "the second press reprinted the class")
        self.assertOpened(self.check(ADA_NO, first["Ada Obi"]), "Ada Obi")

    def test_a_child_with_no_admission_number_is_named_and_gets_no_slip(self):
        Membership.objects.filter(pk=self.bola.pk).update(reference="")

        slips = self.slips()

        self.assertEqual([slip.student_name for slip in slips.slips], ["Ada Obi"])
        self.assertEqual(slips.without_a_number, ["Bola Eze"])
        html = pdf.slips_html(slips, "st-marys.testserver/check/")
        self.assertIn("No slip was printed for 1 child", html)
        self.assertIn("Bola Eze", html)

        # Given a number, the next press prints her, and only her.
        Membership.objects.filter(pk=self.bola.pk).update(reference=BOLA_NO)
        self.assertEqual([slip.student_name for slip in self.slips().slips], ["Bola Eze"])

    def test_a_lost_slip_is_replaced_and_the_old_pin_stops_opening(self):
        old = self.pins()["Ada Obi"]

        new = self.pins(number="sm/001")["Ada Obi"]

        self.assertNotEqual(old, new)
        self.assertNotOpened(self.check(ADA_NO, old), "the replaced slip")
        self.assertOpened(self.check(ADA_NO, new), "Ada Obi")

    def test_a_lost_slip_asked_for_by_a_number_nobody_here_has_is_refused(self):
        self.pins()
        with self.assertRaises(checker.NoSuchChild):
            self.slips(number="SM/999")

    def test_printing_sends_nothing(self):
        """Paper, never a message: D11. An absence, so there is no guard to control."""
        self.pins()
        self.pins(self.grace)

        self.assertEqual(FakeMessage.objects.count(), 0)
        for school in (self.stmarys, self.grace):
            with connected_to(school):
                self.assertEqual(Notice.objects.count(), 0)

    def test_the_slips_name_the_child_and_carry_nothing_off_the_card(self):
        slips = self.slips()

        html = pdf.slips_html(slips, "st-marys.testserver/check/")

        for slip in slips.slips:
            self.assertIn(slip.student_name, html)
            self.assertIn(slip.printed_pin, html)
        self.assertIn(ADA_NO, html)
        self.assertIn("st-marys.testserver/check/", html)
        # The PINs are random digits and can contain Ada's 88 by chance (it did,
        # on CI), so they come out before the page is searched for a mark.
        for slip in slips.slips:
            html = html.replace(slip.printed_pin, "")
        for card_content in ("Mathematics", "English", "88", "position", "average"):
            self.assertNotIn(card_content, html)


class ThePinsAreAppendOnlyTests(CheckerSetUp):
    def test_the_database_refuses_an_update_and_a_delete(self):
        self.pins()
        with connected_to(self.stmarys):
            pin = CheckerPin.objects.first()
            for statement in (
                "UPDATE results_checkerpin SET pin_hash = 'x' WHERE id = %s",
                "DELETE FROM results_checkerpin WHERE id = %s",
            ):
                with self.subTest(statement=statement.split()[0]):
                    with self.assertRefusedBy("results_checkerpin is append-only"):
                        with connection.cursor() as cursor, transaction.atomic():
                            cursor.execute(statement, [pin.pk])

    def test_the_model_refuses_before_the_database_is_asked(self):
        self.pins()
        with connected_to(self.stmarys):
            pin = CheckerPin.objects.first()
            with self.assertRaises(CheckerPinsAreAppendOnly):
                pin.save()
            with self.assertRaises(CheckerPinsAreAppendOnly):
                pin.delete()


class OpeningACardTests(CheckerSetUp):
    """Requirements 8 and 12: the family's payload, and one refusal for everything."""

    def setUp(self):
        super().setUp()
        self.ours = self.pins()
        self.ada_pin = self.ours["Ada Obi"]
        self.bola_pin = self.ours["Bola Eze"]

    def test_the_number_and_the_pin_open_the_card_the_family_page_serves(self):
        opened = self.check(ADA_NO, self.ada_pin)

        self.client.force_login(self.mama)
        served = self.client.get(self.card_url(self.stmarys, self.ada), HTTP_HOST=HOST)
        self.assertEqual(served.status_code, 200)
        self.assertEqual(opened.status_code, 200)
        self.assertEqual(opened.content, served.content)

    def test_the_answer_has_no_position_and_no_class_average(self):
        """#21's idiom: on the raw bytes, so a renamed or nested field still fails."""
        response = self.check(ADA_NO, self.ada_pin)

        self.assertOpened(response, "Ada Obi")
        for field in (b"position", b"class_average", b"roster_size"):
            self.assertNotIn(field, response.content)

    def test_the_pin_as_the_slip_prints_it_and_the_number_in_any_case(self):
        grouped = checker.printed(self.ada_pin)
        for number, pin in (
            (ADA_NO, grouped),
            ("sm/001", grouped.replace(" ", "-")),
            ("  SM/001 ", f" {self.ada_pin} "),
        ):
            with self.subTest(number=number, pin=pin):
                self.assertOpened(self.check(number, pin), "Ada Obi")

    def test_one_refusal_for_every_way_of_being_wrong(self):
        replaced = self.ada_pin
        current = self.pins(number=ADA_NO)["Ada Obi"]
        self.assertOpened(self.check(ADA_NO, current), "Ada Obi")

        failures = {
            "an unknown admission number": ("SM/999", current),
            "a wrong PIN": (ADA_NO, "000000000000"),
            "a replaced PIN": (ADA_NO, replaced),
            "another child's PIN": (ADA_NO, self.bola_pin),
            "a PIN too short": (ADA_NO, current[:11]),
            "nothing typed": ("", ""),
        }
        bodies = set()
        for case, (number, pin) in failures.items():
            with self.subTest(case=case):
                response = self.check(number, pin)
                self.assertNotOpened(response, case)
                bodies.add(response.content)
        self.assertEqual(len(bodies), 1, "two failures can be told apart")

    def test_another_childs_pin_opens_neither_child(self):
        self.assertNotOpened(self.check(ADA_NO, self.bola_pin))
        self.assertNotOpened(self.check(BOLA_NO, self.ada_pin))

    def test_the_pin_is_never_read_from_a_url(self):
        self.client.logout()
        response = self.client.get(
            CHECK, {"admission_number": ADA_NO, "pin": self.ada_pin}, HTTP_HOST=HOST
        )
        self.assertEqual(response.status_code, 405)

    def test_a_pin_stops_opening_once_the_next_session_has_begun(self):
        today = timezone.localdate()
        with connected_to(self.stmarys):
            next_term = Term.objects.create(
                session="2099/2100", name=TermName.FIRST.value,
                starts_on=today + timedelta(days=1), ends_on=today + timedelta(days=90),
            )
        self.assertOpened(self.check(ADA_NO, self.ada_pin), "Ada Obi")

        with connected_to(self.stmarys):
            Term.objects.filter(pk=next_term.pk).update(starts_on=today)
        self.assertNotOpened(self.check(ADA_NO, self.ada_pin), "a PIN from last session")


@override_settings(
    CHECKER_MAX_FAILURES_PER_ADMISSION_NUMBER=3, CHECKER_MAX_FAILURES_PER_ADDRESS=5
)
class WrongAnswersAreCountedNeverLockedTests(CheckerSetUp):
    """Requirement 12's second half: counted per number and per address, and it waits."""

    WRONG = "999999999999"

    def setUp(self):
        super().setUp()
        pins = self.pins()
        self.ada_pin, self.bola_pin = pins["Ada Obi"], pins["Bola Eze"]

    def guess(self, number, times, *, address_of=lambda i: f"10.0.1.{i}"):
        for i in range(times):
            self.assertNotOpened(self.check(number, self.WRONG, address=address_of(i)))

    def test_wrong_answers_make_the_number_wait_even_for_the_right_pin(self):
        """From three addresses, so it is the number's bucket that closes."""
        self.guess(ADA_NO, 3)

        self.assertWaits(self.check(ADA_NO, self.ada_pin, address="10.0.9.9"), "the right PIN")
        self.assertOpened(self.check(BOLA_NO, self.bola_pin, address="10.0.9.9"), "Bola Eze")

    def test_a_number_nobody_has_is_counted_as_typed(self):
        """Otherwise a wait would say which admission numbers exist."""
        self.guess("SM/999", 3)

        self.assertWaits(self.check("SM/999", self.WRONG, address="10.0.9.9"))

    def test_wrong_answers_make_the_address_wait(self):
        """Across five different numbers, so it is the address's bucket that closes."""
        for i in range(5):
            self.assertNotOpened(self.check(f"XX/{i}", self.WRONG, address="10.0.2.2"))

        self.assertWaits(self.check(ADA_NO, self.ada_pin, address="10.0.2.2"), "that machine")
        self.assertOpened(self.check(ADA_NO, self.ada_pin, address="10.0.3.3"), "Ada Obi")

    def test_the_wait_ends_by_itself(self):
        self.guess(ADA_NO, 3)
        self.assertWaits(self.check(ADA_NO, self.ada_pin))

        SignInAttempts.objects.filter(scope=SignInScope.CHECKER_NUMBER).update(
            window_started_at=timezone.now() - timedelta(hours=1)
        )

        self.assertOpened(self.check(ADA_NO, self.ada_pin), "Ada Obi")

    def test_a_right_answer_forgives_the_numbers_mistakes_and_not_the_addresses(self):
        self.guess(ADA_NO, 2, address_of=lambda i: HERE)
        self.assertOpened(self.check(ADA_NO, self.ada_pin), "Ada Obi")

        self.assertFalse(
            SignInAttempts.objects.filter(scope=SignInScope.CHECKER_NUMBER).exists()
        )
        self.assertEqual(
            SignInAttempts.objects.get(scope=SignInScope.CHECKER_ADDRESS).failures, 2
        )


class AWithheldCardIsHeldInTheCheckerTests(CheckerSetUp):
    """Requirement 9: the fee gate, in the gate's order, with the PIN as the claim."""

    def setUp(self):
        super().setUp()
        self.ada_pin = self.pins()["Ada Obi"]
        self.enable_withholding()
        self.withhold(self.ada)

    def test_the_right_pin_is_told_the_card_is_held_and_who_to_ring(self):
        response = self.check(ADA_NO, self.ada_pin)

        self.assertWithheld(response, "a family with the slip")
        for card_content in (b"Mathematics", b"subjects", b"own_average"):
            self.assertNotIn(card_content, response.content)

    def test_a_wrong_pin_is_the_one_refusal_and_learns_nothing_of_the_withholding(self):
        response = self.check(ADA_NO, "123412341234")

        self.assertNotOpened(response, "a stranger with Ada's number")
        self.assertNotTheWithheldBody(response, "a stranger with Ada's number")

    def test_lifting_it_opens_the_card(self):
        self.lift(self.ada)
        self.assertOpened(self.check(ADA_NO, self.ada_pin), "Ada Obi")


class EachSchoolsCheckerIsItsOwnTests(CheckerSetUp):
    """Requirement 10: SM/001 is Ada at St Mary's and Ngozi at Grace."""

    def setUp(self):
        super().setUp()
        self.ada_pin = self.pins()["Ada Obi"]
        self.ngozi_pin = self.pins(self.grace)["Ngozi Ade"]

    def test_each_hosts_number_and_pin_open_only_its_own_child(self):
        self.assertOpened(self.check(ADA_NO, self.ada_pin, host=HOST), "Ada Obi")
        self.assertOpened(self.check(NGOZI_NO, self.ngozi_pin, host=THEIR_HOST), "Ngozi Ade")

    def test_a_st_marys_pin_opens_nothing_on_graces_host(self):
        self.assertNotOpened(self.check(ADA_NO, self.ada_pin, host=THEIR_HOST), "Grace's host")
        self.assertNotOpened(self.check(NGOZI_NO, self.ngozi_pin, host=HOST), "St Mary's host")

    @override_settings(
        CHECKER_MAX_FAILURES_PER_ADMISSION_NUMBER=3, CHECKER_MAX_FAILURES_PER_ADDRESS=3
    )
    def test_wrong_answers_at_one_school_do_not_make_a_family_at_another_wait(self):
        """Same number, same address: both buckets are closed at St Mary's only."""
        for _ in range(3):
            self.assertNotOpened(self.check(ADA_NO, "999999999999", host=HOST))
        self.assertWaits(self.check(ADA_NO, self.ada_pin, host=HOST))

        self.assertOpened(self.check(NGOZI_NO, self.ngozi_pin, host=THEIR_HOST), "Ngozi Ade")


class TheChainPagePrintsSlipsTests(CheckerSetUp):
    """The staff route and the chain page's two fields. Ordinary tests."""

    def setUp(self):
        super().setUp()
        with connected_to(self.stmarys):
            Term.objects.filter(pk=self.term_of(self.stmarys, TermName.FIRST.value).pk).update(
                is_current=True
            )

    def slips_url(self):
        return f"/api/results/chain/{self.group_id}/checker-slips/"

    def post_slips(self, user, payload=None):
        self.client.force_login(user)
        return self.client.post(
            self.slips_url(), payload or {}, content_type="application/json", HTTP_HOST=HOST
        )

    def row(self, user):
        self.client.force_login(user)
        response = self.client.get("/api/results/chain/", HTTP_HOST=HOST)
        self.assertEqual(response.status_code, 200, response.content)
        (row,) = [r for r in response.json()["rows"] if r["class_group_id"] == self.group_id]
        return row

    def test_the_principal_is_handed_the_pdf_and_nothing_keeps_it(self):
        response = self.post_slips(self.principal)

        self.assertEqual(response.status_code, 200, response.content[:200])
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        self.assertRegex(response["Content-Disposition"], r'^attachment; filename="[a-z0-9-]+\.pdf"$')
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_a_teacher_is_refused_and_nothing_is_minted(self):
        response = self.post_slips(self.teacher)

        self.assertEqual(response.status_code, 403)
        with connected_to(self.stmarys):
            self.assertFalse(CheckerPin.objects.exists())

    def test_a_second_press_with_nobody_left_says_so(self):
        self.post_slips(self.principal)

        response = self.post_slips(self.principal)

        self.assertEqual(response.status_code, 409)
        self.assertIn("already has a slip", response.json()["detail"])

    def test_a_lost_slip_for_a_number_not_in_the_class_is_refused_in_words(self):
        response = self.post_slips(self.principal, {"admission_number": "SM/999"})

        self.assertEqual(response.status_code, 422)
        self.assertIn("No child in this class", response.json()["detail"])

    def test_the_chain_row_says_how_many_have_a_slip_to_whoever_may_print(self):
        self.assertEqual(
            (self.row(self.principal)["may_print_slips"], self.row(self.principal)["slips_printed"]),
            (True, 0),
        )
        self.pins()
        self.assertEqual(self.row(self.staff[Role.ADMIN])["slips_printed"], 2)

        teacher = self.row(self.teacher)
        self.assertEqual((teacher["may_print_slips"], teacher["slips_printed"]), (False, None))

