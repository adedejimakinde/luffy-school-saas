"""`typography.keep_together()`: what stays on one line (`docs/phone-width-sweep.md`).

`static/web/html.js`'s `keepTogether()` is the same rule for a page module, and
`tests/js/` holds it there.
"""

from django.test import SimpleTestCase

from typography import NBSP, keep_together


def held(text):
    return text.replace(" ", NBSP)


class KeepTogetherTests(SimpleTestCase):
    def test_a_class_name_is_held(self):
        self.assertEqual(keep_together("JSS 1A and SS 2B"), f"{held('JSS 1A')} and {held('SS 2B')}")

    def test_a_date_is_held_with_its_short_weekday_and_its_year(self):
        self.assertEqual(keep_together("Opens Fri 20 Nov"), f"Opens {held('Fri 20 Nov')}")
        self.assertEqual(keep_together("27 Nov 2026, 14:05"), f"{held('27 Nov 2026')}, 14:05")
        self.assertEqual(keep_together("Last updated 9 November 2026"), f"Last updated {held('9 November 2026')}")
        self.assertEqual(keep_together("since November 2026"), f"since {held('November 2026')}")

    def test_a_whole_weekday_may_end_the_line_before_its_date(self):
        """"Monday 14 December 2026" is wider than a 320px phone's line at 130% text."""
        self.assertEqual(keep_together("Monday 14 December 2026"), f"Monday {held('14 December 2026')}")

    def test_a_pin_and_a_time_with_its_am_or_pm_are_held(self):
        self.assertEqual(keep_together("PIN 0105 7149"), f"PIN {held('0105 7149')}")
        self.assertEqual(keep_together("27 Nov 2026, 7:33 p.m."), f"{held('27 Nov 2026')}, {held('7:33 p.m.')}")

    def test_words_that_only_look_like_a_date_are_left_free(self):
        for text in ("10 Marks", "3 Mayors", "1 of 10", "Section 2 of 4"):
            with self.subTest(text=text):
                self.assertEqual(keep_together(text), text)

    def test_nothing_in_nothing_out(self):
        self.assertEqual(keep_together(""), "")
        self.assertIsNone(keep_together(None))
