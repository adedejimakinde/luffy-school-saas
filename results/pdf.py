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

## No authority question is asked here

Who may read a card belongs to the surface serving it. A worker rendering a
batch has no request to ask it of, and a renderer that pretended otherwise would
be answering with whatever the last caller left behind. `card_api` asks it for
the page; a future download route asks it for the file.
"""

from django.template.loader import render_to_string

from .card_api import card_columns, card_payload, card_rows


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
        {"card": payload, "columns": columns, "rows": card_rows(payload, columns)},
    )


__all__ = ["render", "html_for"]
