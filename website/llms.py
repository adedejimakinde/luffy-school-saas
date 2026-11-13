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

from django.http import HttpResponse
from django.urls import reverse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_http_methods

from .contact import contact
from .crawlers import site_url
from . import price
from .features import GROUPS, feature
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
    details = contact()
    lines = [
        "# Classnode",
        "",
        "> Classnode is school management software for secondary schools across Nigeria, made by "
        "Classnode Edtech Limited (RC 9926572), based in " + (details["location"] or "Nigeria") + ". Teachers enter scores and "
        "take registers on their phones. The school approves results, prints report cards, tracks "
        "fees and lets parents check results online. " + price.sentence(),
        "",
        "## Who it is for",
        "",
        "Private secondary schools across Nigeria: their principals, bursars, exam officers and "
        "teachers, and the parents of their students. Report cards are the standard report card, "
        "or your state's format such as the Ogun State report sheet.",
        "",
        "## What it includes",
        "",
    ]
    for heading, features in GROUPS:
        lines += [f"### {heading}", ""]
        lines += [_feature(feature) for feature in features]
        lines.append("")
    lines += [
        "## About and security",
        "",
        f"Classnode is run by Classnode Edtech Limited, RC 9926572, based in {details['location'] or 'Nigeria'}. "
        "It was founded by Adedeji Makinde.",
        "",
        f"- Backups: {_line(feature('backups').line)}",
        "- Each school's records are kept apart from every other school's.",
        "- Staff see only their own part, by role.",
        "- Parents see only their own children.",
        f"- More: {site}/about/",
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
        f"- Email: {details['email']}",
        f"- Book a demo: {site}/#demo",
    ]
    if details["location"]:
        lines.append(f"- Location: {details['location']}")
    if details["phone"]:
        lines.append(f"- Support phone: {details['phone']}")
    if details["linkedin"]:
        lines.append(f"- LinkedIn: {details['linkedin']}")
    if details["google"]:
        lines.append(f"- Google Business Profile: {details['google']}")
    lines.append("")
    return "\n".join(lines)


#: How long a reader may keep the file. An hour: a post published or a price changed shows
#: within it, and a crawler fetching the file does not reach the database every time.
CACHE_SECONDS = 3600


@require_http_methods(["GET", "HEAD"])
@cache_control(public=True, max_age=CACHE_SECONDS)
def llms(request):
    return HttpResponse(llms_text(), content_type="text/markdown; charset=utf-8")
