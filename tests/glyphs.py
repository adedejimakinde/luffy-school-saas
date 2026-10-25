"""The letters, names and amounts the design's fonts must draw, and how to ask whether they do.

A Nigerian school's pages carry Yoruba's ẹ ọ ṣ, Igbo's ị ụ ṅ, Hausa's ɓ ɗ ƙ ƴ, the
tone marks written over and under them, and the naira sign. A font that lacks one
does not fail: the browser draws that letter in whatever the phone has, so a
child's name comes out in two typefaces. That is the failure these tests are
for, and it does not show as an error anywhere.

`covering()` is the one question: which of the design's faces (`static/web/
design.css`) would draw this character: **a face whose `unicode-range` includes
it and whose file has a glyph for it**. Both halves matter. A letter in the file
but outside the range is never asked of that file, and a range that names a
letter the file lacks asks and gets nothing. `tests/test_design.py` holds the
design to the first question; the theme contract and the PDFs to the second.
"""

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from django.conf import settings

STATIC = Path(settings.BASE_DIR) / "static"
DESIGN = STATIC / "web" / "design.css"
FONTS = STATIC / "web" / "fonts"

#: Yoruba, Igbo and Hausa letters, the apostrophe Hausa writes, and the naira sign.
LETTERS = "ẹọṣẸỌṢịụṅỊỤṄɓɗƙƴƁƊƘƳʼ₦ǹǸ"

#: The marks written over and under a letter: grave, acute, dot below, dot above, macron.
MARKS = "̣̀́̇̄"

#: Names as a school writes them, with tones and underdots, as typed (NFC).
NAMES = tuple(
    unicodedata.normalize("NFC", name)
    for name in (
        "Ọláòlúwa Adéṣínà",
        "Ìfẹ́olúwa Ọ̀ṣọ́",
        "Ṣadé Ẹ̀kọ́",
        "Ɓatsari Ɗanjuma Ƙasim Ƴar’adua",
        "Ịfeanyị Ụgọchukwụ Ṅwa",
    )
)

AMOUNTS = ("₦125,000", "₦48,620,500")

#: Every character the names and amounts use, and the letters above.
CHARACTERS = sorted(set(LETTERS + MARKS + "".join(NAMES) + "".join(AMOUNTS)) - {" ", ","})


def _intervals(text):
    """`U+0020-007E, U+00A0` as [(0x20, 0x7E), (0xA0, 0xA0)]."""
    out = []
    for token in re.findall(r"U\+([0-9A-Fa-f]+)(?:-([0-9A-Fa-f]+))?", text):
        low = int(token[0], 16)
        out.append((low, int(token[1], 16) if token[1] else low))
    return out


@lru_cache(maxsize=None)
def faces():
    """The design's `@font-face` rules: family, weight, file, the ranges it asks for, the rest as written."""
    found = []
    for body in re.findall(r"@font-face\s*{(.*?)}", DESIGN.read_text(), re.S):
        found.append(
            {
                "family": re.search(r'font-family:\s*"([^"]+)"', body).group(1),
                "weight": int(re.search(r"font-weight:\s*(\d+)", body).group(1)),
                "file": re.search(r'url\("fonts/([^"]+)"\)', body).group(1),
                "ranges": _intervals(re.search(r"unicode-range:\s*([^;]+);", body).group(1)),
                "body": body,
            }
        )
    return tuple(found)


def in_range(face, character):
    return any(low <= ord(character) <= high for low, high in face["ranges"])


@lru_cache(maxsize=None)
def cmap_of(file):
    from fontTools.ttLib import TTFont

    return frozenset(TTFont(FONTS / file).getBestCmap())


def covering(character, weight=400):
    """The design's faces at `weight` that would draw `character`, in the order the stylesheet asks."""
    return [
        face["family"]
        for face in faces()
        if face["weight"] == weight and in_range(face, character) and ord(character) in cmap_of(face["file"])
    ]


__all__ = ["AMOUNTS", "CHARACTERS", "LETTERS", "MARKS", "NAMES", "covering", "faces", "in_range"]
