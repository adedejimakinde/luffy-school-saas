"""Classnode's public site, on `settings.SITE_HOST` only: the homepage, the
pricing page, the questions and answers, the privacy notice, the terms and the
sitemap (`website.llms` answers `/llms.txt`).

All server-drawn, like a school's own page (`schools.views.school_site`): the
one inline script moves the homepage's slider, counts its figures up and closes
the phone menu, and is not needed to read anything or to send the form. The
homepage's other `<script>` is structured data for search engines, which no
browser runs.

The only host search engines are asked to index (`website/crawlers.py`), so
every page here carries its own title, description, canonical address and
share card (`site_page`).
"""

import json
import re
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_http_methods

from accounts.throttling import client_address
from schools.hosts import portal_host

from .crawlers import NOINDEX, site_url
from .features import included, premium
from .forms import DemoRequestForm
from .models import DemoRequest
from .notify import demo_requested

#: The price as the page prints it, comma and all. Structured data's `price`
#: stays the bare number schema.org asks for; every sentence carries this.
#: `docs/website.md` lists where it appears.
PRICE = "The first term is free, then ₦1,500 per student, per term. No setup fee."

#: Each public page's title and description, by route name, in the order the
#: sitemap lists them. Every title is the page's own, starts or ends with the
#: name, and is 60 characters or fewer, so a search result shows all of it; every
#: description is under 155. A page added to `urls_site.py` is added here too,
#: or its tests say so.
PAGES = {
    "site-home": (
        "Classnode: School software for Nigerian schools",
        "Results, report cards, fees and registers for Nigerian secondary schools. " + PRICE,
    ),
    "site-pricing": (
        "Classnode pricing: first term free, then ₦1,500",
        "Everything Classnode includes for every school, and the premium add-on. " + PRICE,
    ),
    "site-faq": (
        "Classnode FAQ: Nigerian school software questions",
        "Plain answers on what Classnode does, the Ogun State report card, the price, weak "
        "networks, parents' results, your data and CBT.",
    ),
    "site-privacy": (
        "Privacy notice: Classnode",
        "What Classnode collects about schools, staff, students and parents, why we use it, "
        "who sees it, how long we keep it, and your rights.",
    ),
    "site-terms": (
        "Terms of use: Classnode",
        "The terms for schools using Classnode: what the service does, signing in, fees, "
        "the school's data, our responsibility and ending the service.",
    ),
    "site-blog": (
        "Classnode blog: results, fees and registers",
        "Notes for principals, bursars and teachers on running a Nigerian secondary school: "
        "results, fees, registers and the term in between.",
    ),
}

#: The homepage's questions and answers, drawn on the page and given to search
#: engines as FAQPage structured data from this one list, so the two cannot
#: differ. Answers are HTML written here; the structured data carries their text.
FAQ = [
    ("Do our teachers need laptops?",
     "No. Classnode works in the browser on the phones your teachers already carry. "
     "There is nothing to install."),
    ("What happens when the network is bad?",
     "Scores and registers stay on the phone and send when the connection comes back. "
     "Teachers can keep working in the meantime."),
    ("Can we use the Ogun State report sheet?",
     "Yes. Switch on the Ogun State template in setup and your report cards follow the "
     "sheet the Ministry asks for."),
    ("Can we bring our current student list?",
     "Yes. Send it as an Excel or CSV file and it is imported into your classes. We help "
     "you with it during setup."),
    ("How do parents pay school fees?",
     "By bank transfer, the way they already do. Each child has their own account number, "
     "so the payment shows on that child's record."),
    ("Who can see our school's records?",
     "Only your staff, each according to their role, and parents for their own children. "
     "Your records are kept apart from every other school's. Our "
     '<a href="/privacy/">privacy notice</a> has the details.'),
]


#: The CBT features by the name the page gives them, in the order the pricing
#: page lists them; each is governed by its own "coming soon" setting
#: (`website.features`).
_CBT = {
    "CBT: school tests": "school tests",
    "CBT: UTME-style practice": "UTME-style practice",
    "CBT: WASSCE-style practice": "WASSCE-style practice",
}


def _series(names):
    """`names` as a plain English list: "a", "a and b", "a, b and c"."""
    names = list(names)
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _cbt_answer():
    """Whether Classnode has CBT, as the pricing page says it today.

    Read from the same "coming soon" settings as the pricing page on every
    request, so this answer changes the day a setting does and not later.
    """
    items = {item["label"]: item["coming_soon"] for group in included() for item in group["items"]}
    soon = [name for label, name in _CBT.items() if items[label]]
    live = [name for label, name in _CBT.items() if not items[label]]
    if not live:
        return ("Not yet. CBT is coming soon: " + _series(soon) + ", all on questions the school "
                "writes. Exam PIN slips are available now.")
    if not soon:
        return ("Yes. Teachers write questions, set timed tests, and the computer marks them. "
                "UTME-style and WASSCE-style practice use questions the school writes.")
    return ("Part of it. Available now: " + _series(live) + ". Coming soon: " + _series(soon)
            + ". All of it uses questions the school writes.")


def faq_page():
    """The questions on `/faq/`, as (question, answer) with the answer written in HTML.

    Drawn on the page and given to search engines as FAQPage structured data
    from this one list, as the homepage's `FAQ` is. Every answer says what the
    product does today, in the words the pricing page and the homepage use.
    """
    return [
        ("What is the best school management software for Nigerian secondary schools?",
         "The best one is the one your teachers will really use every day. For a Nigerian secondary "
         "school, that means software that works on a phone, copes with a poor network, and follows "
         "the report sheet your state asks for. Classnode is built for exactly that. It covers results "
         "and report cards, fees, registers and parent result checks. "
         'Book a <a href="/#demo">demo</a> and try it with your own classes.'),
        ("What does Classnode do?",
         "Classnode is school management software for Nigerian secondary schools, made by Classnode "
         "Edtech Limited. Teachers enter CA and exam scores on their phones. Totals, grades, class "
         "positions and remarks are worked out for you. You approve each class, print report cards "
         "with affective and psychomotor ratings, track school fees, take registers and let parents "
         'check results online. See everything in the price on the <a href="/pricing/">pricing page</a>.'),
        ("Does it support the Ogun State report card?",
         "Yes. Switch on the Ogun State template in setup and your report cards follow the sheet "
         "the Ministry asks for."),
        ("How much does it cost?",
         PRICE + " Everything on the "
         '<a href="/pricing/">pricing page</a> is in that price. The premium add-on is priced by asking.'),
        ("Is there a free trial?",
         "Yes. Your school's first term is free, with no setup fee. After that it is ₦1,500 per "
         "student, per term. If you would like to see it first, book a demo and we will call you "
         "within two working days."),
        ("Does it work on weak networks and cheap phones?",
         "Yes. Classnode works in the browser on the phones your teachers already carry. There is "
         "nothing to install and no laptop is needed. Pages are kept light, so they open quickly "
         "on a slow connection. When the network drops, scores and registers stay on the phone and "
         "send when the connection comes back."),
        ("Can parents check results on their phones?",
         "Yes. A parent opens a child's report card in the browser with the admission number and "
         "the PIN on a paper slip. No account is needed. Parents see a result only after you have "
         "approved the class and released it."),
        ("Is our school's data safe and private?",
         "Your school's records are kept apart from every other school's. Only your staff, each "
         "according to their role, and parents for their own children can see them. A payment "
         "cannot be edited or deleted, only reversed with a reason. The database is backed up every "
         'night. Our <a href="/privacy/">privacy notice</a> has the details.'),
        ("How fast can we start?",
         "Book a demo and we will call you within two working days. To set up, send us your class "
         "lists and fee items, as an Excel or CSV file if you have one. We add your classes, "
         "students and staff, then walk your team through it. There is no setup fee."),
        ("Does it have CBT?", _cbt_answer()),
    ]


def site_page(request, template, context=None, status=200):
    """A page of the public site: the one kind of page search engines are asked to index.

    Every view below draws through here, so each page carries its title and
    description from `PAGES`, its canonical address (the bare domain over
    https, no query) and the site's address for the share image, and says it
    is `indexable`, which is what keeps `templates/design/head.html` from
    writing its noindex.

    A page that is not one of `PAGES` (a blog post, the blog's later pages)
    passes its own `title`, `description` and `canonical` in `context`, which
    is read last.
    """
    title, description = PAGES.get(request.resolver_match.url_name, ("", ""))
    return render(
        request,
        template,
        {
            "indexable": True,
            "title": title,
            "description": description,
            "site_url": site_url(),
            "canonical": site_url() + request.path,
            "portal_host": portal_host(),
            **(context or {}),
        },
        status=status,
    )


#: The logo search engines are given, a 512 x 512 PNG of the header's mark at
#: a fixed address on the site (`WHITENOISE_ROOT` in settings.py), never a
#: hashed static name that moves when the file is collected again.
LOGO = "/icon-512.png"


def logo(site):
    """The Organization's `logo`, at `site`'s address."""
    return {"@type": "ImageObject", "url": site + LOGO, "width": 512, "height": 512}


def _json_ld(data):
    """`data` as JSON safe to put inside a `<script>` element."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return mark_safe(text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def _faq_schema(faq):
    """FAQPage structured data for `faq`, a list of (question, answer in HTML)."""
    return {
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": question,
                "acceptedAnswer": {"@type": "Answer", "text": strip_tags(answer)},
            }
            for question, answer in faq
        ],
    }


def _organization(site):
    """Who publishes the site.

    The town and state, and no street: there is no public office to send
    anyone to. The phone line and the LinkedIn and Google Business Profile
    pages are named only when a deployment sets them (`settings.SITE_PHONE`,
    `SITE_LINKEDIN_URL`, `SITE_GOOGLE_BUSINESS_URL`); nothing is made up.
    """
    organization = {
        "@type": "Organization",
        "@id": f"{site}/#organization",
        "name": "Classnode Edtech Limited",
        "alternateName": "Classnode",
        "url": f"{site}/",
        "logo": logo(site),
        "email": "hello@classnode.co",
        "address": {
            "@type": "PostalAddress",
            "addressLocality": "Abeokuta",
            "addressRegion": "Ogun State",
            "addressCountry": "NG",
        },
    }
    if settings.SITE_PHONE:
        organization["telephone"] = settings.SITE_PHONE
    profiles = [
        url
        for url in (settings.SITE_LINKEDIN_URL, settings.SITE_GOOGLE_BUSINESS_URL)
        if url.startswith("https://")
    ]
    if profiles:
        organization["sameAs"] = profiles
    return organization


def structured_data():
    """Who publishes the site, what it sells, and the homepage's questions.

    No street address, no ratings and no reviews: there is no public office,
    and no rating or review exists that we could stand behind.
    """
    site = site_url()
    organization = f"{site}/#organization"
    return _json_ld({
        "@context": "https://schema.org",
        "@graph": [
            _organization(site),
            {
                "@type": "SoftwareApplication",
                "name": "Classnode",
                "url": f"{site}/",
                "applicationCategory": "EducationalApplication",
                "operatingSystem": "Web browser",
                "description": "School management software for Nigerian secondary schools: "
                               "results and report cards, fees and registers in one place. "
                               + PRICE,
                "publisher": {"@id": organization},
                "offers": [
                    {
                        "@type": "Offer",
                        "name": "First term",
                        "price": "0",
                        "priceCurrency": "NGN",
                        "description": "The first term is free. No setup fee.",
                    },
                    {
                        "@type": "Offer",
                        "name": "Every term after the first",
                        "price": "1500",
                        "priceCurrency": "NGN",
                        "description": "₦1,500 per student, per term. No setup fee.",
                        "priceSpecification": {
                            "@type": "UnitPriceSpecification",
                            "price": "1500",
                            "priceCurrency": "NGN",
                            "unitText": "per student, per term",
                        },
                    },
                ],
            },
            _faq_schema(FAQ),
        ],
    })


def faq_structured_data(faq):
    """The `/faq/` page's FAQPage, for the same questions the page shows."""
    return _json_ld({"@context": "https://schema.org", **_faq_schema(faq)})


#: Whether the privacy notice and the terms are still waiting for the lawyer's
#: wording. While they are, each says so in one line at the top, asks search
#: engines not to index it (the page and the `X-Robots-Tag` header, which says
#: it for a reader that is not a browser), and is left out of the sitemap. Flip
#: it to `False` when the lawyer's version is in: the line goes, the pages
#: become indexable and the sitemap lists them again. `docs/handover.md`.
LEGAL_IN_DRAFT = True

#: The routes of the pages `LEGAL_IN_DRAFT` governs.
LEGAL_PAGES = frozenset({"site-privacy", "site-terms"})

#: A fact or a claim still to be settled, drawn on the legal pages as a box
#: (`.todo`). Only `settings.SHOW_LEGAL_TODOS` shows them; a public reader gets
#: the text without them. The notes stay in the templates, so nothing is lost.
_TODO_NOTE = re.compile(r'[ \t]*<span class="todo">.*?</span>', re.S)

#: What a stripped note can leave behind: a paragraph with nothing in it, and a
#: section with a heading and nothing under it (with its line in the contents).
_EMPTY_PARAGRAPH = re.compile(r"[ \t]*<p>\s*</p>\n?")
_EMPTY_SECTION = re.compile(r'<section id="([a-z-]+)">\s*<h2>[^<]*</h2>\s*</section>\n?')


def _without_todo_notes(page):
    """The page as a public reader gets it: no note, no empty paragraph or section."""
    page = _EMPTY_PARAGRAPH.sub("", _TODO_NOTE.sub("", page))
    for section in _EMPTY_SECTION.findall(page):
        page = re.sub(rf'[ \t]*<li><a href="#{section}">[^<]*</a></li>\n?', "", page)
    return _EMPTY_SECTION.sub("", page)


def legal_page(request, template):
    """A legal page: its TODO notes only where the setting asks, and a draft's marks while it is one."""
    response = site_page(
        request,
        template,
        {"indexable": not LEGAL_IN_DRAFT, "legal_draft": LEGAL_IN_DRAFT},
    )
    if not settings.SHOW_LEGAL_TODOS:
        response.content = _without_todo_notes(response.content.decode())
    if LEGAL_IN_DRAFT:
        response["X-Robots-Tag"] = NOINDEX
    return response


#: Where the form sends a reader back to once it is saved: the thank-you, in
#: place of the form, and the browser's back and reload do not post it twice.
SENT = "/?sent=1#demo"


def too_many_from(address):
    """Whether this address has left its hour's worth of requests already."""
    since = timezone.now() - timedelta(hours=1)
    return (
        DemoRequest.objects.filter(address=address, created_at__gte=since).count()
        >= settings.DEMO_REQUESTS_PER_HOUR
    )


@require_http_methods(["GET", "HEAD", "POST"])
def homepage(request):
    form = DemoRequestForm()
    status = 200
    refused = ""
    if request.method == "POST":
        form = DemoRequestForm(request.POST)
        if form.is_bait_taken():
            # Answered as if it worked, so a script learns nothing from it.
            return redirect(SENT)
        if not form.is_valid():
            refused, status = "invalid", 400
        else:
            address = client_address(request)
            if too_many_from(address):
                refused, status = "limited", 429
            else:
                demo = form.save(commit=False)
                demo.address = address
                demo.save()
                transaction.on_commit(lambda: demo_requested(demo.pk))
                return redirect(SENT)
    return site_page(
        request,
        "website/home.html",
        {
            "form": form,
            "refused": refused,
            "sent": request.method == "GET" and request.GET.get("sent") == "1",
            "faq": [(question, mark_safe(answer)) for question, answer in FAQ],
            "structured_data": structured_data(),
        },
        status=status,
    )


@require_http_methods(["GET", "HEAD"])
def pricing(request):
    """The price, everything it includes, and the premium add-on. Which features still wear
    "Coming soon" is `website.features`, read from settings on every request."""
    return site_page(request, "website/pricing.html", {"groups": included(), "premium": premium(), "nav_pricing": True})


@require_http_methods(["GET", "HEAD"])
def faq(request):
    """Ten plain questions and answers, also given to search engines as FAQPage structured data."""
    questions = faq_page()
    return site_page(
        request,
        "website/faq.html",
        {
            "faq": [(question, mark_safe(answer)) for question, answer in questions],
            "structured_data": faq_structured_data(questions),
            "nav_faq": True,
        },
    )


@require_http_methods(["GET", "HEAD"])
def privacy(request):
    """The privacy notice. Plain words, every legal claim marked for the lawyer."""
    return legal_page(request, "website/privacy.html")


@require_http_methods(["GET", "HEAD"])
def terms(request):
    """The terms of use, on the same terms as `privacy`."""
    return legal_page(request, "website/terms.html")


@require_http_methods(["GET", "HEAD"])
def sitemap(request):
    """Every public page, `PAGES`, then every published blog post, and nothing on any other host.

    The privacy notice and the terms are left out while `LEGAL_IN_DRAFT`.

    A post is listed while it is published and not a moment longer: a draft, a
    post in review and an unpublished one are never here (`blog.models.PostQuerySet.published`).
    """
    from blog.models import Post

    posts = Post.objects.published().order_by("-published_at").only("slug", "updated_at")
    return render(
        request,
        "website/sitemap.xml",
        {
            "urls": [
                site_url() + reverse(name)
                for name in PAGES
                if not (LEGAL_IN_DRAFT and name in LEGAL_PAGES)
            ],
            "posts": [
                (site_url() + reverse("blog-post", args=[post.slug]), post.updated_at)
                for post in posts
            ],
        },
        content_type="application/xml; charset=utf-8",
    )
