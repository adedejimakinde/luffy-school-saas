"""The bell schedule and the timetable. T1, decided 2026-09-24.

Two schools throughout. St Mary's is under test; Grace Academy has its own
teacher and its own class, so a lookup that forgot `school=` would find them.

Claims, each with the test that fails without it:

1. A teacher in two classes at once is refused — at the database — unless it is
   the same subject.
2. The same subject in two classes at once is allowed: a combined lesson.
3. Periods do not overlap, at the database; a period may start the minute the
   last one ends.
4. Copying last term fills an empty term and never writes over one.
5. Admin and the vice principal (academic) edit; the principal and every
   teacher read and are told they may not edit; everybody else gets a flat 404.
6. Another school's teacher cannot be put on this school's timetable, and is
   not named in the refusal.
7. A cloned test schema carries both exclusion constraints
   (`schools.tests.test_tenant_template`, which compares every constraint).
"""

import json
from datetime import date, time

from django.db import connection
from django.test import TestCase

from academics.models import ClassGroup, Term, TermName
from accounts.models import Role, User
from accounts.services import grant_membership
from gradebook.models import Subject
from schools.models import Domain, School
from schools.tests.tenants import connected_to, make_school
from tests.refusals import RefusalAssertions
from timetable import services
from timetable.models import Period, TimetableSlot, Weekday

PASSWORD = "correct-horse-battery"
HOST = "st-marys.testserver"
API = "/api/timetable/"
NOBODY = 10**9


class TimetableSetUp(RefusalAssertions, TestCase):
    def setUp(self):
        self.stmarys = make_school("St Mary's", "st-marys", "st_marys")
        self.grace = make_school("Grace Academy", "grace", "grace")
        Domain.objects.create(tenant=self.stmarys, domain=HOST, is_primary=True)
        portal = School(name="Portal", slug="portal", schema_name="public")
        portal.auto_create_schema = False
        portal.save()
        Domain.objects.create(tenant=portal, domain="testserver", is_primary=True)

        def person(username, name, role, school=None):
            user = User.objects.create_user(username, PASSWORD, full_name=name)
            return grant_membership(user, school or self.stmarys, role)

        self.admin = person("ade", "Ade Admin", Role.ADMIN)
        self.vp = person("vera", "Vera Vp", Role.VICE_PRINCIPAL_ACADEMIC)
        self.principal = person("ngozi", "Ngozi Head", Role.PRINCIPAL)
        self.kemi = person("kemi", "Kemi Maths", Role.TEACHER)
        self.tunde = person("tunde", "Tunde English", Role.TEACHER)
        self.bursar = person("bola", "Bola Bursar", Role.BURSAR)
        self.parent = person("uche", "Uche Parent", Role.PARENT)
        self.student = person("ada", "Ada Obi", Role.STUDENT)
        self.their_teacher = person("zara", "Zara Grace", Role.TEACHER, school=self.grace)

        with connected_to(self.stmarys):
            self.first = Term.objects.create(
                session="2025/2026", name=TermName.FIRST,
                starts_on=date(2025, 9, 15), ends_on=date(2025, 12, 12), is_current=True,
            )
            self.second = Term.objects.create(
                session="2025/2026", name=TermName.SECOND,
                starts_on=date(2026, 1, 5), ends_on=date(2026, 4, 2),
            )
            self.jss1a = ClassGroup.objects.create(name="JSS 1A", level=1)
            self.jss1b = ClassGroup.objects.create(name="JSS 1B", level=1)
            self.maths = Subject.objects.create(name="Mathematics", code="MTH")
            self.english = Subject.objects.create(name="English", code="ENG")
            self.p1 = Period.objects.create(starts_at=time(8, 0), ends_at=time(8, 40), label="Period 1")
            # A five-minute changeover, so that nothing but the one test
            # about it depends on back-to-back periods being allowed.
            self.p2 = Period.objects.create(starts_at=time(8, 45), ends_at=time(9, 25), label="Period 2")
        with connected_to(self.grace):
            self.their_class = ClassGroup.objects.create(name="JSS 1A", level=1)

    def tearDown(self):
        connection.set_schema_to_public()

    # -- helpers --------------------------------------------------------------

    def lesson(self, group, subject, teacher, *, weekday=Weekday.MONDAY, period=None, term=None):
        """A row straight into the table, past every service: what the
        database alone allows."""
        return TimetableSlot.objects.create(
            term=term or self.first,
            class_group=group,
            weekday=weekday,
            period=period or self.p1,
            subject=subject,
            teacher_membership_id=teacher.pk,
        )

    def get(self, member, path, host=HOST):
        self.client.force_login(member.user)
        return self.client.get(f"{API}{path}", HTTP_HOST=host)

    def put(self, member, path, body, host=HOST):
        self.client.force_login(member.user)
        return self.client.put(
            f"{API}{path}", data=json.dumps(body), content_type="application/json", HTTP_HOST=host
        )

    def put_lesson(self, member, group=None, **overrides):
        body = {
            "term_id": self.first.pk,
            "weekday": Weekday.MONDAY,
            "period_id": self.p1.pk,
            "subject_id": self.maths.pk,
            "teacher_membership_id": self.kemi.pk,
        }
        body.update(overrides)
        return self.put(member, f"classes/{(group or self.jss1a).pk}/lessons/", body)

    def missing(self):
        """The body an administrator gets for a class that does not exist."""
        answer = self.get(self.admin, f"classes/{NOBODY}/?term_id={self.first.pk}")
        self.assertEqual(answer.status_code, 404, "the fixture's refusal moved")
        return answer.content

    def slots(self, school=None):
        with connected_to(school or self.stmarys):
            return list(TimetableSlot.objects.order_by("pk"))


class TheClashRuleTests(TimetableSetUp):
    """Claims 1 and 2, at the database: rows written straight into the table."""

    def test_a_teacher_in_two_classes_at_once_is_refused(self):
        """CONTROL 1: dropping the exclusion constraint makes this red."""
        with connected_to(self.stmarys):
            self.lesson(self.jss1a, self.maths, self.kemi)

            with self.assertRefusedBy("a_teacher_teaches_one_subject_at_a_time"):
                self.lesson(self.jss1b, self.english, self.kemi)

    def test_the_same_subject_in_two_classes_at_once_is_one_combined_lesson(self):
        """CONTROL 2: an exclusion constraint without `subject WITH <>` — a
        teacher in one room at a time, full stop — makes this red."""
        with connected_to(self.stmarys):
            self.lesson(self.jss1a, self.maths, self.kemi)
            self.lesson(self.jss1b, self.maths, self.kemi)

            self.assertEqual(TimetableSlot.objects.filter(teacher_membership_id=self.kemi.pk).count(), 2)

    def test_the_clash_is_per_slot(self):
        """The rule does not reach past its own slot: the next period, another
        day and another term are all free for the same teacher."""
        with connected_to(self.stmarys):
            self.lesson(self.jss1a, self.maths, self.kemi)
            self.lesson(self.jss1b, self.english, self.kemi, period=self.p2)
            self.lesson(self.jss1b, self.english, self.kemi, weekday=Weekday.TUESDAY)
            self.lesson(self.jss1b, self.english, self.kemi, term=self.second)

            self.assertEqual(TimetableSlot.objects.count(), 4)

    def test_a_class_has_one_lesson_at_a_time(self):
        with connected_to(self.stmarys):
            self.lesson(self.jss1a, self.maths, self.kemi)

            with self.assertRefusedBy("one_lesson_per_class_per_slot"):
                self.lesson(self.jss1a, self.english, self.tunde)

    def test_a_double_period_is_two_slots_and_a_free_period_is_none(self):
        with connected_to(self.stmarys):
            self.lesson(self.jss1a, self.maths, self.kemi, period=self.p1)
            self.lesson(self.jss1a, self.maths, self.kemi, period=self.p2)

            self.assertEqual(TimetableSlot.objects.filter(weekday=Weekday.MONDAY).count(), 2)
            self.assertFalse(TimetableSlot.objects.filter(weekday=Weekday.TUESDAY).exists())

    def test_saturday_is_not_a_school_day(self):
        with connected_to(self.stmarys):
            with self.assertRefusedBy("a_weekday_is_a_school_day"):
                self.lesson(self.jss1a, self.maths, self.kemi, weekday=6)


class TheBellScheduleTests(TimetableSetUp):
    """Claim 3."""

    def test_two_periods_at_once_are_refused(self):
        with connected_to(self.stmarys):
            with self.assertRefusedBy("periods_do_not_overlap"):
                Period.objects.create(starts_at=time(8, 20), ends_at=time(9, 0))

    def test_a_period_may_start_the_minute_the_last_one_ends(self):
        """`[)`: 08:45–09:25 and 09:25–10:05 share an instant and no time.

        CONTROL 3: a closed range (`[]`) makes this red — every school's
        back-to-back periods would be refused as overlapping.
        """
        with connected_to(self.stmarys):
            Period.objects.create(starts_at=time(9, 25), ends_at=time(10, 5))

            self.assertEqual(Period.objects.count(), 3)

    def test_a_period_ends_after_it_starts(self):
        with connected_to(self.stmarys):
            with self.assertRefusedBy("a_period_ends_after_it_starts"):
                Period.objects.create(starts_at=time(11, 0), ends_at=time(10, 0))

    def test_the_service_says_so_in_a_sentence(self):
        with connected_to(self.stmarys):
            with self.assertRaises(services.PeriodsOverlap):
                services.add_period(time(8, 30), time(9, 0))

    def test_a_period_with_lessons_in_it_is_not_removed(self):
        with connected_to(self.stmarys):
            self.lesson(self.jss1a, self.maths, self.kemi)

            with self.assertRaises(services.PeriodInUse):
                services.remove_period(self.p1)
            services.remove_period(self.p2)

            self.assertEqual(list(Period.objects.all()), [self.p1])

    def test_each_school_keeps_its_own_bell(self):
        with connected_to(self.grace):
            Period.objects.create(starts_at=time(8, 20), ends_at=time(9, 0))

            self.assertEqual(Period.objects.count(), 1)


class SettingALessonTests(TimetableSetUp):
    def test_a_clash_is_a_sentence_naming_what_it_clashed_with(self):
        with connected_to(self.stmarys):
            services.set_lesson(self.first, self.jss1a, Weekday.MONDAY, self.p1, self.maths, self.kemi)

            with self.assertRaises(services.TeacherIsElsewhere) as refused:
                services.set_lesson(self.first, self.jss1b, Weekday.MONDAY, self.p1, self.english, self.kemi)

        self.assertIn("Mathematics to JSS 1A", str(refused.exception))
        self.assertEqual(len(self.slots()), 1)

    def test_a_combined_lesson_is_set_like_any_other(self):
        with connected_to(self.stmarys):
            services.set_lesson(self.first, self.jss1a, Weekday.MONDAY, self.p1, self.maths, self.kemi)
            _, created = services.set_lesson(
                self.first, self.jss1b, Weekday.MONDAY, self.p1, self.maths, self.kemi
            )

        self.assertTrue(created)
        self.assertEqual(len(self.slots()), 2)

    def test_setting_a_slot_again_replaces_it(self):
        with connected_to(self.stmarys):
            services.set_lesson(self.first, self.jss1a, Weekday.MONDAY, self.p1, self.maths, self.kemi)
            slot, created = services.set_lesson(
                self.first, self.jss1a, Weekday.MONDAY, self.p1, self.english, self.tunde
            )

        self.assertFalse(created)
        [only] = self.slots()
        self.assertEqual((only.subject_id, only.teacher_membership_id), (self.english.pk, self.tunde.pk))

    def test_a_teacher_who_has_left_is_not_timetabled(self):
        self.kemi.end()
        with connected_to(self.stmarys):
            with self.assertRaises(services.NotThisSchoolsTeacher):
                services.set_lesson(self.first, self.jss1a, Weekday.MONDAY, self.p1, self.maths, self.kemi)

    def test_a_bursar_is_not_a_teacher(self):
        with connected_to(self.stmarys):
            with self.assertRaises(services.NotThisSchoolsTeacher):
                services.set_lesson(self.first, self.jss1a, Weekday.MONDAY, self.p1, self.maths, self.bursar)

    def test_another_schools_teacher_is_refused_by_the_service(self):
        with connected_to(self.stmarys):
            with self.assertRaises(services.NotThisSchoolsTeacher):
                services.set_lesson(
                    self.first, self.jss1a, Weekday.MONDAY, self.p1, self.maths, self.their_teacher
                )


class CopyingLastTermTests(TimetableSetUp):
    """Claim 4."""

    def fill_first_term(self):
        with connected_to(self.stmarys):
            self.lesson(self.jss1a, self.maths, self.kemi)
            self.lesson(self.jss1a, self.maths, self.kemi, period=self.p2)
            self.lesson(self.jss1b, self.english, self.tunde)

    def test_an_empty_term_is_filled_from_the_last(self):
        self.fill_first_term()
        with connected_to(self.stmarys):
            done = services.copy_last_term(self.second, by=self.admin.user)

            copied = list(TimetableSlot.objects.filter(term=self.second).order_by("class_group", "period__starts_at"))
            self.assertEqual(done.from_term, self.first)
        self.assertEqual(done.copied, 3)
        self.assertEqual(
            [(s.class_group_id, s.weekday, s.period_id, s.subject_id, s.teacher_membership_id) for s in copied],
            [
                (self.jss1a.pk, Weekday.MONDAY, self.p1.pk, self.maths.pk, self.kemi.pk),
                (self.jss1a.pk, Weekday.MONDAY, self.p2.pk, self.maths.pk, self.kemi.pk),
                (self.jss1b.pk, Weekday.MONDAY, self.p1.pk, self.english.pk, self.tunde.pk),
            ],
        )
        self.assertEqual(len(self.slots()), 6, "the first term's own lessons moved")

    def test_a_term_with_lessons_is_never_written_over(self):
        """CONTROL 4: dropping the emptiness check makes this red."""
        self.fill_first_term()
        with connected_to(self.stmarys):
            self.lesson(self.jss1a, self.english, self.tunde, term=self.second)

            with self.assertRaises(services.TimetableNotEmpty):
                services.copy_last_term(self.second)

            self.assertEqual(TimetableSlot.objects.filter(term=self.second).count(), 1)

    def test_what_has_gone_is_left_behind_and_counted(self):
        self.fill_first_term()
        self.tunde.end()
        with connected_to(self.stmarys):
            Subject.objects.filter(pk=self.maths.pk).update(is_active=False)

            done = services.copy_last_term(self.second)

        self.assertEqual((done.copied, done.skipped_subject, done.skipped_teacher), (0, 2, 1))

    def test_a_lesson_naming_another_schools_teacher_is_not_carried_forward(self):
        """The copy's teacher read is scoped to the schema being written. A row
        naming Grace's teacher could only be here by a write that went round
        the service, and the copy must not make a second one.

        CONTROL 8: the read losing `school__schema_name=` makes this red."""
        with connected_to(self.stmarys):
            self.lesson(self.jss1a, self.maths, self.their_teacher)

            done = services.copy_last_term(self.second)

            self.assertFalse(TimetableSlot.objects.filter(term=self.second).exists())
        self.assertEqual((done.copied, done.skipped_teacher), (0, 1))

    def test_the_first_term_there_is_has_nothing_to_copy(self):
        with connected_to(self.stmarys):
            with self.assertRaises(services.NoEarlierTerm):
                services.copy_last_term(self.first)


class WhoMayReadTests(TimetableSetUp):
    """Claim 5, the reading half."""

    def test_every_teacher_and_the_people_who_run_the_school_read_it(self):
        for member in (self.kemi, self.tunde, self.principal, self.vp, self.admin):
            with self.subTest(member=member.user.username):
                self.assertEqual(self.get(member, "").status_code, 200)
                self.assertEqual(
                    self.get(member, f"classes/{self.jss1a.pk}/?term_id={self.first.pk}").status_code, 200
                )

    def test_everybody_else_gets_the_flat_404(self):
        """CONTROL 5: the routes skipping the read check make this red."""
        missing = self.missing()

        for member in (self.bursar, self.parent, self.student):
            with self.subTest(member=member.user.username):
                for path in ("", f"classes/{self.jss1a.pk}/?term_id={self.first.pk}"):
                    answer = self.get(member, path)

                    self.assertEqual(answer.status_code, 404)
                    self.assertEqual(answer.content, missing)

    def test_there_is_no_timetable_on_the_portal(self):
        self.assertEqual(self.get(self.admin, "", host="testserver").status_code, 404)

    def test_a_week_is_every_lesson_with_its_teacher(self):
        with connected_to(self.stmarys):
            self.lesson(self.jss1a, self.maths, self.kemi)
            self.lesson(self.jss1a, self.english, self.tunde, weekday=Weekday.FRIDAY, period=self.p2)

        body = self.get(self.tunde, f"classes/{self.jss1a.pk}/?term_id={self.first.pk}").json()

        self.assertEqual(
            [(l["weekday"], l["period_id"], l["code"], l["teacher"]) for l in body["lessons"]],
            [(1, self.p1.pk, "MTH", "Kemi Maths"), (5, self.p2.pk, "ENG", "Tunde English")],
        )

    def test_a_reader_gets_no_list_of_teachers_to_choose_from(self):
        body = self.get(self.kemi, "").json()

        self.assertFalse(body["may_edit"])
        self.assertEqual((body["subjects"], body["teachers"]), ([], []))


class WhoMayEditTests(TimetableSetUp):
    """Claim 5, the writing half, and claim 6."""

    def test_the_administrator_and_the_vp_set_lessons(self):
        for member, group in ((self.admin, self.jss1a), (self.vp, self.jss1b)):
            with self.subTest(member=member.user.username):
                answer = self.put_lesson(member, group, subject_id=self.maths.pk)

                self.assertEqual(answer.status_code, 201, answer.content)
        self.assertEqual(len(self.slots()), 2, "a combined lesson was refused")

    def test_the_principal_and_a_teacher_are_told_they_may_not(self):
        """CONTROL 6: the write routes skipping the edit check makes this red."""
        for member in (self.principal, self.kemi):
            with self.subTest(member=member.user.username):
                answer = self.put_lesson(member)

                self.assertEqual(answer.status_code, 403)
                self.assertEqual(
                    answer.json(),
                    {"detail": "The timetable is set by an administrator or the vice principal (academic)."},
                )
        self.assertEqual(self.slots(), [])

    def test_a_bursar_editing_gets_the_flat_404(self):
        missing = self.missing()

        answer = self.put_lesson(self.bursar)

        self.assertEqual(answer.status_code, 404)
        self.assertEqual(answer.content, missing)
        self.assertEqual(self.slots(), [])

    def test_a_clash_is_a_409_that_names_the_other_lesson(self):
        self.put_lesson(self.admin, self.jss1a)

        answer = self.put_lesson(self.admin, self.jss1b, subject_id=self.english.pk)

        self.assertEqual(answer.status_code, 409)
        self.assertIn("Mathematics to JSS 1A", answer.json()["detail"])
        self.assertEqual(len(self.slots()), 1)

    def test_another_schools_teacher_is_not_found_and_not_named(self):
        """Claim 6. CONTROL 7: the teacher lookup losing `school=` makes this
        red — the service would refuse her, but by naming her school."""
        answer = self.put_lesson(self.admin, teacher_membership_id=self.their_teacher.pk)

        self.assertEqual(answer.status_code, 422)
        self.assertEqual(answer.json(), {"detail": "Choose one of the school's teachers."})
        self.assertNotIn(b"Zara", answer.content)
        self.assertNotIn(b"Grace", answer.content)
        self.assertEqual(self.slots(), [])
        self.assertEqual(self.slots(school=self.grace), [])

    def test_a_class_that_is_not_ours_is_the_flat_404(self):
        """A class id is a row in this school's own table, so another school's
        class is simply an id this school does not have."""
        missing = self.missing()

        answer = self.put_lesson(self.admin, ClassGroup(pk=NOBODY))

        self.assertEqual(answer.status_code, 404)
        self.assertEqual(answer.content, missing)
        self.assertEqual(self.slots(), [])

    def test_clearing_a_slot_makes_it_a_free_period(self):
        self.put_lesson(self.admin)
        self.client.force_login(self.admin.user)

        answer = self.client.delete(
            f"{API}classes/{self.jss1a.pk}/lessons/?term_id={self.first.pk}&weekday=1&period_id={self.p1.pk}",
            HTTP_HOST=HOST,
        )

        self.assertEqual(answer.status_code, 204)
        self.assertEqual(self.slots(), [])

    def test_copying_is_offered_only_into_an_empty_term_and_says_what_it_did(self):
        self.put_lesson(self.admin)
        self.assertTrue(self.get(self.admin, f"?term_id={self.second.pk}").json()["term_is_empty"])
        self.client.force_login(self.admin.user)

        done = self.client.post(f"{API}terms/{self.second.pk}/copy/", HTTP_HOST=HOST)
        again = self.client.post(f"{API}terms/{self.second.pk}/copy/", HTTP_HOST=HOST)

        self.assertEqual(done.status_code, 201)
        self.assertEqual(done.json()["copied"], 1)
        self.assertEqual(again.status_code, 409)
        self.assertFalse(self.get(self.admin, f"?term_id={self.second.pk}").json()["term_is_empty"])

    def test_the_bell_is_set_by_the_same_people(self):
        answer = self.client.post(
            f"{API}periods/",
            data=json.dumps({"starts_at": "09:30", "ends_at": "10:10", "label": "Period 3"}),
            content_type="application/json",
            HTTP_HOST=HOST,
        )
        self.assertEqual(answer.status_code, 401)

        self.client.force_login(self.principal.user)
        refused = self.client.post(
            f"{API}periods/",
            data=json.dumps({"starts_at": "09:30", "ends_at": "10:10"}),
            content_type="application/json",
            HTTP_HOST=HOST,
        )
        self.client.force_login(self.vp.user)
        added = self.client.post(
            f"{API}periods/",
            data=json.dumps({"starts_at": "09:30", "ends_at": "10:10", "label": "Period 3"}),
            content_type="application/json",
            HTTP_HOST=HOST,
        )
        overlapping = self.client.post(
            f"{API}periods/",
            data=json.dumps({"starts_at": "09:00", "ends_at": "09:30"}),
            content_type="application/json",
            HTTP_HOST=HOST,
        )

        self.assertEqual(refused.status_code, 403)
        self.assertEqual(added.status_code, 201)
        self.assertEqual(added.json()["starts_at"], "09:30")
        self.assertEqual(overlapping.status_code, 422)


class TheFrameTests(TimetableSetUp):
    def test_the_frame_names_no_lesson(self):
        with connected_to(self.stmarys):
            self.lesson(self.jss1a, self.maths, self.kemi)
        self.client.force_login(self.kemi.user)

        page = self.client.get("/timetable/", HTTP_HOST=HOST).content.decode()

        self.assertIn('id="timetable"', page)
        self.assertIn('data-on-school="yes"', page)
        for absent in ("Mathematics", "JSS 1A", "Kemi", "St Mary"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, page)
        # Not `}}`: the import map is JSON and ends in two braces.
        for delimiter in ("{#", "#}", "{%"):
            with self.subTest(delimiter=delimiter):
                self.assertNotIn(delimiter, page)

    def test_the_portal_frame_says_it_is_not_a_school(self):
        page = self.client.get("/timetable/", HTTP_HOST="testserver").content.decode()

        self.assertIn('data-on-school=""', page)
