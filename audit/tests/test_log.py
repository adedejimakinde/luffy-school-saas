"""The setup log: written with who and when, kept in each school's own schema,
and never changed or removed, in Python or in Postgres.

## Controls

- The trigger migration's `CREATE TRIGGER` operation was removed and the
  template rebuilt: the trigger, raw-SQL and bulk-update tests went red;
  restored.
- `Change.save()` lost its second-save refusal: `test_a_row_is_not_saved_twice`
  went red; restored.
"""

from django.db import DatabaseError, connection, transaction
from django.test import TestCase

from accounts.models import Role, User
from accounts.services import grant_membership
from audit import log
from audit.models import Change, ChangeIsKept
from schools.models import School
from schools.tests.tenants import connected_to, make_school

PASSWORD = "a-long-password-1"


class LogSetUp(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = make_school("Sunrise College", "sunrise", "sunrise")
        cls.b = make_school("Harbour College", "harbour", "harbour")
        cls.principal = grant_membership(
            User.objects.create_user("kunle", PASSWORD, full_name="Kunle Lawal"), cls.a, Role.PRINCIPAL,
        ).user

    def tearDown(self):
        connection.set_schema_to_public()

    def write(self, school=None):
        return log.record(
            self.principal, school or self.a, action="renamed", kind="class",
            item_name="JSS 1A", summary="Renamed JSS 1A to JSS 1 Gold.",
            before={"name": "JSS 1A"}, after={"name": "JSS 1 Gold"},
        )


class WhoAndWhenTests(LogSetUp):
    def test_a_row_says_who_did_what_and_when(self):
        self.write()

        with connected_to(self.a):
            row = Change.objects.get()
        self.assertEqual(row.by_id, self.principal.pk)
        self.assertEqual(row.by_name, "Kunle Lawal")
        self.assertEqual(row.by_roles, "principal")
        self.assertEqual(row.summary, "Renamed JSS 1A to JSS 1 Gold.")
        self.assertEqual(row.before, {"name": "JSS 1A"})
        self.assertIsNotNone(row.at)

    def test_written_from_the_portal_it_lands_in_the_schools_own_schema(self):
        connection.set_schema_to_public()
        self.write()

        with connected_to(self.a):
            self.assertEqual(Change.objects.count(), 1)
        with connected_to(self.b):
            self.assertEqual(Change.objects.count(), 0)

    def test_one_schools_log_is_not_on_anothers_connection(self):
        self.write(self.b)

        with connected_to(self.a):
            self.assertEqual(Change.objects.count(), 0)


class AppendOnlyTests(LogSetUp):
    def test_a_row_is_not_saved_twice(self):
        row = self.write()
        with connected_to(self.a):
            row.summary = "Something else."
            with self.assertRaises(ChangeIsKept):
                row.save()

    def test_a_row_is_not_deleted(self):
        row = self.write()
        with connected_to(self.a):
            with self.assertRaises(ChangeIsKept):
                row.delete()

    def test_postgres_refuses_an_update(self):
        self.write()
        with connected_to(self.a):
            with self.assertRaises(DatabaseError) as caught, transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("UPDATE audit_change SET summary = 'rewritten'")
            self.assertIn("append-only", str(caught.exception))
            self.assertEqual(Change.objects.get().summary, "Renamed JSS 1A to JSS 1 Gold.")

    def test_postgres_refuses_a_delete_and_a_bulk_delete(self):
        self.write()
        with connected_to(self.a):
            with self.assertRaises(DatabaseError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("DELETE FROM audit_change")
            with self.assertRaises(DatabaseError), transaction.atomic():
                Change.objects.all().update(summary="bulk")
            self.assertEqual(Change.objects.count(), 1)

    def test_every_school_gets_the_trigger(self):
        for school in (self.a, self.b):
            with connected_to(school):
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT count(*) FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE t.tgname = 'audit_change_append_only' AND n.nspname = %s",
                        [school.schema_name],
                    )
                    self.assertEqual(cursor.fetchone()[0], 1)


class TheEmailAndTheCrestAreLoggedTests(LogSetUp):
    def test_saving_and_clearing_the_contact_email_is_logged(self):
        from schools.contact import set_contact_email_as

        school = School.objects.get(pk=self.a.pk)
        set_contact_email_as(self.principal, school, "office@sunrise.example")
        set_contact_email_as(self.principal, school, "office@sunrise.example")
        set_contact_email_as(self.principal, school, "")

        with connected_to(self.a):
            rows = list(Change.objects.order_by("id").values_list("action", "kind", "by_id"))
        self.assertEqual(rows, [
            ("saved", "contact-email", self.principal.pk),
            ("cleared", "contact-email", self.principal.pk),
        ])
