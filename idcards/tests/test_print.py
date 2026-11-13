"""The ID card print job: counts, the print log, a day, and a worker that dies. `docs/id-cards.md`.

Everything the report cards' class print is held to, for the same reasons:
a count that silently comes back short is a child at the gate with no card;
a file kept longer than a day is a class's photographs kept longer than a day;
and a job whose worker died must say so rather than show a progress bar for ever.
"""

import io
from datetime import timedelta
from unittest import mock

import pikepdf
from django.utils import timezone

from academics.models import TermName
from accounts.models import Role
from files import service as files_service
from files import storage
from files.models import StoredFile
from idcards import printing
from idcards.models import IdCard, IdCardPrint, PrintState
from idcards.tasks import build_id_cards
from schools.models import Domain
from schools.tests.tenants import connected_to

from .base import IdCardSetUp


def pages_and_bookmarks(content):
    with pikepdf.open(io.BytesIO(content)) as doc:
        with doc.open_outline() as outline:
            return len(doc.pages), [item.title for item in outline.root]


class TheCountTests(IdCardSetUp):
    def test_the_whole_class_when_nobody_is_chosen(self):
        job, pdf = self.printed(self.principal)
        pages, marks = pages_and_bookmarks(pdf)
        self.assertEqual((job.card_count, pages), (2, 2))
        self.assertEqual(len(marks), 1)
        self.assertIn("Ada Obi to Bola Eze", marks[0])

    def test_only_the_children_chosen(self):
        job, pdf = self.printed(self.principal, ids=[self.bola.pk])
        self.assertEqual(job.card_count, 1)
        self.assertEqual(job.student_ids, [self.bola.pk])
        self.assertIn("Bola Eze to Bola Eze", pages_and_bookmarks(pdf)[1][0])
        with connected_to(self.stmarys):
            # Only the child printed has a card on record.
            self.assertEqual(list(IdCard.objects.values_list("student_membership_id", flat=True)), [self.bola.pk])

    def test_a_class_of_twenty_five_is_three_sheets_six_pages_and_a_bookmark_each(self):
        self.more_children(23)
        job, pdf = self.printed(self.principal)
        pages, marks = pages_and_bookmarks(pdf)
        self.assertEqual((job.card_count, pages, len(marks)), (25, 6, 3))

    def test_a_child_not_in_the_class_is_refused_not_dropped(self):
        response = self.start(self.principal, ids=[self.bola.pk, self.ngozi.pk])
        self.assertEqual(response.status_code, 422)
        self.assertIn("1 of the children chosen is not in JSS 1A", response.json()["detail"])
        self.assertEqual(self.queued, [])
        with connected_to(self.stmarys):
            self.assertFalse(IdCardPrint.objects.exists())

    def test_a_class_with_nobody_in_it_is_refused_with_a_sentence(self):
        response = self.start(self.principal, term_id=self.terms[TermName.FIRST.value], group_id=self._other_group())
        self.assertEqual(response.status_code, 409)
        self.assertIn("no children placed", response.json()["detail"])

    def _other_group(self):
        from academics.models import ClassGroup

        with connected_to(self.stmarys):
            return ClassGroup.objects.create(name="JSS 2A", level=2).pk

    def test_a_child_whose_membership_has_ended_has_no_card(self):
        self.bola.end()
        job, _ = self.printed(self.principal)
        self.assertEqual(job.card_count, 1)

    def test_a_school_with_no_web_address_is_refused_rather_than_printing_codes_to_nowhere(self):
        Domain.objects.filter(tenant=self.stmarys).update(is_primary=False)
        # No primary host: the request would not even resolve a tenant, so ask the rule directly.
        with connected_to(self.stmarys):
            from academics.models import ClassGroup, Term

            with self.assertRaises(printing.NothingToPrint) as raised:
                printing.start(
                    self.principal, self.stmarys, ClassGroup.objects.get(pk=self.group_id),
                    Term.objects.get(pk=self.terms[TermName.FIRST.value]),
                )
        self.assertIn("no web address", str(raised.exception))

    def test_the_overview_counts_the_children_a_print_would_hold(self):
        body = self.overview(self.principal).json()
        (group,) = body["classes"]
        self.assertEqual((group["name"], group["students"]), ("JSS 1A", 2))
        self.bola.end()
        self.assertEqual(self.overview(self.principal).json()["classes"][0]["students"], 1)

    def test_the_roster_lists_names_and_admission_numbers(self):
        children = self.roster(self.principal).json()["children"]
        self.assertEqual(
            [(c["name"], c["admission_number"]) for c in children],
            [("Ada Obi", "STM/001"), ("Bola Eze", "STM/002")],
        )

    def test_the_overview_names_the_expiry_and_whether_a_phone_is_on_record(self):
        body = self.overview(self.principal).json()
        self.assertTrue(body["phone_set"])
        self.assertEqual(body["term"]["session"], self.session)
        self.assertTrue(body["term"]["expires_on"])
        self.stmarys.phone = ""
        self.stmarys.save(update_fields=["phone"])
        self.assertFalse(self.overview(self.principal).json()["phone_set"])


class ThePrintLogTests(IdCardSetUp):
    def test_every_print_is_logged_with_who_what_when_and_how_many(self):
        job, _ = self.printed(self.principal)
        self.printed(self.staff[Role.ADMIN], ids=[self.ada.pk])
        with connected_to(self.stmarys):
            rows = list(IdCardPrint.objects.order_by("id"))
        self.assertEqual(len(rows), 2)
        first, second = rows
        self.assertEqual(
            (first.requested_by_id, first.requested_by_name, first.requested_by_roles, first.class_group_name,
             first.session, first.card_count, first.state, first.student_ids),
            (self.principal.pk, self.principal.full_name, "principal", "JSS 1A", self.session, 2, PrintState.READY, []),
        )
        self.assertEqual(
            (second.requested_by_id, second.requested_by_roles, second.card_count, second.student_ids),
            (self.staff[Role.ADMIN].pk, "admin", 1, [self.ada.pk]),
        )
        self.assertIsNotNone(first.created_at)
        self.assertIsNotNone(first.finished_at)

    def test_the_page_lists_the_log_and_only_the_askers_download(self):
        job, _ = self.printed(self.principal)
        mine = self.overview(self.principal).json()["prints"]
        theirs = self.overview(self.staff[Role.VICE_PRINCIPAL_ACADEMIC]).json()["prints"]
        self.assertEqual([p["id"] for p in mine], [job.pk])
        self.assertEqual((mine[0]["by"], mine[0]["card_count"]), (self.principal.full_name, 2))
        self.assertTrue(mine[0]["mine_to_download"])
        self.assertEqual([p["id"] for p in theirs], [job.pk])
        self.assertFalse(theirs[0]["mine_to_download"])

    def test_a_refused_print_leaves_nothing_in_the_log(self):
        self.start(self.staff[Role.TEACHER])
        with connected_to(self.stmarys):
            self.assertFalse(IdCardPrint.objects.exists())


class ADayTests(IdCardSetUp):
    def age(self, job, by):
        with connected_to(self.stmarys):
            StoredFile.objects.filter(key=job.file_key).update(created_at=timezone.now() - by)
            IdCardPrint.objects.filter(pk=job.pk).update(
                created_at=timezone.now() - by, finished_at=timezone.now() - by
            )

    def on_disk(self, job):
        return storage.path_of("st_marys", job.file_key, printing.VARIANT).exists()

    def test_kept_for_a_day(self):
        job, _ = self.printed(self.principal)
        self.age(job, timedelta(hours=23, minutes=59))
        with connected_to(self.stmarys), self.captureOnCommitCallbacks(execute=True):
            files_service.sweep()
        self.assertTrue(self.on_disk(job))
        self.assertEqual(self.download(self.principal, job.pk).status_code, 200)

    def test_after_24_hours_it_is_refused_removed_and_the_log_stays(self):
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
            log = IdCardPrint.objects.get(pk=job.pk)
        self.assertFalse(self.on_disk(job))
        self.assertEqual(self.download(self.principal, job.pk).status_code, 410)
        # The print log: who, which class, which term, how many.
        self.assertEqual(
            (log.requested_by_id, log.class_group_name, log.card_count, log.state),
            (self.principal.pk, "JSS 1A", 2, PrintState.READY),
        )
        self.assertIn("same QR codes", self.status(self.principal, job.pk).json()["detail"])

    def test_the_file_is_private_and_made_not_uploaded(self):
        job, _ = self.printed(self.principal)
        with connected_to(self.stmarys):
            stored = StoredFile.objects.get(key=job.file_key)
        self.assertEqual((stored.kind, stored.public, stored.origin), ("id_cards", False, "made"))
        self.assertEqual(stored.uploaded_by_id, self.principal.pk)

    def test_the_sweep_leaves_other_schools_alone(self):
        job, _ = self.printed(self.principal)
        self.age(job, timedelta(days=2))
        with connected_to(self.grace), self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(files_service.sweep()["expired"], 0)
        self.assertTrue(self.on_disk(job))


class TheJobTests(IdCardSetUp):
    def test_pressing_twice_is_one_job(self):
        with self.captureOnCommitCallbacks(execute=True):
            first = self.start(self.principal).json()["id"]
        with self.captureOnCommitCallbacks(execute=True):
            second = self.start(self.principal).json()["id"]
        self.assertEqual(first, second)
        self.assertEqual(len(self.queued), 1)

    def test_two_people_pressing_are_two_jobs(self):
        first = self.start(self.principal).json()["id"]
        second = self.start(self.staff[Role.ADMIN]).json()["id"]
        self.assertNotEqual(first, second)

    def test_the_message_names_the_school_and_the_job(self):
        with self.captureOnCommitCallbacks(execute=True):
            job_id = self.start(self.staff[Role.VICE_PRINCIPAL_ACADEMIC]).json()["id"]
        self.assertIn(("st_marys", job_id), self.queued)

    def test_a_second_worker_leaves_a_live_job_alone_and_takes_over_a_dead_one(self):
        job_id = self.start(self.principal).json()["id"]
        with connected_to(self.stmarys):
            self.assertIsNotNone(printing.claim(job_id))
            self.assertIsNone(printing.claim(job_id), "the heartbeat is fresh")
            later = timezone.now() + printing.STALE_AFTER + timedelta(seconds=1)
            self.assertIsNotNone(printing.claim(job_id, now=later), "the heartbeat went stale")

    def test_a_job_whose_message_was_lost_is_asked_for_again_by_a_status_read(self):
        job_id = self.start(self.principal).json()["id"]
        with connected_to(self.stmarys):
            IdCardPrint.objects.filter(pk=job_id).update(last_enqueued_at=timezone.now() - timedelta(minutes=5))
        with self.captureOnCommitCallbacks(execute=True):
            self.status(self.principal, job_id)
        self.assertEqual(len(self.queued), 1)

    def test_a_finished_job_is_not_made_twice(self):
        job, _ = self.printed(self.principal)
        self.assertIsNone(self.run_job(job.pk))

    def test_a_job_that_dies_says_so_and_leaves_nothing_in_the_build_directory(self):
        job_id = self.start(self.principal).json()["id"]
        with mock.patch.object(printing, "merge", side_effect=RuntimeError("pikepdf fell over")):
            build_id_cards.apply(args=["st_marys", job_id])
        answer = self.status(self.principal, job_id).json()
        self.assertEqual(answer["state"], PrintState.FAILED)
        self.assertNotIn("pikepdf", answer["detail"])
        self.assertIsNone(answer["download_url"])
        with connected_to(self.stmarys):
            self.assertIn("pikepdf fell over", IdCardPrint.objects.get(pk=job_id).error)
        self.assertEqual(list((storage.root() / storage.BUILDING / "st_marys").iterdir()), [])
        self.assertEqual(self.download(self.principal, job_id).status_code, 409)

    def test_progress_is_reported(self):
        job_id = self.start(self.principal).json()["id"]
        answer = self.status(self.principal, job_id).json()
        self.assertEqual((answer["state"], answer["done"], answer["total"]), ("pending", 0, 2))
        self.run_job(job_id)
        answer = self.status(self.principal, job_id).json()
        self.assertEqual((answer["state"], answer["done"], answer["total"]), ("ready", 2, 2))
        self.assertEqual(answer["download_url"], f"/api/id-cards/jobs/{job_id}/pdf/")
        self.assertIn("2 ID cards ready", answer["detail"])
        self.assertIn("flipped on the long edge", answer["detail"])

    def test_the_file_is_sent_to_the_browser_with_a_sensible_name(self):
        job, _ = self.printed(self.principal)
        response = self.download(self.principal, job.pk)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("id-cards-jss-1a", response["Content-Disposition"])
        self.assertIn("private", response["Cache-Control"])
