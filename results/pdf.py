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

## The columns are the union, not the first subject's

`AssessmentCellOut`s hang off each `SubjectLineOut`, and an assessment belongs to
a subject — so two subjects in one term need not have the same ones. A header
row taken from the first subject would label Mathematics' columns and then print
English's marks underneath them. `_columns()` takes the ordered union and
`_rows()` aligns every line against it, leaving a gap where a subject has no
such assessment.

The order is the frozen print order, which within a subject is **creation
order**: `cards._assessments_for()` orders by `(subject name, assessment id)`
and says in as many words that it is deliberately *not* alphabetical, because
`Assessment.Meta.ordering` ends in `name` and would print "Exam, First CA,
Second CA". It is still a guess — `Assessment` has no explicit print order,
which is **issue #42**, and this is the surface that makes it
must-fix-before-release: it is where the wrong order is visible to a parent.

*Across* subjects the header is first-seen order, so where two subjects disagree
about the order of names they share, the first subject read wins and the second
one's row is printed in the header's order rather than its own. One row of
columns cannot honour two orders at once; #42 is what settles it, by giving
every assessment a position that does not depend on which subject was read
first.

## A mark is printed with the total it is out of

`Assessment.max_score` is per `(term, subject, name)` — "a CA is commonly out of
20 or 30", as its own docstring says — so a bare "45" under a header reading
"Exam" does not tell a parent whether that was a good one. Columns are therefore
keyed on `(name, max_score)` rather than the name alone, and the header carries
the maximum. Keying on the name alone would put Mathematics' Exam out of 60 and
English's Exam out of 100 in one column headed "Exam", where 45 and 45 read as
equal performance and are not.

## No authority question is asked here

Who may read a card belongs to the surface serving it. A worker rendering a
batch has no request to ask it of, and a renderer that pretended otherwise would
be answering with whatever the last caller left behind. `card_api` asks it for
the page; a future download route asks it for the file.
"""

from django.template.loader import render_to_string

from .card_api import card_payload


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
    columns = _columns(payload)
    return render_to_string(
        "results/report_card.html",
        {"card": payload, "columns": columns, "rows": _rows(payload, columns)},
    )


def _columns(payload) -> list[dict]:
    """Every assessment on this card, once, in the order first seen.

    Keyed on `(name, max_score)` and **not on the name alone**. An assessment
    belongs to a subject — `uniq_assessment_term_subject_name` is per
    `(term, subject, name)` — so Mathematics' "Exam" and English's "Exam" are
    two different assessments and may be out of two different totals. One column
    headed "Exam" would print 45-out-of-60 and 45-out-of-100 as the same mark,
    on the document a parent is most likely to query with a teacher.

    `dict` rather than a `set`: the order is the frozen print order and a set
    would replace it with whatever the hash happened to be, which is the kind of
    ordering bug that agrees with itself until the day it does not.
    """
    seen = {}
    for line in payload.subjects:
        for cell in line.assessments:
            seen.setdefault((cell.assessment_name, cell.max_score), None)
    return [{"name": name, "max_score": max_score} for name, max_score in seen]


def _rows(payload, columns) -> list[dict]:
    """Each subject line with its cells aligned to `columns`; `None` for a gap.

    A `None` is a subject that had no such assessment at all, which prints as a
    gap and is a different thing from a cell whose `score` is null — that is an
    assessment this child was not marked in, and it prints as a dash. Two
    absences that mean different things must not look the same on a card
    somebody is going to ask a teacher about.
    """
    rows = []
    for line in payload.subjects:
        by_key = {
            (cell.assessment_name, cell.max_score): cell for cell in line.assessments
        }
        rows.append(
            {
                "line": line,
                "cells": [
                    by_key.get((column["name"], column["max_score"]))
                    for column in columns
                ],
            }
        )
    return rows


__all__ = ["render", "html_for"]
