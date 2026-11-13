"""ID cards as paper: CR80 cards, ten to an A4 sheet, with cut marks. `docs/id-cards.md`.

A card is a credit card, 85.6 x 54 mm. Two columns of five fill 171.2 x 270 mm
of an A4 sheet and leave 19.4 mm at the sides and 13.5 mm top and bottom, which
is where the cut marks go. The cards touch, so one cut along a mark parts two
of them, and nothing a card prints sits nearer than 3 mm to its edge, so a cut
a millimetre out costs nothing but the thin colour rule.

Each sheet of fronts is followed by the sheet of backs for the same ten
children. The backs' columns are mirrored, so that printed double-sided and
flipped on the long edge (what every office printer's "two-sided" means) a
child's back lands behind their front.

The geometry is written once, below, in millimetres, and the template is handed
finished numbers: it does no arithmetic of its own.
"""

from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string

CARD_W = 85.6
CARD_H = 54.0
COLUMNS = 2
ROWS = 5
PER_SHEET = COLUMNS * ROWS
PAGE_W = 210.0
PAGE_H = 297.0

GRID_W = CARD_W * COLUMNS
GRID_H = CARD_H * ROWS
LEFT = (PAGE_W - GRID_W) / 2
TOP = (PAGE_H - GRID_H) / 2

#: Cut marks: a hairline, 4 mm long, starting 1.5 mm clear of the card area so
#: that the mark never prints on a card.
MARK_LEN = 4.0
MARK_GAP = 1.5
MARK_WEIGHT = 0.12

#: The design's own Hanken Grotesk, loaded by path as the report card does.
FONTS = Path(settings.BASE_DIR) / "static" / "web" / "fonts"


def _mm(value: float) -> str:
    """A length in millimetres as CSS: a fixed decimal point whatever the locale."""
    return f"{value:.2f}mm"


def cell_positions():
    """`[(row, column, left, top)]` for the ten places on a sheet, in reading order."""
    return [
        (row, column, LEFT + column * CARD_W, TOP + row * CARD_H)
        for row in range(ROWS)
        for column in range(COLUMNS)
    ]


def cut_marks():
    """Every cut mark as `(left, top, width, height)` in mm: ticks past each line's two ends."""
    marks = []
    for column in range(COLUMNS + 1):
        x = LEFT + column * CARD_W - MARK_WEIGHT / 2
        marks.append((x, TOP - MARK_GAP - MARK_LEN, MARK_WEIGHT, MARK_LEN))
        marks.append((x, TOP + GRID_H + MARK_GAP, MARK_WEIGHT, MARK_LEN))
    for row in range(ROWS + 1):
        y = TOP + row * CARD_H - MARK_WEIGHT / 2
        marks.append((LEFT - MARK_GAP - MARK_LEN, y, MARK_LEN, MARK_WEIGHT))
        marks.append((LEFT + GRID_W + MARK_GAP, y, MARK_LEN, MARK_WEIGHT))
    return marks


def _style(left, top, width=None, height=None) -> str:
    parts = [f"left:{_mm(left)}", f"top:{_mm(top)}"]
    if width is not None:
        parts += [f"width:{_mm(width)}", f"height:{_mm(height)}"]
    return ";".join(parts)


def sheets_for(faces, *, first_sheet: int, total_sheets: int):
    """The pages for one run of up to ten children: their fronts, then their backs.

    Returns `[{"side", "caption", "cells", "marks"}]`. A cell is the card's
    position (`style`) and the child's `face`; on the backs' page the columns
    are swapped, which is the whole of duplex alignment.
    """
    if len(faces) > PER_SHEET:
        raise ValueError(f"A sheet holds {PER_SHEET} cards, not {len(faces)}.")
    places = cell_positions()
    marks = [{"style": _style(*m)} for m in cut_marks()]
    pages = []
    for side in ("front", "back"):
        cells = []
        for index, face in enumerate(faces):
            row, column, _, _ = places[index]
            shown = column if side == "front" else COLUMNS - 1 - column
            cells.append(
                {
                    "face": face,
                    "style": _style(LEFT + shown * CARD_W, TOP + row * CARD_H, CARD_W, CARD_H),
                }
            )
        pages.append(
            {
                "side": side,
                "caption": f"Sheet {first_sheet} of {total_sheets}, "
                + ("fronts" if side == "front" else "backs: print double-sided, flip on the long edge"),
                "cells": cells,
                "marks": marks,
            }
        )
    return pages


def html_for(school, class_name: str, faces, *, first_sheet: int = 1, total_sheets: int = 1) -> str:
    """The HTML for one run of up to ten children, before WeasyPrint sees it.

    Split from `write_pdf()` so a test can read what a card says as text, and
    what it must not say, without parsing a PDF.
    """
    return render_to_string(
        "idcards/sheet.html",
        {
            "school": school,
            "class_name": class_name,
            "pages": sheets_for(faces, first_sheet=first_sheet, total_sheets=total_sheets),
            "fonts": FONTS.as_uri(),
            "card_w": _mm(CARD_W),
            "card_h": _mm(CARD_H),
            "page_h": _mm(PAGE_H - 0.2),
            "caption_style": _style(LEFT, 4.2, GRID_W, 4.0),
        },
    )


def write_pdf(html: str, path: Path) -> None:
    """Render `html` to `path`. Imported lazily, as `results.pdf` does, so a
    machine without Pango can still import this module and start a worker."""
    from weasyprint import HTML

    HTML(string=html).write_pdf(path)


__all__ = ["CARD_H", "CARD_W", "PER_SHEET", "cell_positions", "cut_marks", "html_for", "sheets_for", "write_pdf"]
