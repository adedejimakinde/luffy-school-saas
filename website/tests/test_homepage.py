"""Classnode's homepage, on the public site host and nowhere else.

What a browser has to be asked (the slider moving, pausing and holding still
under reduced motion, the figures counting, every width) is
`tests/ui/screens.test.js`'s. This is what the server and the files can answer
for: which host serves the page and what it refuses there, that the words are
the words given and keep the writing rules, that a demo request is saved, sent
to the inbox and platform staff, and refused to a honeypot or a flood, that the
page stays inside its budgets, and that its motion keeps its rules.
"""

import html
import re
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.models import User
from schools.models import Domain, School
from tests.test_budget import STATIC, _ASSET, served_files, urls_in_css
from website.models import DemoRequest

SITE = "classnode.testserver"
PORTAL = "app.classnode.testserver"

#: Every sentence the page was given, word for word.
COPY = [
    "Features", "How it works", "Pricing", "Questions", "Staff sign in", "Parent sign in", "Book a demo",
    "For Nigerian private secondary schools",
    "Results, fees and registers, all in one place.",
    "Teachers enter scores and take the register on their phones. You approve results, see who "
    "has paid, and keep less paper in the office.",
    "See pricing", "₦2,500 per student, per term. No setup fee.",
    "Screens show Crestfield Demo College, a demo school. Every name and figure is made up.",
    "What changes in your school", "Less chasing, less paper, fewer late nights.",
    "Report cards that add up by themselves",
    "Teachers enter CA and exam scores once. Totals and grades are worked out for you, and every "
    "report card carries your crest.",
    "Schools in Ogun State can switch on the report sheet the Ministry and OGSERA ask for.",
    "See who has paid, and who still owes",
    "Each child has their own account number, so a transfer lands on the right record. You see "
    "what came in this term and what is still outstanding, without matching bank alerts to names.",
    "The register, taken on staff phones every morning",
    "Class teachers mark the register with one tap per child. If the network drops, it waits on "
    "the phone and sends when the connection comes back.",
    "Each person sees only their own part",
    "Teachers see their own classes. The bursar sees fees. You see the whole school. A payment "
    "cannot be edited or deleted, only reversed with a reason, and every school's records are "
    "kept apart from every other school's.",
    "Ready for your next term in three steps.",
    "We set up your school",
    "Send us your class lists and fee items. We add your classes, students and staff, then walk "
    "your team through it.",
    "Teachers enter scores and registers",
    "On their own phones, through the term. You can see what is done and what is still waiting.",
    "You approve and release results",
    "Check each class's broadsheet, approve it, and release. Parents read the report card online.",
    "One simple price.", "Per student, per term", "No setup fee.",
    "Results and report cards, including the Ogun State template",
    "Fee tracking, with an account number for each child",
    "Daily registers on staff phones",
    "Logins for the principal, bursar and teachers",
    "Parents read report cards online",
    "We set up your school with you",
    "Leave your details and we will call you within two working days.",
    "Your name", "School name", "Phone number", "Email (optional)", "Number of students",
    "Request a call",
    "What schools ask us.",
    "Do our teachers need laptops?",
    "What happens when the network is bad?",
    "Can we use the Ogun State report sheet?",
    "Can we bring our current student list?",
    "How do parents pay school fees?",
    "Who can see our school's records?",
    "See it with your own classes.",
    "Book a demo and we will call you within two working days.",
    "School management for Nigerian secondary schools.",
    "Product", "Features", "Pricing", "Sign in", "Staff sign in", "Parent sign in",
    "Company", "Privacy", "Terms", "hello@classnode.co",
    "© 2026 Classnode Edtech Limited · RC 9926572",
]

#: The floating cards' figures, each the figure in the showcase's screens
#: (`schools/showcase.py`, `ShowcaseTests` holds the school to them).
FIGURES = {"48.6": 2, "93.8": 1, "7": 1}

#: The writing rules' words and phrases, never on the page.
BANNED = [
    "seamless", "seamlessly", "effortless", "empower", "unlock", "elevate", "revolutionize",
    "streamline", "cutting-edge", "leverage", "robust", "game-changer", "next-level",
    "all-in-one", "one-stop", "world-class", "in today's", "it's not just", "whether you're",
    "look no further", "peace of mind", "take it to the next level", "at your fingertips",
    "journey",
]

FORM = {
    "name": "Mrs Adaeze Obi",
    "school": "Grace Heights College",
    "phone": "0803 555 0100",
    "email": "proprietor@grace.example",
    "students": "640",
}


def visible_text(page, *, questions=True):
    """What a reader is shown or read: the body's text and its labels.

    `questions=False` leaves out the FAQ's questions, the one place a question
    mark belongs."""
    body = page.split("<body", 1)[1]
    if not questions:
        body = re.sub(r"<summary>.*?</summary>", " ", body, flags=re.S)
    body = re.sub(r"<(script|style)\b.*?</\1>", " ", body, flags=re.S)
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.S)
    labels = " ".join(re.findall(r'aria-label="([^"]*)"', body))
    text = re.sub(r"</?(?:span|a|strong|b|em)\b[^>]*>", "", body)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(f"{text} {labels}")).strip()


def words(fragment):
    """`visible_text` of a piece of a page rather than the whole of one."""
    return visible_text(f"<body>{fragment}").removeprefix(">").strip()


@override_settings(
    SITE_HOST=SITE,
    ALLOWED_HOSTS=[".classnode.testserver", "testserver"],
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEMO_REQUESTS_PER_HOUR=3,
    DEMO_REQUEST_INBOX="hello@classnode.co",
)
class SiteSetUp(TestCase):
    @classmethod
    def setUpTestData(cls):
        portal = School(name="Portal", slug="portal", schema_name="public")
        portal.auto_create_schema = False
        portal.save()
        Domain.objects.create(tenant=portal, domain=PORTAL, is_primary=True)
        User.objects.create_user("ops", "a-long-password-1", email="ops@classnode.example",
                                 is_platform_staff=True)
        User.objects.create_user("ops2", "a-long-password-1", email="sales@classnode.example",
                                 is_platform_staff=True)
        # Platform staff with no address, and a school's staff member with one:
        # neither is written to.
        User.objects.create_user("ops3", "a-long-password-1", is_platform_staff=True)
        User.objects.create_user("teacher", "a-long-password-1", email="t@school.example")

    def get(self, path="/", host=SITE, **extra):
        return self.client.get(path, HTTP_HOST=host, **extra)

    def post(self, data=None, address="10.0.0.1"):
        return self.client.post(
            "/", data=FORM if data is None else data, HTTP_HOST=SITE, REMOTE_ADDR=address
        )


class TheSiteHostTests(SiteSetUp):
    def test_the_site_host_serves_the_homepage(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Results, fees and registers, all in one place.")

    def test_www_is_the_same_site(self):
        self.assertEqual(self.get(host=f"www.{SITE}").status_code, 200)

    def test_the_site_host_serves_no_door_admin_or_api(self):
        for path in ("/admin/", "/sign-in/", "/staff-sign-in/", "/api/csrf/", "/platform/",
                     "/cards/", "/check/", "/register/"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path).status_code, 404)

    def test_every_other_host_is_unchanged(self):
        """The portal still has no root, and a host nobody owns is still 404."""
        self.assertEqual(self.get("/", host=PORTAL).status_code, 404)
        self.assertEqual(self.get("/sign-in/", host=PORTAL).status_code, 200)
        self.assertEqual(self.get("/", host="nobody.classnode.testserver").status_code, 404)

    def test_with_no_site_host_the_bare_domain_is_nobodys(self):
        with override_settings(SITE_HOST=None):
            self.assertEqual(self.get().status_code, 404)

    def test_the_doors_are_linked_on_the_portal(self):
        page = self.get().content.decode()
        self.assertIn(f'href="//{PORTAL}/staff-sign-in/"', page)
        self.assertIn(f'href="//{PORTAL}/sign-in/"', page)


class TheWordsTests(SiteSetUp):
    def test_every_given_sentence_is_on_the_page(self):
        text = visible_text(self.get().content.decode())
        for sentence in COPY:
            with self.subTest(sentence=sentence[:40]):
                self.assertIn(sentence, text)

    def test_the_thank_you_replaces_the_form_once_sent(self):
        text = visible_text(self.get("/?sent=1").content.decode())
        self.assertIn("Thank you. We will be in touch soon.", text)
        self.assertNotIn("Request a call", text)

    def test_the_writing_rules_hold(self):
        for path in ("/", "/?sent=1", "/privacy/", "/terms/"):
            page = self.get(path).content.decode()
            text = visible_text(page)
            with self.subTest(path=path):
                self.assertNotRegex(text, "[–—]", "an en or em dash")
                self.assertNotIn("!", text)
                self.assertNotIn("?", visible_text(page, questions=False), "a question outside the FAQ")
                self.assertNotRegex(text, r"(^|[.:] )Imagine\b")
                for word in BANNED:
                    self.assertNotRegex(text.lower(), rf"(?<![a-z]){re.escape(word)}(?![a-z])", word)

    def test_the_faq_is_six_native_questions_that_end_in_one(self):
        page = self.get().content.decode()
        questions = re.findall(r"<details>\s*<summary>(.*?)</summary>", page, flags=re.S)
        self.assertEqual(len(questions), 6)
        for question in questions:
            self.assertTrue(question.endswith("?"), question)

    def test_the_place_for_real_quotes_is_kept_hidden_and_empty(self):
        page = self.get().content.decode()
        proof = re.search(r'<section class="proof" hidden[^>]*>(.*?)</section>', page, flags=re.S)
        self.assertIsNotNone(proof)
        self.assertEqual(proof.group(1).strip(), "")

    def test_the_floating_figures_are_the_screens_figures(self):
        page = self.get().content.decode()
        found = re.findall(r'data-count="([\d.]+)"[^>]*>([\d.]+)<', page)
        for value, shown in found:
            self.assertEqual(value, shown, "the figure without a script is the final one")
        counts = {}
        for value, _ in found:
            counts[value] = counts.get(value, 0) + 1
        self.assertEqual(counts, FIGURES)

    def test_the_writing_rules_find_what_they_look_for(self):
        """The control: a page breaking each rule is caught by the same checks."""
        broken = visible_text("<body><p>A seamless journey — imagine it! Why?</p><summary>Fine?</summary>")
        self.assertRegex(broken, "[–—]")
        self.assertIn("?", visible_text("<body><p>Why?</p><summary>Fine?</summary>", questions=False))
        self.assertNotIn("?", visible_text("<body><summary>Fine?</summary>", questions=False))
        self.assertIn("!", broken)
        self.assertRegex(broken.lower(), r"(?<![a-z])journey(?![a-z])")


class TheFooterTests(SiteSetUp):
    """The owner's footer: the logo and one line, three columns of links, one legal line."""

    def footer(self, path="/"):
        return self.get(path).content.decode().split('<footer class="site-foot', 1)[1].split("</footer>", 1)[0]

    def test_three_columns_hold_the_given_links_in_order(self):
        columns = re.findall(r'<div class="foot-col[^"]*">(.*?)</div>', self.footer(), flags=re.S)
        found = [
            (words(re.search(r"<h2[^>]*>(.*?)</h2>", column, flags=re.S).group(1)),
             [(href, words(label)) for href, label in
              re.findall(r'<a href="([^"]+)">(.*?)</a>', column, flags=re.S)])
            for column in columns
        ]
        self.assertEqual(found, [
            ("Product", [("/#features", "Features"), ("/#pricing", "Pricing"), ("/#demo", "Book a demo")]),
            ("Sign in", [(f"//{PORTAL}/staff-sign-in/", "Staff sign in"),
                         (f"//{PORTAL}/sign-in/", "Parent sign in")]),
            ("Company", [("/privacy/", "Privacy"), ("/terms/", "Terms"),
                         ("mailto:hello@classnode.co", "hello@classnode.co")]),
        ])

    def test_the_logo_and_tagline_come_first(self):
        footer = self.footer()
        self.assertLess(footer.index('class="logo"'), footer.index("foot-tagline"))
        self.assertLess(footer.index("foot-tagline"), footer.index('class="foot-links"'))

    def test_the_company_is_named_once_on_one_legal_line(self):
        for path in ("/", "/privacy/", "/terms/"):
            footer = self.footer(path)
            text = visible_text("<body>" + footer)
            legal = re.search(r'<p class="foot-legal[^"]*">(.*?)</p>\s*</div>\s*$', footer, flags=re.S)
            with self.subTest(path=path):
                self.assertEqual(text.count("Classnode Edtech Limited"), 1)
                self.assertIsNotNone(legal, "the legal line closes the footer")
                self.assertEqual(words(legal.group(1)),
                                 "© 2026 Classnode Edtech Limited · RC 9926572")
                self.assertNotIn("Classnode. Nigeria.", text)
                self.assertEqual(text.count("RC 9926572"), 1)


class TheDemoRequestTests(SiteSetUp):
    def test_a_request_is_saved_and_sent_to_the_inbox_and_platform_staff(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post()
        self.assertRedirects(response, "/?sent=1#demo", fetch_redirect_response=False)
        demo = DemoRequest.objects.get()
        self.assertEqual((demo.school, demo.students, demo.address), ("Grace Heights College", 640, "10.0.0.1"))
        (message,) = mail.outbox
        self.assertEqual(sorted(message.to), ["hello@classnode.co", "ops@classnode.example", "sales@classnode.example"])
        self.assertEqual(message.reply_to, ["proprietor@grace.example"])
        self.assertIn("Grace Heights College", message.subject)
        for line in ("Mrs Adaeze Obi", "0803 555 0100", "Students: 640"):
            self.assertIn(line, message.body)

    @override_settings(DEMO_REQUEST_INBOX="hello@classnode.co")
    def test_the_inbox_is_written_to_with_no_platform_staff_address(self):
        User.objects.filter(is_platform_staff=True).update(email=None)
        with self.captureOnCommitCallbacks(execute=True):
            self.post()
        self.assertEqual(mail.outbox[0].to, ["hello@classnode.co"])

    @override_settings(DEMO_REQUEST_INBOX="")
    def test_without_an_inbox_only_platform_staff_are_written_to(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.post()
        self.assertEqual(sorted(mail.outbox[0].to), ["ops@classnode.example", "sales@classnode.example"])

    def test_email_is_optional(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.post({**FORM, "email": ""})
        self.assertEqual(DemoRequest.objects.get().email, "")
        self.assertIsNone(mail.outbox[0].reply_to or None)

    def test_a_failed_send_keeps_the_request(self):
        with mock.patch("website.notify.EmailMessage.send", side_effect=OSError("down")), \
                self.assertLogs("website.notify", "ERROR"), \
                self.captureOnCommitCallbacks(execute=True):
            response = self.post()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(DemoRequest.objects.count(), 1)

    def test_the_honeypot_saves_and_sends_nothing_and_looks_the_same(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post({**FORM, "website": "http://spam.example"})
        self.assertRedirects(response, "/?sent=1#demo", fetch_redirect_response=False)
        self.assertEqual(DemoRequest.objects.count(), 0)
        self.assertEqual(mail.outbox, [])

    def test_a_missing_or_wrong_field_is_refused_in_a_sentence(self):
        for field, value in (("name", ""), ("school", ""), ("phone", "call me"),
                             ("students", "0"), ("students", "lots"), ("email", "not-an-email")):
            with self.subTest(field=field, value=value):
                response = self.post({**FORM, field: value})
                self.assertEqual(response.status_code, 400)
                page = response.content.decode()
                self.assertIn("Something is missing or not right. Check the marked fields and send it again.", page)
                self.assertRegex(page, rf'name="{field}"[^>]*aria-invalid="true"')
        self.assertEqual(DemoRequest.objects.count(), 0)

    def test_one_address_is_held_to_its_hourly_limit(self):
        for _ in range(3):
            self.assertEqual(self.post().status_code, 302)
        response = self.post()
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "Too many requests from this connection. Try again in an hour.", status_code=429)
        self.assertEqual(DemoRequest.objects.count(), 3)
        # Another address is not held by it.
        self.assertEqual(self.post(address="10.0.0.2").status_code, 302)

    def test_the_hour_runs_out(self):
        for _ in range(3):
            self.post()
        DemoRequest.objects.update(created_at=timezone.now() - timedelta(minutes=61))
        self.assertEqual(self.post().status_code, 302)

    def test_the_form_is_csrf_protected(self):
        client = self.client_class(enforce_csrf_checks=True)
        response = client.post("/", data=FORM, HTTP_HOST=SITE)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(DemoRequest.objects.count(), 0)


_CANDIDATE = re.compile(r"(\S+)\s+(\d+)w")


def largest(srcset):
    """The widest candidate in a srcset: what a phone at 2x asks for."""
    return max(_CANDIDATE.findall(srcset), key=lambda c: int(c[1]))[0]


def fetched_on_a_phone(page):
    """Every image URL a phone fetches, the deferred and lazy ones too.

    A `<picture>` with a phone `<source>` gives that source's widest file;
    any other image its own widest. The desk-only files are not counted,
    because a phone never asks for them."""
    urls = []
    for picture in re.findall(r"<picture>(.*?)</picture>", page, flags=re.S):
        phone = re.search(r'<source media="\(max-width[^"]*"[^>]*?(?:data-)?srcset="([^"]+)"', picture)
        if phone:
            urls.append(largest(phone.group(1)))
        else:
            img = re.search(r'(?:data-)?srcset="([^"]+)"', picture)
            urls.append(largest(img.group(1)))
    outside = re.sub(r"<picture>.*?</picture>", "", page, flags=re.S)
    for tag in re.findall(r"<img\b[^>]*>", outside):
        srcset = re.search(r'(?:data-)?srcset="([^"]+)"', tag)
        urls.append(largest(srcset.group(1)) if srcset else re.search(r'src="([^"]+)"', tag).group(1))
    return urls


class TheBudgetsTests(SiteSetUp):
    def setUp(self):
        self.page = self.get().content.decode()
        self.served = served_files()

    def assets(self):
        found = {self.served[url] for url in _ASSET.findall(self.page) if url in self.served}
        for path in list(found):
            if path.endswith(".css"):
                found.update(urls_in_css(path))
        return {a for a in found if not a.endswith(".webp")}

    def test_a_phone_fetches_under_400_kb_with_every_image(self):
        """Every image a phone asks for counted at 2x, the deferred slides and
        the lazy photos too, so the budget cannot lean on which of them a
        browser happens to fetch early. Uncompressed, so the bytes over the
        wire are fewer."""
        assets = self.assets()
        for expected in ("web/design.css", "website/website.css",
                         "web/fonts/hanken-grotesk-400.woff2", "web/fonts/hanken-grotesk-700.woff2"):
            self.assertIn(expected, assets)
        images = [self.served[url] for url in fetched_on_a_phone(self.page)]
        self.assertEqual(len(images), 7, images)
        weight = len(self.page.encode()) + sum((STATIC / a).stat().st_size for a in [*assets, *images])
        self.assertLess(weight, 400 * 1024, f"{weight} bytes: {sorted(assets)} {images}")

    def test_every_photo_is_under_60_kb(self):
        for photo in (STATIC / "website" / "photos").glob("*.webp"):
            with self.subTest(photo=photo.name):
                self.assertLess(photo.stat().st_size, 60 * 1000)

    def test_every_asset_is_from_this_host(self):
        for url in _ASSET.findall(self.page):
            with self.subTest(url=url):
                self.assertTrue(url.startswith(settings.STATIC_URL), url)
        for srcset in re.findall(r'srcset="([^"]+)"', self.page):
            for url, _ in _CANDIDATE.findall(srcset):
                self.assertTrue(url.startswith(settings.STATIC_URL), url)
        self.assertNotRegex(self.page, r'(src|href|srcset)="https?://')

    def test_images_are_webp_sized_described_and_only_the_hero_eager(self):
        top, below = self.page.split('<section class="proof"', 1)
        hero = re.findall(r"<img\b[^>]*>", top)
        rest = re.findall(r"<img\b[^>]*>", below)
        self.assertEqual(len(hero), 5, "the principal and the four screens")
        self.assertEqual(len(rest), 2, "the bursar and the teacher")
        for tag in hero + rest:
            with self.subTest(image=tag[:80]):
                self.assertRegex(tag, r'srcset="[^"]+\.webp \d+w')
                self.assertRegex(tag, r'width="\d+"')
                self.assertRegex(tag, r'height="\d+"')
                self.assertRegex(tag, r'alt="[^"]{12,}"')
        eager = [t for t in hero if " srcset=" in t]
        self.assertEqual(len(eager), 2, "the principal and the first screen load with the page")
        self.assertEqual(sum('fetchpriority="high"' in t for t in hero), 1)
        for tag in hero:
            if tag not in eager:
                self.assertIn("data-srcset=", tag, "screens 2 to 4 wait for the page to load")
        for tag in rest:
            self.assertIn('loading="lazy"', tag)

    def test_the_drawings_are_inline_and_small(self):
        drawings = re.findall(r"<svg\b.*?</svg>", self.page, flags=re.S)
        self.assertLess(sum(len(d.encode()) for d in drawings), 15 * 1024)
        network = re.search(r'<svg class="nodes".*?</svg>', self.page, flags=re.S).group(0)
        self.assertLess(len(network.encode()), 5 * 1024)
        self.assertIn('aria-hidden="true"', network)
        for drawing in drawings:
            self.assertNotRegex(drawing, r"<animate|#[0-9A-Fa-f]{3,6}\b(?!-)|rgb\(", drawing[:60])

    def test_there_is_one_script_inline_and_small(self):
        scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", self.page, flags=re.S)
        self.assertEqual(len(scripts), 1)
        attrs, code = scripts[0]
        self.assertEqual(attrs.strip(), 'type="module"')
        parts = [re.sub(r"/\*.*?\*/", "", part, flags=re.S).strip()
                 for part in re.split(r"(?=/\* The hero slider)|(?=/\* Figures)", code)]
        menu, slider, figures = parts
        self.assertLess(len(slider.encode()), 2 * 1024, "the slider")
        self.assertLess(len(figures.encode()), 1024, "the counting figures")
        self.assertIn("setTimeout(()=>{show(i+1);run()},5000)", slider)
        self.assertIn("prefers-reduced-motion: reduce", slider)
        self.assertIn("prefers-reduced-motion: reduce", figures)


CSS = Path(settings.BASE_DIR) / "static" / "website" / "website.css"
DESIGN = Path(settings.BASE_DIR) / "static" / "web" / "design.css"


def without_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def outside_media(css, query):
    """The stylesheet with every `@media` block matching `query` cut out."""
    out, i = [], 0
    for match in re.finditer(r"@media[^{]*" + re.escape(query) + r"[^{]*{", css):
        if match.start() < i:
            continue
        out.append(css[i:match.start()])
        depth, j = 1, match.end()
        while depth:
            depth += {"{": 1, "}": -1}.get(css[j], 0)
            j += 1
        i = j
    out.append(css[i:])
    return "".join(out)


class TheMotionRulesTests(TestCase):
    def test_nothing_moves_outside_no_preference(self):
        css = without_comments(CSS.read_text())
        still = re.sub(r"@keyframes[^{]*{(?:[^{}]*{[^{}]*})*[^{}]*}", "", outside_media(
            css, "prefers-reduced-motion: no-preference"))
        self.assertNotRegex(still, r"\b(animation|transition)[a-z-]*\s*:")
        # The control: the cut found the motion it was meant to cut.
        self.assertRegex(css, r"animation:")
        self.assertRegex(css, r"transition:")

    def test_the_crossfade_the_float_and_the_rise(self):
        css = without_comments(CSS.read_text())
        self.assertIn("transition: opacity 600ms ease", css)
        self.assertRegex(css, r"@keyframes float \{ 0%, 100% \{ translate: 0 0; \} 50% \{ translate: 0 -5px; \} \}")
        for seconds in re.findall(r"\.float-[a-f](?:, \.float-[a-f])* \{ animation-duration: ([\d.]+)s", css):
            self.assertTrue(4 <= float(seconds) <= 6, seconds)
        self.assertIn("animation-timeline: view()", css)
        self.assertIn("@supports (animation-timeline: view())", css)


def _hex(value):
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def _tokens():
    """design.css's colours and website.css's mixes of them, worked out."""
    css = without_comments(DESIGN.read_text()) + without_comments(CSS.read_text())
    roots = "".join(re.findall(r"(?<![\w-]):root \{([^}]*)\}", css))
    raw = dict(re.findall(r"--([a-z-]+):\s*([^;]+);", roots))
    resolved = {}

    def value(name):
        if name in resolved:
            return resolved[name]
        text = raw[name].strip()
        mix = re.fullmatch(r"color-mix\(in srgb, var\(--([a-z-]+)\) (\d+)%, var\(--([a-z-]+)\)\)", text)
        if mix:
            a, share, b = value(mix.group(1)), int(mix.group(2)) / 100, value(mix.group(3))
            resolved[name] = tuple(x * share + y * (1 - share) for x, y in zip(a, b))
        else:
            resolved[name] = _hex(text)
        return resolved[name]

    return value


def contrast(a, b):
    def lum(c):
        def ch(v):
            v /= 255
            return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
        return sum(w * ch(v) for w, v in zip((0.2126, 0.7152, 0.0722), c))
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class TheContrastTests(TestCase):
    """Worked out from the tokens, so a change of shade is checked where it is made."""

    def test_words_on_the_blues_are_4_5_to_1_or_better(self):
        token = _tokens()
        for text, ground in (("card", "brand"), ("on-brand", "brand"), ("on-brand", "brand-deep"),
                             ("card", "brand-deeper"), ("on-deep", "brand-deeper"),
                             ("on-deep-muted", "brand-deeper"), ("on-deep-legal", "brand-deeper"),
                             ("muted", "brand-wash"), ("text", "brand-wash"), ("brand", "card")):
            with self.subTest(text=text, ground=ground):
                self.assertGreaterEqual(contrast(token(text), token(ground)), 4.5)

    def test_white_icons_on_the_accent_tiles_are_4_5_to_1_or_better(self):
        token = _tokens()
        for tile in ("teal", "amber", "coral", "brand"):
            with self.subTest(tile=tile):
                self.assertGreaterEqual(contrast(token("card"), token(tile)), 4.5)
