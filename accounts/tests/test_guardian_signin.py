"""Signing in with a handset: what it refuses, what it will not say, what it records.

`docs/parent-access.md` D3 and D9, and the half of `accounts/tests/test_login.py`
that does not transfer. That file pins a password door; this one pins a door
where the credential is a phone somebody is holding, and the differences are
where the bugs are.

**What it will not say is most of the file.** D3 removed the password, so every
reason to refuse here is a fact about who a school holds a record for — and D9
states the consequence as a requirement rather than leaving it to be inferred:
no account creation, no enumeration, and no "we have sent you a code" for an
unknown value. So the assertions below compare whole responses rather than
status codes, exactly as `RefusalSaysNothingTests` does for passwords. A body
differing by a word is as good an oracle as one differing by a status.

**The shared handset is not an edge case and is tested as the ordinary thing it
is.** `GuardianContact.value` carries no unique constraint precisely because one
household has one phone and two parents. That makes sign-in a *choice*, made by
whoever is holding the phone, which nothing can verify — so what the design owes
is a record of it, and `GuardianSignInRecordsTheChoiceTests` is where that is
held.

**The escalation refusal is the one guard here that is not about disclosure.**
`settings.GUARDIAN_SESSION_AGE` is thirty days because a lost handset reaches
"a parent-scoped read of their own children"; `SchoolAccessMiddleware` is what
makes that sentence true, and a guardian who is also a bursar is the person it
is true about.

Controls are recorded in the docstring of the test they belong to, per operating
rule 5 and `docs/parent-access.md`'s correctness requirements: every guard gets
one, aimed at the branch the test actually routes through.
"""

from datetime import timedelta

from django.db import connection
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from api import CSRF_FAILED

from accounts import guardian_contacts, guardian_signin, services
from accounts.models import (
    GuardianContactCode,
    GuardianSignIn,
    Role,
    SignInAttempts,
    SignInScope,
    User,
    VerificationCodeStatus,
)
from accounts.signin import TOO_MANY_ATTEMPTS
from schools.models import Domain
from schools.tests.test_invitations import make_school
from tests.guardians import give_verified_channel

PASSWORD = "correct-horse-battery"
PORTAL = "testserver"
SCHOOL_HOST = "st-marys.testserver"

#: One number, and for most of this file one guardian behind it. The shared
#: household is built by giving a second guardian the same value, which the
#: schema allows on purpose.
HANDSET = "08031234567"


class GuardianSignInSetUp(TestCase):
    """A portal, a school, a guardian with a child and a verified handset."""

    def setUp(self):
        portal = make_school("Portal", "portal", "public")
        Domain.objects.create(tenant=portal, domain=PORTAL, is_primary=True)

        self.stmarys = make_school("St Mary's", "st-marys", "st_marys")
        Domain.objects.create(tenant=self.stmarys, domain=SCHOOL_HOST, is_primary=True)

        self.mama = User.objects.create_user("mama", PASSWORD, full_name="Mama Ada")
        self.child = services.enroll_student(
            User.objects.create_user("STM/2026/0042", PASSWORD, full_name="Ada Okonkwo"),
            self.stmarys,
        )
        services.link_guardian(self.mama, self.child)
        self.contact = give_verified_channel(self.mama, HANDSET)

    def tearDown(self):
        """Back to `public`. `test_login.py`'s docstring gives the reason.

        `TenantMainMiddleware` leaves the connection on whichever schema the
        host resolved to, and some requests below go to a school's host.
        """
        connection.set_schema_to_public()
        super().tearDown()

    # -- the two doors -------------------------------------------------------

    def ask_for_a_code(self, value=HANDSET, host=PORTAL, **extra):
        return self.client.post(
            "/api/guardian/code/",
            data={"value": value},
            content_type="application/json",
            HTTP_HOST=host,
            **extra,
        )

    def answer(self, code, value=HANDSET, guardian=None, host=PORTAL, **extra):
        payload = {"value": value, "code": code}
        if guardian is not None:
            payload["guardian"] = guardian
        return self.client.post(
            "/api/guardian/session/",
            data=payload,
            content_type="application/json",
            HTTP_HOST=host,
            **extra,
        )

    # -- helpers -------------------------------------------------------------

    def mint(self, contact=None):
        """A live sign-in code, through the service the route uses.

        The raw code never leaves `_mint_code()` — it is stored as a SHA-256 —
        so a test that wants to answer one has to be the caller that minted it.
        The confirm path exercised afterwards is the real one.
        """
        _, raw_code = guardian_contacts.request_sign_in_code(contact or self.contact)
        return raw_code

    def go_quiet(self, contact=None, days=400):
        """Push every answered code back, so the channel reads as dormant.

        `last_authenticated_at()` is a fold over `confirmed_at`, so this is the
        honest way to age a channel: there is no column to set.
        """
        contact = contact or self.contact
        GuardianContactCode.objects.filter(
            contact=contact, status=VerificationCodeStatus.CONFIRMED
        ).update(confirmed_at=timezone.now() - timedelta(days=days))

    def signed_in(self) -> bool:
        return "_auth_user_id" in self.client.session

    def signed_in_as(self):
        return int(self.client.session["_auth_user_id"])


class WhereTheGuardianDoorsLiveTests(GuardianSignInSetUp):
    """The portal, and nowhere else — `/api/login/`'s rule, for the same reason.

    A guardian with children at two schools signs in once. A school's host
    refuses anybody without an active membership there, so a code door served
    from one would mean a parent needed a session per school.
    """

    def test_the_portal_serves_both(self):
        self.assertEqual(self.ask_for_a_code().status_code, 200)
        self.assertEqual(self.answer(self.mint()).status_code, 200)

    def test_a_schools_own_host_serves_neither(self):
        """404 on both, and no session opened by the attempt.

        CONTROL: dropping `_portal_only(request)` from either view turns that
        route's assertion here green-to-red — the request is served and the 404
        becomes a 200.
        """
        self.assertEqual(self.ask_for_a_code(host=SCHOOL_HOST).status_code, 404)
        self.assertEqual(self.answer(self.mint(), host=SCHOOL_HOST).status_code, 404)
        self.assertFalse(self.signed_in())


class TheCsrfCheckTests(GuardianSignInSetUp):
    """Hand-checked, because ninja exempts its own views from the middleware.

    `enforce_csrf_checks=True`, because the default test client sets
    `_dont_enforce_csrf_checks` and none of this would run — the gap
    `test_login.py` records having shipped once already.
    """

    def setUp(self):
        super().setUp()
        self.client = Client(enforce_csrf_checks=True)

    def test_both_doors_refuse_a_request_with_no_token(self):
        """CONTROL: removing the `_guardian_csrf_failure()` call from a view
        turns that door's 403 into a 200 and this red."""
        for label, response in (
            ("code", self.ask_for_a_code()),
            ("session", self.answer(self.mint())),
        ):
            with self.subTest(door=label):
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()["code"], CSRF_FAILED)
        self.assertFalse(self.signed_in())

    def test_a_token_from_the_csrf_route_lets_both_through(self):
        token = self.client.get("/api/csrf/", HTTP_HOST=PORTAL).json()["csrf_token"]

        self.assertEqual(self.ask_for_a_code(HTTP_X_CSRFTOKEN=token).status_code, 200)
        self.assertEqual(
            self.answer(self.mint(), HTTP_X_CSRFTOKEN=token).status_code, 200
        )

    def test_a_refused_request_is_not_counted_as_a_guess(self):
        """It never reached a code. Counting it would let anybody spend somebody
        else's window without knowing a single credential."""
        self.answer("000000")

        self.assertEqual(SignInAttempts.objects.count(), 0)


class TheRequestDoorSaysOneThingTests(GuardianSignInSetUp):
    """D9's "no enumeration", asserted as whole responses.

    Every value gets the same status and the same bytes. What differs behind it
    is whether a code row appeared, which is asserted separately — a test that
    only checked the body could not tell "said the same thing and sent one" from
    "said the same thing and sent nothing to everybody".
    """

    def unknown(self):
        return self.ask_for_a_code(value="08039999999")

    def test_a_known_and_an_unknown_value_are_indistinguishable(self):
        """CONTROL: returning a 404 when `_live_contacts_for()` is empty — the
        obvious, helpful thing to write — turns this red on the status, and
        returning a different sentence turns it red on the content."""
        known = self.ask_for_a_code()
        unknown = self.unknown()

        self.assertEqual(known.status_code, 200)
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.content, unknown.content)

    def test_the_sentence_claims_nothing_about_having_sent_anything(self):
        """D9 forbids "we have sent you a code" for an unknown value, and a
        denial would be the same oracle facing the other way. The answer is
        conditional, so it is true whoever types it."""
        body = self.ask_for_a_code().json()["detail"]

        self.assertEqual(body, guardian_signin.CODE_REQUESTED)
        self.assertIn("If that number", body)

    def test_a_known_value_really_does_mint_one(self):
        """The control for the two above: identical bodies prove nothing if
        neither call ever sends anything."""
        before = GuardianContactCode.objects.count()

        self.ask_for_a_code()

        self.assertEqual(GuardianContactCode.objects.count(), before + 1)

    def test_an_unknown_value_mints_nothing(self):
        before = GuardianContactCode.objects.count()

        self.unknown()

        self.assertEqual(GuardianContactCode.objects.count(), before)

    def test_a_dormant_channel_is_answered_the_same_way_and_sent_nothing(self):
        """The refusal a careless implementation leaks, and why it is raised.

        `ChannelDormant` carries `last_authenticated_at` because a school-facing
        caller needs to say when. A guardian-facing one must not say it is
        dormant at all — that is "this number is known to us", which is the
        enumeration D9 forbids.

        CONTROL: letting `request_code()` propagate `GuardianContactError`
        instead of swallowing it turns this into a 500 and the test red.
        """
        self.go_quiet()
        before = GuardianContactCode.objects.count()

        dormant = self.ask_for_a_code()

        self.assertEqual(dormant.content, self.unknown().content)
        self.assertEqual(GuardianContactCode.objects.count(), before)

    def test_an_unverified_channel_is_answered_the_same_way(self):
        """A channel a school typed and nobody has proved opens nothing, and
        says nothing about itself either."""
        unproved = User.objects.create_user("papa", PASSWORD, full_name="Papa Ada")
        services.link_guardian(unproved, self.child)
        account = guardian_contacts.guardian_account_for(unproved)
        guardian_contacts.GuardianContact.objects.create(
            guardian=account,
            channel_type=guardian_contacts.ContactChannel.PHONE,
            value="08037777777",
            created_by=unproved,
        )

        response = self.ask_for_a_code(value="08037777777")

        self.assertEqual(response.content, self.unknown().content)


class OneRefusalWhateverWentWrongTests(GuardianSignInSetUp):
    """Every way of failing at the session door looks the same from outside."""

    def refusals(self):
        """One response per way of failing, each from a fresh client.

        A fresh client per case because a failure counted against the throttle
        would otherwise turn the last of them into a 429 — which would make this
        test pass for a reason that has nothing to do with the refusals.
        """
        cases = {}

        cases["a wrong code"] = self.answer("000000")

        self.client = Client()
        cases["an unknown value"] = self.answer("000000", value="08039999999")

        self.client = Client()
        self.go_quiet()
        cases["a dormant channel"] = self.answer("000000")

        return cases

    def test_every_failure_is_the_same_response(self):
        """CONTROL: answering a dormant channel with its own sentence — the
        thing a support-minded implementation reaches for — turns this red on
        content while leaving every status identical, which is why the
        comparison is on bytes."""
        cases = self.refusals()
        bodies = {label: r.content for label, r in cases.items()}

        for label, response in cases.items():
            with self.subTest(case=label):
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.json()["code"], guardian_signin.BAD_CODE)

        self.assertEqual(len(set(bodies.values())), 1, bodies)

    def test_no_failure_opens_a_session(self):
        for label, response in self.refusals().items():
            with self.subTest(case=label):
                self.assertFalse(self.signed_in())

    def test_a_right_code_does_open_one(self):
        """The control for the class: identical refusals prove nothing if the
        door refuses everybody."""
        response = self.answer(self.mint())

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.signed_in())
        self.assertEqual(self.signed_in_as(), self.mama.pk)

    def test_a_code_cannot_be_answered_twice(self):
        """Spent is spent — `_confirm_code()` marks it CONFIRMED."""
        raw = self.mint()
        self.answer(raw)
        self.client = Client()

        again = self.answer(raw)

        self.assertEqual(again.status_code, 401)
        self.assertFalse(self.signed_in())


@override_settings(SIGN_IN_MAX_FAILURES_PER_CHANNEL=3)
class TheChannelThrottleTests(GuardianSignInSetUp):
    """Counted, not locked, and counted against the value as typed."""

    def wrong(self, times, value=HANDSET):
        for _ in range(times):
            response = self.answer("000000", value=value)
        return response

    def test_the_window_closes_after_the_limit(self):
        """CONTROL: asking the throttle after the lookup instead of before it —
        `sign_in_with_code()`'s first three lines — lets a caller keep guessing
        as long as they read the 429, and this test stays green while doing so.
        The control for *that* is the one below, which asserts a right code is
        refused while the window is shut."""
        self.wrong(3)

        response = self.answer("000000")

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json()["code"], TOO_MANY_ATTEMPTS)
        self.assertIn("Retry-After", response)

    def test_a_closed_window_refuses_the_right_code_too(self):
        """The point of asking the throttle first. A window that let a correct
        answer through would be no limit at all — an attacker reads the 429 and
        keeps going."""
        raw = self.mint()
        self.wrong(3)

        response = self.answer(raw)

        self.assertEqual(response.status_code, 429)
        self.assertFalse(self.signed_in())

    def test_being_throttled_says_nothing_about_who_exists(self):
        """The throttle is outside the one-refusal rule and does not break it:
        counted as typed, so an invented number closes its own window exactly
        as a real one does."""
        real = self.wrong(4)
        self.client = Client()
        invented = self.wrong(4, value="08039999999")

        self.assertEqual(real.status_code, 429)
        self.assertEqual(real.content, invented.content)

    def test_it_is_a_separate_bucket_from_the_password_door(self):
        """The reason `CHANNEL` exists rather than reusing `IDENTIFIER`.

        A parent's number is on the enrolment form. If the two doors shared a
        bucket, anyone who could read one could close a teacher's password door
        by guessing codes at it.

        CONTROL: returning `SignInScope.IDENTIFIER` from `guardian_signin`'s two
        throttle calls turns the second assertion red — the password door is
        found closed by traffic it never saw.
        """
        self.wrong(4)

        self.assertIsNotNone(
            SignInAttempts.objects.filter(scope=SignInScope.CHANNEL).first(),
            "the guardian door counted nothing",
        )
        self.assertFalse(
            SignInAttempts.objects.filter(scope=SignInScope.IDENTIFIER).exists(),
            "guessing codes closed the password door for the same number",
        )


class TheSharedHandsetTests(GuardianSignInSetUp):
    """One phone, two parents — the case the schema has no unique index for."""

    def setUp(self):
        super().setUp()
        self.papa = User.objects.create_user("papa", PASSWORD, full_name="Papa Ada")
        services.link_guardian(self.papa, self.child)
        self.papas_contact = give_verified_channel(self.papa, HANDSET)

    def public_id_of(self, user):
        return str(guardian_contacts.guardian_account_for(user).public_id)

    def test_a_right_code_offers_the_choice_and_opens_nothing(self):
        """202, not 200 — a different body shape gets a different status, so a
        client treating any 2xx as "signed in" is wrong loudly.

        CONTROL: having `_pick()` return `offered[0]` when no pick is named
        turns this red on both halves: a session opens, as whichever guardian
        happened to be created first.
        """
        response = self.answer(self.mint())

        self.assertEqual(response.status_code, 202)
        self.assertFalse(self.signed_in())
        offered = {option["guardian"] for option in response.json()["choose"]}
        self.assertEqual(
            offered, {self.public_id_of(self.mama), self.public_id_of(self.papa)}
        )

    def test_the_offer_names_people_by_the_opaque_identifier(self):
        """D9's stable opaque identifier finally has a reader. Never the row pk,
        which leaks how many guardians exist, and never the channel value."""
        options = self.answer(self.mint()).json()["choose"]

        for option in options:
            with self.subTest(guardian=option["full_name"]):
                self.assertNotEqual(option["guardian"], str(self.mama.pk))
                self.assertNotEqual(option["guardian"], str(self.papa.pk))
                self.assertNotIn(HANDSET, option["guardian"])

    def test_the_pick_comes_back_and_opens_the_session(self):
        self.answer(self.mint())

        response = self.answer("", guardian=self.public_id_of(self.papa))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.signed_in())
        self.assertEqual(self.signed_in_as(), self.papa.pk)

    def test_a_pick_naming_somebody_outside_the_offer_is_the_ordinary_refusal(self):
        """Not a different refusal, or poking at identifiers would be a way to
        learn which ones are real."""
        stranger = User.objects.create_user("uncle", PASSWORD, full_name="Uncle Emeka")
        services.link_guardian(stranger, self.child)
        outsider = self.public_id_of(stranger)
        self.answer(self.mint())

        response = self.answer("", guardian=outsider)

        self.assertEqual(response.status_code, 401)
        self.assertFalse(self.signed_in())

    def test_a_fresh_code_wins_over_an_abandoned_pick(self):
        """The guardian who gives up half way through is the same guardian who
        tries again. A parked pick that swallowed the next code would strand
        them on their own session.

        CONTROL: reading the parked pick before the code — `if pending is not
        None` without the `and not raw_code` — turns this red.
        """
        self.answer(self.mint())

        response = self.answer(self.mint())

        self.assertEqual(response.status_code, 202)

    def test_one_guardian_on_a_handset_is_never_asked_to_choose(self):
        """The ordinary case stays one round trip. Asking would be a round trip
        to tell somebody their own name."""
        self.papas_contact.revoked_at = timezone.now()
        self.papas_contact.save(update_fields=["revoked_at"])

        response = self.answer(self.mint())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.signed_in_as(), self.mama.pk)


class GuardianSignInRecordsTheChoiceTests(GuardianSignInSetUp):
    """Who was offered, who was picked, and what proved the handset.

    The pick is self-asserted — D3 makes the handset the credential and it
    belongs to both parents equally, so nothing at sign-in can check it. A
    self-asserted choice nobody wrote down is one nobody can audit a term later,
    when a guardian says they never saw a card their co-parent acted on.
    """

    def setUp(self):
        super().setUp()
        self.papa = User.objects.create_user("papa", PASSWORD, full_name="Papa Ada")
        services.link_guardian(self.papa, self.child)
        give_verified_channel(self.papa, HANDSET)
        self.papas_id = str(guardian_contacts.guardian_account_for(self.papa).public_id)

    def test_the_row_holds_all_three(self):
        raw = self.mint()
        self.answer(raw)
        self.answer("", guardian=self.papas_id)

        row = GuardianSignIn.objects.get()
        self.assertEqual(row.picked.user_id, self.papa.pk)
        self.assertEqual(
            {account.user_id for account in row.offered.all()},
            {self.mama.pk, self.papa.pk},
            "the alternatives are the half a dispute actually asks about",
        )
        self.assertEqual(row.proof.status, VerificationCodeStatus.CONFIRMED)
        self.assertIsNotNone(row.proof.confirmed_at)

    def test_offered_includes_the_one_picked(self):
        """Storing only the ones not chosen would make the row unreadable on its
        own: "offered two, picked one" needs both halves in one place."""
        self.answer(self.mint())
        self.answer("", guardian=self.papas_id)

        row = GuardianSignIn.objects.get()
        self.assertIn(row.picked, list(row.offered.all()))

    def test_an_ordinary_single_guardian_sign_in_is_recorded_too(self):
        """A record that only existed for shared handsets would answer "was
        there a choice" by its own absence, which is not the same as answering
        it."""
        GuardianSignIn.objects.all().delete()
        solo = User.objects.create_user("solo", PASSWORD, full_name="Solo Parent")
        services.link_guardian(solo, self.child)
        contact = give_verified_channel(solo, "08035555555")
        _, raw = guardian_contacts.request_sign_in_code(contact)

        self.answer(raw, value="08035555555")

        row = GuardianSignIn.objects.get()
        self.assertEqual(row.picked.user_id, solo.pk)
        self.assertEqual(row.offered.count(), 1)

    def test_a_replayed_pick_opens_nothing_and_writes_nothing(self):
        """`one_session_per_answered_code`, and the reason it is a constraint.

        The shared-handset path parks a spent code on the session, so "this code
        already opened a session" is a state two concurrent picks can both read
        as false. A bound needs a constraint behind it.

        CONTROL: dropping the `UniqueConstraint` from `GuardianSignIn.Meta`
        leaves both picks recorded and the second session opened — two rows for
        one handset proof, disagreeing about who was at the phone.
        """
        self.answer(self.mint())
        self.answer("", guardian=self.papas_id)
        proof = GuardianSignIn.objects.get().proof

        self.client = Client()
        replay = GuardianSignIn.record(
            offered=[], picked=guardian_contacts.guardian_account_for(self.mama),
            proof=proof,
        )

        self.assertIsNone(replay, "a second session was recorded against one code")
        self.assertEqual(GuardianSignIn.objects.count(), 1)


class ACodeSessionReachesPARENTAndNothingElseTests(GuardianSignInSetUp):
    """The escalation refusal, and the claim in `settings.py` it makes true.

    `GUARDIAN_SESSION_AGE` is thirty days because a lost handset reaches a
    parent-scoped read of that guardian's own children. A guardian who is also a
    bursar is an ordinary person rather than a corner case —
    `results.tests.test_withholding.TheClaimIsNotABool` is about exactly her —
    and without this her bursar role rides a session opened with six digits off
    an SMS: `_may_read()` answers `STAFF`, so the fee gate serves her a card
    withheld from her own family, and `WITHHOLDING_ROLES` lets her hold one back.
    Not the gradebook — `MARK_ENTERING_ROLES` leaves a bursar out on purpose.

    Two schools' worth of role is not what is at stake here; what is at stake is
    two *credentials* for one person, so the comparison throughout is the same
    user signed in two ways.
    """

    def setUp(self):
        super().setUp()
        services.grant_membership(self.mama, self.stmarys, Role.BURSAR)

    def test_a_password_session_keeps_the_staff_role(self):
        """The control for the class, and it has to come first: a test that only
        showed the code session narrowed would pass just as well against a
        middleware that refused this person outright."""
        self.client.force_login(self.mama)

        response = self.client.get("/api/csrf/", HTTP_HOST=SCHOOL_HOST)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.mama.roles_at(self.stmarys),
            {Role.PARENT.value, Role.BURSAR.value},
            "she really is both, or the narrowing below has nothing to remove",
        )

    def test_the_narrowing_is_in_the_one_place_every_guard_reads(self):
        """`roles_at()`, not `request.school_roles`.

        Nothing on the platform reads `request.school_roles` —
        `card_api._may_read()`, `gradebook.services.can_enter_marks()` and the
        rest all call `user.roles_at()` with `request.user`. The first version
        of this narrowed the middleware's own copy, which restricted nothing at
        all while reading exactly like a restriction.

        CONTROL: dropping the `& {Role.PARENT.value}` filter from `roles_at()`
        turns this red — the bursar role survives a session opened with six
        digits, and `_may_read()` hands her the STAFF claim on her own child's
        withheld card.
        """
        self.mama.parent_scoped_credential = True
        self.assertEqual(self.mama.roles_at(self.stmarys), {Role.PARENT.value})

        self.mama.parent_scoped_credential = False
        self.assertEqual(
            self.mama.roles_at(self.stmarys),
            {Role.PARENT.value, Role.BURSAR.value},
        )

    def test_the_default_is_off_for_a_user_nobody_narrowed(self):
        """A class-level default, so a management command or a fixture that
        never met a request is not silently parent-scoped."""
        self.assertFalse(User().parent_scoped_credential)
        self.assertFalse(self.mama.parent_scoped_credential)

    def test_a_code_session_with_no_parent_role_there_is_refused(self):
        """The narrowing leaves nothing, so the middleware refuses — which is
        what "reaches their own children and nothing else" means for a school
        where this guardian has no child.

        CONTROL: removing the `&= {Role.PARENT.value}` intersection lets this
        request through on the bursar role and turns the 403 into a 200.
        """
        grace = make_school("Grace Academy", "grace", "grace")
        Domain.objects.create(tenant=grace, domain="grace.testserver", is_primary=True)
        services.grant_membership(self.mama, grace, Role.BURSAR)
        self.answer(self.mint())

        response = self.client.get("/api/csrf/", HTTP_HOST="grace.testserver")

        self.assertEqual(response.status_code, 403)

    def test_the_platform_staff_bypass_does_not_apply_to_a_code_session(self):
        """That bypass exists so somebody operating the platform is not locked
        out of a school they hold no membership at. Six digits off an SMS is not
        how they prove they are that person.

        CONTROL: moving the `is_platform_staff` check ahead of the narrowing
        turns this red.
        """
        grace = make_school("Grace Academy", "grace", "grace")
        Domain.objects.create(tenant=grace, domain="grace.testserver", is_primary=True)
        self.mama.is_platform_staff = True
        self.mama.save(update_fields=["is_platform_staff"])
        self.answer(self.mint())

        response = self.client.get("/api/csrf/", HTTP_HOST="grace.testserver")

        self.assertEqual(response.status_code, 403)
