"""What the blog's tests stand on: the site, the portal, two schools, and every kind of login.

Two real schools, because a rule about "any school's data" is a rule about
more than one (`docs/claude-memory/luffy-phase-1-workflow.md`). Each has its
own host and a teacher with a password; the writer, the second writer and the
editor are blog accounts and nothing else; platform staff are platform staff.
"""

import io

from django.db import connection
from django.test import TestCase, override_settings

from accounts.models import Role as SchoolRole
from accounts.models import User
from accounts.services import grant_membership
from blog import images, workflow
from blog.models import Post
from schools.models import Domain, School
from schools.tests.tenants import make_school

SITE = "classnode.testserver"
PORTAL = "app.classnode.testserver"
SCHOOLS = (("Sunrise Academy", "sunrise", "sunrise"), ("Harbour College", "harbour", "harbour"))


def picture(width=1600, height=1000, fmt="PNG", colour=(20, 61, 140)) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(out, format=fmt)
    return out.getvalue()


def complete(post, by, *, slug=None, body="Words a reader reads.\n\n## A heading\n\nMore words."):
    """Fill in everything a post needs to be published, cover included."""
    post = workflow.save(by, post, {
        "title": f"A post called {slug or post.pk}",
        "slug": slug or f"post-{post.pk}",
        "summary": "What the post is about, in a sentence.",
        "body": body,
        "seo_title": "A post for search",
        "seo_description": "What a search result says about the post.",
        "cover_alt": "A plain blue picture standing in for a photo",
        "tags": ["Fees"],
    })
    cover = images.store(post, picture(), cover=True, by=by)
    return workflow.set_cover(by, post, cover)


@override_settings(
    SITE_HOST=SITE,
    ALLOWED_HOSTS=[".classnode.testserver", "testserver"],
    MESSAGING_PROVIDERS={"email": "messaging.fake.FakeProvider", "phone": "messaging.fake.FakeProvider"},
)
class BlogSetUp(TestCase):
    @classmethod
    def setUpTestData(cls):
        portal = School(name="Portal", slug="portal", schema_name="public")
        portal.auto_create_schema = False
        portal.save()
        Domain.objects.create(tenant=portal, domain=PORTAL, is_primary=True)

        cls.schools = {}
        cls.teachers = {}
        for name, slug, schema in SCHOOLS:
            school = make_school(name, slug, schema)
            host = f"{slug}.classnode.testserver"
            Domain.objects.create(tenant=school, domain=host, is_primary=True)
            teacher = User.objects.create_user(
                f"{slug}-teacher", "a-long-password-1", full_name=f"{name} Teacher",
                email=f"teacher@{slug}.example",
            )
            grant_membership(teacher, school, SchoolRole.TEACHER)
            cls.schools[host] = school
            cls.teachers[host] = teacher

        def blog_account(username, name, role):
            user = User(username=username, email=username, full_name=name, blog_role=role)
            user.set_unusable_password()
            user.save()
            return user

        cls.writer = blog_account("writer@blog.example", "Kemi Oladipo", "writer")
        cls.other_writer = blog_account("other@blog.example", "Ifeoma Nwosu", "writer")
        cls.editor = blog_account("editor@blog.example", "Tunde Bello", "editor")
        cls.ops = User.objects.create_user(
            "ops", "a-long-password-1", full_name="Platform Staff", is_platform_staff=True
        )

    def tearDown(self):
        # A request to a school's host leaves the connection on its schema.
        connection.set_schema_to_public()

    # -- requests ------------------------------------------------------------

    def as_(self, user):
        self.client.logout()
        if user is not None:
            self.client.force_login(user)
        return self.client

    def get(self, path, host=PORTAL, user=None, **extra):
        return self.as_(user).get(path, HTTP_HOST=host, **extra)

    def post(self, path, data=None, host=PORTAL, user=None, **extra):
        return self.as_(user).post(path, data or {}, HTTP_HOST=host, **extra)

    def site(self, path):
        self.client.logout()
        return self.client.get(path, HTTP_HOST=SITE)

    # -- posts ---------------------------------------------------------------

    def draft(self, author=None, slug=None):
        author = author or self.writer
        return complete(workflow.new_post(author), author, slug=slug)

    def in_review(self, author=None, slug=None):
        post = self.draft(author, slug)
        return workflow.submit(author or self.writer, post)

    def published(self, slug=None):
        post = self.in_review(slug=slug)
        return workflow.publish(self.editor, post)

    def reload(self, post) -> Post:
        return Post.objects.get(pk=post.pk)
