"""The blog's writing side, on the portal's `/write/` only (`urls_public.py`).

- `/write/sign-in/`: an email, then the code sent to it (`blog.signin`).
- `/write/`: a writer's own posts, by state.
- `/write/posts/<id>/`: the editor. Markdown beside a live preview, the
  cover, the address, the summary, the SEO title and description, the tags,
  and the buttons this person may press on this post now.
- `/write/review/`: every post, for editors only, starting with the ones
  waiting for review.

Plain forms that post and redirect, so every page works with no script; the
editor's module (`static/write/app.js`, named on the editor page and
nowhere else) adds the live preview, the counters, the picture box and the
phone's tabs.

**Who gets in** is asked here first, on every view: nobody signed in is sent
to sign in; a login that is not a blog account (school staff, a parent,
platform staff) is refused; and then `blog.workflow` asks again for each
post and each move. A post a person may not open is a 404, so a writer
cannot learn another writer's drafts exist by trying numbers.

Every page here is the portal's, so `website.crawlers` marks it noindex and
`templates/design/head.html` writes the same.
"""

from urllib.parse import urlencode

from django.contrib.auth import logout
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

import pages
from website.crawlers import site_url

from . import images, markdown, signin, workflow
from .forms import CodeForm, EmailForm, NoteForm, PostForm
from .models import BlogImage, Post, Status
from .views import serve_image

#: The editor's modules, the entry point last (`pages.import_map`). Loaded by
#: the editor's page and no other: never by a page on classnode.co.
EDITOR_MODULES = ("write/tools.js", "write/app.js")

#: Where a picture of a post that is not published yet is served, on the portal.
PORTAL_IMAGES = "/write/images/"

#: The states a list can be narrowed to, in the order the tabs show them.
STATES = [
    ("", "All"),
    (Status.DRAFT, "Drafts"),
    (Status.IN_REVIEW, "In review"),
    (Status.PUBLISHED, "Published"),
]

#: What each move says once it is done, on the editor's page.
DONE = {
    "saved": "Saved.",
    "submitted": "Sent for review. An editor will read it.",
    "published": "Published. It is on classnode.co/blog/ now.",
    "unpublished": "Unpublished. It is off classnode.co and back in Drafts.",
    "sent-back": "Sent back to the writer with your note.",
    "created": "A new draft. Give it a title.",
}


def _require_blog_account(request):
    """None if this is a writer or an editor; otherwise the response to give."""
    if not request.user.is_authenticated:
        return redirect(f"{reverse('write-sign-in')}?{urlencode({'next': request.get_full_path()})}")
    if not workflow.is_blog_account(request.user):
        raise PermissionDenied("This page is for the blog's writers and editors.")
    return None


def _post_for(request, pk) -> Post:
    """The post, if this person may open it; a 404 otherwise, never a 403."""
    post = Post.objects.select_related("author", "cover").filter(pk=pk).first()
    if post is None or not workflow.can_open(request.user, post):
        raise Http404("No such post.")
    return post


def _shell(request, **context):
    return {
        "me": request.user,
        "is_editor": workflow.is_editor(request.user),
        "site_url": site_url(),
        **context,
    }


# -- signing in --------------------------------------------------------------


def _next(request, value):
    if value and url_has_allowed_host_and_scheme(value, allowed_hosts={request.get_host()}) and value.startswith("/write/"):
        return value
    return reverse("write-posts")


@require_http_methods(["GET", "HEAD", "POST"])
def sign_in(request):
    """Step one: an email address. Step two: the code sent to it."""
    if workflow.is_blog_account(request.user):
        return redirect(_next(request, request.GET.get("next")))
    template = "blog/write/sign_in.html"
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    context = {"next": next_url, "step": "email", "site_url": site_url()}

    if request.method != "POST":
        return render(request, template, context)

    if "code" in request.POST:
        form = CodeForm(request.POST)
        context.update(step="code", email=request.POST.get("email", ""))
        if not form.is_valid():
            context["refused"] = signin.REFUSED
            return render(request, template, context, status=400)
        try:
            signin.sign_in_with_code(request, form.cleaned_data["email"], form.cleaned_data["code"])
        except signin.TooManyAttempts:
            context["refused"] = signin.THROTTLED
            return render(request, template, context, status=429)
        except signin.BadCode:
            context["refused"] = signin.REFUSED
            return render(request, template, context, status=400)
        return redirect(_next(request, next_url))

    form = EmailForm(request.POST)
    if not form.is_valid():
        context["refused"] = "Type the email address your blog account uses."
        return render(request, template, context, status=400)
    try:
        signin.request_code(request, form.cleaned_data["email"])
    except signin.TooManyAttempts:
        context["refused"] = signin.THROTTLED
        return render(request, template, context, status=429)
    context.update(step="code", email=form.cleaned_data["email"], sent=signin.CODE_REQUESTED)
    return render(request, template, context)


@require_POST
def sign_out(request):
    logout(request)
    return redirect("write-sign-in")


# -- the lists ---------------------------------------------------------------


def _tabs(queryset, current, url):
    counts = dict(queryset.order_by().values_list("status").annotate(n=Count("pk")))
    tabs = []
    for value, label in STATES:
        tabs.append({
            "value": value,
            "label": label,
            "count": sum(counts.values()) if not value else counts.get(value, 0),
            "href": url if not value else f"{url}?{urlencode({'state': value})}",
            "current": value == current,
        })
    return tabs


def _listed(queryset):
    return queryset.select_related("author").defer("body", "html").order_by("-updated_at", "-id")


@require_http_methods(["GET", "HEAD"])
def posts(request):
    """The signed-in person's own posts, by state."""
    refusal = _require_blog_account(request)
    if refusal:
        return refusal
    state = request.GET.get("state", "")
    if state not in {value for value, _ in STATES}:
        state = ""
    mine = Post.objects.filter(author=request.user)
    shown = mine.filter(status=state) if state else mine
    return render(request, "blog/write/posts.html", _shell(
        request,
        current="posts",
        tabs=_tabs(mine, state, reverse("write-posts")),
        posts=_listed(shown),
    ))


@require_http_methods(["GET", "HEAD"])
def review(request):
    """Every post, for an editor: in review first, oldest waiting at the top."""
    refusal = _require_blog_account(request)
    if refusal:
        return refusal
    if not workflow.is_editor(request.user):
        raise PermissionDenied("Only an editor can open the review queue.")
    state = request.GET.get("state", Status.IN_REVIEW)
    if state not in {value for value, _ in STATES}:
        state = Status.IN_REVIEW
    everything = Post.objects.all()
    shown = everything.filter(status=state) if state else everything
    listed = _listed(shown)
    if state == Status.IN_REVIEW:
        listed = listed.order_by("submitted_at", "id")
    tabs = [tab for tab in _tabs(everything, state, reverse("write-review")) if tab["value"]]
    for tab in tabs:
        if tab["value"] == Status.IN_REVIEW:
            tab["href"] = reverse("write-review")
    return render(request, "blog/write/review.html", _shell(
        request, current="review", tabs=tabs, posts=listed, state=state,
    ))


@require_POST
def new(request):
    refusal = _require_blog_account(request)
    if refusal:
        return refusal
    post = workflow.new_post(request.user)
    return redirect(f"{reverse('write-post', args=[post.pk])}?done=created")


# -- the editor --------------------------------------------------------------


def _current(post) -> dict:
    """The post's fields as the form spells them."""
    return {
        "title": post.title,
        "slug": "" if post.slug.startswith("draft-") else post.slug,
        "summary": post.summary,
        "body": post.body,
        "seo_title": post.seo_title,
        "seo_description": post.seo_description,
        "tags": ", ".join(post.tags),
        "cover_alt": post.cover_alt,
    }


def _sent(request, post) -> dict:
    """The fields this request sent, over the post's own: a field not sent is kept, never blanked."""
    data = _current(post)
    for name in data:
        if name in request.POST:
            data[name] = request.POST[name]
    return data


def _editor(request, post, form=None, *, status=200, problems=None, refused=""):
    if form is None:
        form = PostForm(post=post, initial=_current(post))
    body = form["body"].value() or ""
    preview = markdown.render(
        body, images={i.key: i for i in post.images.all()}, base=PORTAL_IMAGES
    )
    may_edit = workflow.can_edit(request.user, post)
    is_editor = workflow.is_editor(request.user)
    is_author = post.author_id == request.user.pk
    return render(request, "blog/write/editor.html", _shell(
        request,
        current="review" if is_editor and not is_author else "posts",
        post=post,
        form=form,
        preview=preview,
        words=markdown.words(body),
        may_edit=may_edit,
        may_submit=is_author and post.status == Status.DRAFT,
        may_publish=is_editor and post.status != Status.PUBLISHED,
        may_unpublish=is_editor and post.status == Status.PUBLISHED,
        may_send_back=is_editor and post.status == Status.IN_REVIEW,
        problems=problems,
        refused=refused,
        done=DONE.get(request.GET.get("done", ""), ""),
        site_address=f"{site_url()}/blog/",
        portal_images=PORTAL_IMAGES,
        prose=True,
        editor_page=True,
        import_map=pages.import_map(*EDITOR_MODULES),
    ), status=status)


@require_http_methods(["GET", "HEAD", "POST"])
def editor(request, pk):
    refusal = _require_blog_account(request)
    if refusal:
        return refusal
    post = _post_for(request, pk)
    if request.method != "POST":
        return _editor(request, post)

    action = request.POST.get("action", "save")
    form = None
    try:
        if workflow.can_edit(request.user, post) and action in ("save", "submit", "publish", "send_back"):
            form = PostForm(_sent(request, post), request.FILES, post=post)
            if not form.is_valid():
                return _editor(request, post, form, status=400)
            post = workflow.save(request.user, post, form.values())
            upload = form.cleaned_data.get("cover")
            if upload:
                try:
                    picture = images.store(post, _read(upload), cover=True, by=request.user)
                except images.ImageRefused as exc:
                    form.add_error("cover", str(exc))
                    return _editor(request, post, form, status=400)
                post = workflow.set_cover(request.user, post, picture)

        if action == "save":
            if form is None:
                raise workflow.NotAllowed("You cannot change this post now.")
            done = "saved"
        elif action == "submit":
            workflow.submit(request.user, post)
            done = "submitted"
        elif action == "publish":
            workflow.publish(request.user, post)
            done = "published"
        elif action == "unpublish":
            workflow.unpublish(request.user, post)
            done = "unpublished"
        elif action == "send_back":
            note = NoteForm(request.POST)
            workflow.send_back(request.user, post, note.data.get("note", "")[:2000])
            done = "sent-back"
        else:
            raise Http404("No such action.")
    except workflow.NotAllowed as exc:
        post.refresh_from_db()
        return _editor(request, post, form, status=403, refused=str(exc))
    except workflow.NotReady as exc:
        post.refresh_from_db()
        return _editor(request, post, form, status=400, problems=exc.problems)
    return redirect(f"{reverse('write-post', args=[post.pk])}?done={done}")


def _read(upload) -> bytes:
    """An uploaded file's bytes, refused by its size before they are read into memory."""
    if upload is None:
        return b""
    if upload.size > images.MAX_UPLOAD_BYTES:
        raise images.ImageRefused("A picture can be at most 10 MB. Save it smaller and try again.")
    return upload.read()


@require_POST
def preview(request, pk):
    """The Markdown sent, drawn and sanitised exactly as the post would be. Saves nothing."""
    refusal = _require_blog_account(request)
    if refusal:
        return JsonResponse({"detail": "Sign in again."}, status=401)
    post = _post_for(request, pk)
    body = request.POST.get("body", "")
    html = markdown.render(body, images={i.key: i for i in post.images.all()}, base=PORTAL_IMAGES)
    words = markdown.words(body)
    return JsonResponse({"html": html, "words": words, "minutes": max(1, -(-words // 200))})


@require_POST
def upload(request, pk):
    """A picture for the post's body, as WebP. Answers its key, for `![alt](image:KEY)`."""
    refusal = _require_blog_account(request)
    if refusal:
        return JsonResponse({"detail": "Sign in again."}, status=401)
    post = _post_for(request, pk)
    if not workflow.can_edit(request.user, post):
        return JsonResponse({"detail": "You cannot change this post now."}, status=403)
    upload = request.FILES.get("file")
    try:
        picture = images.store(post, _read(upload), cover=False, by=request.user)
    except images.ImageRefused as exc:
        return JsonResponse({"detail": str(exc)}, status=400)
    return JsonResponse({
        "key": picture.key,
        "width": picture.width,
        "height": picture.height,
        "bytes": picture.bytes,
        "src": f"{PORTAL_IMAGES}{picture.key}.webp",
    })


@require_http_methods(["GET", "HEAD"])
def view(request, pk):
    """The post drawn as a reader will see it, on the portal, before or after it is published."""
    refusal = _require_blog_account(request)
    if refusal:
        return refusal
    post = _post_for(request, pk)
    html = markdown.render(
        post.body, images={i.key: i for i in post.images.all()}, base=PORTAL_IMAGES
    )
    return render(request, "blog/write/preview.html", _shell(
        request, current="posts", post=post, html=html, base=PORTAL_IMAGES, prose=True,
    ))


@require_http_methods(["GET", "HEAD"])
def portal_image(request, key, small=False):
    """A picture of a post this person may open. Never cached by anybody else."""
    refusal = _require_blog_account(request)
    if refusal:
        raise Http404("No such picture.")
    found = BlogImage.objects.select_related("post").filter(key=key).first()
    if found is None or not workflow.can_open(request.user, found.post):
        raise Http404("No such picture.")
    response = serve_image(found, small)
    response["Cache-Control"] = "private, no-store"
    return response


@require_http_methods(["GET", "HEAD"])
def portal_image_small(request, key):
    return portal_image(request, key, small=True)
