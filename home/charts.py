"""The dashboard's two drawings, as numbers a template can put into an SVG.

Drawn on the server and sent inside the page: no chart library, no script, and
nothing for a phone to compute. Each function takes plain numbers and returns
coordinates already rounded to a tenth of a pixel, so the markup stays short.

The template owns the `<svg>` and its classes; this module owns the geometry
and nothing else, so it can be tested without rendering anything.
"""

from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass(frozen=True)
class Spark:
    #: The line, as an SVG path.
    line: str
    #: The same line closed down to the baseline, for the light fill under it.
    area: str
    #: Where the last point sits, for the dot that marks "now".
    end_x: float
    end_y: float
    width: int
    height: int


def _r(value: float) -> float:
    return round(value, 1)


def sparkline(
    values: Sequence[int], slots: int, *, width: int = 280, height: int = 64, ceiling: Optional[int] = None
) -> Optional[Spark]:
    """A running total over `slots` steps, of which `values` are the ones so far.

    The x axis is the whole span (a term's weeks), not just the weeks that have
    happened, so a line that stops halfway across reads as "halfway through".
    `ceiling` is the top of the y axis (what was expected); without one the
    highest value is the top. A pad of 2px keeps the stroke inside the box.

    None when there is nothing to draw: no slots, or no values.
    """
    if slots < 1 or not values:
        return None
    pad = 2
    top = max(ceiling or 0, max(values), 1)
    step = (width - 2 * pad) / max(slots - 1, 1)

    def point(i, v):
        return _r(pad + i * step), _r(height - pad - (v / top) * (height - 2 * pad))

    points = [point(i, v) for i, v in enumerate(values[:slots])]
    line = "M" + " L".join(f"{x} {y}" for x, y in points)
    base = height - pad
    area = f"{line} L{points[-1][0]} {base} L{points[0][0]} {base} Z"
    return Spark(line, area, points[-1][0], points[-1][1], width, height)


@dataclass(frozen=True)
class Bar:
    label: str
    percent: Optional[int]
    is_today: bool
    #: Left edge, top edge and height inside the drawing, in pixels.
    x: float
    y: float
    h: float


def bars(days: Sequence[tuple], *, width: int = 280, height: int = 48, floor: int = 2, bar: int = 40) -> list:
    """One bar per (label, percent or None, is_today). None draws a stub.

    A day with no register is drawn as a 2px stub rather than a zero-height
    gap, so the week keeps its shape; its label still says which day it was.
    """
    out = []
    slot = width / max(len(days), 1)
    for i, (label, percent, is_today) in enumerate(days):
        h = floor if percent is None else max(floor, _r(height * percent / 100))
        out.append(Bar(label, percent, is_today, _r(i * slot + (slot - bar) / 2), _r(height - h), h))
    return out


__all__ = ["Bar", "Spark", "bars", "sparkline"]
