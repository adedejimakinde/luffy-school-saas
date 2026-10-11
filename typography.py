"""Text that has to stay on one line: class and level names.

"JSS 1C" split across two lines reads as a level called "JSS" and a class
called "1C". So wherever a class or level name is printed, the spaces inside it
become non-breaking spaces (U+00A0). The browser still wraps the sentence
around it; it just never wraps *inside* the name.

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


def keep_together(text) -> str:
    """`text` with every class or level name held on one line."""
    if not text:
        return text
    return _LEVEL.sub(lambda m: re.sub(r"\s+", NBSP, m.group(0)), str(text))


register = template.Library()


@register.filter(is_safe=True)
def nobreak(value):
    """`keep_together()` for a template. Safe in, safe out: a space is not markup."""
    return keep_together(value)


__all__ = ["NBSP", "keep_together", "nobreak", "register"]
