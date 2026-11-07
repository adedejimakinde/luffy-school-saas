""""Print report cards": a class's cards as one PDF. `docs/class-print.md`.

Two schools throughout, St Mary's and Grace, from `ReportCardApiSetUp`.

- **Who**: the principal, the vice principal (academic) and the administrator
  for any class; the class teacher for their own; nobody else, asked on every
  route (start, status, download), not only where the button is drawn.
- **Preview or released**: before release every page carries the stamp, and
  nothing of the preview's freeze is kept; after release no page does.
- **The count** is the children chosen, one bookmark each, and a paper not
  marked prints as the single card prints it, "-", not 0.
- **A day**: the file is refused after 24 hours and removed by the sweep; the
  job row, which is the log, stays.
- **Ogun State**: its affective and psychomotor sections are printed.
- **Tenancy**: another school's staff can neither start nor download a
  school's print. `test_a_principal_elsewhere_who_is_a_parent_here_cannot_print`
  is the one that fails when `may_print()` asks roles anywhere rather than
  roles here (the control is described in the PR).
"""

import io
import tempfile
import time
from datetime import timedelta
from unittest import mock

import pikepdf
from django.test import override_settings
from django.utils import timezone

from academics.models import ClassGroup, Term, TermName
from academics.services import assign_class_teacher
from accounts.models import Role, User
from accounts.services import enroll_student, grant_membership, link_guardian
from academics.services import place_student
from files import service as files_service
from files import storage
from files.models import StoredFile
from results import class_print, ogun
from results.models import ClassCardPrint, PrintState, ReleasedCard, ReleasedCardPdf, ResultSheet
from results.tasks import build_class_cards, render_card_pdf
from results.tests.test_card_api import HOST, PASSWORD, THEIR_HOST, ReportCardApiSetUp
from schools.tests.tenants import connected_to
from tests.guardians import give_verified_channel

FIRST = TermName.FIRST.value


def body(response) -> bytes:
    if getattr(response, "streaming", False):
        return b"".join(response.streaming_content)
    return response.content


def stamped(page) -> bool:
    """Does this page draw the preview stamp, with the words in it?

    Not a flag looked up: the page's own content must invoke a form whose
    content shows the words.
    """
    xobjects = page.obj.get("/Resources", {}).get("/XObject", {})
    drawn = {
        str(operands[0])
        for operands, operator in pikepdf.parse_content_stream(page)
        if str(operator) == "Do"
    }
    for name in drawn:
        form = xobjects.get(name)
        if form is None or form.get("/Subtype") != pikepdf.Name.Form:
            continue
        shown = [
            bytes(operands[0])
            for operands, operator in pikepdf.parse_content_stream(form)
            if str(operator) == "Tj"
        ]
        if class_print.WATERMARK.encode() in shown:
            return True
    return False


def read(content):
    """`(pages, bookmark titles, every page stamped?, any page stamped?)`."""
    with pikepdf.open(io.BytesIO(content)) as pdf:
        with pdf.open_outline() as outline:
            titles = [item.title for item in outline.root]
        marks = [stamped(page) for page in pdf.pages]
        return len(pdf.pages), titles, all(marks), any(marks)


class ClassPrintSetUp(ReportCardApiSetUp):
    def setUp(self):
        super().setUp()
        root = tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        settings = override_settings(FILES_ROOT=root.name, FILES_X_ACCEL=False)
        settings.enable()
        self.addCleanup(settings.disable)

        self.admin = self.staff[Role.ADMIN]
        # A teacher who teaches here and is nobody's class teacher.
        self.subject_teacher = self._one_staff(self.stmarys, "subject", Role.TEACHER)
        # A paper only Ada sat: Bola's is not marked, and prints as "-".
        self._mark(self.stmarys, FIRST, self.ada, "maths", "Project", 9, out_of=10)
        self.queued = []
        enqueue = mock.patch.object(class_print, "_enqueue", side_effect=lambda s, j: self.queued.append((s, j)))
        enqueue.start()
        self.addCleanup(enqueue.stop)

    # -- the calls -------------------------------------------------------------

    def host(self, school):
        return HOST if school == self.stmarys else THEIR_HOST

    def as_(self, user):
        if user is None:
            self.client.logout()
        else:
            self.client.force_login(user)

    def start(self, user, school=None, ids=None, group_id=None, term_id=None, host=None):
        school = school or self.stmarys
        self.as_(user)
        group_id = group_id or (self.group_id if school == self.stmarys else self.their_group_id)
        term_id = term_id or self.terms_of(school)[FIRST]
        return self.client.post(
            f"/api/results/print-cards/{group_id}/{term_id}/",
            {"student_ids": ids or []},
            content_type="application/json",
            HTTP_HOST=host or self.host(school),
        )

    def printable(self, user, school=None):
        school = school or self.stmarys
        self.as_(user)
        group_id = self.group_id if school == self.stmarys else self.their_group_id
        return self.client.get(
            f"/api/results/print-cards/{group_id}/{self.terms_of(school)[FIRST]}/", HTTP_HOST=self.host(school)
        )

    def status(self, user, job_id, school=None, host=None):
        self.as_(user)
        return self.client.get(f"/api/results/print-jobs/{job_id}/", HTTP_HOST=host or self.host(school or self.stmarys))

    def download(self, user, job_id, school=None, host=None):
        self.as_(user)
        return self.client.get(
            f"/api/results/print-jobs/{job_id}/pdf/", HTTP_HOST=host or self.host(school or self.stmarys)
        )

    def run_job(self, job_id, school=None):
        school = school or self.stmarys
        return build_class_cards.apply(args=[school.schema_name, job_id]).get()

    def printed(self, user, school=None, ids=None):
        """Start, run, and download. Returns `(job, pdf bytes)`."""
        school = school or self.stmarys
        response = self.start(user, school, ids)
        self.assertEqual(response.status_code, 202, response.content)
        job_id = response.json()["id"]
        self.run_job(job_id, school)
        got = self.download(user, job_id, school)
        self.assertEqual(got.status_code, 200, None if got.status_code == 200 else got.content[:300])
        with connected_to(school):
            job = ClassCardPrint.objects.get(pk=job_id)
        return job, body(got)


class WhoMayPrintTests(ClassPrintSetUp):
    """Every role, on the server, on every route."""

    def test_the_office_and_the_class_teacher_may_start_a_print(self):
        for user in (self.principal, self.vp, self.admin, self.teacher):
            with self.subTest(user=user.username):
                response = self.start(user)
                self.assertEqual(response.status_code, 202, response.content)

    def test_nobody_else_may(self):
        student = User.objects.get(pk=self.ada.user_id)
        for user in (self.subject_teacher, self.bursar, self.mama, student):
            with self.subTest(user=user.username):
                self.assertIn(self.start(user).status_code, (403, 404))
                self.assertIn(self.printable(user).status_code, (403, 404))
        with connected_to(self.stmarys):
            self.assertFalse(ClassCardPrint.objects.exists())

    def test_signed_out_is_refused(self):
        self.assertEqual(self.start(None).status_code, 401)

    def test_a_class_teacher_may_not_print_another_class(self):
        with connected_to(self.stmarys):
            other = ClassGroup.objects.create(name="JSS 1B", level=1)
        response = self.start(self.teacher, group_id=other.pk)
        self.assertEqual(response.status_code, 403, response.content)
        # The control: the principal may print the same class.
        self.assertEqual(self.start(self.principal, group_id=other.pk).status_code, 409)  # nobody in it

    def test_only_the_person_who_asked_may_watch_or_download(self):
        job, _ = self.printed(self.principal)
        for user in (self.vp, self.admin, self.teacher, self.subject_teacher, self.mama):
            with self.subTest(user=user.username):
                self.assertEqual(self.status(user, job.pk).status_code, 404)
                self.assertEqual(self.download(user, job.pk).status_code, 404)
        self.assertEqual(self.status(self.principal, job.pk).status_code, 200)

    def test_a_class_teacher_taken_off_the_class_loses_the_file(self):
        job, _ = self.printed(self.teacher)
        with connected_to(self.stmarys):
            assign_class_teacher(
                self.group_of(self.stmarys), self.term_of(self.stmarys, FIRST),
                self.subject_teacher.memberships.get(school=self.stmarys, role=Role.TEACHER),
            )
        self.assertEqual(self.download(self.teacher, job.pk).status_code, 404)
        self.assertEqual(self.status(self.teacher, job.pk).status_code, 404)

    def test_the_chain_offers_the_button_to_the_same_people(self):
        with connected_to(self.stmarys):
            Term.objects.filter(pk=self.terms[FIRST]).update(is_current=True)
        for user, offered in (
            (self.principal, True), (self.vp, True), (self.admin, True), (self.teacher, True),
            (self.subject_teacher, False),
        ):
            with self.subTest(user=user.username):
                self.as_(user)
                rows = self.client.get("/api/results/chain/", HTTP_HOST=HOST).json()["rows"]
                self.assertEqual([r["may_print_cards"] for r in rows], [offered])


class PreviewOrReleasedTests(ClassPrintSetUp):
    def test_before_release_every_page_says_preview_and_nothing_is_kept(self):
        job, content = self.printed(self.principal)

        pages, titles, every, _ = read(content)
        self.assertTrue(job.preview)
        self.assertTrue(every, "every page of a preview carries the stamp")
        self.assertEqual(titles, ["Ada Obi", "Bola Eze"])
        self.assertIn("preview-not-released", class_print.filename(job))
        with connected_to(self.stmarys):
            # The preview froze the class to draw it, and kept none of it.
            self.assertFalse(ReleasedCard.objects.exists())
            self.assertFalse(ReleasedCardPdf.objects.exists())

    def test_after_release_no_page_does(self):
        self.release()
        job, content = self.printed(self.principal)

        _, titles, _, any_ = read(content)
        self.assertFalse(job.preview)
        self.assertFalse(any_, "a released card carries no stamp")
        self.assertEqual(titles, ["Ada Obi", "Bola Eze"])
        self.assertNotIn("preview", class_print.filename(job))

    def test_the_control_the_stamp_test_can_see_a_stamp(self):
        """`stamped()` is what the two tests above rely on, so it is shown to
        tell a stamped page from an unstamped one, on the same card."""
        self.release()
        with connected_to(self.stmarys):
            card = ReleasedCard.objects.get(student_membership_id=self.ada.pk)
            from results import pdf

            raw = pdf.render(card)
        root = storage.building_dir("st_marys")
        (root / "a.pdf").write_bytes(raw)
        class_print.merge([("Ada", root / "a.pdf")], root / "plain.pdf", preview=False, title="t")
        class_print.merge([("Ada", root / "a.pdf")], root / "stamped.pdf", preview=True, title="t")
        self.assertFalse(read((root / "plain.pdf").read_bytes())[3])
        self.assertTrue(read((root / "stamped.pdf").read_bytes())[2])

    def test_a_released_print_uses_the_file_that_went_home(self):
        self.release()
        with connected_to(self.stmarys):
            for card in ReleasedCard.objects.all():
                render_card_pdf.apply(args=["st_marys", card.pk]).get()
        # Every card has its file, so nothing is drawn again.
        with mock.patch("results.pdf.render", side_effect=AssertionError("rendered again")):
            job, content = self.printed(self.principal)
        self.assertEqual(job.card_count, 2)

    def test_the_family_copy_and_never_the_health_copy(self):
        self.release()
        with connected_to(self.stmarys):
            card = ReleasedCard.objects.get(student_membership_id=self.ada.pk)
            render_card_pdf.apply(args=["st_marys", card.pk]).get()
            ReleasedCardPdf.objects.filter(card=card).update(health_content=b"%PDF-not-this-one")
        job, content = self.printed(self.principal, ids=[self.ada.pk])
        self.assertEqual(read(content)[1], ["Ada Obi"])


class TheCountTests(ClassPrintSetUp):
    def test_the_cards_are_the_children_chosen(self):
        job, content = self.printed(self.principal, ids=[self.bola.pk])
        pages, titles, _, _ = read(content)
        self.assertEqual(titles, ["Bola Eze"])
        self.assertEqual(job.card_count, 1)
        self.assertGreaterEqual(pages, 1)

    def test_the_whole_class_when_nobody_is_chosen(self):
        self.release()
        job, content = self.printed(self.principal)
        self.assertEqual(read(content)[1], ["Ada Obi", "Bola Eze"])
        self.assertEqual((job.card_count, job.done, job.total), (2, 2, 2))

    def test_a_child_not_in_the_class_is_refused_not_dropped(self):
        response = self.start(self.principal, ids=[self.ada.pk, self.ngozi.pk + 999])
        self.assertEqual(response.status_code, 422, response.content)

    def test_who_can_be_chosen(self):
        answer = self.printable(self.teacher).json()
        self.assertTrue(answer["preview"])
        self.assertEqual([c["name"] for c in answer["children"]], ["Ada Obi", "Bola Eze"])

    def test_a_paper_not_marked_is_a_dash_as_on_the_single_card(self):
        with connected_to(self.stmarys):
            pages = class_print.preview_html(
                self.group_of(self.stmarys), self.term_of(self.stmarys, FIRST), {self.bola.pk}
            )
        [(name, html)] = pages
        self.assertEqual(name, "Bola Eze")
        row = html.split("Mathematics", 1)[1].split("</tr>", 1)[0]
        cells = row.split('<td class="n">')[1:]
        # Exam 61, then Project not marked: a dash, never 0.
        self.assertIn("61", cells[0])
        self.assertIn('<span class="blank">-</span>', cells[1])
        self.assertNotIn(">0<", cells[1])

    def test_the_released_card_says_the_same(self):
        self.release()
        from results import pdf

        with connected_to(self.stmarys):
            card = ReleasedCard.objects.get(student_membership_id=self.bola.pk)
            released = pdf.html_for(card)
        self.assertIn('<span class="blank">-</span>', released.split("Mathematics", 1)[1].split("</tr>", 1)[0])


class ADayTests(ClassPrintSetUp):
    def age(self, job, by):
        with connected_to(self.stmarys):
            StoredFile.objects.filter(key=job.file_key).update(created_at=timezone.now() - by)
            ClassCardPrint.objects.filter(pk=job.pk).update(
                created_at=timezone.now() - by, finished_at=timezone.now() - by
            )

    def on_disk(self, job):
        return storage.path_of("st_marys", job.file_key, class_print.VARIANT).exists()

    def test_kept_for_a_day(self):
        job, _ = self.printed(self.principal)
        self.age(job, timedelta(hours=23, minutes=59))
        with connected_to(self.stmarys), self.captureOnCommitCallbacks(execute=True):
            files_service.sweep()
        self.assertTrue(self.on_disk(job))
        self.assertEqual(self.download(self.principal, job.pk).status_code, 200)

    def test_after_24_hours_it_is_refused_and_removed_and_the_log_stays(self):
        job, _ = self.printed(self.principal)
        self.assertTrue(self.on_disk(job))
        self.age(job, timedelta(hours=24, seconds=1))

        # Refused at once, before the hourly check has run.
        self.assertEqual(self.download(self.principal, job.pk).status_code, 410)
        self.assertIsNone(self.status(self.principal, job.pk).json()["download_url"])

        # The bytes go once the row's removal commits (`files.service.discard`).
        with connected_to(self.stmarys), self.captureOnCommitCallbacks(execute=True):
            swept = files_service.sweep()
        with connected_to(self.stmarys):
            self.assertEqual(swept["expired"], 1)
            self.assertFalse(StoredFile.objects.filter(key=job.file_key).exists())
            log = ClassCardPrint.objects.get(pk=job.pk)
        self.assertFalse(self.on_disk(job))
        self.assertEqual(self.download(self.principal, job.pk).status_code, 410)
        # The print log: who, which class, which term, preview or not, how many.
        self.assertEqual(
            (log.requested_by_id, log.class_group_name, log.term_label, log.preview, log.card_count),
            (self.principal.pk, "JSS 1A", str(self.term_of_in(self.stmarys)), True, 2),
        )

    def term_of_in(self, school):
        with connected_to(school):
            return self.term_of(school, FIRST)

    def test_the_sweep_leaves_other_schools_alone(self):
        job, _ = self.printed(self.principal)
        self.age(job, timedelta(days=2))
        with connected_to(self.grace), self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(files_service.sweep()["expired"], 0)
        self.assertTrue(self.on_disk(job))

    def test_the_generic_file_route_never_sends_it(self):
        job, _ = self.printed(self.principal)
        self.as_(self.principal)
        response = self.client.get(f"/files/{job.file_key}/{class_print.VARIANT}", HTTP_HOST=HOST)
        self.assertEqual(response.status_code, 404)


class TheJobTests(ClassPrintSetUp):
    def test_pressing_twice_is_one_job(self):
        with self.captureOnCommitCallbacks(execute=True):
            first = self.start(self.principal).json()["id"]
        with self.captureOnCommitCallbacks(execute=True):
            second = self.start(self.principal).json()["id"]
        self.assertEqual(first, second)
        self.assertEqual(len(self.queued), 1)

    def test_the_message_names_the_school_and_the_job(self):
        # `on_commit` does not run inside a TestCase unless asked to.
        with self.captureOnCommitCallbacks(execute=True):
            job_id = self.start(self.vp).json()["id"]
        self.assertIn(("st_marys", job_id), self.queued)

    def test_a_second_worker_leaves_a_live_job_alone_and_takes_over_a_dead_one(self):
        job_id = self.start(self.principal).json()["id"]
        with connected_to(self.stmarys):
            self.assertIsNotNone(class_print.claim(job_id))
            self.assertIsNone(class_print.claim(job_id), "the heartbeat is fresh")
            later = timezone.now() + class_print.STALE_AFTER + timedelta(seconds=1)
            self.assertIsNotNone(class_print.claim(job_id, now=later), "the heartbeat went stale")

    def test_a_finished_job_is_not_made_twice(self):
        job, _ = self.printed(self.principal)
        self.assertIsNone(self.run_job(job.pk))

    def test_a_job_that_dies_says_so(self):
        job_id = self.start(self.principal).json()["id"]
        with mock.patch.object(class_print, "merge", side_effect=RuntimeError("pikepdf fell over")):
            build_class_cards.apply(args=["st_marys", job_id])
        answer = self.status(self.principal, job_id).json()
        self.assertEqual(answer["state"], PrintState.FAILED)
        self.assertNotIn("pikepdf", answer["detail"])
        with connected_to(self.stmarys):
            self.assertIn("pikepdf fell over", ClassCardPrint.objects.get(pk=job_id).error)
        # Nothing half-made is left in the build directory.
        self.assertEqual(list((storage.root() / storage.BUILDING / "st_marys").iterdir()), [])

    def test_progress_is_reported(self):
        job_id = self.start(self.principal).json()["id"]
        answer = self.status(self.principal, job_id).json()
        self.assertEqual((answer["state"], answer["done"], answer["total"]), ("pending", 0, 2))
        self.run_job(job_id)
        answer = self.status(self.principal, job_id).json()
        self.assertEqual((answer["state"], answer["done"], answer["total"]), ("ready", 2, 2))
        self.assertEqual(answer["download_url"], f"/api/results/print-jobs/{job_id}/pdf/")


class OgunTemplateTests(ClassPrintSetUp):
    def setUp(self):
        super().setUp()
        with connected_to(self.stmarys):
            ogun.set_template_as(self.principal, self.stmarys, "ogun")

    def test_the_ogun_card_prints_its_affective_and_psychomotor_sections(self):
        with connected_to(self.stmarys):
            pages = class_print.preview_html(self.group_of(self.stmarys), self.term_of(self.stmarys, FIRST))
        self.assertEqual(len(pages), 2)
        for name, html in pages:
            with self.subTest(name=name):
                self.assertIn("<h3>Affective</h3>", html)
                self.assertIn("<h3>Psychomotor</h3>", html)
                for trait in ogun.AFFECTIVE + ogun.PSYCHOMOTOR:
                    self.assertIn(trait.replace("&", "&amp;"), html)

    def test_and_the_whole_class_prints_as_one_file(self):
        self.release()
        with connected_to(self.stmarys):
            card = ReleasedCard.objects.get(student_membership_id=self.ada.pk)
            from results import pdf

            self.assertIn("<h3>Psychomotor</h3>", pdf.html_for(card))
        job, content = self.printed(self.principal)
        self.assertEqual(read(content)[1], ["Ada Obi", "Bola Eze"])


class TwoSchoolsTests(ClassPrintSetUp):
    """One school's staff can never start or download another school's print."""

    def test_another_schools_principal_cannot_start_one_here(self):
        response = self.start(self.their_principal, self.stmarys)
        self.assertIn(response.status_code, (403, 404))
        with connected_to(self.stmarys):
            self.assertFalse(ClassCardPrint.objects.exists())

    def test_a_principal_elsewhere_who_is_a_parent_here_cannot_print(self):
        """Signed in at St Mary's (as a parent), so past the middleware: only
        `may_print()` asking roles *here* stands between them and the class."""
        both = User.objects.create_user("both", PASSWORD, full_name="Both Ways")
        grant_membership(both, self.grace, Role.PRINCIPAL)
        link_guardian(both, self.bola)
        give_verified_channel(both, "08030000099")
        job, _ = self.printed(self.principal)

        self.assertEqual(self.start(both, self.stmarys).status_code, 403)
        self.assertEqual(self.printable(both, self.stmarys).status_code, 403)
        self.assertEqual(self.status(both, job.pk).status_code, 404)
        self.assertEqual(self.download(both, job.pk).status_code, 404)
        with connected_to(self.stmarys):
            self.assertEqual(ClassCardPrint.objects.count(), 1)
        # The control: at Grace, where they are principal, they may.
        self.assertEqual(self.start(both, self.grace).status_code, 202)

    def test_a_job_id_means_a_job_in_this_school_only(self):
        """Per-schema sequences: both schools' first print is job 1."""
        ours, our_pdf = self.printed(self.principal)
        theirs, their_pdf = self.printed(self.their_principal, self.grace)
        self.assertEqual(ours.pk, theirs.pk)
        self.assertEqual(read(our_pdf)[1], ["Ada Obi", "Bola Eze"])
        self.assertEqual(read(their_pdf)[1], ["Ngozi Ade"])
        # Each principal, on the other school's host, is refused.
        self.assertIn(self.download(self.their_principal, ours.pk, host=HOST).status_code, (403, 404))
        self.assertIn(self.download(self.principal, theirs.pk, host=THEIR_HOST).status_code, (403, 404))

    def test_the_file_is_in_the_school_the_message_named(self):
        job_id = self.start(self.principal).json()["id"]
        with connected_to(self.grace):
            # The worker is told St Mary's, whatever the connection was on.
            self.run_job(job_id, self.stmarys)
        with connected_to(self.stmarys):
            job = ClassCardPrint.objects.get(pk=job_id)
            stored = StoredFile.objects.get(key=job.file_key)
        with connected_to(self.grace):
            self.assertFalse(StoredFile.objects.filter(key=job.file_key).exists())
        self.assertEqual(stored.schema_name, "st_marys")
        self.assertEqual(stored.uploaded_by_id, self.principal.pk)
        self.assertTrue(storage.path_of("st_marys", job.file_key, class_print.VARIANT).exists())
        self.assertIn(self.download(self.their_principal, job_id, host=THEIR_HOST).status_code, (404,))
        self.as_(self.their_principal)
        self.assertEqual(
            self.client.get(f"/files/{job.file_key}/{class_print.VARIANT}", HTTP_HOST=THEIR_HOST).status_code, 404
        )


class TwentyFiveCardsTests(ClassPrintSetUp):
    """The measurement for the PR: a class of 25, preview and released.

    Printed, not asserted, for `FortyFiveCardsTests`' reason. What is asserted
    is that every child is in the file once.
    """

    CLASS_SIZE = 25

    def setUp(self):
        super().setUp()
        with connected_to(self.stmarys):
            group = self.group_of(self.stmarys)
            term = self.term_of(self.stmarys, FIRST)
        for index in range(self.CLASS_SIZE - 2):
            child = enroll_student(
                User.objects.create_user(f"pupil{index}", PASSWORD, full_name=f"Pupil {index:02d}"), self.stmarys
            )
            with connected_to(self.stmarys):
                place_student(group, term, child)
            self._mark(self.stmarys, FIRST, child, "maths", "Exam", 40 + index)
            self._mark(self.stmarys, FIRST, child, "english", "Exam", 35 + index)

    def test_twenty_five_cards(self):
        timings = {}
        for kind in ("preview", "released"):
            if kind == "released":
                self.release()
            started = time.perf_counter()
            job, content = self.printed(self.principal)
            timings[kind] = time.perf_counter() - started
            pages, titles, _, _ = read(content)
            self.assertEqual(len(titles), self.CLASS_SIZE)
            self.assertEqual(len(set(titles)), self.CLASS_SIZE)
            self.assertEqual(job.card_count, self.CLASS_SIZE)
            timings[f"{kind}_kib"] = len(content) / 1024
            timings[f"{kind}_pages"] = pages
        print(
            f"\n[class print] {self.CLASS_SIZE} cards: preview {timings['preview']:.2f}s "
            f"({timings['preview_pages']} pages, {timings['preview_kib']:.0f} KiB), released "
            f"{timings['released']:.2f}s ({timings['released_pages']} pages, {timings['released_kib']:.0f} KiB)"
        )
