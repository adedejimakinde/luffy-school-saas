"""`/llms.txt`: a plain Markdown summary of the public site for AI search tools.

The format is llmstxt.org's: a title, a one-paragraph summary in a quote, then
sections of plain text and links. Written for ChatGPT, Gemini, Perplexity,
Claude and the like to read in one go, and answered on `settings.SITE_HOST`
only, like every page in `urls_site.py`.

Nothing in it is typed in twice. The features are `website.features`, which the
homepage, the pricing page and the FAQ read too; the price is `website.price`,
from `settings.PRICE_PER_STUDENT_NAIRA`; the pages and what they say about
themselves are `website.views.pages()`, the privacy notice and the terms listed
last and only once they are no longer a draft (as the sitemap does); and the
blog's posts are the published ones, never a draft. So the file moves when the
pricing page does.
"""

import re

from django.conf import settings
from django.http import HttpResponse
from django.urls import reverse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_http_methods

from .crawlers import site_url
from . import price
from .features import GROUPS
from .views import LEGAL_IN_DRAFT, LEGAL_PAGES, pages

#: How many of the newest blog posts the file lists. The blog has the rest.
POSTS = 25

_SPACE = re.compile(r"\s+")


def _line(text):
    """`text` on one line, for a list item or a link's words."""
    return _SPACE.sub(" ", str(text)).strip()


def _link(title, url, about):
    title = _line(title).replace("[", "(").replace("]", ")")
    return f"- [{title}]({url}): {_line(about)}"


def _feature(feature):
    return f"- {feature.name}: {_line(feature.line)}" + (f" {_line(feature.detail)}" if feature.detail else "")


def llms_text():
    """The whole file, as it should read now."""
    from blog.models import Post

    site = site_url()
    lines = [
        "# Classnode",
        "",
        "> Classnode is school management software for Nigerian secondary schools, made by "
        "Classnode Edtech Limited (RC 9926572) in Abeokuta, Ogun State. Teachers enter scores and "
        "take registers on their phones. The school approves results, prints report cards, tracks "
        "fees and lets parents check results online. " + price.sentence(),
        "",
        "## Who it is for",
        "",
        "Private secondary schools in Nigeria: their principals, bursars, exam officers and "
        "teachers, and the parents of their students. Schools in Ogun State can print the Ogun "
        "State report card.",
        "",
        "## What it includes",
        "",
    ]
    for heading, features in GROUPS:
        lines += [f"### {heading}", ""]
        lines += [_feature(feature) for feature in features]
        lines.append("")
    lines += [
        "## Data",
        "",
        "Each school's records are kept apart from every other school's. Staff see only their own "
        "part, by role, and parents see only their own children.",
        "",
        "## Price",
        "",
        price.sentence(),
        "",
        "## Pages",
        "",
    ]
    meta = pages()
    for name, (title, about) in meta.items():
        if name not in LEGAL_PAGES:
            lines.append(_link(title, site + reverse(name), about))
    posts = list(
        Post.objects.published()
        .order_by("-published_at")
        .only("slug", "title", "seo_title", "summary", "seo_description")[:POSTS]
    )
    if posts:
        lines += ["", "## Blog", ""]
        lines += [
            _link(post.page_title, site + reverse("blog-post", args=[post.slug]), post.page_description)
            for post in posts
        ]
    if not LEGAL_IN_DRAFT:
        lines += ["", "## Optional", ""]
        lines += [
            _link(meta[name][0], site + reverse(name), meta[name][1])
            for name in sorted(LEGAL_PAGES)
        ]
    lines += [
        "",
        "## Contact",
        "",
        f"- Email: {price.CONTACT_EMAIL}",
        f"- Book a demo: {site}/#demo",
        "- Location: Abeokuta, Ogun State, Nigeria",
    ]
    if settings.SITE_PHONE:
        lines.append(f"- Phone: {settings.SITE_PHONE}")
    lines.append("")
    return "\n".join(lines)


#: How long a reader may keep the file. An hour: a post published or a price changed shows
#: within it, and a crawler fetching the file does not reach the database every time.
CACHE_SECONDS = 3600


@require_http_methods(["GET", "HEAD"])
@cache_control(public=True, max_age=CACHE_SECONDS)
def llms(request):
    return HttpResponse(llms_text(), content_type="text/markdown; charset=utf-8")
