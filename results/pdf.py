"""A released card as a PDF. Task 7.

The file a school prints and a family keeps. It is rendered from
`card_api.card_payload()` — the same object the page is served from — through a
Django template and WeasyPrint.

## Built from the family payload, not from the row

`ReleasedCard` carries `position`, `roster_size` and, on its subject lines,
`subject_position`; task 9 adds the term-absence reasons and the promotion
*suggestion*. Every one of those is staff-only and prints on no family's card.
They are kept off this page by **not being in the object the template can see**
— `ReportCardOut` has no slot for any of them — rather than by a template
remembering not to print them. A renderer handed the model row would have all of
them in scope and nothing but care between them and the paper, which is the
arrangement issue #21 exists to refuse.

That is also why `card_api.card_payload()` was extracted rather than copied: two
assemblies of "what a card says" is two places for a slot to appear, and they
would drift the first time one was edited.

## The grid comes from `card_api` as well, and for the same reason

`card_columns()` and `card_rows()` build the header row and the aligned subject
rows. They were `_columns()` and `_rows()` in this file, which is the same
mistake as a renderer assembling its own payload one level down: which papers
are columns, and in what order they print, is part of what a card *says*. They
now live beside `card_payload()`, which is where that is assembled once and
where the argument for their shape is written — the union rather than the first
subject's row, the `(name, max_score)` key, and the frozen print order that
closed issue #42.

## A mark is printed with the total it is out of

`Assessment.max_score` is per `(term, subject, name)` — "a CA is commonly out of
20 or 30", as its own docstring says — so a bare "45" under a header reading
"Exam" does not tell a parent whether that was a good one. The template prints
the maximum in every header cell and beside every subject total, which is the
page's half of the `(name, max_score)` keying `card_columns()` argues for.

## The school leads, and Classnode is a footnote

The header is the school's, on white: its crest (or its initials in a circle),
its name in its one colour (`results.look`), and a 3mm rule of that colour
under it. A solid band of colour was the first draft; schools print hundreds
of cards, and a band uses a lot of ink and streaks on a cheap printer. The
colour is on the name and the card's rules and nowhere else, so every other
word is dark ink. Classnode appears once, small, at the foot of each page.

## One thing the payload does not carry, read here

The admission number and the date the next term begins are on `ReportCardOut`
itself now (`card_payload()`), so the family's page and this file read one
number and one date rather than each computing its own — the PDF used to
recompute both here, and the family's page had neither. Only the grade key is
not on the payload: it is not a fact about one card, and none is a staff-only
figure this module has to keep off the page.

- **The admission number** is `Membership.reference`, which the card row does
  not freeze. The PDF is rendered when the card is released and stored
  (`ReleasedCardPdf`), so the number on it is the one on record at release.
- **"Next term begins"** is `Term.next_term_starts_on`, and the line is left
  out when the school has not set it. Parents look for it first.
- **The grade key** is this school's own scale (`grades.scale()`), one line,
  highest band first, so a parent can read a letter without asking.

The font is the design's own Hanken Grotesk, from the same self-hosted files
the pages serve, loaded by path. WeasyPrint subsets it, so a card is about the
size it was.

## No authority question is asked here

Who may read a card belongs to the surface serving it. A worker rendering a
batch has no request to ask it of, and a renderer that pretended otherwise would
be answering with whatever the last caller left behind. `card_api` asks it for
the page; a future download route asks it for the file.
"""

from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string

from . import grades, look
from .card_api import card_columns, card_payload, card_rows

#: The design's two weights, self-hosted beside `design.css`.
FONTS = Path(settings.BASE_DIR) / "static" / "web" / "fonts"


def render(card) -> bytes:
    """One released card as PDF bytes. Takes a `ReleasedCard`.

    Imported lazily inside the function: WeasyPrint pulls in Pango through
    `cffi` at import time and raises `OSError` on a machine without the system
    libraries, which would otherwise make this module unimportable — and this
    module is reachable from `results.tasks`, which Celery autodiscovers at
    worker start. A missing font package would stop the worker booting at all
    rather than failing the one job that needs it. See `docs/background.md`.
    """
    from weasyprint import HTML

    return HTML(string=html_for(card)).write_pdf()


def html_for(card) -> str:
    """The rendered HTML, before WeasyPrint sees it.

    Split from `render()` so that a test can assert what is and is not on the
    page without needing Pango installed, and so that the staff-only exclusions
    are checkable as text rather than by parsing a PDF.
    """
    payload = card_payload(card)
    columns = card_columns(payload)
    return render_to_string(
        "results/report_card.html",
        {
            "card": payload,
            "columns": columns,
            "rows": card_rows(payload, columns),
            # Read from this school's own schema, at render time. The PDF is
            # stored once made, so a card keeps the crest it was printed with.
            "look": look.for_card(payload.school_name),
            # Both read off `payload` rather than off `card` a second time —
            # `card_payload()` is the one place either is worked out now, so
            # the family's page and this file cannot print two different
            # admission numbers or two different resumption dates for the
            # same card.
            "admission_number": payload.admission_number,
            "next_term_begins": payload.next_term_begins,
            "grade_key": grade_key(grades.scale()),
            "fonts": FONTS.as_uri(),
        },
    )


def _number(value: Decimal) -> str:
    """75 for 75.00, 74.5 for 74.50: a mark as a person writes it."""
    text = f"{value:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def grade_key(bands) -> list[str]:
    """"A1 75 to 100", "B2 70 to 74", ...: each band's letter and range.

    Bands are stored as minimums, highest first (`GradeBand` says why), so a
    band runs from its own minimum to just under the one above it. "Just
    under" is a whole mark when every minimum is whole, and a hundredth when
    the school has used decimals, so the key never shows a range the scale
    does not have.
    """
    bands = list(bands)
    whole = all(b.minimum == b.minimum.to_integral_value() for b in bands)
    step = Decimal(1) if whole else Decimal("0.01")
    key, top = [], Decimal(100)
    for band in bands:
        key.append(f"{band.letter} {_number(band.minimum)} to {_number(top)}")
        top = band.minimum - step
    return key


def render_slips(slips, checker_address: str) -> bytes:
    """One class's result-checker slips as PDF bytes. `docs/messaging.md` D11.

    Rendered **in the request that mints the PINs**, unlike a card, because the
    raw PINs exist only here: a worker would need them on the broker, and a file
    stored for later would be the PINs at rest. A class is a page or eight of
    plain text, not a card each.
    """
    from weasyprint import HTML

    return HTML(string=slips_html(slips, checker_address)).write_pdf()


def slips_html(slips, checker_address: str) -> str:
    """The slips' HTML before WeasyPrint sees it, so a test can read it as text."""
    return render_to_string(
        "results/checker_slips.html",
        {
            "school_name": slips.school_name,
            "slips": slips.slips,
            "without_a_number": slips.without_a_number,
            "checker_address": checker_address,
        },
    )


__all__ = ["render", "html_for", "render_slips", "slips_html"]
