"""What Classnode's blog keeps: its posts, their pictures, and the writers' sign-in codes.

All in the public schema, in `SHARED_APPS`: the blog is the platform's own and
no school's, the same reason `website.DemoRequest` is there. `docs/blog.md`
says what each rule is for; the rules themselves are in `blog.workflow`
(who may do what to a post), `blog.markdown` (what a post's words may turn
into) and `blog.images` (what a picture is turned into).
"""

import secrets

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Status(models.TextChoices):
    """A post's three states. Only `PUBLISHED` is ever on classnode.co."""

    DRAFT = "draft", "Draft"
    IN_REVIEW = "review", "In review"
    PUBLISHED = "published", "Published"


class Role(models.TextChoices):
    """`accounts.User.blog_role`, named. Blank is everybody who is not a blog account."""

    WRITER = "writer", "Writer"
    EDITOR = "editor", "Editor"


#: The longest each field may be, which the editor's counters show and the
#: form holds. Titles and descriptions are the lengths search results show.
TITLE_MAX = 120
SLUG_MAX = 80
SUMMARY_MAX = 200
SEO_TITLE_MAX = 60
SEO_DESCRIPTION_MAX = 155
ALT_MAX = 200
TAGS_MAX = 5
TAG_MAX = 30


class PostQuerySet(models.QuerySet):
    def published(self):
        """What classnode.co may show: published, and nothing else, ever."""
        return self.filter(status=Status.PUBLISHED)

    def visible_to(self, user):
        """What `user` may open on /write/: an editor every post, a writer their own."""
        if getattr(user, "blog_role", "") == Role.EDITOR:
            return self
        if getattr(user, "blog_role", "") == Role.WRITER:
            return self.filter(author=user)
        return self.none()


class Post(models.Model):
    """One post, from its first draft to its publication and back.

    `body` is the Markdown the writer typed; `html` is what it was rendered
    and sanitised into (`blog.markdown.render()`) the last time it was saved,
    with its pictures pointing at `/blog/images/`. The public page draws `html`
    and never renders anything itself.
    """

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="blog_posts", on_delete=models.PROTECT
    )
    status = models.CharField(max_length=16, choices=Status, default=Status.DRAFT)

    title = models.CharField(max_length=TITLE_MAX, blank=True)
    slug = models.SlugField(max_length=SLUG_MAX, unique=True)
    summary = models.CharField(max_length=SUMMARY_MAX, blank=True)
    body = models.TextField(blank=True)
    html = models.TextField(blank=True, editable=False)
    words = models.PositiveIntegerField(default=0, editable=False)
    seo_title = models.CharField(max_length=SEO_TITLE_MAX, blank=True)
    seo_description = models.CharField(max_length=SEO_DESCRIPTION_MAX, blank=True)
    tags = models.JSONField(default=list, blank=True)
    cover = models.ForeignKey(
        "BlogImage", null=True, blank=True, related_name="+", on_delete=models.SET_NULL
    )
    cover_alt = models.CharField(max_length=ALT_MAX, blank=True)

    #: What the editor said when they sent it back. Cleared when it is sent again.
    review_note = models.TextField(blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)
    submitted_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    #: Set once, the first time it is published. The address is fixed from then
    #: on (`blog.workflow`), so a link anybody shared keeps working.
    first_published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        related_name="+",
        on_delete=models.PROTECT,
    )

    objects = PostQuerySet.as_manager()

    class Meta:
        ordering = ["-published_at", "-updated_at", "-id"]
        indexes = [models.Index(fields=["status", "-published_at"])]
        constraints = [
            # A published post carries the date it was published: the list,
            # the sitemap and the structured data all read it.
            models.CheckConstraint(
                condition=~Q(status="published") | Q(published_at__isnull=False),
                name="blog_published_post_has_a_date",
            ),
            models.CheckConstraint(
                condition=Q(status__in=["draft", "review", "published"]),
                name="blog_post_status_is_known",
            ),
        ]

    def __str__(self):
        return self.title or self.slug

    @property
    def is_published(self) -> bool:
        return self.status == Status.PUBLISHED

    @property
    def minutes(self) -> int:
        """Minutes to read, at 200 words a minute, and never 0."""
        return max(1, -(-self.words // 200))

    @property
    def page_title(self) -> str:
        return self.seo_title or self.title

    @property
    def page_description(self) -> str:
        return self.seo_description or self.summary


def new_key() -> str:
    return secrets.token_hex(16)


class BlogImage(models.Model):
    """A picture for one post, as WebP, drawn again from the upload (`blog.images`).

    Kept in the database, as a school's crest is (`results.ReportCardSettings`),
    because the platform has no file storage. `key` is random, so a picture's
    address says nothing about any other, and **it is served on classnode.co
    only while its post is published** (`blog.views.image`). `small` is the
    same picture half as wide, for a phone.
    """

    key = models.CharField(max_length=32, unique=True, default=new_key, editable=False)
    post = models.ForeignKey(Post, related_name="images", on_delete=models.CASCADE)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="+", on_delete=models.PROTECT
    )
    is_cover = models.BooleanField(default=False)
    width = models.PositiveIntegerField()
    height = models.PositiveIntegerField()
    data = models.BinaryField()
    small_width = models.PositiveIntegerField()
    small_height = models.PositiveIntegerField()
    small = models.BinaryField()
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.key} ({self.width}x{self.height})"

    @property
    def bytes(self) -> int:
        return len(self.data)


class CodeStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    CONFIRMED = "confirmed", "Confirmed"
    SPENT = "spent", "Spent"


class SignInCode(models.Model):
    """A six-digit code emailed to a blog account, stored as its SHA-256 only.

    `accounts.GuardianContactCode`'s rules, for a writer's email rather than a
    guardian's channel (`blog.signin` says why it is a table of its own): one
    live code per account, five guesses, a fifteen-minute life, and every
    lookup scoped to the account, never global, because six digits collide.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="blog_sign_in_codes", on_delete=models.CASCADE
    )
    code_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=CodeStatus, default=CodeStatus.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    #: When a worker took it to send, so it is sent at most once (`blog.tasks`).
    claimed_at = models.DateTimeField(null=True, blank=True)
    #: What the provider said: an `messaging.models.Outcome` value, or blank.
    outcome = models.CharField(max_length=16, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["user", "created_at"]),
        ]

    def __str__(self):
        return f"{self.get_status_display()} blog code for {self.user_id}"

    @property
    def is_expired(self) -> bool:
        return timezone.now() >= self.expires_at
