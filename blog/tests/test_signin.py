"""Signing in to the blog: an email, then the code sent to it (`blog.signin`)."""

import re
from datetime import timedelta
from unittest import mock

from django.utils import timezone

from accounts.models import SignInAttempts
from blog import signin, tasks
from blog.models import CodeStatus, SignInCode
from messaging.models import FakeMessage

from .fixtures import BlogSetUp


def sent_now(code_id, sealed):
    """The worker's job, done on the spot, as if the queue were instant."""
    return tasks.send_sign_in_code(code_id, sealed)


class SignInSetUp(BlogSetUp):
    def setUp(self):
        patcher = mock.patch.object(
            tasks.send_sign_in_code, "apply_async",
            side_effect=lambda args, retry: sent_now(*args),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def ask(self, email, address="10.0.0.1"):
        self.client.logout()
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                "/write/sign-in/", {"email": email}, HTTP_HOST="app.classnode.testserver",
                REMOTE_ADDR=address,
            )

    def answer(self, email, code, address="10.0.0.1"):
        return self.client.post(
            "/write/sign-in/", {"email": email, "code": code}, HTTP_HOST="app.classnode.testserver",
            REMOTE_ADDR=address,
        )

    def code_sent_to(self, email):
        message = FakeMessage.objects.filter(address=email).order_by("-id").first()
        return re.search(r"\b(\d{6})\b", message.text).group(1) if message else None


class TheDoorTests(SignInSetUp):
    def test_a_writer_gets_a_code_by_email_and_signs_in_with_it(self):
        response = self.ask("Writer@Blog.example")
        self.assertContains(response, signin.CODE_REQUESTED)
        code = self.code_sent_to(self.writer.email)
        self.assertIsNotNone(code)
        self.assertIn("sign-in code", FakeMessage.objects.get().text)
        stored = SignInCode.objects.get(user=self.writer)
        self.assertNotIn(code, stored.code_hash)

        response = self.answer("writer@blog.example", code)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/write/")
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.writer.pk)
        self.assertEqual(SignInCode.objects.get(pk=stored.pk).status, CodeStatus.CONFIRMED)

    def test_the_answer_is_the_same_for_an_address_that_is_nobodys_or_school_staffs(self):
        for email in ("nobody@example.com", "teacher@sunrise.example"):
            with self.subTest(email=email):
                response = self.ask(email)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, signin.CODE_REQUESTED)
        self.assertFalse(FakeMessage.objects.exists())
        self.assertFalse(SignInCode.objects.exists())

    def test_a_wrong_code_is_refused_in_one_sentence_and_signs_nobody_in(self):
        self.ask(self.writer.email)
        response = self.answer(self.writer.email, "000000" if self.code_sent_to(self.writer.email) != "000000" else "111111")
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, signin.REFUSED, status_code=400)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_a_code_dies_after_five_wrong_guesses_and_after_fifteen_minutes(self):
        self.ask(self.writer.email)
        code = self.code_sent_to(self.writer.email)
        wrong = "999999" if code != "999999" else "888888"
        for _ in range(5):
            self.answer(self.writer.email, wrong)
        self.assertEqual(self.answer(self.writer.email, code).status_code, 400)

        self.ask(self.writer.email)
        code = self.code_sent_to(self.writer.email)
        SignInCode.objects.filter(status=CodeStatus.PENDING).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.answer(self.writer.email, code).status_code, 400)

    def test_a_new_code_ends_the_one_before_it(self):
        self.ask(self.writer.email)
        first = self.code_sent_to(self.writer.email)
        self.ask(self.writer.email)
        second = self.code_sent_to(self.writer.email)
        self.assertEqual(SignInCode.objects.filter(status=CodeStatus.PENDING).count(), 1)
        if first != second:
            self.assertEqual(self.answer(self.writer.email, first).status_code, 400)
        self.assertEqual(self.answer(self.writer.email, second).status_code, 302)

    def test_a_code_cannot_open_another_accounts_session(self):
        self.ask(self.writer.email)
        code = self.code_sent_to(self.writer.email)
        self.assertEqual(self.answer(self.editor.email, code).status_code, 400)

    def test_no_more_than_five_codes_an_hour_and_the_same_answer_after(self):
        for _ in range(7):
            response = self.ask(self.writer.email)
            self.assertContains(response, signin.CODE_REQUESTED)
        self.assertEqual(FakeMessage.objects.count(), signin.SENDS_PER_HOUR)

    def test_too_many_wrong_codes_close_the_door_for_a_while(self):
        self.ask(self.writer.email)
        with self.settings(SIGN_IN_MAX_FAILURES_PER_CHANNEL=3):
            for _ in range(3):
                self.answer(self.writer.email, "123456", address="10.0.0.9")
            response = self.answer(self.writer.email, "123456", address="10.0.0.9")
        self.assertEqual(response.status_code, 429)
        self.assertTrue(SignInAttempts.objects.filter(scope="blog_email").exists())

    def test_a_removed_account_gets_no_code(self):
        self.writer.is_active = False
        self.writer.save(update_fields=["is_active"])
        self.ask(self.writer.email)
        self.assertFalse(FakeMessage.objects.exists())

    def test_signing_out(self):
        self.client.force_login(self.writer)
        response = self.client.post("/write/sign-out/", HTTP_HOST="app.classnode.testserver")
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_the_door_is_a_csrf_checked_form(self):
        from django.test import Client

        strict = Client(enforce_csrf_checks=True)
        response = strict.post("/write/sign-in/", {"email": self.writer.email}, HTTP_HOST="app.classnode.testserver")
        self.assertEqual(response.status_code, 403)
