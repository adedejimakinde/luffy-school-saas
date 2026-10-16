"""Who reaches what: a writer, an editor, school staff, platform staff, and nobody signed in.

The two rules the owner asked to see held with a control (`docs/blog.md`
records the runs):

- **A writer cannot publish.** `WriterCannotPublishTests`, through
  `blog.workflow.publish()`'s editor check, the one place that decides it.
- **A writer cannot reach a school's data.** `WriterCannotReachSchoolDataTests`,
  through `blog.middleware.BlogAccountMiddleware`. A blog account can hold no
  membership (a trigger) and is never platform staff (a check), so a writer
  with no membership is refused by `SchoolAccessMiddleware` as well; the test
  that matters is the one where the trigger has been got round and the writer
  *does* hold a membership, because there the middleware is the only thing
  between them and the school's books.
"""

from django.db import IntegrityError, connection, transaction

from accounts.models import Membership, MembershipStatus
from accounts.models import Role as SchoolRole
from accounts.services import grant_membership
from blog.models import Status

from .fixtures import PORTAL, BlogSetUp

SUNRISE = "sunrise.classnode.testserver"
HARBOUR = "harbour.classnode.testserver"

#: A school's pages and the API they read: a frame, the register and the fee books.
SCHOOL_PATHS = ("/home/", "/register/", "/fees/", "/api/fees/classes/", "/api/home/")

#: The portal's pages that are not the blog's: the platform, its API, the admin, the doors.
PORTAL_PATHS = (
    "/platform/",
    "/platform/handover/",
    "/api/platform/schools/",
    "/api/platform/unrouted/",
    "/admin/",
    "/sign-in/",
    "/staff-sign-in/",
    "/home/",
)

BLOG_ONLY = "blog only"


class WriterCannotPublishTests(BlogSetUp):
    """The page shows a writer no Publish button; this posts it anyway."""

    def assert_still(self, post, status):
        self.assertEqual(self.reload(post).status, status)
        self.assertEqual(self.site(f"/blog/{post.slug}/").status_code, 404)
        self.assertNotIn(f"/blog/{post.slug}/", self.site("/sitemap.xml").content.decode())

    def test_a_writer_cannot_publish_their_own_draft(self):
        post = self.draft(slug="writers-draft")
        response = self.post(f"/write/posts/{post.pk}/", {"action": "publish"}, user=self.writer)
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "Only an editor can do that.", status_code=403)
        self.assert_still(post, Status.DRAFT)

    def test_a_writer_cannot_publish_their_post_in_review(self):
        post = self.in_review(slug="writers-review")
        response = self.post(f"/write/posts/{post.pk}/", {"action": "publish"}, user=self.writer)
        self.assertEqual(response.status_code, 403)
        self.assert_still(post, Status.IN_REVIEW)

    def test_a_writer_cannot_unpublish_or_send_back(self):
        live = self.published(slug="live-one")
        response = self.post(f"/write/posts/{live.pk}/", {"action": "unpublish"}, user=self.writer)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.reload(live).status, Status.PUBLISHED)

        waiting = self.in_review(slug="waiting-one")
        response = self.post(
            f"/write/posts/{waiting.pk}/", {"action": "send_back", "note": "x"}, user=self.writer
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.reload(waiting).status, Status.IN_REVIEW)

    def test_a_writer_cannot_change_their_post_once_it_is_in_review(self):
        post = self.in_review(slug="frozen")
        response = self.post(
            f"/write/posts/{post.pk}/", {"action": "save", "title": "Changed"}, user=self.writer
        )
        self.assertEqual(response.status_code, 403)
        self.assertNotEqual(self.reload(post).title, "Changed")

    def test_an_editor_can_publish_and_it_is_public_at_once(self):
        """The other side of the rule: the same request, from an editor, works."""
        post = self.in_review(slug="for-the-editor")
        response = self.post(f"/write/posts/{post.pk}/", {"action": "publish"}, user=self.editor)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.reload(post).status, Status.PUBLISHED)
        self.assertEqual(self.site("/blog/for-the-editor/").status_code, 200)
        self.assertIn("/blog/for-the-editor/", self.site("/sitemap.xml").content.decode())


class WriterCannotReachSchoolDataTests(BlogSetUp):
    def assert_refused(self, response, where):
        self.assertEqual(response.status_code, 403, where)
        self.assertIn(BLOG_ONLY, response.content.decode(), where)

    def test_a_writer_is_refused_on_every_schools_host(self):
        for host in (SUNRISE, HARBOUR):
            for path in SCHOOL_PATHS:
                with self.subTest(host=host, path=path):
                    self.assert_refused(self.get(path, host=host, user=self.writer), f"{host}{path}")

    def test_even_holding_a_membership_the_trigger_should_have_refused(self):
        """The trigger got round (as a bad migration or a raw insert might), and still refused.

        A bursar at Sunrise reads Sunrise's fee books; this writer is made one
        with the trigger off, and the books are still out of reach.
        """
        school = self.schools[SUNRISE]
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL session_replication_role = replica")
            Membership.objects.create(
                user=self.writer, school=school, role=SchoolRole.BURSAR,
                status=MembershipStatus.ACTIVE,
            )
            cursor.execute("SET LOCAL session_replication_role = origin")
        self.assertEqual(self.writer.roles_at(school), {SchoolRole.BURSAR})

        bursar = self.teachers[SUNRISE]
        grant_membership(bursar, school, SchoolRole.BURSAR)
        books = self.get("/api/fees/classes/", host=SUNRISE, user=bursar)
        self.assertEqual(books.status_code, 200, "a bursar there does read the books")

        for path in SCHOOL_PATHS:
            with self.subTest(path=path):
                self.assert_refused(self.get(path, host=SUNRISE, user=self.writer), path)

    def test_an_editor_is_refused_on_every_schools_host_too(self):
        for path in SCHOOL_PATHS:
            with self.subTest(path=path):
                self.assert_refused(self.get(path, host=HARBOUR, user=self.editor), path)

    def test_a_writer_and_an_editor_reach_nothing_on_the_portal_but_the_blog(self):
        for user in (self.writer, self.editor):
            for path in PORTAL_PATHS:
                with self.subTest(user=user.username, path=path):
                    self.assert_refused(self.get(path, user=user), path)
            with self.subTest(user=user.username, path="/write/"):
                self.assertEqual(self.get("/write/", user=user).status_code, 200)


class ABlogAccountIsNothingElseTests(BlogSetUp):
    """The two rules in the database: no membership, and never platform staff."""

    def test_a_blog_account_cannot_be_given_a_membership(self):
        with self.assertRaisesRegex(IntegrityError, "blog_account_holds_no_membership"):
            with transaction.atomic():
                grant_membership(self.writer, self.schools[SUNRISE], SchoolRole.TEACHER)

    def test_a_member_of_a_school_cannot_be_made_a_blog_account(self):
        teacher = self.teachers[SUNRISE]
        teacher.blog_role = "writer"
        with self.assertRaisesRegex(IntegrityError, "membership_holder_gets_no_blog_role"):
            with transaction.atomic():
                teacher.save()

    def test_platform_staff_cannot_be_a_blog_account(self):
        self.ops.blog_role = "editor"
        with self.assertRaisesRegex(IntegrityError, "blog_account_is_not_staff"):
            with transaction.atomic():
                self.ops.save()


class WritersAndTheirPostsTests(BlogSetUp):
    def test_a_writer_sees_their_own_posts_and_never_another_writers(self):
        mine = self.draft(slug="mine")
        theirs = self.draft(self.other_writer, slug="theirs")
        page = self.get("/write/", user=self.writer).content.decode()
        self.assertIn("A post called mine", page)
        self.assertNotIn("A post called theirs", page)
        for path in (
            f"/write/posts/{theirs.pk}/",
            f"/write/posts/{theirs.pk}/view/",
        ):
            with self.subTest(path=path):
                self.assertEqual(self.get(path, user=self.writer).status_code, 404)
        for path in (f"/write/posts/{theirs.pk}/preview/", f"/write/posts/{theirs.pk}/images/"):
            with self.subTest(path=path):
                self.assertEqual(self.post(path, user=self.writer).status_code, 404)
        image = theirs.cover.key
        self.assertEqual(self.get(f"/write/images/{image}.webp", user=self.writer).status_code, 404)
        self.assertEqual(self.get(f"/write/posts/{mine.pk}/", user=self.writer).status_code, 200)

    def test_a_writer_cannot_edit_another_writers_draft(self):
        theirs = self.draft(self.other_writer, slug="not-yours")
        response = self.post(
            f"/write/posts/{theirs.pk}/", {"action": "save", "title": "Mine now"}, user=self.writer
        )
        self.assertEqual(response.status_code, 404)
        self.assertNotEqual(self.reload(theirs).title, "Mine now")

    def test_a_writer_cannot_open_the_review_queue(self):
        self.assertEqual(self.get("/write/review/", user=self.writer).status_code, 403)

    def test_a_writer_creates_edits_and_sends_for_review(self):
        response = self.post("/write/new/", user=self.writer)
        self.assertEqual(response.status_code, 302)
        post = self.writer.blog_posts.get()
        self.assertEqual(post.status, Status.DRAFT)
        response = self.post(f"/write/posts/{post.pk}/", {"action": "submit", "title": "Half a post"}, user=self.writer)
        self.assertEqual(response.status_code, 400, "not ready: no summary, cover or SEO fields")
        self.assertContains(response, "Add a cover picture", status_code=400)
        self.assertEqual(self.reload(post).status, Status.DRAFT)
        post = self.draft(slug="ready")
        response = self.post(f"/write/posts/{post.pk}/", {"action": "submit"}, user=self.writer)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.reload(post).status, Status.IN_REVIEW)


class EditorsTests(BlogSetUp):
    def test_an_editor_sees_every_post_in_the_review_queue(self):
        self.in_review(slug="one")
        self.in_review(self.other_writer, slug="two")
        page = self.get("/write/review/", user=self.editor).content.decode()
        self.assertIn("A post called one", page)
        self.assertIn("A post called two", page)

    def test_an_editor_edits_any_post_in_any_state(self):
        for post in (self.draft(slug="d"), self.in_review(slug="r"), self.published(slug="p")):
            with self.subTest(status=post.status):
                response = self.post(
                    f"/write/posts/{post.pk}/",
                    {"action": "save", "title": "Edited by the editor", "summary": post.summary,
                     "body": post.body, "seo_title": post.seo_title,
                     "seo_description": post.seo_description, "cover_alt": post.cover_alt},
                    user=self.editor,
                )
                self.assertEqual(response.status_code, 302)
                self.assertEqual(self.reload(post).title, "Edited by the editor")

    def test_send_back_returns_it_to_the_writer_with_the_note(self):
        post = self.in_review(slug="back")
        response = self.post(
            f"/write/posts/{post.pk}/", {"action": "send_back", "note": "Shorten the opening."},
            user=self.editor,
        )
        self.assertEqual(response.status_code, 302)
        post = self.reload(post)
        self.assertEqual((post.status, post.review_note), (Status.DRAFT, "Shorten the opening."))
        self.assertContains(self.get("/write/", user=self.writer), "Shorten the opening.")

    def test_unpublish_takes_it_off_the_site_and_the_sitemap_at_once(self):
        post = self.published(slug="gone-soon")
        self.assertEqual(self.site("/blog/gone-soon/").status_code, 200)
        image = post.cover.key
        self.assertEqual(self.site(f"/blog/images/{image}.webp").status_code, 200)
        response = self.post(f"/write/posts/{post.pk}/", {"action": "unpublish"}, user=self.editor)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.reload(post).status, Status.DRAFT)
        self.assertEqual(self.site("/blog/gone-soon/").status_code, 404)
        self.assertEqual(self.site(f"/blog/images/{image}.webp").status_code, 404)
        self.assertNotIn("gone-soon", self.site("/sitemap.xml").content.decode())
        self.assertNotIn("gone-soon", self.site("/blog/").content.decode())


class SchoolStaffAndPlatformStaffTests(BlogSetUp):
    def test_school_staff_cannot_open_the_writing_side(self):
        teacher = self.teachers[SUNRISE]
        post = self.draft(slug="private")
        for path in ("/write/", "/write/review/", f"/write/posts/{post.pk}/"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path, user=teacher).status_code, 403)
        self.assertEqual(self.post("/write/new/", user=teacher).status_code, 403)
        self.assertEqual(self.post(f"/write/posts/{post.pk}/", {"action": "publish"}, user=teacher).status_code, 403)
        self.assertEqual(self.reload(post).status, Status.DRAFT)

    def test_school_staff_still_reach_their_school(self):
        """The blog's middleware asks nothing of a login that is not a blog account."""
        teacher = self.teachers[SUNRISE]
        self.assertEqual(self.get("/home/", host=SUNRISE, user=teacher).status_code, 200)

    def test_platform_staff_are_not_editors(self):
        post = self.in_review(slug="for-staff")
        for path in ("/write/", "/write/review/", f"/write/posts/{post.pk}/"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path, user=self.ops).status_code, 403)
        self.assertEqual(self.post(f"/write/posts/{post.pk}/", {"action": "publish"}, user=self.ops).status_code, 403)
        self.assertEqual(self.reload(post).status, Status.IN_REVIEW)


class NobodySignedInTests(BlogSetUp):
    def test_the_writing_side_sends_them_to_sign_in(self):
        post = self.draft(slug="anon")
        for path in ("/write/", "/write/review/", f"/write/posts/{post.pk}/", f"/write/posts/{post.pk}/view/"):
            with self.subTest(path=path):
                response = self.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response["Location"].startswith("/write/sign-in/?next="))
        self.assertEqual(self.post(f"/write/posts/{post.pk}/", {"action": "publish"}).status_code, 302)
        self.assertEqual(self.reload(post).status, Status.DRAFT)
        self.assertEqual(self.post(f"/write/posts/{post.pk}/preview/", {"body": "x"}).status_code, 401)
        self.assertEqual(self.get(f"/write/images/{post.cover.key}.webp").status_code, 404)

    def test_the_writing_side_is_on_the_portal_alone(self):
        from .fixtures import SITE

        for host in (SITE, SUNRISE):
            with self.subTest(host=host):
                self.assertEqual(self.get("/write/", host=host).status_code, 404)
                self.assertEqual(self.get("/write/sign-in/", host=host).status_code, 404)

    def test_every_writing_page_is_noindex(self):
        self.assertEqual(self.get("/write/sign-in/")["X-Robots-Tag"], "noindex, nofollow")
        self.assertContains(self.get("/write/sign-in/"), '<meta name="robots" content="noindex, nofollow">')
        page = self.get("/write/", user=self.writer)
        self.assertEqual(page["X-Robots-Tag"], "noindex, nofollow")
        self.assertContains(page, '<meta name="robots" content="noindex, nofollow">')

    def test_portal_pages_still_answer_anybody_not_signed_in(self):
        self.assertEqual(self.get("/sign-in/").status_code, 200)
        self.assertEqual(self.get("/staff-sign-in/").status_code, 200)
        self.assertEqual(PORTAL, "app.classnode.testserver")


class UploadsTests(BlogSetUp):
    def test_a_picture_is_stored_as_webp_and_its_key_answered(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from blog import images

        from .fixtures import picture

        post = self.draft(slug="with-pictures")
        upload = SimpleUploadedFile("photo.png", picture(2400, 1200), content_type="image/png")
        response = self.post(f"/write/posts/{post.pk}/images/", {"file": upload}, user=self.writer)
        self.assertEqual(response.status_code, 200)
        answer = response.json()
        self.assertEqual((answer["width"], answer["height"]), (1600, 800))
        image = self.get(f"/write/images/{answer['key']}.webp", user=self.writer)
        self.assertEqual(image["Content-Type"], "image/webp")
        self.assertEqual(image["Cache-Control"], "private, no-store")

        too_big = SimpleUploadedFile("huge.png", b"x" * (images.MAX_UPLOAD_BYTES + 1), content_type="image/png")
        response = self.post(f"/write/posts/{post.pk}/images/", {"file": too_big}, user=self.writer)
        self.assertEqual(response.status_code, 400)
        self.assertIn("at most 10 MB", response.json()["detail"])

    def test_a_writer_cannot_add_a_picture_once_the_post_is_in_review(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from .fixtures import picture

        post = self.in_review(slug="no-more-pictures")
        upload = SimpleUploadedFile("photo.png", picture(), content_type="image/png")
        response = self.post(f"/write/posts/{post.pk}/images/", {"file": upload}, user=self.writer)
        self.assertEqual(response.status_code, 403)
