"""The blog on classnode.co: the list, each post, and their pictures.

Server-drawn pages of the public site (`website.views.site_page`), so each is
indexable and carries its own title, description and canonical address, and
each post its own share card (the cover) and Article structured data. **Only
published posts exist here.** A draft or a post in review is a 404 at its
address, its pictures are 404s, and none of it is in the sitemap; there is no
switch on this host that shows anything else.

No script but the site's own (the phone menu). The editor's module is served
on the portal's `/write/` and is never named by a page here.
"""

from django.core.paginator import EmptyPage, Paginator
from django.http import Http404, HttpResponse
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from website.crawlers import site_url
from website.views import _json_ld, site_page

from .models import BlogImage, Post

PER_PAGE = 12

#: The blog's own stylesheet, after website.css (`website/base.html`).
STYLESHEETS = ("blog/blog.css",)

#: The columns a list or a card needs. A post's body, its HTML and its
#: pictures' bytes stay in the database.
_CARD = ("cover__data", "cover__small", "body", "html")


def published():
    return (
        Post.objects.published()
        .select_related("cover", "author")
        .defer(*_CARD)
        .order_by("-published_at", "-id")
    )


@require_http_methods(["GET", "HEAD"])
def index(request, page=1):
    """Every published post, newest first, twelve to a page; or "First posts coming soon"."""
    if page == 1 and request.resolver_match.url_name != "site-blog":
        # /blog/page/1/ is /blog/.
        raise Http404("Page 1 is /blog/.")
    paginator = Paginator(published(), PER_PAGE)
    try:
        current = paginator.page(page)
    except EmptyPage:
        if page != 1:
            raise Http404("No such page.")
        current = paginator.page(1)
    posts = list(current.object_list)
    context = {
        "posts": posts,
        "page": current,
        "paginator": paginator,
        "nav_blog": True,
        "stylesheets": STYLESHEETS,
    }
    if page > 1:
        context.update(
            title=f"Blog, page {page}: Classnode",
            description=f"Page {page} of Classnode's blog for Nigerian secondary schools.",
            canonical=site_url() + request.path,
        )
    if posts:
        context["lead_image"] = posts[0].cover
    return site_page(request, "blog/index.html", context)


def _article(post, canonical, image_url):
    site = site_url()
    return _json_ld({
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": post.title[:110],
        "description": post.page_description,
        "image": [image_url],
        "datePublished": post.first_published_at.isoformat(),
        "dateModified": max(post.updated_at, post.published_at).isoformat(),
        "author": {"@type": "Person", "name": post.author.full_name},
        "publisher": {
            "@type": "Organization",
            "@id": f"{site}/#organization",
            "name": "Classnode Edtech Limited",
            "logo": {
                "@type": "ImageObject",
                "url": site + static("website/logo.png"),
                "width": 512,
                "height": 512,
            },
        },
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical},
        "keywords": ", ".join(post.tags),
    })


@require_http_methods(["GET", "HEAD"])
def post(request, slug):
    """One published post. Anything else at this address is a 404."""
    found = (
        Post.objects.published()
        .select_related("cover", "author")
        .defer("cover__data", "cover__small")
        .filter(slug=slug)
        .first()
    )
    if found is None:
        raise Http404("No such post.")
    canonical = site_url() + reverse("blog-post", args=[found.slug])
    image_url = (
        site_url() + reverse("blog-image", args=[found.cover.key]) if found.cover_id else ""
    )
    more = list(published().exclude(pk=found.pk)[:3])
    return site_page(
        request,
        "blog/post.html",
        {
            "post": found,
            "more": more,
            "title": found.page_title,
            "description": found.page_description,
            "canonical": canonical,
            "og_type": "article",
            "og_image": image_url,
            "og_image_alt": found.cover_alt,
            "structured_data": _article(found, canonical, image_url),
            "nav_blog": True,
            "stylesheets": STYLESHEETS,
        },
    )


def serve_image(image, small: bool):
    data = bytes(image.small if small else image.data)
    response = HttpResponse(data, content_type="image/webp")
    response["Content-Length"] = str(len(data))
    return response


@require_http_methods(["GET", "HEAD"])
def image(request, key, small=False):
    """A published post's picture. A draft's, or one that does not exist, is a 404."""
    found = BlogImage.objects.filter(key=key, post__status="published").first()
    if found is None:
        raise Http404("No such picture.")
    response = serve_image(found, small)
    # An hour: a picture whose post is unpublished stops being served here at
    # once, and a reader's copy goes stale within the hour.
    response["Cache-Control"] = "public, max-age=3600"
    return response


@require_http_methods(["GET", "HEAD"])
def image_small(request, key):
    return image(request, key, small=True)


__all__ = ["index", "post", "image", "image_small"]
