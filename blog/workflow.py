"""Who may do what to a post, and the three states it moves between.

    Draft --submit--> In review --publish--> Published
      ^                 |                      |
      +---send back-----+                      |
      +----------------------unpublish---------+

- **A writer** creates posts, edits their own while they are drafts, and sends
  them for review. Nothing else: not another writer's post, not their own
  once it is in review or published, and never publish or unpublish.
- **An editor** may do everything to every post: edit it in any state,
  publish it, send it back with a note, unpublish it. An editor's own draft
  can be published straight from draft.
- **Anybody else** is not a blog account and gets nothing here; `blog.views`
  refuses them before they reach this module, and every function below asks
  again, so a new caller cannot forget.

Every move locks the post's row first, so two editors pressing Publish and
Send back at once leave it in one state, decided by whoever got there first.

**Publishing needs a whole post**: a title, an address, a summary, words, a
cover and its description, an SEO title and description, and a description
for every picture in the body (`problems()`). A writer is told the same list
when they send it for review.
"""

import re
import secrets

from django.db import transaction
from django.utils import timezone

from . import markdown
from .models import Post, Role, Status

SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
#: Addresses the blog's own routes use (`/blog/page/2/`, `/blog/images/...`).
RESERVED_SLUGS = {"page", "images", "write", "feed", "rss"}


class NotAllowed(Exception):
    """This person may not do this to this post. The message is for them."""


class NotReady(Exception):
    """The post is missing something it needs to go further. `problems` says what."""

    def __init__(self, problems):
        super().__init__("This post is not ready yet.")
        self.problems = list(problems)


def is_blog_account(user) -> bool:
    return bool(getattr(user, "is_authenticated", False) and getattr(user, "blog_role", ""))


def is_editor(user) -> bool:
    return is_blog_account(user) and user.blog_role == Role.EDITOR


def is_writer(user) -> bool:
    return is_blog_account(user) and user.blog_role == Role.WRITER


def can_open(user, post) -> bool:
    """Whether `user` may see this post on /write/ at all."""
    return is_editor(user) or (is_writer(user) and post.author_id == user.pk)


def can_edit(user, post) -> bool:
    """An editor, always; its writer, while it is a draft."""
    if is_editor(user):
        return True
    return is_writer(user) and post.author_id == user.pk and post.status == Status.DRAFT


def _require(allowed: bool, message: str):
    if not allowed:
        raise NotAllowed(message)


def _require_editor(user):
    _require(is_editor(user), "Only an editor can do that.")


def _locked(post) -> Post:
    return Post.objects.select_for_update().get(pk=post.pk)


# -- making and saving -------------------------------------------------------


def new_post(author) -> Post:
    """An empty draft for `author`, with a placeholder address until it has a title."""
    _require(is_blog_account(author), "Only a writer or an editor can write a post.")
    return Post.objects.create(author=author, slug=f"draft-{secrets.token_hex(4)}")


def slug_problem(slug: str, post=None):
    """Why `slug` cannot be this post's address, or None."""
    if not slug:
        return "Give the post an address."
    if len(slug) > 80 or not SLUG.match(slug):
        return "An address is lower-case letters, numbers and single hyphens, like second-term-fees."
    if slug in RESERVED_SLUGS:
        return "That address is used by the blog itself. Choose another."
    taken = Post.objects.filter(slug=slug)
    if post is not None:
        taken = taken.exclude(pk=post.pk)
    if taken.exists():
        return "Another post already has that address."
    return None


def rendered(post) -> str:
    """The body as the public page draws it, pictures from `/blog/images/`."""
    images = {image.key: image for image in post.images.all()}
    return markdown.render(post.body, images=images, base="/blog/images/")


@transaction.atomic
def save(actor, post, values: dict) -> Post:
    """Write `values` (already checked by `blog.forms.PostForm`) to the post.

    The address is fixed once the post has been published, so a link somebody
    shared keeps working; `values["slug"]` is ignored from then on.
    """
    post = _locked(post)
    _require(can_edit(actor, post), "You cannot change this post now.")
    if post.first_published_at is not None:
        values = {k: v for k, v in values.items() if k != "slug"}
    for field, value in values.items():
        setattr(post, field, value)
    post.html = rendered(post)
    post.words = markdown.words(post.body)
    post.updated_at = timezone.now()
    post.save()
    return post


@transaction.atomic
def set_cover(actor, post, image) -> Post:
    post = _locked(post)
    _require(can_edit(actor, post), "You cannot change this post now.")
    _require(image.post_id == post.pk, "That picture belongs to another post.")
    post.cover = image
    post.updated_at = timezone.now()
    post.save(update_fields=["cover", "updated_at"])
    return post


def problems(post) -> list:
    """What the post still needs before it can be sent for review or published."""
    found = []
    if not post.title.strip():
        found.append("Give it a title.")
    slug = slug_problem(post.slug, post)
    if slug or post.slug.startswith("draft-"):
        found.append(slug or "Give it an address of its own.")
    if not post.summary.strip():
        found.append("Write a summary.")
    if not post.body.strip():
        found.append("Write the post.")
    if post.cover_id is None:
        found.append("Add a cover picture. It is also the picture shown when the post is shared.")
    elif not post.cover_alt.strip():
        found.append("Describe the cover picture.")
    if not post.seo_title.strip():
        found.append("Give it an SEO title.")
    if not post.seo_description.strip():
        found.append("Give it an SEO description.")
    if markdown.images_without_alt(post.body):
        found.append("Describe every picture in the post.")
    keys = set(post.images.values_list("key", flat=True))
    if any(key not in keys for key in markdown.image_keys(post.body)):
        found.append("A picture in the post is not one uploaded to it. Add it again.")
    return found


def _require_ready(post):
    found = problems(post)
    if found:
        raise NotReady(found)


# -- the moves ---------------------------------------------------------------


@transaction.atomic
def submit(actor, post) -> Post:
    """Draft to In review, by its writer (or an editor, for their own)."""
    post = _locked(post)
    _require(
        is_blog_account(actor) and post.author_id == actor.pk,
        "Only the post's writer can send it for review.",
    )
    _require(post.status == Status.DRAFT, "This post is not a draft.")
    _require_ready(post)
    post.status = Status.IN_REVIEW
    post.submitted_at = timezone.now()
    post.review_note = ""
    post.save(update_fields=["status", "submitted_at", "review_note"])
    return post


@transaction.atomic
def publish(actor, post) -> Post:
    """In review (or an editor's draft) to Published. Editors only."""
    post = _locked(post)
    _require_editor(actor)
    _require(post.status != Status.PUBLISHED, "This post is already published.")
    _require_ready(post)
    now = timezone.now()
    post.status = Status.PUBLISHED
    post.published_at = now
    post.first_published_at = post.first_published_at or now
    post.published_by = actor
    post.review_note = ""
    post.html = rendered(post)
    post.save()
    return post


@transaction.atomic
def unpublish(actor, post) -> Post:
    """Published back to Draft: off classnode.co and out of the sitemap at once."""
    post = _locked(post)
    _require_editor(actor)
    _require(post.status == Status.PUBLISHED, "This post is not published.")
    post.status = Status.DRAFT
    post.published_at = None
    post.save(update_fields=["status", "published_at"])
    return post


@transaction.atomic
def send_back(actor, post, note: str) -> Post:
    """In review back to Draft, with the editor's note for the writer."""
    post = _locked(post)
    _require_editor(actor)
    _require(post.status == Status.IN_REVIEW, "This post is not in review.")
    post.status = Status.DRAFT
    post.review_note = (note or "").strip()
    post.save(update_fields=["status", "review_note"])
    return post
