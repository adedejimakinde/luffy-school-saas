"""The transfer handshake has no route, on purpose, for now. Audit finding G-16, issue #346.

**A known-limit test** (`docs/operating-rules.md` rule 5, "The one exception").
It asserts a gap, so it has no guard to break: it goes red the day somebody
gives the handshake a route. Read a red one the opposite way round: update
issue #346, move these cases into a test of the route, and rewrite the
"There is no HTTP surface" paragraph of `docs/membership.md`.

Why it stays disabled is issue #346 and `docs/membership.md`: the receiving
school has no safe way to name another school's child, an accept on the
receiving host cannot take the child off the sending school's class lists
(they are in the sending school's schema), and what a receiving school may read
before it agrees needs confirming.

**The companion** (`TheServiceIsCompleteTests`) shows the limit is a boundary
and not an absence: both schools' admins, each with authority at one end only,
complete a handshake at the service layer. It also pins reason two as a fact:
after the accept, the child is still on the sending school's class list.
"""

import pathlib

from django.test import TestCase

from academics import services as academics
from academics.models import ClassGroup, ClassPlacement, Term, TermName
from accounts import services, transfers
from accounts.models import MembershipStatus, Role, User
from schools.tests.tenants import connected_to, make_school

ROOT = pathlib.Path(__file__).resolve().parents[2]
HANDSHAKE = ("request_transfer_as", "accept_transfer_as", "decline_transfer_as",
             "withdraw_transfer_as", "transfers_awaiting")


def _calls(source) -> bool:
    import ast

    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name in HANDSHAKE:
                return True
    return False


class NothingButTheTestsCallsTheHandshakeTests(TestCase):
    def test_no_application_module_calls_the_handshake(self):
        """Every `.py` outside a tests directory, parsed: a call of any of the
        five, by name or as an attribute. Docstrings that mention them are not
        calls. Goes red when a route, a page or a command calls one."""
        callers = []
        for path in ROOT.rglob("*.py"):
            relative = path.relative_to(ROOT)
            parts = relative.parts
            if parts[0] in ("node_modules", ".git") or "tests" in parts or "migrations" in parts:
                continue
            if _calls(path.read_text(encoding="utf-8", errors="ignore")):
                callers.append(relative.as_posix())
        self.assertEqual(callers, [], "the handshake has a caller now: see issue #346 and this module's docstring")

    def test_the_search_can_find_a_caller(self):
        """The control on the search above: given a call, it finds it, so an
        empty answer means no caller, not a search that finds nothing."""
        self.assertTrue(_calls("from accounts import transfers\ntransfers.accept_transfer_as(a, r)\n"))
        self.assertTrue(_calls("request_transfer_as(a, s, t)\n"))
        self.assertFalse(_calls('"""Neither `request_transfer_as()` nor this."""\n'))

    def test_no_route_answers_for_a_transfer(self):
        from django.urls import get_resolver

        def names(resolver, prefix=""):
            for pattern in resolver.url_patterns:
                yield prefix + str(pattern.pattern)
                if hasattr(pattern, "url_patterns"):
                    yield from names(pattern, prefix + str(pattern.pattern))

        for urlconf in ("urls", "urls_public"):
            with self.subTest(urlconf=urlconf):
                routes = [r for r in names(get_resolver(urlconf)) if "transfer" in r.lower()]
                self.assertEqual(routes, [])


class TheServiceIsCompleteTests(TestCase):
    def setUp(self):
        self.stmarys = make_school("St Mary's", "st-marys", "st_marys")
        self.grace = make_school("Grace Academy", "grace", "grace")
        self.their_admin = User.objects.create_user("abeg", None, full_name="Abeg Nwosu")
        services.grant_membership(self.their_admin, self.grace, Role.ADMIN)
        self.our_admin = User.objects.create_user("amaka", None, full_name="Amaka Obi")
        services.grant_membership(self.our_admin, self.stmarys, Role.ADMIN)
        self.ada = services.enroll_student(
            User.objects.create_user("ada", None, full_name="Ada Obi"), self.stmarys, reference="A1"
        )
        with connected_to(self.stmarys):
            self.term = Term.objects.create(
                session="2025/2026", name=TermName.FIRST, is_current=True,
                starts_on="2025-09-15", ends_on="2025-12-12",
            )
            academics.place_student(ClassGroup.objects.create(name="JSS 1A", level=1), self.term, self.ada)

    def tearDown(self):
        from django.db import connection

        connection.set_schema_to_public()

    def test_two_schools_each_signing_their_own_end_move_the_child(self):
        request = transfers.request_transfer_as(self.our_admin, self.ada, self.grace)
        moved = transfers.accept_transfer_as(self.their_admin, request, reference="G7")

        self.ada.refresh_from_db()
        self.assertEqual(self.ada.status, MembershipStatus.ENDED)
        self.assertEqual((moved.school, moved.reference), (self.grace, "G7"))

    def test_an_accept_leaves_the_child_on_the_sending_schools_class_list(self):
        """Reason two of issue #346, as a fact: the accept cannot reach St Mary's
        schema, so Ada is still in JSS 1A there. A route must solve this first."""
        request = transfers.request_transfer_as(self.our_admin, self.ada, self.grace)
        transfers.accept_transfer_as(self.their_admin, request, reference="G7")

        with connected_to(self.stmarys):
            self.assertTrue(
                ClassPlacement.objects.filter(term=self.term, student_membership_id=self.ada.pk).exists()
            )
