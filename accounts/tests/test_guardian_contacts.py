"""The guardian's contact channel: recorded by a school, proved by the guardian.

`docs/parent-access.md` D9 and D10. Every guard here has a control recorded
against it in the docstring of the test that covers it — the method operating
rule 5 sets out: break the thing deliberately, re-run, read the failure.

Two schools throughout. A guardian record spans schools by construction (D5),
so a single-tenant test of one is blind to the entire class of bug where a
school reaches a guardian it has no child in common with.
"""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts import checks, guardian_contacts, services
from accounts.models import (
    MAX_VERIFICATION_ATTEMPTS,
    ContactChannel,
    Membership,
    MembershipStatus,
    GuardianAccount,
    GuardianContact,
    GuardianContactCode,
    Role,
    User,
    VerificationCodeStatus,
)
from accounts.services import NotPermitted
from schools.models import School
from tests.refusals import RefusalAssertions

PASSWORD = "correct-horse-battery"


def make_school(name, slug, schema_name):
    school = School(name=name, slug=slug, schema_name=schema_name)
    school.auto_create_schema = False
    school.save()
    return school


def make_user(username, full_name, **extra):
    return User.objects.create_user(username, PASSWORD, full_name=full_name, **extra)


class TwoSchools(TestCase):
    """One parent with a child at each of two schools, and an admin at each."""

    def setUp(self):
        self.st_marys = make_school("St Mary's", "st-marys", "st_marys")
        self.grace = make_school("Grace Academy", "grace", "grace")

        self.marys_admin = make_user("marys-admin", "Bisi Adeyemi")
        services.grant_membership(self.marys_admin, self.st_marys, Role.ADMIN)
        self.grace_admin = make_user("grace-admin", "Tunde Bello")
        services.grant_membership(self.grace_admin, self.grace, Role.ADMIN)

        self.parent = make_user("ada-parent", "Ada Okonkwo")
        self.child_at_marys = services.enroll_student(
            make_user("STM/2026/0042", "Chidi Okonkwo"), self.st_marys
        )
        services.link_guardian(self.parent, self.child_at_marys)

        # A second, unrelated guardian whose only child is at Grace.
        self.other_parent = make_user("emeka-parent", "Emeka Nwosu")
        self.child_at_grace = services.enroll_student(
            make_user("GA/2026/0007", "Ngozi Nwosu"), self.grace
        )
        services.link_guardian(self.other_parent, self.child_at_grace)

    def record(self, admin, parent, channel_type, value):
        return guardian_contacts.record_contact_as(admin, parent, channel_type, value)


class TheGuardianRecordTests(TwoSchools):
    def test_one_guardian_account_survives_a_second_school(self):
        """One person, one record — the shape D10 calls "one row, one action"."""
        services.link_guardian(self.parent, self.child_at_grace)
        first = guardian_contacts.guardian_account_for(self.parent)
        again = guardian_contacts.guardian_account_for(self.parent)

        self.assertEqual(first.pk, again.pk)
        self.assertEqual(GuardianAccount.objects.filter(user=self.parent).count(), 1)
        # Two children at two schools, still one guardian record.
        self.assertEqual(self.parent.guardianships.count(), 2)

    def test_the_opaque_identifier_is_neither_the_pk_nor_the_channel(self):
        """D9's stable opaque identifier, and what it is not.

        CONTROL: replacing `public_id`'s default with `lambda: uuid.UUID(int=0)`
        leaves every account sharing one id; the uniqueness assertion goes red.
        """
        account = guardian_contacts.guardian_account_for(self.parent)
        other = guardian_contacts.guardian_account_for(self.other_parent)

        self.assertNotEqual(account.public_id, other.public_id)
        self.assertNotEqual(str(account.public_id), str(account.pk))
        stamped = account.public_id
        account.refresh_from_db()
        self.assertEqual(account.public_id, stamped)

    def test_the_identifier_does_not_move_when_a_channel_is_recorded(self):
        account = guardian_contacts.guardian_account_for(self.parent)
        before = account.public_id
        self.record(self.marys_admin, self.parent, ContactChannel.PHONE, "08031234567")
        account.refresh_from_db()
        self.assertEqual(account.public_id, before)


class NormalizationIsReusedTests(TwoSchools):
    def test_a_phone_is_stored_in_e164_however_it_was_typed(self):
        """PR #2's normalizer, not a second copy of it.

        CONTROL: dropping the `normalize_phone()` call from
        `GuardianContact.normalize_value()` stores "0803 123 4567" verbatim and
        both assertions go red.
        """
        contact = self.record(
            self.marys_admin, self.parent, ContactChannel.PHONE, "0803 123 4567"
        )
        self.assertEqual(contact.value, "+2348031234567")
        contact.refresh_from_db()
        self.assertEqual(contact.value, "+2348031234567")

    def test_the_channel_and_a_user_identifier_agree_about_one_number(self):
        """The two resolvers are separate code; the normalization under them is not.

        `matching_identifier()` reads `User` columns and cannot see the contact
        table, so this pins the thing that must not drift: one number typed two
        ways lands on one guardian here exactly as it lands on one account there.
        """
        self.parent.phone = "+2348031234567"
        self.parent.save()
        contact = self.record(
            self.marys_admin, self.parent, ContactChannel.PHONE, "08031234567"
        )
        guardian_contacts.confirm_verification(
            contact, guardian_contacts.request_verification(contact)[1]
        )

        for typed in ("08031234567", "+234 803 123 4567", "+2348031234567"):
            with self.subTest(typed=typed):
                self.assertEqual(
                    list(User.objects.matching_identifier(typed)), [self.parent]
                )
                self.assertEqual(
                    [a.user for a in guardian_contacts.resolve_guardians(typed)],
                    [self.parent],
                )

    def test_a_direct_create_normalizes_too(self):
        """`Model.save()` does not call `full_clean()`, so `clean()` is not enough.

        The service goes through `full_clean()` and would have looked correct
        forever; `GuardianContact.objects.create()` does not, and is what a
        management command, a data migration or the next service will reach for.
        This is issue #91's shape — the one `Guardianship.save()` already
        carries an override for — and it is a gap the other tests in this class
        cannot see, because they all enter through `record_contact_as()`.

        CONTROL: removing the `GuardianContact.save()` override stores
        "0803 123 4567" verbatim and this goes red, while every other test in
        this class stays green.
        """
        account = guardian_contacts.guardian_account_for(self.parent)
        contact = GuardianContact.objects.create(
            guardian=account,
            channel_type=ContactChannel.PHONE,
            value="0803 123 4567",
            created_by=self.marys_admin,
        )
        contact.refresh_from_db()
        self.assertEqual(contact.value, "+2348031234567")

    def test_an_email_channel_is_lowercased_and_validated(self):
        """CONTROL: removing `validate_email()` from `normalize_value()` stores
        "not-an-address" as an email channel and the refusal assertion goes red.
        """
        contact = self.record(
            self.marys_admin, self.parent, ContactChannel.EMAIL, "Ada@StMarys.NG"
        )
        self.assertEqual(contact.value, "ada@stmarys.ng")

        with self.assertRaises(ValidationError):
            guardian_contacts.record_contact(
                guardian_contacts.guardian_account_for(self.other_parent),
                ContactChannel.EMAIL,
                "not-an-address",
                created_by=self.grace_admin,
            )

    def test_the_type_is_a_field_and_both_kinds_round_trip(self):
        """D9's "type is a field, not a hardcoded assumption", as data."""
        phone = self.record(
            self.marys_admin, self.parent, ContactChannel.PHONE, "08031234567"
        )
        email = self.record(
            self.grace_admin, self.other_parent, ContactChannel.EMAIL, "emeka@grace.ng"
        )
        self.assertEqual(phone.channel_type, ContactChannel.PHONE)
        self.assertEqual(email.channel_type, ContactChannel.EMAIL)


class OneHandsetTwoGuardiansTests(TwoSchools):
    def test_two_guardians_may_hold_the_same_number(self):
        """The household case, and why `value` carries no unique index.

        CONTROL: adding `unique=True` to `GuardianContact.value` and migrating
        makes the second `record_contact_as()` raise IntegrityError — which is
        exactly the parent a school could not enter.
        """
        first = self.record(
            self.marys_admin, self.parent, ContactChannel.PHONE, "08031234567"
        )
        second = self.record(
            self.grace_admin, self.other_parent, ContactChannel.PHONE, "08031234567"
        )
        self.assertEqual(first.value, second.value)
        self.assertNotEqual(first.guardian_id, second.guardian_id)

    def test_a_shared_number_resolves_to_both_guardians(self):
        """Callers must be built for more than one. Pinned so PR C cannot assume `.get()`."""
        for admin, parent in (
            (self.marys_admin, self.parent),
            (self.grace_admin, self.other_parent),
        ):
            contact = self.record(admin, parent, ContactChannel.PHONE, "08031234567")
            _, raw = guardian_contacts.request_verification(contact)
            guardian_contacts.confirm_verification(contact, raw)

        found = guardian_contacts.resolve_guardians("08031234567")
        self.assertCountEqual(
            [a.user for a in found], [self.parent, self.other_parent]
        )


class OneLiveChannelTests(TwoSchools, RefusalAssertions):
    """One live channel of each type: an email and a phone, never two of either. #111."""

    def test_a_guardian_may_hold_a_live_email_and_a_live_phone(self):
        """The admission form one school described: both taken, both live.

        CONTROL: restoring the per-guardian check in `record_contact()`
        (`live_contact()` with no type) refuses the email, and this goes red.
        """
        phone = self.record(self.marys_admin, self.parent, ContactChannel.PHONE, "08031234567")
        email = self.record(self.marys_admin, self.parent, ContactChannel.EMAIL, "ada@stmarys.ng")
        for contact in (phone, email):
            _, raw = guardian_contacts.request_verification(contact)
            self.assertTrue(guardian_contacts.confirm_verification(contact, raw))

        account = guardian_contacts.guardian_account_for(self.parent)
        self.assertEqual(
            [(c.channel_type, c.is_live) for c in account.live_contacts()],
            [(ContactChannel.PHONE, True), (ContactChannel.EMAIL, True)],
        )

    def test_the_service_refuses_a_second_live_phone(self):
        """CONTROL: deleting the `live_contact(channel_type)` check in
        `record_contact()` lets the call through to the database, where
        `one_live_contact_per_guardian_per_channel` refuses it as an
        IntegrityError instead — so the test goes red on the exception type,
        not on nothing happening.
        """
        self.record(self.marys_admin, self.parent, ContactChannel.PHONE, "08031234567")
        with self.assertRaises(guardian_contacts.ChannelAlreadyRecorded):
            self.record(self.marys_admin, self.parent, ContactChannel.PHONE, "08039999999")

    def test_the_database_refuses_it_too_when_the_service_is_bypassed(self):
        """The service check and the constraint agree, per operating rule 3.

        CONTROL: keying the constraint on `guardian` alone again lets the email
        in below as well, and the first `create` of it goes red instead; keying
        it on nothing lets the second phone in, and `assertRefusedBy` goes red.
        """
        account = guardian_contacts.guardian_account_for(self.parent)
        for channel_type, value in (
            (ContactChannel.PHONE, "+2348031234567"),
            (ContactChannel.EMAIL, "ada@stmarys.ng"),
        ):
            GuardianContact.objects.create(
                guardian=account, channel_type=channel_type, value=value,
                created_by=self.marys_admin,
            )
        with self.assertRefusedBy("one_live_contact_per_guardian_per_channel"):
            GuardianContact.objects.create(
                guardian=account,
                channel_type=ContactChannel.PHONE,
                value="+2348039999999",
                created_by=self.marys_admin,
            )

    def test_a_second_guardian_is_unaffected_by_the_first_ones_channel(self):
        self.record(self.marys_admin, self.parent, ContactChannel.PHONE, "08031234567")
        second = self.record(
            self.grace_admin, self.other_parent, ContactChannel.PHONE, "08039998888"
        )
        self.assertIsNotNone(second.pk)


class TheChannelIsAppendOnlyTests(TwoSchools, RefusalAssertions):
    """The four refusals in `accounts_guardian_contact_append_only`.

    CONTROL for all of them: reversing
    `0011_a_contact_channel_is_append_only` (or dropping the trigger) makes
    every `assertRefusedBy` here go red, each reporting that no exception was
    raised. Run one at a time — a control run invalidates anything measured
    before it.
    """

    def setUp(self):
        super().setUp()
        self.contact = self.record(
            self.marys_admin, self.parent, ContactChannel.PHONE, "08031234567"
        )

    def test_the_value_cannot_be_rewritten(self):
        with self.assertRefusedBy("guardian_contact_is_append_only"):
            GuardianContact.objects.filter(pk=self.contact.pk).update(
                value="+2348039998888"
            )

    def test_the_channel_type_cannot_be_rewritten(self):
        with self.assertRefusedBy("guardian_contact_is_append_only"):
            GuardianContact.objects.filter(pk=self.contact.pk).update(
                channel_type=ContactChannel.EMAIL
            )

    def test_the_guardian_it_belongs_to_cannot_be_rewritten(self):
        other = guardian_contacts.guardian_account_for(self.other_parent)
        with self.assertRefusedBy("guardian_contact_is_append_only"):
            GuardianContact.objects.filter(pk=self.contact.pk).update(
                guardian=other
            )

    def test_the_row_cannot_be_deleted(self):
        with self.assertRefusedBy("guardian_contact_is_append_only"):
            GuardianContact.objects.filter(pk=self.contact.pk).delete()

    def test_a_verified_channel_does_not_verify_twice(self):
        GuardianContact.objects.filter(pk=self.contact.pk).update(
            verified_at=timezone.now()
        )
        with self.assertRefusedBy("guardian_contact_verifies_once"):
            GuardianContact.objects.filter(pk=self.contact.pk).update(
                verified_at=timezone.now() + timedelta(days=1)
            )

    def test_a_verified_channel_cannot_be_unverified(self):
        GuardianContact.objects.filter(pk=self.contact.pk).update(
            verified_at=timezone.now()
        )
        with self.assertRefusedBy("guardian_contact_verifies_once"):
            GuardianContact.objects.filter(pk=self.contact.pk).update(verified_at=None)

    def test_a_revoked_channel_cannot_be_verified(self):
        """The refusal the other three do not cover.

        A channel revoked while still unverified has `verified_at IS NULL`, so
        the one-way check passes and the stamp would land — quietly bringing a
        replaced channel back to life.

        CONTROL: deleting only the `a_revoked_channel_stays_revoked` branch from
        the trigger lets the UPDATE through, and this test alone goes red while
        the other five in this class stay green.
        """
        GuardianContact.objects.filter(pk=self.contact.pk).update(
            revoked_at=timezone.now()
        )
        with self.assertRefusedBy("a_revoked_channel_stays_revoked"):
            GuardianContact.objects.filter(pk=self.contact.pk).update(
                verified_at=timezone.now()
            )

    def test_a_revoked_channel_does_not_revoke_twice(self):
        GuardianContact.objects.filter(pk=self.contact.pk).update(
            revoked_at=timezone.now()
        )
        with self.assertRefusedBy("guardian_contact_revokes_once"):
            GuardianContact.objects.filter(pk=self.contact.pk).update(
                revoked_at=timezone.now() + timedelta(days=1)
            )

    def test_the_two_stamps_that_are_permitted_actually_land(self):
        """The trigger permits what it is supposed to permit.

        Without this, every test above would still pass with a trigger that
        refused *all* updates — which is rule 5's "passes for a reason
        unrelated to its subject", one layer up.
        """
        stamped = timezone.now()
        GuardianContact.objects.filter(pk=self.contact.pk).update(verified_at=stamped)
        GuardianContact.objects.filter(pk=self.contact.pk).update(revoked_at=stamped)
        self.contact.refresh_from_db()
        self.assertEqual(self.contact.verified_at, stamped)
        self.assertEqual(self.contact.revoked_at, stamped)


class VerificationTests(TwoSchools):
    def setUp(self):
        super().setUp()
        self.contact = self.record(
            self.marys_admin, self.parent, ContactChannel.PHONE, "08031234567"
        )

    def test_a_recorded_channel_is_not_live_until_the_code_comes_back(self):
        """D9's gate, as the predicate PR C will read.

        CONTROL: making `confirm_verification()` stamp `verified_at` before
        comparing the digest turns the first assertion green too early and this
        goes red.
        """
        account = guardian_contacts.guardian_account_for(self.parent)
        self.assertFalse(account.has_verified_channel())
        self.assertFalse(self.contact.is_verified)

        code, raw = guardian_contacts.request_verification(self.contact)
        self.assertFalse(account.has_verified_channel())

        self.assertTrue(guardian_contacts.confirm_verification(self.contact, raw))
        self.assertTrue(account.has_verified_channel())
        self.contact.refresh_from_db()
        self.assertTrue(self.contact.is_live)

    def test_the_code_is_never_stored(self):
        """CONTROL: adding a plaintext `code` column and writing `raw` to it
        makes the sweep below find it and this test go red.
        """
        code, raw = guardian_contacts.request_verification(self.contact)
        code.refresh_from_db()
        self.assertNotIn(raw, str(code.__dict__))
        self.assertEqual(code.code_hash, guardian_contacts.hash_code(raw))
        self.assertEqual(len(code.code_hash), 64)

    def test_a_wrong_code_is_refused_and_counted(self):
        code, raw = guardian_contacts.request_verification(self.contact)
        wrong = "000000" if raw != "000000" else "111111"

        self.assertFalse(guardian_contacts.confirm_verification(self.contact, wrong))
        code.refresh_from_db()
        self.assertEqual(code.attempts, 1)
        self.assertEqual(code.status, VerificationCodeStatus.PENDING)
        self.contact.refresh_from_db()
        self.assertFalse(self.contact.is_verified)

    def test_a_code_dies_after_the_attempt_cap(self):
        """The cap, not the digest, is what stands between a six-digit code and a guess.

        CONTROL: removing `or code.attempts_exhausted` from
        `confirm_verification()` lets the right code still work after the cap,
        and the assertion below goes red. That control only bites because the
        cap is now read in exactly one place — while the wrong-guess branch
        *also* spent the code at the cap, this branch was unreachable and no
        control could turn it red.
        """
        code, raw = guardian_contacts.request_verification(self.contact)
        wrong = "000000" if raw != "000000" else "111111"

        for _ in range(MAX_VERIFICATION_ATTEMPTS):
            self.assertFalse(
                guardian_contacts.confirm_verification(self.contact, wrong)
            )

        code.refresh_from_db()
        self.assertEqual(code.attempts, MAX_VERIFICATION_ATTEMPTS)

        # The one that matters: the *correct* code no longer works. The code is
        # dead, not the guess. Read on this presentation rather than stamped
        # during the loop, so the cap is one branch with one reader.
        self.assertFalse(guardian_contacts.confirm_verification(self.contact, raw))
        code.refresh_from_db()
        self.assertEqual(code.status, VerificationCodeStatus.SPENT)
        self.contact.refresh_from_db()
        self.assertFalse(self.contact.is_verified)

    def test_an_expired_code_is_refused(self):
        _, raw = guardian_contacts.request_verification(
            self.contact, ttl=timedelta(seconds=-1)
        )
        self.assertFalse(guardian_contacts.confirm_verification(self.contact, raw))
        self.contact.refresh_from_db()
        self.assertFalse(self.contact.is_verified)

    def test_a_resend_kills_the_code_it_replaces(self):
        """Exactly one live code per channel, so resending does not widen the target.

        CONTROL: removing the `.update(status=SPENT)` sweep from
        `request_verification()` leaves the first code PENDING and the first
        assertion goes red.
        """
        first_row, first = guardian_contacts.request_verification(self.contact)
        second_row, second = guardian_contacts.request_verification(self.contact)

        self.assertFalse(guardian_contacts.confirm_verification(self.contact, first))
        first_row.refresh_from_db()
        self.assertEqual(first_row.status, VerificationCodeStatus.SPENT)
        self.assertTrue(guardian_contacts.confirm_verification(self.contact, second))

    def test_a_code_is_spent_once(self):
        _, raw = guardian_contacts.request_verification(self.contact)
        self.assertTrue(guardian_contacts.confirm_verification(self.contact, raw))
        self.assertFalse(guardian_contacts.confirm_verification(self.contact, raw))

    def test_an_already_verified_channel_takes_no_new_code(self):
        _, raw = guardian_contacts.request_verification(self.contact)
        guardian_contacts.confirm_verification(self.contact, raw)
        self.contact.refresh_from_db()
        with self.assertRaises(guardian_contacts.ChannelNotVerifiable):
            guardian_contacts.request_verification(self.contact)

    def test_an_empty_code_verifies_nothing(self):
        guardian_contacts.request_verification(self.contact)
        for empty in ("", None):
            with self.subTest(empty=empty):
                self.assertFalse(
                    guardian_contacts.confirm_verification(self.contact, empty)
                )


class ACodeBelongsToOneChannelTests(TwoSchools):
    """The one place this deliberately departs from `Invitation.validate_token()`.

    That method looks a token up *globally* by `token_hash`, which is safe for
    32 bytes of entropy. A six-digit code has a million values, so a global
    lookup would let a code minted for one guardian act on another's channel.
    """

    def setUp(self):
        super().setUp()
        self.marys_contact = self.record(
            self.marys_admin, self.parent, ContactChannel.PHONE, "08031234567"
        )
        self.grace_contact = self.record(
            self.grace_admin, self.other_parent, ContactChannel.PHONE, "08039998888"
        )

    def test_one_guardians_code_cannot_touch_anothers_channel(self):
        """CONTROL: dropping `contact=locked` from the `GuardianContactCode`
        filter in `confirm_verification()` makes the lookup global. Grace's
        channel is then verified by St Mary's code, and both final assertions
        go red.

        **The mint order is the whole test, and the first version of it had the
        order backwards.** The lookup is `.order_by("-created_at", "-id")`, so a
        global filter returns the *newest* pending code. With St Mary's minted
        first, a global lookup would have found Grace's own code, failed the
        digest comparison, and returned False — the test passed with the guard
        removed and proved nothing. St Mary's code has to be the newest one for
        the broken lookup to reach it, which is what makes this aim at the
        branch the call actually routes through rather than the branch its name
        implies.
        """
        guardian_contacts.request_verification(self.grace_contact)
        _, marys_raw = guardian_contacts.request_verification(self.marys_contact)

        self.assertFalse(
            guardian_contacts.confirm_verification(self.grace_contact, marys_raw)
        )

        self.marys_contact.refresh_from_db()
        self.grace_contact.refresh_from_db()
        # Grace's channel is the one the broken lookup would verify, using a
        # code sent to a different guardian at a different school.
        self.assertFalse(self.grace_contact.is_verified)
        self.assertFalse(self.marys_contact.is_verified)

    def test_the_code_hash_column_is_not_unique(self):
        """Two channels may legitimately be issued the same six digits.

        CONTROL: adding `unique=True` to `code_hash` and migrating makes the
        second insert raise IntegrityError, which is a collision a real system
        would hit roughly once in a million sends.
        """
        shared = guardian_contacts.hash_code("123456")
        for contact in (self.marys_contact, self.grace_contact):
            GuardianContactCode.objects.create(
                contact=contact,
                code_hash=shared,
                expires_at=timezone.now() + timedelta(minutes=15),
            )
        self.assertEqual(
            GuardianContactCode.objects.filter(code_hash=shared).count(), 2
        )


class NeverAutoCreateFromAnInboundContactTests(TwoSchools):
    def test_an_unknown_value_creates_nothing_and_resolves_to_nobody(self):
        """D9's "no account, no enumeration, no 'we sent you a code'".

        CONTROL: there is no code path to break here, and that is the point —
        the guard is structural. `resolve_guardians()` is the only function that
        takes a raw value and it is a read. Giving it a `get_or_create` would
        make the count assertions go red.
        """
        before = GuardianAccount.objects.count()
        for unknown in ("08130000000", "nobody@nowhere.ng", "", None, "not a thing"):
            with self.subTest(unknown=unknown):
                self.assertEqual(
                    list(guardian_contacts.resolve_guardians(unknown)), []
                )
        self.assertEqual(GuardianAccount.objects.count(), before)
        self.assertEqual(GuardianContact.objects.count(), 0)
        self.assertEqual(GuardianContactCode.objects.count(), 0)

    def test_an_unverified_channel_resolves_to_nobody(self):
        """A channel a school typed proves nothing until the code comes back.

        CONTROL: dropping `contacts__verified_at__isnull=False` from
        `resolve_guardians()` returns the guardian before verification and this
        goes red.
        """
        contact = self.record(
            self.marys_admin, self.parent, ContactChannel.PHONE, "08031234567"
        )
        self.assertEqual(list(guardian_contacts.resolve_guardians("08031234567")), [])

        _, raw = guardian_contacts.request_verification(contact)
        guardian_contacts.confirm_verification(contact, raw)
        self.assertEqual(
            [a.user for a in guardian_contacts.resolve_guardians("08031234567")],
            [self.parent],
        )

    def test_a_revoked_channel_resolves_to_nobody(self):
        """CONTROL: dropping `contacts__revoked_at__isnull=True` from
        `resolve_guardians()` keeps returning the guardian after the channel is
        replaced, and this goes red.
        """
        contact = self.record(
            self.marys_admin, self.parent, ContactChannel.PHONE, "08031234567"
        )
        _, raw = guardian_contacts.request_verification(contact)
        guardian_contacts.confirm_verification(contact, raw)

        GuardianContact.objects.filter(pk=contact.pk).update(revoked_at=timezone.now())
        self.assertEqual(list(guardian_contacts.resolve_guardians("08031234567")), [])


@override_settings(
    VERIFICATION_SEND_WINDOW=3600,
    MAX_VERIFICATION_SENDS_PER_CHANNEL=3,
    MAX_VERIFICATION_SENDS_PER_SCHOOL=4,
)
class SendsAreRateLimitedTests(TwoSchools):
    """OPEN-3's "rate limiting per number and per school".

    A code is a metered SMS to a real handset, so an unbounded send path is a
    bill, a way to make a stranger's phone ring all afternoon, and the hole
    through `MAX_VERIFICATION_ATTEMPTS` — an attacker out of guesses just asks
    for another code.
    """

    def setUp(self):
        super().setUp()
        self.contact = self.record(
            self.marys_admin, self.parent, ContactChannel.PHONE, "08031234567"
        )

    def test_a_channel_stops_accepting_sends_at_the_limit(self):
        """CONTROL: removing the `_assert_within_send_limits()` call from
        `request_verification()` lets the fourth send through and this goes red.
        """
        for _ in range(3):
            guardian_contacts.request_verification(self.contact)

        with self.assertRaises(guardian_contacts.VerificationRateLimited) as caught:
            guardian_contacts.request_verification(self.contact)
        self.assertGreater(caught.exception.retry_after, 0)
        self.assertLessEqual(caught.exception.retry_after, 3600)

    def test_a_refused_send_mints_nothing_and_spares_the_live_code(self):
        """The limit is checked before anything is written or spent.

        A guardian still holding a good code must not lose it because somebody
        else pushed the channel over its limit — which is what would happen if
        the check ran after the supersede sweep.

        CONTROL: moving `_assert_within_send_limits()` below the
        `.update(status=SPENT)` sweep is **not** enough on its own — the sweep
        does run, but `request_verification()` is `@transaction.atomic` and the
        refusal rolls it back, so the live code survives and this stays green.
        Removing the decorator as well is what turns it red. As with
        `test_a_refused_call_leaves_no_guardian_record_behind`, two mechanisms
        hold this and the atomic block is the load-bearing one; the ordering is
        the statement of intent.
        """
        for _ in range(2):
            guardian_contacts.request_verification(self.contact)
        _, good = guardian_contacts.request_verification(self.contact)
        before = GuardianContactCode.objects.count()

        with self.assertRaises(guardian_contacts.VerificationRateLimited):
            guardian_contacts.request_verification(self.contact)

        self.assertEqual(GuardianContactCode.objects.count(), before)
        # The code the guardian is holding still works.
        self.assertTrue(guardian_contacts.confirm_verification(self.contact, good))

    def test_the_limit_follows_the_handset_not_the_row(self):
        """Two guardians sharing one number share one budget.

        Counting per contact row would hand an attacker two windows for one
        phone, which is `throttling.key_for()`'s reasoning applied to the same
        fact. The cost — one household's sends can make the other wait — is the
        trade `client_address()` already names.

        CONTROL: keying the count on `contact=contact` instead of on
        `contact__value` lets Grace's guardian send a full three to the same
        handset, and this goes red.
        """
        shared = self.record(
            self.grace_admin, self.other_parent, ContactChannel.PHONE, "08031234567"
        )
        self.assertNotEqual(self.contact.pk, shared.pk)
        self.assertEqual(self.contact.value, shared.value)

        for _ in range(3):
            guardian_contacts.request_verification(self.contact)

        with self.assertRaises(guardian_contacts.VerificationRateLimited):
            guardian_contacts.request_verification(shared)

    def test_a_different_number_is_unaffected(self):
        """The limit is per channel, not a global tap. Aimed at the other branch
        of the same filter: without `contact__value` in it at all, every send on
        the platform would share one budget and this would go red.
        """
        for _ in range(3):
            guardian_contacts.request_verification(self.contact)

        elsewhere = self.record(
            self.grace_admin, self.other_parent, ContactChannel.PHONE, "08039998888"
        )
        code, _ = guardian_contacts.request_verification(elsewhere)
        self.assertIsNotNone(code.pk)

    def test_a_school_stops_sending_at_its_own_limit(self):
        """The per-school half, and it is reachable rather than dead code.

        Two tenants is the whole test: St Mary's exhausting its budget must not
        touch Grace's, and the count has to be keyed on the school the authority
        was found at.

        CONTROL: removing the `school_id is None` block's body — the second half
        of `_assert_within_send_limits()` — lets St Mary's send a fifth and this
        goes red.
        """
        # Four sends from St Mary's, spread across channels so the per-channel
        # limit is not what refuses: two guardians at this school, two each.
        second_child = services.enroll_student(
            make_user("STM/2026/0043", "Amaka Eze"), self.st_marys
        )
        second_parent = make_user("amaka-parent", "Uche Eze")
        services.link_guardian(second_parent, second_child)
        other_contact = guardian_contacts.record_contact_as(
            self.marys_admin, second_parent, ContactChannel.PHONE, "08035550001"
        )

        for contact in (self.contact, other_contact):
            for _ in range(2):
                guardian_contacts.request_verification_as(self.marys_admin, contact)

        third_child = services.enroll_student(
            make_user("STM/2026/0044", "Ifeanyi Obi"), self.st_marys
        )
        third_parent = make_user("ifeanyi-parent", "Chioma Obi")
        services.link_guardian(third_parent, third_child)
        third_contact = guardian_contacts.record_contact_as(
            self.marys_admin, third_parent, ContactChannel.PHONE, "08035550002"
        )
        with self.assertRaises(guardian_contacts.VerificationRateLimited):
            guardian_contacts.request_verification_as(self.marys_admin, third_contact)

        # Grace is untouched by St Mary's spending.
        grace_contact = guardian_contacts.record_contact_as(
            self.grace_admin, self.other_parent, ContactChannel.PHONE, "08039998888"
        )
        code, _ = guardian_contacts.request_verification_as(
            self.grace_admin, grace_contact
        )
        self.assertEqual(code.requested_by_school_id, self.grace.pk)

    def test_the_send_is_counted_against_the_school_that_was_entitled_to_it(self):
        """A caller never names the school, so it cannot name someone else's.

        CONTROL: making `request_verification_as()` take a `school_id` argument
        from its caller instead of from the authority check would make this
        assertion meaningless — it is here to pin that the two answers come from
        one pass.
        """
        code, _ = guardian_contacts.request_verification_as(
            self.marys_admin, self.contact
        )
        self.assertEqual(code.requested_by_school_id, self.st_marys.pk)

    def test_platform_staff_are_behind_no_school(self):
        operator = make_user("operator2", "Platform Operator", is_platform_staff=True)
        code, _ = guardian_contacts.request_verification_as(operator, self.contact)
        self.assertIsNone(code.requested_by_school_id)

    def test_an_unauthorised_actor_cannot_send_at_all(self):
        """CONTROL: dropping `_require_authority_over_guardian()` from
        `request_verification_as()` lets Grace's admin send to St Mary's parent
        — and bill it to a school it has no relationship with — and this goes
        red.
        """
        with self.assertRaises(NotPermitted):
            guardian_contacts.request_verification_as(self.grace_admin, self.contact)

    def test_the_window_is_read_per_call(self):
        """A limit that ignored its own setting would be a limit nobody can tune."""
        for _ in range(3):
            guardian_contacts.request_verification(self.contact)
        with override_settings(MAX_VERIFICATION_SENDS_PER_CHANNEL=4):
            code, _ = guardian_contacts.request_verification(self.contact)
            self.assertIsNotNone(code.pk)


class AuthorityIsPerSchoolTests(TwoSchools):
    def test_an_admin_cannot_record_a_channel_for_another_schools_guardian(self):
        """The two-tenant case the whole module is set up for.

        CONTROL: deleting the `_require_authority_over_guardian()` call from
        `record_contact_as()` lets Grace's admin write St Mary's parent's
        channel, and this goes red.
        """
        with self.assertRaises(NotPermitted):
            self.record(
                self.grace_admin, self.parent, ContactChannel.PHONE, "08031234567"
            )

    def test_a_refused_call_leaves_no_guardian_record_behind(self):
        """A refused call creates no guardian record, and **two** things hold that.

        Authority is checked ahead of `guardian_account_for()`, on the ordering
        `services.link_guardian()` argues for — refuse before writing rather
        than write and lean on the rollback. `record_contact_as()` is also
        `@transaction.atomic`, so the rollback would take it back anyway.

        CONTROL: **either one alone leaves this green**, which is worth stating
        because the obvious control does not work. Moving `guardian_account_for()`
        above the check still rolls back; removing the decorator still never
        creates anything. Removing *both* — reorder and drop `@transaction.atomic`
        — is what turns this red, and that is the honest statement of what is
        being relied on here.
        """
        before = GuardianAccount.objects.count()
        with self.assertRaises(NotPermitted):
            self.record(
                self.grace_admin, self.parent, ContactChannel.PHONE, "08031234567"
            )
        self.assertEqual(GuardianAccount.objects.count(), before)
        self.assertFalse(GuardianAccount.objects.filter(user=self.parent).exists())

    def test_the_admin_at_the_childs_school_may(self):
        contact = self.record(
            self.marys_admin, self.parent, ContactChannel.PHONE, "08031234567"
        )
        self.assertEqual(contact.created_by, self.marys_admin)

    def test_a_shared_guardian_is_reachable_by_either_school(self):
        """One parent, a child at each school: both admins have authority."""
        services.link_guardian(self.parent, self.child_at_grace)
        contact = self.record(
            self.grace_admin, self.parent, ContactChannel.PHONE, "08031234567"
        )
        self.assertEqual(contact.created_by, self.grace_admin)

    def test_a_teacher_has_no_authority(self):
        """CONTROL: adding TEACHER to `MEMBERSHIP_GRANTING_ROLES` makes this go red.

        Aimed at the role branch of `can_grant_memberships()`, which is a
        different branch from the school branch two tests above.
        """
        teacher = make_user("marys-teacher", "Ngozi Eze")
        services.grant_membership(teacher, self.st_marys, Role.TEACHER)
        with self.assertRaises(NotPermitted):
            self.record(teacher, self.parent, ContactChannel.PHONE, "08031234567")

    def test_platform_staff_act_across_schools(self):
        operator = make_user("operator", "Platform Operator", is_platform_staff=True)
        contact = self.record(
            operator, self.parent, ContactChannel.PHONE, "08031234567"
        )
        self.assertEqual(contact.created_by, operator)

    def test_platform_staff_reach_a_guardian_with_no_live_child(self):
        """The branch the docstring claimed and the code did not have.

        `can_grant_memberships()` says yes to platform staff at any school, but
        the loop only asks it about schools the guardian has a live child at —
        so for a guardian with none the loop never ran, and platform staff were
        refused by a function documented as being able to act across schools.
        A school admin is still refused: no live child is no relationship.

        CONTROL: removing the `is_platform_staff` short-circuit ahead of the
        loop in `_require_authority_over_guardian()` makes this go red, while
        `test_platform_staff_act_across_schools` above stays green — which is
        why both are here.
        """
        orphaned = make_user("no-children", "Former Guardian")
        self.assertFalse(orphaned.guardianships.exists())

        operator = make_user("operator3", "Platform Operator", is_platform_staff=True)
        contact = self.record(
            operator, orphaned, ContactChannel.PHONE, "08037770001"
        )
        self.assertEqual(contact.created_by, operator)

        with self.assertRaises(NotPermitted):
            self.record(
                self.marys_admin, orphaned, ContactChannel.PHONE, "08037770002"
            )


class DormancyTests(TwoSchools):
    """D9's 180 days, and the two traps in reading it.

    The rule is "suspended after 180 days without a successful authentication",
    and both load-bearing words are easy to lose: *successful* (not "asked for
    a code"), and the fact that it is read at the moment a code is requested
    rather than stamped by a sweep nobody runs.
    """

    def setUp(self):
        super().setUp()
        self.contact = self.verified(
            self.record(
                self.marys_admin, self.parent, ContactChannel.PHONE, "08031234567"
            )
        )

    def verified(self, contact):
        code, raw = guardian_contacts.request_verification(contact)
        self.assertTrue(guardian_contacts.confirm_verification(contact, raw))
        contact.refresh_from_db()
        return contact

    def age_every_answer(self, contact, days):
        """Push every answered code on this channel `days` into the past."""
        stamp = timezone.now() - timedelta(days=days)
        GuardianContactCode.objects.filter(
            contact=contact, status=VerificationCodeStatus.CONFIRMED
        ).update(confirmed_at=stamp)
        return stamp

    def test_a_freshly_verified_channel_is_not_dormant(self):
        """The clock starts at verification, with no special case for it.

        The first verification *is* a successful authentication — a code went
        to the handset and came back — so a channel verified this morning has
        an answer inside the window like any other.
        """
        self.assertFalse(guardian_contacts.is_dormant(self.contact))
        self.assertIsNotNone(guardian_contacts.last_authenticated_at(self.contact))

    def test_a_phone_channel_goes_dormant_and_the_sign_in_door_closes(self):
        """CONTROL: removing the `is_dormant(contact)` branch from
        `request_sign_in_code()` mints a code for a channel that has been silent
        for a year, and this goes red on the `assertRaises`.
        """
        stamp = self.age_every_answer(self.contact, 200)
        self.assertTrue(guardian_contacts.is_dormant(self.contact))

        with self.assertRaises(guardian_contacts.ChannelDormant) as caught:
            guardian_contacts.request_sign_in_code(self.contact)
        self.assertEqual(caught.exception.last_authenticated_at, stamp)
        self.assertFalse(
            GuardianContactCode.objects.filter(
                contact=self.contact, status=VerificationCodeStatus.PENDING
            ).exists()
        )

    def test_the_day_before_the_window_closes_is_still_open(self):
        """The open side of the comparison, which needs its own test.

        CONTROL: dropping the `>= _dormancy_window()` comparison from
        `is_dormant()` — so any channel with an answer behind it is dormant —
        closes the door on a channel used last week, and this goes red. Paired
        with `test_a_phone_channel_goes_dormant_...` above, which goes red if
        the comparison is dropped the other way, that pins the window in both
        directions.

        `>=` against `>` is deliberately **not** pinned. The two differ only for
        a channel whose last answer lands on the exact microsecond, which no
        test can hold without freezing the clock and which means nothing to a
        rule measured in days. An assertion that cannot go red for the right
        reason is worse than no assertion — operating rule 5.
        """
        self.age_every_answer(self.contact, 179)
        self.assertFalse(guardian_contacts.is_dormant(self.contact))
        guardian_contacts.request_sign_in_code(self.contact)

    def test_an_email_channel_never_goes_dormant(self):
        """D9 applies the rule to phones only: email is not churned.

        CONTROL: deleting the `channel_type != ContactChannel.PHONE` early
        return from `is_dormant()` makes this address dormant at the same age as
        the number above, and this goes red.
        """
        email = self.verified(
            self.record(
                self.grace_admin, self.other_parent, ContactChannel.EMAIL, "Ada@Mail.Com"
            )
        )
        self.age_every_answer(email, 400)
        self.assertFalse(guardian_contacts.is_dormant(email))
        guardian_contacts.request_sign_in_code(email)

    def test_asking_for_codes_without_answering_them_does_not_hold_it_open(self):
        """*Successful* authentication, which is the word the fold turns on.

        Somebody holding a reassigned number can request codes all day. If the
        clock read `created_at` they would hold the channel open indefinitely
        and never have to answer one — the exact person the rule exists to put
        a school in front of.

        CONTROL: replacing the fold in `last_authenticated_at()` with
        `contact.codes.aggregate(last=Max("created_at"))` — the natural wrong
        implementation, which loses the status filter and the column together —
        lets the fresh unanswered request below reset the clock, `is_dormant()`
        returns False, and this goes red. Swapping only the column is *not* the
        control: the CONFIRMED filter would still exclude the pending row, and
        this would stay green while the guard was half gone.
        """
        stamp = self.age_every_answer(self.contact, 200)

        # A request minted *now*, never answered. Reached through the school
        # door, because the guardian's own door is already shut.
        guardian_contacts.request_reactivation_as(self.marys_admin, self.contact)

        self.assertEqual(guardian_contacts.last_authenticated_at(self.contact), stamp)
        self.assertTrue(guardian_contacts.is_dormant(self.contact))

    def test_dormancy_is_per_contact_row_where_the_send_limit_is_per_value(self):
        """One handset, two guardians, one of them long gone.

        The two limits in this module fold differently on purpose and this is
        the case that shows why. The send limit counts per *value*, because the
        thing it protects is a handset. Dormancy folds per *row*, because the
        thing it protects is a record — and the record of a parent who left the
        household while the number stayed is precisely the stale one.

        CONTROL: keying `last_authenticated_at()` on
        `contact__value=contact.value` instead of on the row keeps the quiet
        guardian alive on the other one's sign-in, and this goes red.
        """
        shared = self.verified(
            self.record(
                self.grace_admin,
                self.other_parent,
                ContactChannel.PHONE,
                "08031234567",
            )
        )
        self.assertEqual(shared.value, self.contact.value)

        # Both have been quiet for a year. Then one of them signs in.
        self.age_every_answer(self.contact, 200)
        self.age_every_answer(shared, 200)
        _, raw = guardian_contacts.request_reactivation_as(
            self.marys_admin, self.contact
        )
        self.assertIsNotNone(
            guardian_contacts.confirm_sign_in_code(self.contact, raw)
        )

        self.assertFalse(guardian_contacts.is_dormant(self.contact))
        self.assertTrue(guardian_contacts.is_dormant(shared))

    @override_settings(GUARDIAN_DORMANCY_DAYS=10)
    def test_the_window_is_read_per_call(self):
        """CONTROL: hoisting `timedelta(days=settings.GUARDIAN_DORMANCY_DAYS)` to
        module scope makes this read the 180 imported at startup, and red.
        """
        self.age_every_answer(self.contact, 11)
        self.assertTrue(guardian_contacts.is_dormant(self.contact))


class ReactivationTests(TwoSchools):
    """D9's "school-side reactivation before any further code is sent".

    No stamp and no reactivation row: a school admin causes one code to go out,
    and the guardian answering it *is* the reactivation.
    """

    def setUp(self):
        super().setUp()
        self.contact = self.record(
            self.marys_admin, self.parent, ContactChannel.PHONE, "08031234567"
        )
        code, raw = guardian_contacts.request_verification(self.contact)
        guardian_contacts.confirm_verification(self.contact, raw)
        self.contact.refresh_from_db()
        GuardianContactCode.objects.filter(
            contact=self.contact, status=VerificationCodeStatus.CONFIRMED
        ).update(confirmed_at=timezone.now() - timedelta(days=200))

    def test_the_school_sends_and_the_guardian_answering_reactivates(self):
        """The whole loop, and the only way the clock ever moves forward."""
        self.assertTrue(guardian_contacts.is_dormant(self.contact))

        _, raw = guardian_contacts.request_reactivation_as(
            self.marys_admin, self.contact
        )
        code = guardian_contacts.confirm_sign_in_code(self.contact, raw)

        self.assertIsNotNone(code)
        self.assertEqual(code.status, VerificationCodeStatus.CONFIRMED)
        self.assertFalse(guardian_contacts.is_dormant(self.contact))
        guardian_contacts.request_sign_in_code(self.contact)

    def test_an_unanswered_reactivation_reactivates_nothing(self):
        """Falls out of the shape rather than needing a rule: the clock is a
        record of the guardian answering, so only the guardian can move it.
        """
        guardian_contacts.request_reactivation_as(self.marys_admin, self.contact)
        self.assertTrue(guardian_contacts.is_dormant(self.contact))
        with self.assertRaises(guardian_contacts.ChannelDormant):
            guardian_contacts.request_sign_in_code(self.contact)

    def test_a_channel_that_is_not_dormant_cannot_be_reactivated(self):
        """The guard that keeps this from being a send-anything-anytime door.

        Without it any school admin could put a code on any live guardian's
        handset whenever they liked — the only send path here not already
        bounded by the channel's own state.

        CONTROL: deleting the `if not is_dormant(contact)` branch from
        `request_reactivation()` lets the second call below mint a code for a
        channel that has just answered one, and this goes red.
        """
        _, raw = guardian_contacts.request_reactivation_as(
            self.marys_admin, self.contact
        )
        guardian_contacts.confirm_sign_in_code(self.contact, raw)

        with self.assertRaises(guardian_contacts.ChannelNotDormant):
            guardian_contacts.request_reactivation_as(self.marys_admin, self.contact)

    def test_an_unverified_channel_is_not_reactivated_either(self):
        """A channel that never proved itself is unverified, not dormant. It
        goes through D10's door, not this one.

        CONTROL: dropping the `not contact.is_live` branch from
        `request_reactivation()` reaches `is_dormant()`, which answers False for
        a channel with no answered code, so the call raises `ChannelNotDormant`
        instead and this goes red on the exception type.
        """
        fresh = self.record(
            self.grace_admin, self.other_parent, ContactChannel.PHONE, "08037654321"
        )
        with self.assertRaises(guardian_contacts.ChannelNotLive):
            guardian_contacts.request_reactivation_as(self.grace_admin, fresh)

    def test_an_admin_from_another_school_cannot_reactivate(self):
        """CONTROL: dropping `_require_authority_over_guardian()` from
        `request_reactivation_as()` lets Grace wake a St Mary's guardian.
        """
        with self.assertRaises(NotPermitted):
            guardian_contacts.request_reactivation_as(self.grace_admin, self.contact)

    def test_the_reactivation_send_is_counted_against_the_school(self):
        """Same rule as D10's send: the school that was entitled pays for it."""
        code, _ = guardian_contacts.request_reactivation_as(
            self.marys_admin, self.contact
        )
        self.assertEqual(code.requested_by_school_id, self.st_marys.pk)


class TheThreeDoorsTests(TwoSchools):
    """A code carries no purpose column; the channel's state is which door.

    That only holds if each door refuses the state the other one wants. These
    are the tests that make "at most one door can have a pending code" true
    rather than merely likely.
    """

    def setUp(self):
        super().setUp()
        self.contact = self.record(
            self.marys_admin, self.parent, ContactChannel.PHONE, "08031234567"
        )

    def verify(self):
        code, raw = guardian_contacts.request_verification(self.contact)
        self.assertTrue(guardian_contacts.confirm_verification(self.contact, raw))
        self.contact.refresh_from_db()

    def test_a_verification_code_cannot_open_a_session(self):
        """The hole `expect_verified` exists to close.

        Without it, a code minted to *prove* a channel could be spent at the
        sign-in door, and a session would open on a channel whose `verified_at`
        was still NULL — D9's gate passed by the one code that was supposed to
        be closing it.

        CONTROL: deleting the
        `if (locked.verified_at is not None) != expect_verified` branch from
        `_confirm_code()` makes the sign-in door accept this code, and this goes
        red on the `assertIsNone`.
        """
        _, raw = guardian_contacts.request_verification(self.contact)

        self.assertIsNone(
            guardian_contacts.confirm_sign_in_code(self.contact, raw)
        )
        self.contact.refresh_from_db()
        self.assertFalse(self.contact.is_verified)

        # And the code was not spent by the door that refused it, so the right
        # door still works.
        self.assertTrue(guardian_contacts.confirm_verification(self.contact, raw))

    def test_a_sign_in_code_cannot_verify_a_channel(self):
        """The same guard read the other way, which is the second control
        `docs/operating-rules.md` rule 5 asks for: two branches, two tests.

        CONTROL: the same deletion as above makes `confirm_verification()`
        return True here, and this goes red.
        """
        self.verify()
        _, raw = guardian_contacts.request_sign_in_code(self.contact)

        self.assertFalse(guardian_contacts.confirm_verification(self.contact, raw))

        # Not spent either: the sign-in door still has its code.
        self.assertIsNotNone(
            guardian_contacts.confirm_sign_in_code(self.contact, raw)
        )

    def test_the_sign_in_door_refuses_an_unverified_channel(self):
        """CONTROL: dropping `if not contact.is_live` from
        `request_sign_in_code()` mints a sign-in code for a channel nobody has
        ever proved, and this goes red.
        """
        with self.assertRaises(guardian_contacts.ChannelNotLive):
            guardian_contacts.request_sign_in_code(self.contact)

    def test_the_sign_in_door_refuses_a_revoked_channel(self):
        """The other half of `is_live`, and a separate branch from the one
        above — D11 revokes a channel that *had* been verified.
        """
        self.verify()
        GuardianContact.objects.filter(pk=self.contact.pk).update(
            revoked_at=timezone.now()
        )
        self.contact.refresh_from_db()
        with self.assertRaises(guardian_contacts.ChannelNotLive):
            guardian_contacts.request_sign_in_code(self.contact)

    def test_the_verification_door_still_refuses_a_verified_channel(self):
        """PR B's rule, unchanged by the split into three doors."""
        self.verify()
        with self.assertRaises(guardian_contacts.ChannelNotVerifiable):
            guardian_contacts.request_verification(self.contact)

    def test_a_sign_in_code_has_no_school_behind_it(self):
        """A guardian asking for their own code names no school, and cannot.

        CONTROL: giving `request_sign_in_code()` a `school_id` parameter and
        threading it through lets a caller choose whose budget to spend, and
        this goes red.
        """
        self.verify()
        code, _ = guardian_contacts.request_sign_in_code(self.contact)
        self.assertIsNone(code.requested_by_school_id)

    def test_a_sign_in_code_is_spent_once(self):
        """The same one-code-at-a-time rule the verification door has, because
        both reach it through `_mint_code()` rather than each having a copy.
        """
        self.verify()
        _, raw = guardian_contacts.request_sign_in_code(self.contact)
        self.assertIsNotNone(guardian_contacts.confirm_sign_in_code(self.contact, raw))
        self.assertIsNone(guardian_contacts.confirm_sign_in_code(self.contact, raw))

    def test_a_resend_at_the_sign_in_door_kills_the_code_it_replaces(self):
        """CONTROL: removing the `.update(status=SPENT)` sweep from
        `_mint_code()` leaves the first code PENDING, and the two row
        assertions below go red.

        **Those two assertions are the test, and the two `confirm` calls under
        them are not.** This was written the other way round first and the
        control caught it green: `_confirm_code()` takes the newest pending code
        and compares against that one, so presenting the superseded code answers
        `None` whether it was swept or not, and presenting the newest one works
        whether it was swept or not. Both calls pass with the guard deleted. The
        state of the replaced row is the only thing that tells the two worlds
        apart, which is why it is asserted directly rather than inferred from
        behaviour that does not depend on it.

        What the sweep actually buys is in the count: one live code at a time,
        so the attempt cap bounds guessing against a fixed target instead of a
        surface that grows with every resend.
        """
        self.verify()
        first_row, first = guardian_contacts.request_sign_in_code(self.contact)
        guardian_contacts.request_sign_in_code(self.contact)

        first_row.refresh_from_db()
        self.assertEqual(first_row.status, VerificationCodeStatus.SPENT)
        self.assertEqual(
            GuardianContactCode.objects.filter(
                contact=self.contact, status=VerificationCodeStatus.PENDING
            ).count(),
            1,
        )

    @override_settings(
        VERIFICATION_SEND_WINDOW=3600, MAX_VERIFICATION_SENDS_PER_CHANNEL=3
    )
    def test_every_door_spends_the_same_channel_budget(self):
        """One handset, one send limit, however the sends were caused.

        Three doors each keeping their own count would be three times the
        limit on one phone, which is the bound OPEN-3 says must hold against
        `MAX_VERIFICATION_ATTEMPTS`.

        CONTROL: moving `_assert_within_send_limits()` out of `_mint_code()`
        into `request_verification()` alone lets the sign-in sends below run
        free, and this goes red.
        """
        # One send verifies the channel; two more at the sign-in door fill it.
        self.verify()
        guardian_contacts.request_sign_in_code(self.contact)
        guardian_contacts.request_sign_in_code(self.contact)

        with self.assertRaises(guardian_contacts.VerificationRateLimited):
            guardian_contacts.request_sign_in_code(self.contact)


class ASessionMustNotOutliveTheDormancyWindowTests(TestCase):
    """`accounts.E002`. The 30/180 relationship is two settings, not a guard.

    Dormancy is read when a code is requested, so it cannot reach a session
    already open — the session has to lapse on its own first, and that only
    happens if it is the shorter of the two. With the defaults it is, by a long
    way. But both are environment variables, and "it works out" is what this
    check turns into something that fails loudly.
    """

    def run_check(self):
        return checks.a_guardian_session_cannot_outlive_the_dormancy_window(None)

    def test_the_shipped_defaults_are_coherent(self):
        self.assertEqual(self.run_check(), [])

    @override_settings(GUARDIAN_SESSION_AGE=200 * 24 * 60 * 60)
    def test_a_session_outliving_the_window_is_refused(self):
        """CONTROL: returning `[]` unconditionally from the check leaves this
        red, which is the only control a pure settings guard can have.
        """
        self.assertEqual([error.id for error in self.run_check()], ["accounts.E002"])

    @override_settings(GUARDIAN_SESSION_AGE=180 * 24 * 60 * 60)
    def test_exactly_equal_is_refused_too(self):
        """The boundary, so `<` and `<=` are told apart.

        CONTROL: relaxing `GUARDIAN_SESSION_AGE < dormancy` to `<=` leaves the
        two tests above green and turns only this one red. Equal means the last
        possible session opens on the last non-dormant day and expires on the
        first dormant one, which is a coincidence rather than a margin.
        """
        self.assertEqual([error.id for error in self.run_check()], ["accounts.E002"])


class TheLinkDoesNotGoLiveUntilTheChannelDoesTests(TwoSchools):
    """D9's gate, as the thing `link_guardian()` now reads.

    `has_verified_channel()` shipped in PR B with nothing reading it, and the
    docstring said so: "this is the predicate; it is not yet the gate". These
    are the tests that make it one.

    The shape the model already had is the shape this needed. `LIVE_STATUSES`
    holds the relationship and `ACCESS_STATUSES` holds the access, and they were
    kept apart precisely so a relationship can exist before the access does.
    """

    def verified_channel_for(self, admin, parent, value="08031234567"):
        """Recorded and proved **by `admin`'s school**, which is the school the
        answer opens (#135) — the way production asks, not the unscoped door."""
        contact = self.record(admin, parent, ContactChannel.PHONE, value)
        _, raw = guardian_contacts.request_verification_as(admin, contact)
        self.assertTrue(guardian_contacts.confirm_verification(contact, raw))
        return contact

    def parent_membership(self, user, school):
        return Membership.objects.get(user=user, school=school, role=Role.PARENT)

    def test_a_guardian_with_no_channel_has_the_relationship_and_not_the_access(self):
        """The whole of the gate in one assertion pair.

        CONTROL: passing `status=MembershipStatus.ACTIVE` unconditionally in
        `link_guardian()` — which is what it did before this — makes the second
        assertion go red.
        """
        membership = self.parent_membership(self.parent, self.st_marys)
        self.assertEqual(membership.status, MembershipStatus.INVITED)
        self.assertFalse(self.parent.has_access_to(self.st_marys))

    def test_the_child_is_still_on_the_dashboard_while_the_parent_waits(self):
        """`LIVE_STATUSES` against `ACCESS_STATUSES`, which is why INVITED was
        the right state and a refusal was not.

        A school enters the guardian, attaches the child, and only then types a
        phone number — D10's order. If withholding access also hid the child,
        the admin who just attached them would be looking at a screen that says
        it did not work.

        CONTROL: scoping `User.children()` to `ACCESS_STATUSES` makes this go
        red, which is the same control that method's own docstring names.
        """
        self.assertIn(self.child_at_marys, list(self.parent.children()))

    def test_verifying_the_channel_turns_the_link_live(self):
        """CONTROL: removing the `activate_guardian_links()` call from
        `confirm_verification()` leaves the membership INVITED and this goes red.
        """
        self.verified_channel_for(self.marys_admin, self.parent)

        self.assertEqual(
            self.parent_membership(self.parent, self.st_marys).status,
            MembershipStatus.ACTIVE,
        )
        self.assertTrue(self.parent.has_access_to(self.st_marys))

    def test_one_answer_opens_only_the_school_that_asked(self):
        """**Reversed by #135.** This used to assert that one channel turned
        every school live at once. It no longer does, on purpose: Grace linked
        this number too — rightly or by a typo, nothing here can tell — and a
        code St Mary's sent, answered for St Mary's, is not the guardian saying
        yes to Grace's child.

        CONTROL: dropping the `school_id=` filter from
        `activate_guardian_links()` promotes Grace too, and this goes red.
        """
        services.link_guardian(self.parent, self.child_at_grace)

        self.verified_channel_for(self.marys_admin, self.parent)

        self.assertEqual(
            self.parent_membership(self.parent, self.st_marys).status,
            MembershipStatus.ACTIVE,
        )
        self.assertEqual(
            self.parent_membership(self.parent, self.grace).status,
            MembershipStatus.INVITED,
            "an answer to St Mary's opened Grace",
        )
        self.assertFalse(self.parent.has_access_to(self.grace))

    def test_a_guardian_verified_at_one_school_waits_at_the_next(self):
        """**Reversed by #135.** This used to pin the opposite — "the gate
        reads the channel, not the order" — and that was the hole: with
        guardians found by contact, a mistyped number belonging to a verified
        parent elsewhere handed them the child at once, with nobody asked.

        CONTROL: `link_guardian()` granting ACTIVE to a guardian with a
        verified channel — what it did before — makes this go red.
        """
        self.verified_channel_for(self.marys_admin, self.parent)
        services.link_guardian(self.parent, self.child_at_grace)

        self.assertEqual(
            self.parent_membership(self.parent, self.grace).status,
            MembershipStatus.INVITED,
            "a channel proved at St Mary's went live at Grace",
        )
        self.assertFalse(self.parent.has_access_to(self.grace))

    def test_a_code_no_school_asked_for_proves_the_channel_and_opens_nothing(self):
        """Platform staff are behind no school, and neither is the unscoped
        door. The channel is proved; no school has been answered.

        CONTROL: activating every waiting school when `requested_by_school_id`
        is None makes this go red.
        """
        contact = self.record(self.marys_admin, self.parent, ContactChannel.PHONE, "08031234567")
        _, raw = guardian_contacts.request_verification(contact)

        self.assertTrue(guardian_contacts.confirm_verification(contact, raw))

        contact.refresh_from_db()
        self.assertIsNotNone(contact.verified_at)
        self.assertEqual(
            self.parent_membership(self.parent, self.st_marys).status,
            MembershipStatus.INVITED,
        )

    def test_a_suspended_parent_is_not_promoted_by_verifying(self):
        """A suspension is a decision; a phone number is not an answer to it.

        Without this, anybody a school had deliberately suspended could reverse
        it by asking for a code — the guard turns a school's decision into
        something the suspended person can undo themselves.

        CONTROL: widening the filter in `activate_guardian_links()` to
        `status__in=(MembershipStatus.INVITED, MembershipStatus.SUSPENDED)`
        makes this go red.
        """
        Membership.objects.filter(
            user=self.parent, school=self.st_marys, role=Role.PARENT
        ).update(status=MembershipStatus.SUSPENDED)

        self.verified_channel_for(self.marys_admin, self.parent)

        self.assertEqual(
            self.parent_membership(self.parent, self.st_marys).status,
            MembershipStatus.SUSPENDED,
        )
        self.assertFalse(self.parent.has_access_to(self.st_marys))

    def test_verifying_promotes_no_role_but_parent(self):
        """A teacher waiting on an invitation is not waiting on a phone number.

        CONTROL: dropping `role=Role.PARENT` from `activate_guardian_links()`
        makes the invited teacher membership below go ACTIVE, and this red.
        """
        # At St Mary's, the school that asks below, so that the school filter
        # cannot hold this on the role filter's behalf.
        services.grant_membership(
            self.parent,
            self.st_marys,
            Role.TEACHER,
            status=MembershipStatus.INVITED,
        )

        self.verified_channel_for(self.marys_admin, self.parent)

        self.assertEqual(
            Membership.objects.get(
                user=self.parent, school=self.st_marys, role=Role.TEACHER
            ).status,
            MembershipStatus.INVITED,
        )

    def test_one_guardians_verification_does_not_promote_another(self):
        """Two tenants, two guardians, one query — the isolation this class of
        change gets wrong by writing an `.update()` with one filter too few.

        CONTROL: dropping `user=guardian` from `activate_guardian_links()`
        promotes every waiting parent on the platform, and this goes red.

        The other parent waits at **St Mary's**, the school that asks, so that
        the school filter cannot hold this on the user filter's behalf.
        """
        services.link_guardian(self.other_parent, self.child_at_marys)

        self.verified_channel_for(self.marys_admin, self.parent)

        self.assertEqual(
            self.parent_membership(self.other_parent, self.st_marys).status,
            MembershipStatus.INVITED,
        )
        self.assertFalse(self.other_parent.has_access_to(self.st_marys))

    def test_a_wrong_code_promotes_nothing(self):
        """The promotion hangs off the confirmed branch, not off being asked.

        CONTROL: moving `activate_guardian_links()` above the
        `if result is None` return in `confirm_verification()` makes a failed
        guess grant access, and this goes red.
        """
        contact = self.record(
            self.marys_admin, self.parent, ContactChannel.PHONE, "08031234567"
        )
        _, raw = guardian_contacts.request_verification(contact)
        wrong = "0" * len(raw) if raw != "0" * len(raw) else "1" * len(raw)

        self.assertFalse(guardian_contacts.confirm_verification(contact, wrong))
        self.assertEqual(
            self.parent_membership(self.parent, self.st_marys).status,
            MembershipStatus.INVITED,
        )
