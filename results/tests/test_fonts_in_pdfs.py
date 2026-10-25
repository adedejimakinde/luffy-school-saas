"""The PDFs draw a Nigerian name in one typeface, not in whatever the printer's machine has.

A report card is set in the design's Hanken Grotesk, with Noto Sans behind it for
Hausa's hooked letters and DejaVu Sans last (`docs/design.md`, "Fonts"). Before
`scripts/fonts.py` recut the files, Hanken lacked ṣ, ₦ and the combining tone marks
as the stylesheet declared them, so DejaVu drew those letters inside the name: two
typefaces in one word on a card that goes home on paper.

What a PDF embeds is the evidence. WeasyPrint embeds each font a document used,
and only those, so a card whose names need DejaVu embeds DejaVu. These tests render
the card's own HTML (and each slip document's) and read the fonts out of the file:
the font programs are in object streams a regex cannot see, so the render asks
for an uncompressed copy of the same document.

The slips are set in DejaVu Sans alone (`checker_slips.html`, `exam_slips.html`): it
holds every letter below, so a name on a slip is one typeface by construction. They
are held to that here, so a font that lost a letter would show as a second font.
"""

import re
from types import SimpleNamespace

from django.test import SimpleTestCase

from academics.models import TermName
from accounts.models import User
from cbt import pdf as exam_pdf
from results import cards, pdf
from results.tests.test_card_api import ReportCardApiSetUp
from schools.models import School
from schools.tests.tenants import connected_to
from tests import glyphs

YORUBA_AND_IGBO = glyphs.NAMES[0]  # Ọláòlúwa Adéṣínà
HAUSA = glyphs.NAMES[3]  # Ɓatsari Ɗanjuma Ƙasim Ƴar’adua
SCHOOL = "Ṣadé Ẹ̀kọ́ Comprehensive College"


def fonts_in(document: bytes) -> set:
    """The base names of the fonts an uncompressed PDF embeds, without WeasyPrint's subset tag."""
    return {
        re.sub(rb"^[A-Z]{6}\+", b"", name).decode()
        for name in re.findall(rb"/BaseFont\s*/([^\s/\]>]+)", document)
    }


def uncompressed(html: str) -> bytes:
    from weasyprint import HTML

    return HTML(string=html).write_pdf(uncompressed_pdf=True)


class TheReportCardsFontsTests(ReportCardApiSetUp):
    def setUp(self):
        super().setUp()
        User.objects.filter(pk=self.ada.user_id).update(full_name=YORUBA_AND_IGBO)
        User.objects.filter(pk=self.bola.user_id).update(full_name=HAUSA)
        School.objects.filter(pk=self.stmarys.pk).update(name=SCHOOL)
        self.stmarys.refresh_from_db()
        self.release()

    def html_for(self, student):
        with connected_to(self.stmarys):
            card = cards.card_for(student, self.term_of(self.stmarys, TermName.FIRST.value))
            return pdf.html_for(card)

    def test_a_yoruba_and_igbo_name_is_drawn_by_hanken_alone(self):
        html = self.html_for(self.ada)
        self.assertIn(YORUBA_AND_IGBO.replace("’", "&#x27;"), html.replace("’", "&#x27;"))
        fonts = fonts_in(uncompressed(html))
        self.assertIn("Hanken-Grotesk", fonts)
        self.assertEqual(fonts - {"Hanken-Grotesk", "Hanken-Grotesk-Bold"}, set(), "a second typeface in the name")

    def test_the_schools_own_name_with_its_tone_marks_too(self):
        self.assertIn("Ṣadé Ẹ̀kọ́", self.html_for(self.ada))
        self.assertNotIn("DejaVu-Sans", fonts_in(uncompressed(self.html_for(self.ada))))

    def test_a_hausa_name_adds_noto_for_its_hooks_and_never_dejavu(self):
        fonts = fonts_in(uncompressed(self.html_for(self.bola)))
        self.assertIn("Hanken-Grotesk", fonts)
        self.assertTrue([f for f in fonts if f.startswith("Noto-Sans")], fonts)  # the name is bold on the card
        self.assertEqual({f for f in fonts if f.startswith("DejaVu")}, set())
        self.assertEqual(fonts - {"Hanken-Grotesk", "Hanken-Grotesk-Bold", "Noto-Sans", "Noto-Sans-Bold"}, set())

    def test_the_control_without_the_noto_face_the_hooks_fall_to_dejavu(self):
        """What the check sees when the fallback is missing: it is not blind to a second font."""
        html = self.html_for(self.bola)
        noto = re.compile(r'\s*@font-face\s*{\s*font-family: "Noto Sans";.*?}', re.S)
        self.assertEqual(len(noto.findall(html)), 2)
        without = noto.sub("", html)
        self.assertTrue([f for f in fonts_in(uncompressed(without)) if f.startswith("DejaVu-Sans")])


class BothReportCardLayoutsLoadTheSameFacesTests(SimpleTestCase):
    """The Ogun State sheet is a second template (`report_card_ogun.html`): the same stack, not its own."""

    def test_each_template_loads_hanken_and_noto_at_both_weights_and_stacks_them_before_dejavu(self):
        from django.template import engines

        for name in ("report_card.html", "report_card_ogun.html"):
            source = engines["django"].engine.get_template(f"results/{name}").source
            with self.subTest(template=name):
                for family, file in (("Hanken Grotesk", "hanken-grotesk"), ("Noto Sans", "noto-sans-hausa")):
                    for weight in (400, 700):
                        self.assertRegex(
                            source,
                            rf'font-family: "{family}";\s*font-weight: {weight};\s*src: url\("{{{{ fonts }}}}/{file}-{weight}\.woff2"\)',
                        )
                stacks = re.findall(r'font:[^;]*"Hanken Grotesk"[^;]*;', source)
                self.assertTrue(stacks)
                for stack in stacks:
                    self.assertIn('"Hanken Grotesk", "Noto Sans", "DejaVu Sans", sans-serif', stack)


class TheSlipsAreOneTypefaceTests(SimpleTestCase):
    def slip(self, name):
        return SimpleNamespace(
            student_name=name,
            class_group_name="JSS 1A",
            term_label="First term",
            session="2026/2027",
            admission_number="STM/001",
            printed_pin="123456789012",
            printed_code="",
            pin="12345678",
        )

    def slips(self, *names):
        return SimpleNamespace(
            school_name=SCHOOL,
            class_group_name="JSS 1A",
            term_label="First term",
            session="2026/2027",
            slips=[self.slip(name) for name in names],
            without_a_number=[],
        )

    def test_the_result_checker_slips_with_every_name_are_dejavu_alone(self):
        fonts = fonts_in(uncompressed(pdf.slips_html(self.slips(*glyphs.NAMES), "st-marys.classnode.co/check/")))
        self.assertEqual({f for f in fonts if not f.startswith("DejaVu-Sans")}, set(), fonts)
        self.assertTrue(fonts)

    def test_the_exam_slips_with_every_name_are_dejavu_alone(self):
        fonts = fonts_in(uncompressed(exam_pdf.slips_html(self.slips(*glyphs.NAMES), "st-marys.classnode.co/sit/")))
        self.assertEqual({f for f in fonts if not f.startswith("DejaVu-Sans")}, set(), fonts)
        self.assertTrue(fonts)

    def test_dejavu_holds_every_letter_a_slip_could_print(self):
        """The reason the slips need no web font: the system face has all of them, at both weights."""
        from fontTools.ttLib import TTFont

        for path in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"):
            for directory in ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu"):
                try:
                    cmap = TTFont(f"{directory}/{path}").getBestCmap()
                    break
                except OSError:
                    continue
            else:
                self.skipTest("DejaVu is not at a path this test knows; the PDF tests above are the check")
            with self.subTest(font=path):
                self.assertEqual([c for c in glyphs.CHARACTERS if ord(c) not in cmap], [])
