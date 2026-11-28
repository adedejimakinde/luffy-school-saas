"""Text that has to stay on one line: class and level names, dates and PINs.

"JSS 1C" split across two lines reads as a level called "JSS" and a class
called "1C"; "Fri 20" at the end of one line and "Nov" at the start of the
next is a date nobody reads at a glance, and an exam PIN copied as two halves
is a wrong PIN. So wherever one is printed, the spaces inside it become
non-breaking spaces (U+00A0). The browser still wraps the sentence around it;
it just never wraps *inside* the name, the date or the PIN.
(`docs/phone-width-sweep.md`; `static/web/html.js` has the same rule as
`keepTogether()` for a page module.)

`keep_together()` is the rule, for Python that builds a sentence; the
`nobreak` filter is the same rule for a template:

    {% load typography %}
    {{ item.title|nobreak }}

Project-level, beside `menu.py`, because every page that names a class needs
it and no one app owns that.
"""

import re

from django import template

NBSP = " "

#: A level and its number, with an arm after it if there is one: "JSS 1",
#: "SS 3", "JSS 1C", "JSS 1 C", "Primary 4", "Year 7B". The arm is one capital
#: letter, attached or after one space; a word after the number ("SS 2
#: Science") is left free to wrap.
_LEVEL = re.compile(
    r"\b(?:JSS|SSS|SS|JS|Primary|Pry|Basic|Year|Grade|Nursery|KG)\s+\d{1,2}(?:\s?[A-Z]\b)?"
)


_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?"
    r"|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\b"
)

#: A day and its month, with a short weekday before and the year after if they
#: are there: "Fri 20 Nov", "20 Nov 2026", "20 November 2026"; and a month and
#: its year, "November 2026". A whole weekday ("Monday") may end a line before
#: the date it names, which a narrow phone needs; a time after a comma stays free.
_DATE = re.compile(
    rf"\b(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+)?\d{{1,2}}\s+{_MONTH}(?:\s+\d{{4}})?\b"
    rf"|\b{_MONTH}\s+\d{{4}}\b"
)

#: A clock time with its "am" or "pm", and an exam PIN printed in two fours.
_TIME_AND_PIN = re.compile(r"\b\d{1,2}[:.]\d{2}\s+[ap]\.?m\b\.?|\b\d{4} \d{4}\b", re.I)


def _hold(match) -> str:
    return re.sub(r"\s+", NBSP, match.group(0))


def keep_together(text) -> str:
    """`text` with every class or level name, date, time and PIN held on one line."""
    if not text:
        return text
    text = _LEVEL.sub(_hold, str(text))
    text = _DATE.sub(_hold, text)
    return _TIME_AND_PIN.sub(_hold, text)


register = template.Library()


@register.filter(is_safe=True)
def nobreak(value):
    """`keep_together()` for a template. Safe in, safe out: a space is not markup."""
    return keep_together(value)


__all__ = ["NBSP", "keep_together", "nobreak", "register"]
