"""`/llms.txt`: a plain Markdown summary of the public site for AI search tools.

The format is llmstxt.org's: a title, a one-paragraph summary in a quote, then
sections of plain text and links. Written for ChatGPT, Gemini, Perplexity,
Claude and the like to read in one go, and answered on `settings.SITE_HOST`
only, like every page in `urls_site.py`.

Nothing in it is typed in twice. The features come from `website.features`,
which the pricing page draws and which reads its "coming soon" settings on
every request; the price is `website.views.PRICE`; the pages and what they say
about themselves are `website.views.PAGES`, the privacy notice and the terms
listed last and only once they are no longer a draft (as the sitemap does); the blog's posts are the
published ones. So the file moves when the pricing page does.
"""

import re

from django.conf import settings
from django.http import HttpResponse
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from .crawlers import site_url
from .features import included, premium
from .views import LEGAL_IN_DRAFT, LEGAL_PAGES, PAGES, PRICE

#: How many of the newest blog posts the file lists. The blog has the rest.
POSTS = 25

_SPACE = re.compile(r"\s+")


def _line(text):
    """`text` on one line, for a list item or a link's words."""
    return _SPACE.sub(" ", str(text)).strip()


def _link(title, url, about):
    title = _line(title).replace("[", "(").replace("]", ")")
    return f"- [{title}]({url}): {_line(about)}"


def _feature(item):
    soon = " (coming soon)" if item["coming_soon"] else ""
    return f"- {item['label']}{soon}: {item['sentence']}"


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
        "fees and lets parents check results online. " + PRICE,
        "",
        "## Who it is for",
        "",
        "Principals, bursars, exam officers and teachers at Nigerian secondary schools, and the "
        "parents of their students. Schools in Ogun State can switch on the report sheet the "
        "Ministry asks for.",
        "",
        "## What it includes",
        "",
    ]
    for group in included():
        lines += [f"### {group['heading']}", ""]
        lines += [_feature(item) for item in group["items"]]
        lines.append("")
    lines += [
        "### Premium add-on (priced by asking)",
        "",
        *[_feature(item) for item in premium()],
        "",
        "## Works on weak networks and cheap phones",
        "",
        "Classnode runs in the browser on the phones teachers already carry. There is nothing to "
        "install. When the network drops, scores and registers stay on the phone and send when the "
        "connection comes back.",
        "",
        "## Data",
        "",
        "Each school's records are kept apart from every other school's. Staff see only their own "
        "part, by role, and parents see only their own children. The database is backed up every "
        "night.",
        "",
        "## Price",
        "",
        PRICE,
        "",
        "## Pages",
        "",
    ]
    for name, (title, about) in PAGES.items():
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
            _link(PAGES[name][0], site + reverse(name), PAGES[name][1])
            for name in sorted(LEGAL_PAGES)
        ]
    lines += [
        "",
        "## Contact",
        "",
        "- Email: hello@classnode.co",
        f"- Book a demo: {site}/#demo",
        "- Location: Abeokuta, Ogun State, Nigeria",
    ]
    if settings.SITE_PHONE:
        lines.append(f"- Phone: {settings.SITE_PHONE}")
    lines.append("")
    return "\n".join(lines)


@require_http_methods(["GET", "HEAD"])
def llms(request):
    return HttpResponse(llms_text(), content_type="text/plain; charset=utf-8")
