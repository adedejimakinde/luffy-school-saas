"""Classnode's homepage, on the public site host and nowhere else.

What a browser has to be asked (the slides moving, pausing and holding still
under reduced motion, every width) is `tests/ui/screens.test.js`'s. This is
what the server and the files can answer for: which host serves the page and
what it refuses there, that the words are the words given and keep the writing
rules, that a demo request is saved, sent to platform staff, and refused to a
honeypot or a flood, and that the page stays inside its budgets.
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
    "Features", "Pricing", "Staff sign in", "Parent sign in", "Book a demo",
    "Results out the same week exams end.",
    "Teachers enter marks on their phones. The principal checks them and releases. "
    "Parents see the report card that evening.",
    "Every child gets their own account number for fees.",
    "Parents pay by transfer, the way they already do. The money goes straight to the "
    "school's bank and onto the right child's record, and the receipt goes out the same minute.",
    "Know who came to school today.",
    "Class teachers take the register in under a minute. When a child is absent, the "
    "parent gets an email.",
    "See what it does",
    "Made for Nigerian secondary schools. Works on the phones your teachers already carry.",
    "What changes in your school",
    "Results",
    "No more typing broadsheets late at night.",
    "Marks go in once. Totals, grades and the broadsheet add up by themselves, and every "
    "report card carries your crest and your colours.",
    "Fees",
    "Stop matching bank alerts to names.",
    "Each child has a bank account number. Whatever a parent pays shows on that child's "
    "record without anyone typing it in.",
    "A payment can't be edited or deleted. If a mistake is made, it is reversed with a "
    "reason, and the reversal stays on record.",
    "Parents",
    "No scratch cards.",
    "Parents sign in with a code sent to their phone. Families without a smartphone can "
    "check a result with the PIN slip you print for them.",
    "Register",
    "Mark the class in one tap per child.",
    "Absences that keep repeating are flagged for you before they become a problem.",
    "For the proprietor",
    "A short summary in your inbox every day: what came in, and what is still owed.",
    "Bad network",
    "Teachers can keep entering marks when the network drops.",
    "Nothing is lost, and it sends when the connection comes back.",
    "Priced per student, per term.",
    "₦2,500 per student, per term. No setup fee.",
    "See it with your own classes.",
    "Leave your details and we will call you within one working day.",
    "Your name", "School name", "Phone number", "Email (optional)", "Number of students",
    "Request a call",
    "Classnode. Nigeria.", "Privacy", "Terms", "hello@classnode.co", "© 2026 Classnode",
]

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


def visible_text(page):
    """What a reader is shown or read: the body's text and its labels."""
    body = page.split("<body", 1)[1]
    body = re.sub(r"<(script|style)\b.*?</\1>", " ", body, flags=re.S)
    body = re.sub(r"<!--.*?-->", " ", body, flags=re.S)
    labels = " ".join(re.findall(r'aria-label="([^"]*)"', body))
    text = re.sub(r"</?(?:span|a|strong|b|em)\b[^>]*>", "", body)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(f"{text} {labels}")).strip()


@override_settings(
    SITE_HOST=SITE,
    ALLOWED_HOSTS=[".classnode.testserver", "testserver"],
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEMO_REQUESTS_PER_HOUR=3,
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
        self.assertContains(response, "Results out the same week exams end.")

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
        for path in ("/", "/?sent=1"):
            text = visible_text(self.get(path).content.decode())
            with self.subTest(path=path):
                self.assertNotRegex(text, "[–—]", "an en or em dash")
                self.assertNotIn("!", text)
                self.assertNotIn("?", text)
                self.assertNotRegex(text, r"(^|[.:] )Imagine\b")
                for word in BANNED:
                    self.assertNotRegex(text.lower(), rf"(?<![a-z]){re.escape(word)}(?![a-z])", word)

    def test_the_writing_rules_find_what_they_look_for(self):
        """The control: a page breaking each rule is caught by the same checks."""
        broken = visible_text("<body><p>A seamless journey — imagine it! Why?</p>")
        self.assertRegex(broken, "[–—]")
        self.assertIn("!", broken)
        self.assertRegex(broken.lower(), r"(?<![a-z])journey(?![a-z])")


class TheDemoRequestTests(SiteSetUp):
    def test_a_request_is_saved_and_sent_to_platform_staff(self):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post()
        self.assertRedirects(response, "/?sent=1#demo", fetch_redirect_response=False)
        demo = DemoRequest.objects.get()
        self.assertEqual((demo.school, demo.students, demo.address), ("Grace Heights College", 640, "10.0.0.1"))
        (message,) = mail.outbox
        self.assertEqual(sorted(message.to), ["ops@classnode.example", "sales@classnode.example"])
        self.assertEqual(message.reply_to, ["proprietor@grace.example"])
        self.assertIn("Grace Heights College", message.subject)
        for line in ("Mrs Adaeze Obi", "0803 555 0100", "Students: 640"):
            self.assertIn(line, message.body)

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

    def test_a_missing_or_wrong_field_is_refused_with_its_todo(self):
        for field, value in (("name", ""), ("school", ""), ("phone", "call me"),
                             ("students", "0"), ("students", "lots"), ("email", "not-an-email")):
            with self.subTest(field=field, value=value):
                response = self.post({**FORM, field: value})
                self.assertEqual(response.status_code, 400)
                page = response.content.decode()
                self.assertIn("TODO: message when a field is missing or not right.", page)
                self.assertRegex(page, rf'name="{field}"[^>]*aria-invalid="true"')
        self.assertEqual(DemoRequest.objects.count(), 0)

    def test_one_address_is_held_to_its_hourly_limit(self):
        for _ in range(3):
            self.assertEqual(self.post().status_code, 302)
        response = self.post()
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "TODO: message when one address has sent too many", status_code=429)
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


class TheBudgetsTests(SiteSetUp):
    def setUp(self):
        self.page = self.get().content.decode()
        self.served = served_files()

    def assets(self):
        found = {self.served[url] for url in _ASSET.findall(self.page) if url in self.served}
        for path in list(found):
            if path.endswith(".css"):
                found.update(urls_in_css(path))
        return found

    def test_the_whole_page_is_under_400_kb_with_every_image(self):
        """Every image counted, the lazy ones too, so "first load" cannot lean
        on which of them a browser happens to fetch early."""
        assets = self.assets()
        for expected in ("web/design.css", "website/website.css", "website/site.js",
                         "web/fonts/hanken-grotesk-400.woff2", "website/shots/marks.webp",
                         "website/shots/home.webp"):
            self.assertIn(expected, assets)
        weight = len(self.page.encode()) + sum((STATIC / a).stat().st_size for a in assets)
        self.assertLess(weight, 400 * 1024, f"{weight} bytes: {sorted(assets)}")

    def test_every_asset_is_from_this_host(self):
        for url in _ASSET.findall(self.page):
            with self.subTest(url=url):
                self.assertTrue(url.startswith(settings.STATIC_URL), url)
        self.assertNotRegex(self.page, r'(src|href)="https?://')

    def test_images_are_webp_sized_and_lazy_below_the_first(self):
        images = re.findall(r"<img\b[^>]*>", self.page)
        self.assertGreaterEqual(len(images), 6)
        for n, tag in enumerate(images):
            with self.subTest(image=tag[:80]):
                self.assertRegex(tag, r'src="[^"]+\.webp"')
                self.assertRegex(tag, r'width="\d+"')
                self.assertRegex(tag, r'height="\d+"')
                if n == 0:
                    self.assertNotIn('loading="lazy"', tag)
                else:
                    self.assertIn('loading="lazy"', tag)

    def test_the_drawings_are_inline_and_under_15_kb(self):
        drawings = re.findall(r"<svg\b.*?</svg>", self.page, flags=re.S)
        # The logo, the pattern, three results tiles, four fees tiles and two
        # bad-network tiles, plus
        # the menu button's three lines.
        self.assertEqual(len(drawings), 12)
        self.assertLess(sum(len(d.encode()) for d in drawings), 15 * 1024)
        for drawing in drawings:
            self.assertNotRegex(drawing, r"<animate|#[0-9A-Fa-f]{3,6}\b(?!-)|rgb\(", drawing[:60])

    def test_there_is_one_module_and_no_other_script(self):
        scripts = re.findall(r"<script\b[^>]*>", self.page)
        self.assertEqual(len(scripts), 1)
        self.assertIn('type="module"', scripts[0])


CSS = Path(settings.BASE_DIR) / "static" / "website" / "website.css"


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

    def test_nothing_loops_and_the_crossfade_is_400ms(self):
        css = without_comments(CSS.read_text())
        self.assertNotIn("infinite", css)
        self.assertNotIn("iteration-count", css)
        self.assertRegex(css, r"\.motion \.slide \{ transition: opacity 0\.4s")
        js = (STATIC / "website" / "site.js").read_text()
        self.assertIn("const ADVANCE_MS = 6000;", js)

    def test_the_hero_pattern_is_under_6_percent_contrast(self):
        """The pattern is the brand blue at the drawing's opacity, on white."""
        css = without_comments(CSS.read_text())
        opacity = float(re.search(r"\.hero-pattern \{[^}]*opacity:\s*([\d.]+)", css).group(1))

        def linear(c):
            c /= 255
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

        brand = (0x14, 0x3D, 0x8C)
        mixed = [255 - opacity * (255 - c) for c in brand]
        lum = sum(w * linear(c) for w, c in zip((0.2126, 0.7152, 0.0722), mixed))
        ratio = 1.05 / (lum + 0.05)
        self.assertLess(ratio, 1.06)
        self.assertGreater(ratio, 1.0, "the pattern is drawn at all")
