"""The master broadsheet: one class and term, on screen, as a PDF and as Excel. `docs/broadsheet.md`.

Two schools throughout, St Mary's and Grace, from `ReportCardApiSetUp`, and a
class built to make the hard cases real rather than assumed:

| child | maths | english | so |
| --- | --- | --- | --- |
| Zainab | whole, best | whole, best | ranked 1st, last by name |
| Ada | whole | whole | ranked 2nd |
| Bola | whole, 61.82 | whole, 54.17 | ranked 3rd, **tied with Chidi** |
| Chidi | the same marks as Bola | the same | ranked 3rd (dense: no 4th) |
| Dayo | **no paper at all** | exam only, CA 1 **not marked** | no total, no average, no place |

- **Who**: the principal, the vice principal (academic) and the administrator
  for any class, a class teacher for their own, nobody else; asked on the view,
  on starting a PDF, on starting an Excel file, and on fetching either.
- **The cards**: every total, average and position is the report card's, the
  same before the class is released as on the card it then writes.
- **Ties and gaps**: the card's tie rule; a missing paper is "-", never 0, and
  nothing is ranked on a subject the child did not sit.
- **The setting**: the school hides positions, so the column and the payload
  field are not there, and the rows are not in rank order either.
- **Preview**: every page of an unreleased PDF carries the stamp; none after.
- **Excel**: opens, with the header the PDF has and a row for every child.
- **Two schools**: `TwoSchoolsTests.test_a_principal_elsewhere_who_is_a_parent_here`
  is the one that fails when the authority asks roles at every school.
"""

import io
from datetime import timedelta
from decimal import Decimal

import pikepdf
from openpyxl import load_workbook
from django.utils import timezone

from academics.models import ClassGroup, Term, TermName
from academics.services import assign_class_teacher, place_student
from accounts.models import Membership, Role, User
from accounts.services import enroll_student, grant_membership, link_guardian
from files import service as files_service
from files import storage
from files.models import StoredFile
from results import broadsheet, broadsheet_files, class_print, look, ogun, positions
from results.models import ClassCardPrint, PrintKind, PrintState, ReleasedCard, ReleasedSubjectResult
from results.tests.test_card_api import HOST, PASSWORD, THEIR_HOST
from results.tests.test_class_print import ClassPrintSetUp, body, stamped
from schools.tests.tenants import connected_to
from tests.guardians import give_verified_channel

FIRST = TermName.FIRST.value


class BroadsheetSetUp(ClassPrintSetUp):
    def setUp(self):
        super().setUp()
        # Ada and Bola exist, with Ada's Project the only paper of its kind.
        # Complete it, so that both are whole and the class can be ranked.
        self._mark(self.stmarys, FIRST, self.bola, "maths", "Project", 7, out_of=10)
        # A second paper in English, so CA and Exam are two different things.
        for child, value in ((self.ada, 15), (self.bola, 10)):
            self._mark(self.stmarys, FIRST, child, "english", "CA 1", value, out_of=20)
        self.chidi = self._child(self.stmarys, "chidi", "Chidi Eze")
        self.zainab = self._child(self.stmarys, "zainab", "Zainab Yusuf")
        self.dayo = self._child(self.stmarys, "dayo", "Dayo Bello")
        # Chidi: exactly Bola's marks, so they tie.
        self._mark(self.stmarys, FIRST, self.chidi, "maths", "Exam", 61)
        self._mark(self.stmarys, FIRST, self.chidi, "maths", "Project", 7, out_of=10)
        self._mark(self.stmarys, FIRST, self.chidi, "english", "Exam", 55)
        self._mark(self.stmarys, FIRST, self.chidi, "english", "CA 1", 10, out_of=20)
        # Zainab: best in both, last in the alphabet.
        self._mark(self.stmarys, FIRST, self.zainab, "maths", "Exam", 95)
        self._mark(self.stmarys, FIRST, self.zainab, "maths", "Project", 10, out_of=10)
        self._mark(self.stmarys, FIRST, self.zainab, "english", "Exam", 80)
        self._mark(self.stmarys, FIRST, self.zainab, "english", "CA 1", 18, out_of=20)
        # Dayo: sat English's exam only. No maths paper, and CA 1 is not marked.
        self._mark(self.stmarys, FIRST, self.dayo, "english", "Exam", 40)

        # A second class, with a child and a teacher of its own, and a third
        # that nobody is in.
        self.other_group_id, self.other_teacher = self._second_class()
        with connected_to(self.stmarys):
            self.empty_group_id = ClassGroup.objects.create(name="JSS 3A", level=3).pk

    def _second_class(self):
        teacher = self._one_staff(self.stmarys, "second", Role.TEACHER)
        femi = enroll_student(User.objects.create_user("femi", PASSWORD, full_name="Femi Ola"), self.stmarys)
        with connected_to(self.stmarys):
            group = ClassGroup.objects.create(name="JSS 2A", level=2)
            membership = teacher.memberships.get(school=self.stmarys, role=Role.TEACHER)
            for term in Term.objects.all():
                assign_class_teacher(group, term, membership)
                place_student(group, term, femi)
        self._mark(self.stmarys, FIRST, femi, "maths", "Exam", 70)
        return group.pk, teacher

    # -- the calls ---------------------------------------------------------------

    def term_id(self, school=None):
        return self.terms_of(school or self.stmarys)[FIRST]

    def sheet_url(self, school=None, group_id=None):
        school = school or self.stmarys
        group_id = group_id or (self.group_id if school == self.stmarys else self.their_group_id)
        return f"/api/results/master-broadsheet/{group_id}/{self.term_id(school)}/"

    def view(self, user, school=None, group_id=None, host=None):
        school = school or self.stmarys
        self.as_(user)
        return self.client.get(self.sheet_url(school, group_id), HTTP_HOST=host or self.host(school))

    def ask(self, user, fmt="pdf", paper="A4", school=None, group_id=None, host=None):
        school = school or self.stmarys
        self.as_(user)
        return self.client.post(
            self.sheet_url(school, group_id) + "files/",
            {"format": fmt, "paper": paper},
            content_type="application/json",
            HTTP_HOST=host or self.host(school),
        )

    def made(self, user, fmt="pdf", paper="A4", school=None):
        """Ask, run the job, download. Returns `(job, bytes)`."""
        school = school or self.stmarys
        response = self.ask(user, fmt, paper, school)
        self.assertEqual(response.status_code, 202, response.content)
        job_id = response.json()["id"]
        self.run_job(job_id, school)
        status = self.status(user, job_id, school).json()
        self.assertEqual(status["state"], "ready", status)
        got = self.client.get(status["download_url"], HTTP_HOST=self.host(school))
        self.assertEqual(got.status_code, 200, None if got.status_code == 200 else got.content[:300])
        with connected_to(school):
            job = ClassCardPrint.objects.get(pk=job_id)
        return job, body(got)

    def show_positions(self, on=True):
        with connected_to(self.stmarys):
            look.set_show_position_as(self.principal, self.stmarys, on)

    def build(self, school=None):
        school = school or self.stmarys
        with connected_to(school):
            return broadsheet.build(self.group_of(school), self.term_of(school, FIRST))

    def names(self, sheet):
        return [row.name for row in sheet.rows]

    def page_text(self, paper="A3"):
        """What the PDF is drawn from, as text: the HTML WeasyPrint is given.

        The PDF's own text is not searchable without a PDF reader this project
        does not carry, and the file is made from exactly this string
        (`broadsheet_files.write_pdf`), the way the cards' tests read
        `pdf.html_for()`. The file itself is opened by the page tests.
        """
        return broadsheet_files.html_for(self.build(), paper)


class WhoMaySeeTests(BroadsheetSetUp):
    def test_the_office_and_the_class_teacher_may_read_print_and_export(self):
        for user in (self.principal, self.vp, self.admin, self.teacher):
            with self.subTest(user=user.username):
                self.assertEqual(self.view(user).status_code, 200)
                self.assertEqual(self.ask(user, "pdf").status_code, 202)
                self.assertEqual(self.ask(user, "xlsx").status_code, 202)

    def test_the_office_may_open_any_class(self):
        for user in (self.principal, self.vp, self.admin):
            with self.subTest(user=user.username):
                self.assertEqual(self.view(user, group_id=self.other_group_id).status_code, 200)
                self.assertEqual(self.ask(user, "xlsx", group_id=self.other_group_id).status_code, 202)

    def test_nobody_else_may(self):
        parent_and_student = (self.mama, self.ada.user)
        for user in (self.subject_teacher, self.bursar) + parent_and_student:
            with self.subTest(user=user.username):
                self.assertIn(self.view(user).status_code, (403, 404))
                self.assertIn(self.ask(user, "pdf").status_code, (403, 404))
                self.assertIn(self.ask(user, "xlsx").status_code, (403, 404))
        with connected_to(self.stmarys):
            self.assertFalse(ClassCardPrint.objects.exists())

    def test_signed_out_is_refused(self):
        self.assertEqual(self.view(None).status_code, 401)
        self.assertEqual(self.ask(None).status_code, 401)

    def test_a_class_teacher_may_only_open_their_own_class(self):
        self.assertEqual(self.view(self.teacher, group_id=self.other_group_id).status_code, 403)
        self.assertEqual(self.ask(self.teacher, "pdf", group_id=self.other_group_id).status_code, 403)
        self.assertEqual(self.ask(self.teacher, "xlsx", group_id=self.other_group_id).status_code, 403)
        # And the other class's teacher, ours.
        self.assertEqual(self.view(self.other_teacher).status_code, 403)
        self.assertEqual(self.ask(self.other_teacher, "xlsx").status_code, 403)
        self.assertEqual(self.view(self.other_teacher, group_id=self.other_group_id).status_code, 200)

    def test_a_refusal_does_not_say_whether_the_class_exists(self):
        """Standing is asked before either lookup: a stranger gets one answer."""
        for user in (self.bursar, self.subject_teacher, self.other_teacher):
            with self.subTest(user=user.username):
                real = self.view(user)
                nonexistent = self.view(user, group_id=987654)
                self.assertEqual((real.status_code, real.json()), (nonexistent.status_code, nonexistent.json()))
                posted = self.ask(user, "xlsx", group_id=987654)
                self.assertEqual((posted.status_code, posted.json()), (real.status_code, real.json()))

    def test_a_teacher_taken_off_the_class_loses_the_file_they_made(self):
        job_id = self.ask(self.teacher, "xlsx").json()["id"]
        self.run_job(job_id)
        self.assertEqual(self.status(self.teacher, job_id).status_code, 200)
        with connected_to(self.stmarys):
            from academics.models import ClassTeacher

            ClassTeacher.objects.all().delete()
        self.assertEqual(self.status(self.teacher, job_id).status_code, 404)

    def test_only_the_person_who_asked_may_watch_or_download(self):
        job_id = self.ask(self.principal, "xlsx").json()["id"]
        self.run_job(job_id)
        self.assertEqual(self.status(self.vp, job_id).status_code, 404)
        self.assertEqual(self.client.get(f"/api/results/print-jobs/{job_id}/file/", HTTP_HOST=HOST).status_code, 404)

    def test_the_results_page_links_the_same_people_to_it(self):
        def links(user):
            self.as_(user)
            rows = self.client.get("/api/results/chain/", HTTP_HOST=HOST).json()["rows"]
            return {row["class_group_id"]: row["master_broadsheet_url"] for row in rows}

        with connected_to(self.stmarys):
            Term.objects.filter(pk=self.term_id()).update(is_current=True)
        term = self.term_id()
        everyone = {
            gid: f"/master-broadsheet/{gid}/{term}/"
            for gid in (self.group_id, self.other_group_id, self.empty_group_id)
        }
        self.assertEqual(links(self.principal), everyone)
        self.assertEqual(links(self.vp), everyone)
        self.assertEqual(links(self.admin), everyone)
        # A class teacher: their own class only.
        self.assertEqual(
            links(self.teacher),
            {**{gid: None for gid in everyone}, self.group_id: everyone[self.group_id]},
        )
        self.assertEqual(set(links(self.subject_teacher).values()), {None})

    def test_the_page_is_a_frame_that_holds_no_figure(self):
        self.as_(self.principal)
        page = self.client.get(f"/master-broadsheet/{self.group_id}/{self.term_id()}/", HTTP_HOST=HOST)
        self.assertEqual(page.status_code, 200)
        for needle in (b"Ada Obi", b"88.18", b"Zainab"):
            self.assertNotIn(needle, page.content)
        self.assertIn(b'data-class="%d"' % self.group_id, page.content)


class TheNumbersAreTheCardsTests(BroadsheetSetUp):
    def setUp(self):
        super().setUp()
        self.show_positions()

    def values(self, sheet):
        return {
            r.name: (r.values, r.total, r.average, r.position, r.grades, r.graded) for r in sheet.rows
        }

    def test_the_released_sheet_is_the_live_sheet_and_both_are_the_cards(self):
        live = self.build()
        self.assertTrue(live.preview)
        self.release()
        released = self.build()
        self.assertFalse(released.preview)

        # Not "close": every cell, total, average, position and grade count.
        self.assertEqual(self.names(live), self.names(released))
        self.assertEqual(self.values(live), self.values(released))
        self.assertEqual(live.footer, released.footer)
        self.assertEqual(live.columns, released.columns)
        self.assertEqual(live.letters, released.letters)
        self.assertEqual(
            [r.promotion for r in live.rows], [r.promotion for r in released.rows]
        )

        # And the cards themselves, which went home.
        with connected_to(self.stmarys):
            cards = {c.student_name: c for c in ReleasedCard.objects.all()}
            self.assertEqual(set(cards), set(self.names(released)))
            for row in released.rows:
                card = cards[row.name]
                with self.subTest(child=row.name):
                    self.assertEqual(row.total, card.total_scored if card.total_available else None)
                    self.assertEqual(row.average, card.own_average)
                    self.assertEqual(row.position, card.position)

    def test_every_subject_percentage_and_letter_is_the_cards_line(self):
        self.release()
        sheet = self.build()
        pct = [i for i, c in enumerate(sheet.columns) if c.key == "pct"]
        with connected_to(self.stmarys):
            for row in sheet.rows:
                lines = {
                    line.subject_name: line
                    for line in ReleasedSubjectResult.objects.filter(card__student_name=row.name)
                }
                shown = {sheet.columns[i].subject: row.values[i] for i in pct}
                for subject, line in lines.items():
                    with self.subTest(child=row.name, subject=subject):
                        self.assertEqual(shown[subject], line.percentage if line.is_complete else None)
                letters = [line.grade_letter for line in lines.values() if line.is_complete and line.grade_letter]
                self.assertEqual(sum(row.grades.values()), len(letters))
                for letter in set(letters):
                    self.assertEqual(row.grades[letter], letters.count(letter))

    def test_positions_follow_the_cards_tie_rule(self):
        sheet = self.build()
        by_name = {r.name: r.position for r in sheet.rows}
        # Dense: Zainab 1st, Ada 2nd, Bola and Chidi tied 3rd, and nobody is 5th.
        self.assertEqual(
            by_name, {"Zainab Yusuf": 1, "Ada Obi": 2, "Bola Eze": 3, "Chidi Eze": 3, "Dayo Bello": None}
        )
        # It is the rule's own function, not a copy of it.
        with connected_to(self.stmarys):
            expected = positions.class_results(self.group_of(self.stmarys), self.term_of(self.stmarys, FIRST)).positions
        self.assertEqual({r.student_id: r.position for r in sheet.rows if r.position}, expected)
        # In rank order, ties by name, the unranked last.
        self.assertEqual(self.names(sheet), ["Zainab Yusuf", "Ada Obi", "Bola Eze", "Chidi Eze", "Dayo Bello"])

    def test_a_missing_paper_is_a_dash_and_never_a_zero(self):
        sheet = self.build()
        dayo = next(r for r in sheet.rows if r.name == "Dayo Bello")
        labels = [(c.subject, c.key) for c in sheet.columns]
        cell = dict(zip(labels, dayo.values))
        # No maths paper at all: nothing, in any column.
        self.assertEqual([cell[("Mathematics", k)] for k in ("ca", "exam", "pct")], [None, None, None])
        # English: the exam is in, CA 1 is not, so the CA total is not the child's, and there is no %.
        self.assertEqual((cell[("English", "exam")], cell[("English", "ca")], cell[("English", "pct")]), (40, None, None))
        # No whole subject: no total, no average, no place, no letters.
        self.assertEqual((dayo.total, dayo.average, dayo.position, dayo.graded), (None, None, None, 0))
        payload = self.view(self.principal).json()
        row = next(r for r in payload["rows"] if r["name"] == "Dayo Bello")
        self.assertEqual(row["cells"].count(None), len(payload["columns"]) - 1)
        self.assertEqual((row["total"], row["average"], row["position"], row["grades"]), (None, None, None, None))
        self.assertNotIn("0", row["cells"])

    def test_the_footer_counts_only_the_figures_that_are_there(self):
        sheet = self.build()
        index = next(i for i, c in enumerate(sheet.columns) if (c.subject, c.key) == ("Mathematics", "pct"))
        highest, lowest, average = (dict(sheet.footer)[label][index] for label in broadsheet.FOOTER)
        zainab, ada, bola = Decimal("95.45"), Decimal("88.18"), Decimal("61.82")
        # Dayo, who sat no maths, is not a zero in the average.
        self.assertEqual((highest, lowest), (zainab, bola))
        self.assertEqual(average, positions.mean_percentage([zainab, ada, bola, bola]))
        self.assertNotEqual(average, positions.mean_percentage([zainab, ada, bola, bola, Decimal(0)]))
        self.assertEqual([label for label, _ in sheet.footer], ["Highest", "Lowest", "Class average"])

    def test_a_standard_subject_is_ca_exam_and_a_percentage(self):
        sheet = self.build()
        english = [(c.key, c.label, c.out_of) for c in sheet.columns if c.subject == "English"]
        self.assertEqual(english, [("ca", "CA", 20), ("exam", "Exam", 100), ("pct", "%", 100)])
        ada = next(r for r in sheet.rows if r.name == "Ada Obi")
        start = next(i for i, c in enumerate(sheet.columns) if c.subject == "English")
        self.assertEqual(ada.values[start:start + 3], [15, 74, Decimal("74.17")])

    def test_the_grade_counts_use_the_schools_own_letters(self):
        sheet = self.build()
        self.assertTrue(sheet.letters)
        with connected_to(self.stmarys):
            from results import grades

            self.assertEqual(sheet.letters[: len(grades.scale())], [b.letter for b in grades.scale()])
        zainab = next(r for r in sheet.rows if r.name == "Zainab Yusuf")
        self.assertEqual(sum(zainab.grades.values()), 2)
        self.assertEqual(zainab.graded, 2)

    def test_the_payload_carries_what_the_page_draws(self):
        payload = self.view(self.principal).json()
        self.assertEqual(
            (payload["class_group"], payload["preview"], payload["template"], payload["show_position"]),
            ("JSS 1A", True, "standard", True),
        )
        self.assertEqual(len(payload["rows"]), 5)
        self.assertTrue(all(len(r["cells"]) == len(payload["columns"]) for r in payload["rows"]))
        self.assertEqual([f["label"] for f in payload["footer"]], ["Highest", "Lowest", "Class average"])
        self.assertEqual(payload["ranked"], 4)

    def test_an_empty_class_has_nothing_to_make(self):
        response = self.ask(self.principal, "xlsx", group_id=self.empty_group_id)
        self.assertEqual(response.status_code, 409)
        sheet = self.view(self.principal, group_id=self.empty_group_id).json()
        self.assertEqual((sheet["rows"], sheet["columns"]), ([], []))


class OgunTemplateTests(BroadsheetSetUp):
    def setUp(self):
        super().setUp()
        with connected_to(self.stmarys):
            ogun.set_template_as(self.principal, self.stmarys, "ogun")
        # A subject with the sheet's own four papers.
        with connected_to(self.stmarys):
            from gradebook.models import Assessment, Score, Subject

            subject = Subject.objects.create(name="Civic Education", code="CIV")
            term = self.term_of(self.stmarys, FIRST)
            papers = [
                Assessment.objects.create(term=term, subject=subject, name=n, max_score=m, position=i)
                for i, (n, m) in enumerate(ogun.ASSESSMENTS)
            ]
            for child, marks in ((self.ada, (9, 8, 7, 60)), (self.bola, (5, 6, 7, 50))):
                for paper, mark in zip(papers, marks):
                    Score.objects.create(assessment=paper, student_membership_id=child.pk, value=mark)
        self.show_positions()

    def test_each_component_has_a_column_before_the_ca_and_the_exam(self):
        sheet = self.build()
        self.assertTrue(sheet.ogun)
        civic = [(c.key, c.label, c.out_of) for c in sheet.columns if c.subject == "Civic Education"]
        self.assertEqual(
            civic,
            [("paper", "1st Test", 10), ("paper", "2nd Test", 10), ("paper", "Assignment", 10),
             ("ca", "CA", 30), ("exam", "Exam", 70), ("pct", "%", 100)],
        )
        start = next(i for i, c in enumerate(sheet.columns) if c.subject == "Civic Education")
        ada = next(r for r in sheet.rows if r.name == "Ada Obi")
        self.assertEqual(ada.values[start:start + 6], [9, 8, 7, 24, 60, Decimal("84.00")])
        # A paper that was never marked for a child is a dash in its own column
        # and in the CA built from it.
        zainab = next(r for r in sheet.rows if r.name == "Zainab Yusuf")
        self.assertEqual(zainab.values[start:start + 6], [None] * 6)

    def test_the_released_ogun_sheet_is_the_live_one(self):
        live = self.build()
        self.release()
        released = self.build()
        self.assertTrue(released.ogun)
        self.assertEqual(live.columns, released.columns)
        self.assertEqual([r.values for r in live.rows], [r.values for r in released.rows])
        self.assertEqual(live.footer, released.footer)

    def test_the_pdf_and_the_excel_file_have_the_components_too(self):
        _, xlsx = self.made(self.principal, "xlsx")
        header = [c.value for c in load_workbook(io.BytesIO(xlsx)).active[broadsheet_files.HEADER_ROW]]
        for label in ("1st Test (10)", "2nd Test (10)", "Assignment (10)", "CA (30)", "Exam (70)"):
            self.assertIn(label, header)
        self.assertTrue(self.made(self.principal, "pdf", "A3")[1].startswith(b"%PDF"))
        text = self.page_text()
        self.assertIn("1st Test", text)
        self.assertIn("Assignment", text)


class PositionSettingTests(BroadsheetSetUp):
    def test_hidden_there_is_no_position_in_the_payload_the_pdf_or_the_file(self):
        self.show_positions(False)
        self.release()
        payload = self.view(self.principal).json()
        self.assertFalse(payload["show_position"])
        self.assertEqual([r["position"] for r in payload["rows"]], [None] * 5)
        self.assertEqual(payload["ranked"], 0)
        # Not hidden by the page: the field has no value to hide.
        self.assertNotIn(b"Position", self.view(self.principal).content)
        # Rows in rank order would print the position anyway: by name instead.
        self.assertEqual([r["name"] for r in payload["rows"]], sorted(r["name"] for r in payload["rows"]))
        self.assertNotEqual(
            [r["name"] for r in payload["rows"]], [r.name for r in self._ranked_order()]
        )

        _, xlsx = self.made(self.principal, "xlsx")
        header = [c.value for c in load_workbook(io.BytesIO(xlsx)).active[broadsheet_files.HEADER_ROW]]
        self.assertNotIn("Position", header)
        self.assertTrue(self.made(self.principal, "pdf")[1].startswith(b"%PDF"))
        self.assertNotIn("Position", self.page_text())

    def _ranked_order(self):
        self.show_positions(True)
        try:
            return self.build().rows
        finally:
            self.show_positions(False)

    def test_shown_it_is_the_cards_position(self):
        self.show_positions(True)
        payload = self.view(self.principal).json()
        self.assertTrue(payload["show_position"])
        self.assertEqual(
            {r["name"]: r["position"] for r in payload["rows"]},
            {"Zainab Yusuf": 1, "Ada Obi": 2, "Bola Eze": 3, "Chidi Eze": 3, "Dayo Bello": None},
        )
        _, xlsx = self.made(self.principal, "xlsx")
        header = [c.value for c in load_workbook(io.BytesIO(xlsx)).active[broadsheet_files.HEADER_ROW]]
        self.assertIn("Position", header)
        self.assertTrue(self.made(self.principal, "pdf")[1].startswith(b"%PDF"))
        self.assertIn("Position", self.page_text())


class PreviewTests(BroadsheetSetUp):
    def pages(self, content):
        with pikepdf.open(io.BytesIO(content)) as pdf:
            return [(tuple(float(v) for v in p.mediabox), stamped(p)) for p in pdf.pages]

    def test_before_release_every_page_says_preview_and_after_none_does(self):
        job, before = self.made(self.principal, "pdf", "A4")
        pages = self.pages(before)
        self.assertTrue(pages)
        self.assertTrue(all(marked for _, marked in pages), "every page of a preview carries the stamp")
        self.assertTrue(job.preview)
        self.assertTrue(self.view(self.principal).json()["preview"])

        self.release()
        job, after = self.made(self.principal, "pdf", "A4")
        self.assertFalse(job.preview)
        self.assertFalse(any(marked for _, marked in self.pages(after)))
        self.assertFalse(self.view(self.principal).json()["preview"])

    def test_the_stamp_is_in_the_page_so_a_viewer_cannot_hide_it(self):
        _, content = self.made(self.principal, "pdf", "A3")
        with pikepdf.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages:
                self.assertNotIn("/Annots", page.obj)
                self.assertNotIn("/OC", page.obj)

    def test_landscape_on_the_paper_chosen(self):
        for paper, (width, height) in (("A4", (841.89, 595.28)), ("A3", (1190.55, 841.89))):
            with self.subTest(paper=paper):
                job, content = self.made(self.principal, "pdf", paper)
                self.assertEqual(job.paper, paper)
                (box, _), *_ = self.pages(content)
                self.assertAlmostEqual(box[2] - box[0], width, delta=1.5)
                self.assertAlmostEqual(box[3] - box[1], height, delta=1.5)

    def test_the_name_says_preview_before_release_and_not_after(self):
        job_id = self.ask(self.principal, "pdf", "A3").json()["id"]
        self.run_job(job_id)
        url = self.status(self.principal, job_id).json()["download_url"]
        disposition = self.client.get(url, HTTP_HOST=HOST)["Content-Disposition"]
        self.assertIn("preview-not-released", disposition)
        self.assertIn("a3", disposition)
        self.assertIn("PREVIEW, NOT RELEASED", self.status(self.principal, job_id).json()["detail"])
        self.release()
        again = self.ask(self.principal, "pdf", "A3").json()["id"]
        self.run_job(again)
        url = self.status(self.principal, again).json()["download_url"]
        self.assertNotIn("preview", self.client.get(url, HTTP_HOST=HOST)["Content-Disposition"])

    def test_every_name_is_on_the_paper(self):
        self.assertTrue(self.made(self.principal, "pdf", "A3")[1].startswith(b"%PDF"))
        text = self.page_text()
        for name in ("Ada Obi", "Bola Eze", "Chidi Eze", "Zainab Yusuf", "Dayo Bello", "Class average", "Highest", "Lowest"):
            self.assertIn(name, text)


class ExcelTests(BroadsheetSetUp):
    def test_it_opens_with_the_pdfs_header_and_a_row_for_every_child(self):
        self.show_positions()
        job, content = self.made(self.principal, "xlsx")
        book = load_workbook(io.BytesIO(content))
        ws = book.active
        sheet = self.build()
        header = [c.value for c in ws[broadsheet_files.HEADER_ROW]]
        self.assertEqual(header, broadsheet_files.header_labels(sheet))
        self.assertEqual(header[0], "Name")
        self.assertEqual(header[-1], "Promotion")
        for expected in ("CA (20)", "Exam (100)", "%", "Total", "Average", "Position"):
            self.assertIn(expected, header)
        children = 5
        self.assertEqual(ws.max_row, broadsheet_files.HEADER_ROW + children + 3)
        names = [ws.cell(row=broadsheet_files.HEADER_ROW + i, column=1).value for i in range(1, children + 1)]
        self.assertEqual(names, self.names(sheet))
        footer = [ws.cell(row=broadsheet_files.HEADER_ROW + children + i, column=1).value for i in (1, 2, 3)]
        self.assertEqual(footer, ["Highest", "Lowest", "Class average"])
        self.assertTrue(job.preview)
        self.assertIn("PREVIEW, NOT RELEASED", ws["A2"].value)

    def test_figures_are_numbers_and_a_missing_paper_is_a_dash(self):
        self.show_positions()
        _, content = self.made(self.principal, "xlsx")
        ws = load_workbook(io.BytesIO(content)).active
        sheet = self.build()
        header = [c.value for c in ws[broadsheet_files.HEADER_ROW]]
        row = {r.name: broadsheet_files.HEADER_ROW + i + 1 for i, r in enumerate(sheet.rows)}
        english_exam = 2 + next(i for i, c in enumerate(sheet.columns) if (c.subject, c.key) == ("English", "exam"))

        def at(name, label):
            column = english_exam if label == "English exam" else header.index(label) + 1
            return ws.cell(row=row[name], column=column).value

        self.assertEqual(at("Ada Obi", "Total"), next(r for r in sheet.rows if r.name == "Ada Obi").total)
        self.assertIsInstance(at("Ada Obi", "Total"), int)
        self.assertAlmostEqual(at("Ada Obi", "Average"), float(next(r for r in sheet.rows if r.name == "Ada Obi").average))
        self.assertEqual(at("Zainab Yusuf", "Position"), 1)
        self.assertEqual(at("Dayo Bello", "Total"), "-")
        self.assertEqual(at("Dayo Bello", "Average"), "-")
        self.assertEqual(at("Dayo Bello", "Position"), "-")
        self.assertEqual(at("Dayo Bello", "English exam"), 40)

    def test_a_name_that_looks_like_a_formula_is_a_name(self):
        Membership.objects.filter(pk=self.dayo.pk).update(display_name="=1+1")
        _, content = self.made(self.principal, "xlsx")
        ws = load_workbook(io.BytesIO(content)).active
        cells = [c for row in ws.iter_rows(min_row=broadsheet_files.HEADER_ROW + 1) for c in row if c.value == "=1+1"]
        self.assertEqual(len(cells), 1)
        self.assertEqual(cells[0].data_type, "s")

    def test_the_released_file_says_released(self):
        self.release()
        job, content = self.made(self.principal, "xlsx")
        ws = load_workbook(io.BytesIO(content)).active
        self.assertFalse(job.preview)
        self.assertNotIn("PREVIEW", ws["A2"].value)

    def test_it_is_sent_as_a_spreadsheet_with_a_name(self):
        job_id = self.ask(self.principal, "xlsx").json()["id"]
        self.run_job(job_id)
        url = self.status(self.principal, job_id).json()["download_url"]
        self.assertTrue(url.endswith("/file/"))
        response = self.client.get(url, HTTP_HOST=HOST)
        self.assertEqual(
            response["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        self.assertRegex(response["Content-Disposition"], r'filename="broadsheet-jss-1a-.*\.xlsx"')
        self.assertEqual(response["Cache-Control"], "private, no-store")


class TheJobPathTests(BroadsheetSetUp):
    """The same log, the same private file and the same day as report cards."""

    def age(self, job, by):
        with connected_to(self.stmarys):
            StoredFile.objects.filter(key=job.file_key).update(created_at=timezone.now() - by)
            ClassCardPrint.objects.filter(pk=job.pk).update(
                created_at=timezone.now() - by, finished_at=timezone.now() - by
            )

    def on_disk(self, job):
        return storage.path_of("st_marys", job.file_key, class_print.variant_of(job)).exists()

    def test_it_is_logged_with_who_what_and_how_many(self):
        for fmt, paper, kind in (("pdf", "A3", PrintKind.BROADSHEET_PDF), ("xlsx", "", PrintKind.BROADSHEET_XLSX)):
            with self.subTest(fmt=fmt):
                job, _ = self.made(self.vp, fmt, paper or "A4")
                self.assertEqual(
                    (job.kind, job.paper, job.requested_by_id, job.class_group_name, job.card_count, job.state),
                    (kind, paper, self.vp.pk, "JSS 1A", 5, PrintState.READY),
                )
                self.assertEqual(job.requested_by_roles, Role.VICE_PRINCIPAL_ACADEMIC.value)
                self.assertTrue(job.preview)

    def test_it_is_a_private_file_for_the_one_person_who_asked(self):
        job, _ = self.made(self.principal, "xlsx")
        with connected_to(self.stmarys):
            stored = StoredFile.objects.get(key=job.file_key)
        self.assertEqual((stored.kind, stored.public, stored.uploaded_by_id), ("class_broadsheet", False, self.principal.pk))
        self.as_(self.principal)
        self.assertEqual(
            self.client.get(f"/files/{job.file_key}/{class_print.variant_of(job)}", HTTP_HOST=HOST).status_code, 404
        )
        self.assertEqual(self.status(self.admin, job.pk).status_code, 404)

    def test_it_is_refused_after_24_hours_removed_by_the_sweep_and_the_log_stays(self):
        job, _ = self.made(self.principal, "pdf", "A4")
        self.age(job, timedelta(hours=23, minutes=59))
        with connected_to(self.stmarys), self.captureOnCommitCallbacks(execute=True):
            files_service.sweep()
        self.assertTrue(self.on_disk(job))
        self.assertEqual(self.status(self.principal, job.pk).json()["state"], "ready")

        self.age(job, timedelta(hours=24, seconds=1))
        url = f"/api/results/print-jobs/{job.pk}/pdf/"
        self.assertEqual(self.client.get(url, HTTP_HOST=HOST).status_code, 410)
        self.assertIsNone(self.status(self.principal, job.pk).json()["download_url"])
        with connected_to(self.stmarys), self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(files_service.sweep()["expired"], 1)
        self.assertFalse(self.on_disk(job))
        with connected_to(self.stmarys):
            log = ClassCardPrint.objects.get(pk=job.pk)
        self.assertEqual((log.requested_by_id, log.kind, log.paper, log.card_count), (self.principal.pk, "broadsheet_pdf", "A4", 5))
        self.assertIn("Make the broadsheet again", self.status(self.principal, job.pk).json()["detail"])

    def test_pressing_twice_is_one_job_and_report_cards_are_another(self):
        first = self.ask(self.principal, "pdf", "A3").json()["id"]
        self.assertEqual(self.ask(self.principal, "pdf", "A3").json()["id"], first)
        self.assertNotEqual(self.ask(self.principal, "pdf", "A4").json()["id"], first)
        self.assertNotEqual(self.ask(self.principal, "xlsx").json()["id"], first)
        cards = self.start(self.principal).json()["id"]
        self.assertNotIn(cards, {first})
        with connected_to(self.stmarys):
            self.assertEqual(ClassCardPrint.objects.get(pk=cards).kind, PrintKind.CARDS)
            self.assertEqual(ClassCardPrint.objects.filter(kind=PrintKind.CARDS).count(), 1)

    def test_a_format_or_paper_that_is_not_offered_is_refused_with_a_sentence(self):
        for fmt, paper in (("docx", ""), ("pdf", "A5"), ("", "")):
            with self.subTest(fmt=fmt, paper=paper):
                response = self.ask(self.principal, fmt, paper)
                self.assertEqual(response.status_code, 422)
                self.assertTrue(response.json()["detail"])
        with connected_to(self.stmarys):
            self.assertFalse(ClassCardPrint.objects.exists())

    def test_the_job_is_the_one_in_the_message_and_failures_say_so(self):
        with self.captureOnCommitCallbacks(execute=True):
            job_id = self.ask(self.principal, "xlsx").json()["id"]
        self.assertEqual(self.queued, [("st_marys", job_id)])
        class_print.record_failure(job_id, RuntimeError("boom"))
        status = self.status(self.principal, job_id).json()
        self.assertEqual(status["state"], "failed")
        self.assertIn("broadsheet could not be made", status["detail"])

    def test_report_cards_still_print_as_they_did(self):
        job, content = self.printed(self.principal)
        self.assertEqual(job.kind, PrintKind.CARDS)
        self.assertTrue(content.startswith(b"%PDF"))


class TwoSchoolsTests(BroadsheetSetUp):
    def test_another_schools_principal_cannot_read_or_make_one_here(self):
        self.assertIn(self.view(self.their_principal, self.stmarys).status_code, (403, 404))
        self.assertIn(self.ask(self.their_principal, "pdf", school=self.stmarys).status_code, (403, 404))
        self.assertIn(self.ask(self.their_principal, "xlsx", school=self.stmarys).status_code, (403, 404))
        with connected_to(self.stmarys):
            self.assertFalse(ClassCardPrint.objects.exists())

    def test_a_principal_elsewhere_who_is_a_parent_here_cannot_see_print_or_export(self):
        """Signed in at St Mary's (as a parent), so past the middleware: only
        `may_see()` asking roles *here* stands between them and the class."""
        both = User.objects.create_user("both", PASSWORD, full_name="Both Ways")
        grant_membership(both, self.grace, Role.PRINCIPAL)
        link_guardian(both, self.bola)
        give_verified_channel(both, "08030000099")
        job, _ = self.made(self.principal, "xlsx")

        self.assertEqual(self.view(both, self.stmarys).status_code, 403)
        self.assertEqual(self.ask(both, "pdf", school=self.stmarys).status_code, 403)
        self.assertEqual(self.ask(both, "xlsx", school=self.stmarys).status_code, 403)
        self.assertEqual(self.status(both, job.pk).status_code, 404)
        self.assertEqual(self.client.get(f"/api/results/print-jobs/{job.pk}/file/", HTTP_HOST=HOST).status_code, 404)
        with connected_to(self.stmarys):
            self.assertEqual(ClassCardPrint.objects.count(), 1)
        # The control: at Grace, where they are principal, they may.
        self.assertEqual(self.view(both, self.grace).status_code, 200)
        self.assertEqual(self.ask(both, "xlsx", school=self.grace).status_code, 202)

    def test_each_school_reads_only_its_own_children(self):
        ours = self.view(self.principal, self.stmarys).json()
        theirs = self.view(self.their_principal, self.grace).json()
        self.assertEqual({r["name"] for r in ours["rows"]}, {"Ada Obi", "Bola Eze", "Chidi Eze", "Zainab Yusuf", "Dayo Bello"})
        self.assertEqual([r["name"] for r in theirs["rows"]], ["Ngozi Ade"])
        self.assertEqual(theirs["school"], "Grace Academy")
        # Grace's class and term ids, asked for on St Mary's host, are not Grace's class.
        self.as_(self.their_principal)
        wrong = self.client.get(self.sheet_url(self.grace), HTTP_HOST=HOST)
        self.assertIn(wrong.status_code, (403, 404))

    def test_a_job_id_means_a_job_in_this_school_only(self):
        """Per-schema sequences: both schools' first job is job 1."""
        ours, our_file = self.made(self.principal, "xlsx")
        theirs, their_file = self.made(self.their_principal, "xlsx", school=self.grace)
        self.assertEqual(ours.pk, theirs.pk)
        our_names = [c.value for c in load_workbook(io.BytesIO(our_file)).active["A"]]
        their_names = [c.value for c in load_workbook(io.BytesIO(their_file)).active["A"]]
        self.assertIn("Ada Obi", our_names)
        self.assertNotIn("Ngozi Ade", our_names)
        self.assertIn("Ngozi Ade", their_names)
        self.assertNotIn("Ada Obi", their_names)
        self.assertEqual(self.status(self.their_principal, ours.pk, host=THEIR_HOST).json()["class_group"], "JSS 1A")
        self.assertEqual(
            self.client.get(f"/api/results/print-jobs/{ours.pk}/file/", HTTP_HOST=THEIR_HOST).status_code, 200
        )

    def test_the_file_is_kept_in_the_school_the_message_named(self):
        job_id = self.ask(self.principal, "xlsx").json()["id"]
        with connected_to(self.grace):
            self.run_job(job_id, self.stmarys)
        with connected_to(self.stmarys):
            job = ClassCardPrint.objects.get(pk=job_id)
            stored = StoredFile.objects.get(key=job.file_key)
        with connected_to(self.grace):
            self.assertFalse(StoredFile.objects.filter(key=job.file_key).exists())
        self.assertEqual(stored.schema_name, "st_marys")
        self.assertTrue(storage.path_of("st_marys", job.file_key, "class-broadsheet.xlsx").exists())
