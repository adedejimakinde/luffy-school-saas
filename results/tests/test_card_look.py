"""The card's look: the school's crest and colour lead, Classnode is a footnote.

Three kinds of claim.

**What a school may set.** A crest is a PNG or a JPG of at most 1 MB, and it is
re-drawn rather than kept: what is stored is a fresh square PNG. A colour must
read on white, because the school's name is printed in it on white paper.

**Whose crest a card can print.** Two schools, one crest. The crest lives in
the school's own schema, and the other school's card, API and database row
never see it. A single-school test could not fail for the one mistake that
matters here, which is a crest stored or read somewhere shared.

**What the card says.** The header is the school's, its colour is on the band
and the rules, "classnode" is in the page footer, and no class position or
class average is anywhere on it.
"""

import io
import re
from datetime import timedelta

from django.db import connection
from django.test import SimpleTestCase
from django.utils.html import escape

from academics.models import TermName
from accounts.models import Membership
from gradebook.models import Subject
from results import cards, look, pdf
from results.models import ReportCardSettings
from results.tests.test_card_api import HOST, THEIR_HOST, ReportCardApiSetUp
from schools.tests.tenants import connected_to

COLOUR = "/api/academics/card/colour/"
CREST = "/api/academics/card/crest/"


def image(fmt="PNG", size=(300, 120), colour=(20, 61, 140), **save):
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, format=fmt, **save)
    return out.getvalue()


class TheColourTests(SimpleTestCase):
    def test_the_default_is_the_designs_blue(self):
        self.assertEqual(look.clean_colour(None), "#143D8C")
        self.assertEqual(look.clean_colour("  "), "#143D8C")

    def test_a_colour_is_written_one_way(self):
        self.assertEqual(look.clean_colour("7a1f2b"), "#7A1F2B")
        self.assertEqual(look.clean_colour("#0b5d3b"), "#0B5D3B")

    def test_a_colour_too_light_for_white_text_is_refused_with_a_reason(self):
        for light in ("#FFFF00", "#CCCCCC", "#FFFFFF", "#7FB3FF"):
            with self.subTest(colour=light):
                with self.assertRaisesRegex(look.LookRefused, "too light"):
                    look.clean_colour(light)

    def test_the_boundary_is_white_texts_four_and_a_half_to_one(self):
        self.assertGreaterEqual(look.contrast_with_white("#143D8C"), 4.5)
        # #767676 is the classic lightest grey that still passes on white.
        self.assertGreaterEqual(look.contrast_with_white("#767676"), 4.5)
        self.assertLess(look.contrast_with_white("#777777"), 4.5)

    def test_something_that_is_not_a_colour_is_refused(self):
        for bad in ("red", "#12345", "#1234567", "rgb(1,2,3)", "#GGGGGG"):
            with self.subTest(value=bad):
                with self.assertRaisesRegex(look.LookRefused, "six hex digits"):
                    look.clean_colour(bad)


class TheCrestTests(SimpleTestCase):
    def test_a_png_or_a_jpg_becomes_a_square_png(self):
        from PIL import Image

        for fmt in ("PNG", "JPEG"):
            with self.subTest(format=fmt):
                drawn = Image.open(io.BytesIO(look.redraw_crest(image(fmt))))
                self.assertEqual((drawn.format, drawn.size), ("PNG", (256, 256)))

    def test_what_is_stored_is_redrawn_and_carries_nothing_of_the_upload(self):
        from PIL import PngImagePlugin

        info = PngImagePlugin.PngInfo()
        info.add_text("Comment", "a secret the school did not mean to publish")
        sent = image("PNG", pnginfo=info) + b"trailing bytes after the image"

        drawn = look.redraw_crest(sent)

        self.assertNotIn(b"a secret", drawn)
        self.assertNotIn(b"trailing bytes", drawn)

    def test_over_a_megabyte_is_refused_before_it_is_opened(self):
        with self.assertRaisesRegex(look.LookRefused, "at most 1 MB"):
            look.redraw_crest(b"\x89PNG" + b"0" * (look.MAX_UPLOAD_BYTES + 1))

    def test_a_gif_or_a_file_that_is_not_an_image_is_refused(self):
        for raw in (image("GIF"), b"not an image at all", b"\x89PNG\r\n\x1a\nbroken"):
            with self.subTest(raw=raw[:12]):
                with self.assertRaisesRegex(look.LookRefused, "PNG or a JPG"):
                    look.redraw_crest(raw)

    def test_an_image_far_larger_than_a_crest_is_refused_before_it_is_decoded(self):
        with self.assertRaisesRegex(look.LookRefused, "far larger"):
            look.redraw_crest(image("PNG", size=(5000, 5000)))

    def test_initials_are_two_letters_at_most(self):
        for name, expected in (
            ("Sunrise Demo Academy", "SD"),
            ("St Mary's", "SM"),
            ("Grace", "G"),
            ("", ""),
        ):
            with self.subTest(name=name):
                self.assertEqual(look.initials(name), expected)


class LookSetUp(ReportCardApiSetUp):
    def setUp(self):
        super().setUp()
        self.release()
        self.release(self.grace)

    def tearDown(self):
        connection.set_schema_to_public()
        super().tearDown()

    def html(self, school=None, child=None):
        school = school or self.stmarys
        child = child or (self.ada if school == self.stmarys else self.ngozi)
        with connected_to(school):
            return pdf.html_for(cards.card_for(child, self.term_of(school, TermName.FIRST.value)))

    def as_user(self, user, host=HOST):
        self.client.force_login(user)
        return host


class TwoSchoolsOneCrestTests(LookSetUp):
    def test_the_control_st_marys_card_prints_its_crest(self):
        """Every exclusion below would pass against a crest nobody could set."""
        host = self.as_user(self.principal)
        response = self.client.post(CREST, {"crest": io.BytesIO(image())}, HTTP_HOST=host)

        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("data:image/png;base64,", self.html())

    def test_one_schools_crest_never_reaches_the_other(self):
        host = self.as_user(self.principal)
        self.client.post(CREST, {"crest": io.BytesIO(image())}, HTTP_HOST=host)

        # Grace's row, card, and API all know nothing of it.
        with connected_to(self.grace):
            self.assertFalse(ReportCardSettings.objects.filter(crest__isnull=False).exists())
        grace = self.html(self.grace)
        self.assertNotIn("data:image/png;base64,", grace)
        self.assertIn('class="initials">GA<', grace)

        self.client.force_login(self.their_principal)
        self.assertEqual(self.client.get(CREST, HTTP_HOST=THEIR_HOST).status_code, 404)
        self.assertEqual(self.client.get(CREST, HTTP_HOST=HOST).status_code, 403)

    def test_one_schools_colour_is_its_own(self):
        host = self.as_user(self.principal)
        self.client.put(COLOUR, {"colour": "#7A1F2B"}, content_type="application/json", HTTP_HOST=host)

        self.assertIn("#7A1F2B", self.html())
        self.assertNotIn("#7A1F2B", self.html(self.grace))
        self.assertIn("#143D8C", self.html(self.grace))


class TheDoorTests(LookSetUp):
    def test_the_principal_sets_both(self):
        host = self.as_user(self.principal)
        colour = self.client.put(COLOUR, {"colour": "0b5d3b"}, content_type="application/json", HTTP_HOST=host)
        crest = self.client.post(CREST, {"crest": io.BytesIO(image("JPEG"))}, HTTP_HOST=host)

        self.assertEqual(colour.json()["colour"], "#0B5D3B")
        self.assertTrue(crest.json()["has_crest"])
        served = self.client.get(CREST, HTTP_HOST=host)
        self.assertEqual((served.status_code, served["Content-Type"]), (200, "image/png"))
        self.assertEqual(served["X-Content-Type-Options"], "nosniff")

    def test_a_teacher_or_a_bursar_is_refused_before_anything_is_read(self):
        for user in (self.teacher, self.bursar):
            host = self.as_user(user)
            with self.subTest(user=user.username):
                self.assertEqual(
                    self.client.put(COLOUR, {"colour": "#0B5D3B"}, content_type="application/json", HTTP_HOST=host).status_code,
                    403,
                )
                # Refused before the missing file is noticed: authority first.
                self.assertEqual(self.client.post(CREST, {}, HTTP_HOST=host).status_code, 403)
                self.assertEqual(self.client.get(CREST, HTTP_HOST=host).status_code, 403)
                self.assertEqual(self.client.delete(CREST, HTTP_HOST=host).status_code, 403)

    def test_a_light_colour_comes_back_as_a_sentence(self):
        host = self.as_user(self.principal)
        response = self.client.put(COLOUR, {"colour": "#FFFF00"}, content_type="application/json", HTTP_HOST=host)

        self.assertEqual(response.status_code, 422)
        self.assertIn("too light", response.json()["detail"])

    def test_an_upload_over_a_megabyte_is_refused(self):
        host = self.as_user(self.principal)
        big = io.BytesIO(b"\x89PNG" + b"0" * (look.MAX_UPLOAD_BYTES + 1))
        big.name = "crest.png"

        response = self.client.post(CREST, {"crest": big}, HTTP_HOST=host)

        self.assertEqual(response.status_code, 422)
        self.assertIn("1 MB", response.json()["detail"])

    def test_no_file_is_a_sentence_not_an_error(self):
        host = self.as_user(self.principal)

        self.assertEqual(self.client.post(CREST, {}, HTTP_HOST=host).status_code, 422)

    def test_removing_the_crest_goes_back_to_the_initials(self):
        host = self.as_user(self.principal)
        self.client.post(CREST, {"crest": io.BytesIO(image())}, HTTP_HOST=host)

        answer = self.client.delete(CREST, HTTP_HOST=host).json()

        self.assertFalse(answer["has_crest"])
        self.assertIn('class="initials">SM<', self.html())

    def test_the_setup_page_is_told_the_look(self):
        host = self.as_user(self.principal)

        card = self.client.get("/api/academics/setup/", HTTP_HOST=host).json()["card"]

        self.assertEqual(
            card,
            {"colour": "#143D8C", "default_colour": "#143D8C", "has_crest": False,
             "crest_version": None, "initials": "SM", "template": "standard"},
        )


class WhatTheCardSaysTests(LookSetUp):
    def test_the_school_leads_on_white_in_its_own_colour(self):
        """The name in the school's colour, a 3mm rule of it, and no solid
        band: a band of colour uses a lot of ink and streaks on the cheap
        printer most cards come off."""
        html = self.html()

        self.assertIn('<div class="head">', html)
        self.assertIn('<div class="head-rule"></div>', html)
        self.assertIn(escape("St Mary's"), html)
        self.assertRegex(html, r"\.head h1 \{[^}]*color: #143D8C")
        self.assertRegex(html, r"\.head-rule \{[^}]*height: 3mm[^}]*background: #143D8C")
        self.assertIn('class="initials">SM<', html)
        self.assertNotIn('class="band"', html)

    def test_classnode_is_a_small_footer_and_nowhere_else(self):
        html = self.html()

        self.assertIn('content: "classnode"', html)
        self.assertEqual(html.lower().count("classnode"), 1)

    def test_no_class_position_or_class_average_is_on_the_card(self):
        """`docs/design.md`: the card shows the child's own average and nothing
        of the class's. Position has its own tests in `test_pdf`; this adds
        the class average, which is on the broadsheet and never on a card."""
        html = self.html()
        for absent in ("Class average", "class average", "Class Average", "Position", "position"):
            with self.subTest(absent=absent):
                self.assertNotIn(absent, html)
        # The child's own average is still there.
        self.assertIn(">Average<", html)

    def test_no_em_dash_in_the_cards_sentences(self):
        """Only the "nothing to show" placeholders, which are data."""
        html = self.html()
        title = re.search(r"<title>(.*?)</title>", html).group(1)

        self.assertNotIn("—", title)
        self.assertIn(":", title)

    def test_the_admission_number_sits_beside_the_name(self):
        Membership.objects.filter(pk=self.ada.pk).update(reference="STM/0042")

        html = self.html()

        self.assertRegex(html, r"<strong>Ada Obi</strong><span class=\"adm\">Adm\. no\. STM/0042</span>")

    def test_no_admission_number_prints_nothing_rather_than_a_label(self):
        self.assertNotIn("Adm. no.", self.html())

    def test_next_term_begins_when_the_school_has_set_it(self):
        with connected_to(self.stmarys):
            term = self.term_of(self.stmarys, TermName.FIRST.value)
            term.next_term_starts_on = term.ends_on + timedelta(days=24)
            term.save(update_fields=["next_term_starts_on"])
            expected = term.next_term_starts_on

        html = self.html()

        self.assertIn(
            f"<strong>Next term begins:</strong> {expected.strftime('%A')} {expected.day} "
            f"{expected.strftime('%B %Y')}",
            html,
        )

    def test_and_says_nothing_when_it_has_not(self):
        self.assertNotIn("Next term begins", self.html())

    def test_the_grade_key_is_the_schools_own_scale_on_one_line(self):
        """Migration 0015's WAEC scale, which the fixture's schools start from."""
        html = self.html()
        key = re.search(r'<p class="key"><strong>Grade key:</strong> (.*?)</p>', html).group(1)

        self.assertTrue(key.startswith("A1 75 to 100, B2 70 to 74, B3 65 to 69"), key)
        self.assertTrue(key.endswith("F9 0 to 39"), key)

    def test_a_papers_maximum_is_on_its_own_line_and_no_word_breaks(self):
        html = self.html()

        self.assertRegex(html, r'<th class="n"><span class="col">[^<]+</span><span class="max">/\d+</span></th>')
        self.assertIn("table.grid thead th { white-space: nowrap; }", html)

    def test_the_font_is_the_designs_own_loaded_from_its_files(self):
        html = self.html()

        for weight in ("400", "700"):
            with self.subTest(weight=weight):
                path = pdf.FONTS / f"hanken-grotesk-{weight}.woff2"
                self.assertTrue(path.exists())
                self.assertIn(f'url("{pdf.FONTS.as_uri()}/hanken-grotesk-{weight}.woff2")', html)
        self.assertIn('font: 9.5pt "Hanken Grotesk"', html)


class TheGradeKeyTests(SimpleTestCase):
    def band(self, letter, minimum):
        from decimal import Decimal

        from results.models import GradeBand

        return GradeBand(letter=letter, minimum=Decimal(minimum))

    def test_whole_minimums_give_whole_ranges(self):
        key = pdf.grade_key([self.band("A", "70"), self.band("C", "50"), self.band("F", "0")])

        self.assertEqual(key, ["A 70 to 100", "C 50 to 69", "F 0 to 49"])

    def test_a_decimal_minimum_gives_ranges_to_the_hundredth(self):
        key = pdf.grade_key([self.band("A", "80"), self.band("B", "49.5"), self.band("C", "0")])

        self.assertEqual(key, ["A 80 to 100", "B 49.5 to 79.99", "C 0 to 49.49"])


def _margin_text(page, keyword):
    """The text WeasyPrint laid out in one of a page's margin boxes."""
    for box in page._page_box.children:
        if getattr(box, "at_keyword", None) == keyword:
            return "".join(getattr(b, "text", "") for b in box.descendants())
    return ""


class ALongSubjectListTests(ReportCardApiSetUp):
    """A subject list too long for one A4 page.

    Thirty-odd subjects still fit on one, which is more than any Nigerian
    card carries. Sixty do not, and that is the case this pins: the list
    breaks onto a second page with nothing lost."""

    SUBJECTS = 60

    def tearDown(self):
        connection.set_schema_to_public()
        super().tearDown()

    def test_a_long_subject_list_breaks_across_a4_pages(self):
        """The table's header repeats on the next page (`display:
        table-header-group`) and every page carries the footer; what is
        asserted here is that the card becomes a real second page rather than
        a squashed or clipped first one."""
        with connected_to(self.stmarys):
            for n in range(self.SUBJECTS):
                subject = Subject.objects.create(name=f"Elective subject {n + 1}", code=f"E{n:02d}")
                self.subjects[f"e{n}"] = subject.pk
        for n in range(self.SUBJECTS):
            self._mark(self.stmarys, TermName.FIRST.value, self.ada, f"e{n}", "Exam", 40 + n)
        self.release()
        from weasyprint import HTML

        with connected_to(self.stmarys):
            card = cards.card_for(self.ada, self.term_of(self.stmarys, TermName.FIRST.value))
            html = pdf.html_for(card)
            content = pdf.render(card)

        # Laid out by WeasyPrint itself: the page objects in the file are in
        # compressed streams, so counting them from the bytes counts nothing.
        pages = HTML(string=html).render().pages
        self.assertGreaterEqual(len(pages), 2)

        # Page 2 onward carries whose card it is; page 1 has the full header.
        runner = "Ada Obi · JSS 1A · First term"
        self.assertEqual(_margin_text(pages[0], "@top-left"), "")
        for page in pages[1:]:
            self.assertIn(runner, _margin_text(page, "@top-left"))
        for n in (1, self.SUBJECTS // 2, self.SUBJECTS):
            self.assertIn(f"Elective subject {n}<", html)
        self.assertTrue(content.startswith(b"%PDF-"))
