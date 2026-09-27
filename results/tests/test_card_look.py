"""The card's look: the school's crest and colour lead, Classnode is a footnote.

Three kinds of claim.

**What a school may set.** A crest is a PNG or a JPG of at most 1 MB, and it is
re-drawn rather than kept: what is stored is a fresh square PNG. A colour must
carry white text, because the school's name is printed in white on it.

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

from django.db import connection
from django.test import SimpleTestCase
from django.utils.html import escape

from academics.models import TermName
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
             "crest_version": None, "initials": "SM"},
        )


class WhatTheCardSaysTests(LookSetUp):
    def test_the_school_leads_in_its_own_colour(self):
        html = self.html()

        self.assertIn('<div class="band">', html)
        self.assertIn(escape("St Mary's"), html)
        self.assertIn("background: #143D8C", html)
        self.assertIn('class="initials">SM<', html)

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
        for n in (1, self.SUBJECTS // 2, self.SUBJECTS):
            self.assertIn(f"Elective subject {n}<", html)
        self.assertTrue(content.startswith(b"%PDF-"))
