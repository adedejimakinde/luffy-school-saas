#!/usr/bin/env python3
"""Cut the design's web fonts, so the files in `static/web/fonts/` can be made again.

    python scripts/fonts.py HankenGrotesk[wght].ttf NotoSans[wdth,wght].ttf [--out DIR]

Needs `fonttools` and `brotli`, both pinned in `requirements.txt`. The two
sources are the families' variable fonts, SIL OFL 1.1, from
https://github.com/google/fonts (`ofl/hankengrotesk/` and `ofl/notosans/`); their
SHA-256 sums are below, and the script refuses any other file, so what is cut is
what was reviewed.

## Why two families

Hanken Grotesk is the design's face. It carries Yoruba's ẹ ọ and Igbo's ị ụ ṅ
and the combining tone marks, but not ṣ, not Hausa's hooked ɓ ɗ ƙ ƴ, not the
apostrophe ʼ and not the naira sign ₦. The files shipped before this one were
cut with the `latin` subset only, so every one of those letters, and every tone
mark and underdot, was drawn in whatever font the phone had: a name like
"Ọláòlúwa Adéṣínà" came out in two typefaces, and the fee amounts' ₦ in a third.

- **`hanken-grotesk-{400,700}.woff2`** now carry what Hanken has, and what its
  own shapes can make: **ṣ and Ṣ** are the font's s and S with its own
  underdot, set where its mark-attachment table puts it (the same way it
  already builds ẹ), **₦** is its N crossed by two bars cut from its own equals
  sign, and **ʼ** is its right quote. Nothing is borrowed.
- **`noto-sans-hausa-{400,700}.woff2`** hold the few letters only a drawing can
  give: Hausa's hooked consonants and ǹ. A face with a `unicode-range`, so a
  page that has none of them never fetches it.

## What is cut

Both families are instanced at weight 400 and 700 (Noto at normal width), then
subset to the characters below, as WOFF2. The `unicode-range` each face needs is
printed, and `tests/test_design.py` holds it to the files.
"""

import argparse
import hashlib
import sys
from pathlib import Path

SOURCES = {
    "hanken": "813b3f8fa0965405669a89b38e51bbefd95eef6b8e20d1cb2d8c10cce062662f",
    "noto": "bfb7bb691513f12e734dc346c03a03f784912432d7e3fa8e56efcf906fe86b3d",
}

#: Google Fonts' `latin` subset, which is what the shipped files held before.
LATIN = (
    list(range(0x0000, 0x0100))
    + [0x0131, 0x0152, 0x0153, 0x02BB, 0x02BC, 0x02C6, 0x02DA, 0x02DC, 0x0304, 0x0308, 0x0329]
    + list(range(0x2000, 0x2070))
    + [0x20AC, 0x2122, 0x2191, 0x2193, 0x2212, 0x2215, 0xFEFF, 0xFFFD]
)

#: Added for Nigerian names and money: the tone marks Yoruba and Igbo write
#: over a letter (grave, acute, macron) and under it (dot below, dot above),
#: Yoruba's ẹ ọ ṣ and Igbo's ị ụ ṅ in both cases, and the naira sign.
NIGERIAN = [
    0x0300, 0x0301, 0x0323, 0x0307,
    0x1E44, 0x1E45,  # Ṅ ṅ
    0x1E62, 0x1E63,  # Ṣ ṣ  (built)
    0x1EB8, 0x1EB9,  # Ẹ ẹ
    0x1ECA, 0x1ECB,  # Ị ị
    0x1ECC, 0x1ECD,  # Ọ ọ
    0x1EE4, 0x1EE5,  # Ụ ụ
    0x20A6,  # ₦  (built)
]

#: What only Noto draws: Hausa's hooked consonants, and the grave-marked n.
HAUSA = [0x0181, 0x0253, 0x018A, 0x0257, 0x0198, 0x0199, 0x01B3, 0x01B4, 0x01F8, 0x01F9]

#: The layout features kept in Hanken: composing and placing marks (`ccmp`, `mark`,
#: `mkmk`, which is what puts a tone mark over a letter with an underdot), kerning
#: and the f-ligatures. The files shipped before kept four more, `frac`, `numr`,
#: `dnom` and `locl`: fractions, which nothing on a page asks for, and forms for
#: languages the platform is not written in. Cutting them pays for the letters
#: added here, on pages already at the 150 KB budget (`tests/test_budget.py`).
HANKEN_FEATURES = ["ccmp", "liga", "kern", "mark", "mkmk"]

#: Noto is scaled to Hanken's x-height (493 in both weights; Noto's is 536 regular
#: and 546 bold) and given Hanken's ascent and descent divided by that scale, so a
#: line with one of its letters has the line height and the letter size of the
#: rest. Written into `static/web/design.css` by hand, and held to the files by
#: `tests/test_design.py`.
NOTO_SIZE_ADJUST = {400: 0.92, 700: 0.90}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def instance(source, wght, wdth=None):
    from fontTools.ttLib import TTFont
    from fontTools.varLib import instancer

    axes = {"wght": wght}
    if wdth is not None:
        axes["wdth"] = wdth
    return instancer.instantiateVariableFont(TTFont(source), axes, inplace=False, updateFontNames=True)


def mark_offset(font, base, mark):
    """Where `mark` goes on `base`: its anchor on the base minus its own anchor, from GPOS."""
    for lookup in font["GPOS"].table.LookupList.Lookup:
        if lookup.LookupType != 4:  # mark-to-base
            continue
        for table in lookup.SubTable:
            if mark in table.MarkCoverage.glyphs and base in table.BaseCoverage.glyphs:
                record = table.MarkArray.MarkRecord[table.MarkCoverage.glyphs.index(mark)]
                anchor = table.BaseArray.BaseRecord[table.BaseCoverage.glyphs.index(base)].BaseAnchor[record.Class]
                return anchor.XCoordinate - record.MarkAnchor.XCoordinate, anchor.YCoordinate - record.MarkAnchor.YCoordinate
    raise SystemExit(f"no mark-to-base anchor for {mark} on {base}")


def add_composite(font, name, codepoints, parts):
    """A glyph made of other glyphs: `parts` is [(glyph, dx, dy, (sx, sy))], the first sets the advance."""
    from fontTools.ttLib.tables._g_l_y_f import Glyph, GlyphComponent

    glyf, hmtx = font["glyf"], font["hmtx"]
    glyph = Glyph()
    glyph.numberOfContours = -1
    glyph.components = []
    for index, (part, dx, dy, (sx, sy)) in enumerate(parts):
        component = GlyphComponent()
        component.glyphName = part
        component.x, component.y = round(dx), round(dy)
        component.flags = 0x0002 | 0x0004  # offsets, rounded to the grid
        if index == 0:
            component.flags |= 0x0200  # use this one's metrics
        if (sx, sy) != (1, 1):
            component.transform = [[sx, 0], [0, sy]]
        glyph.components.append(component)
    order = font.getGlyphOrder()
    font.setGlyphOrder(order + [name])
    glyf.glyphs[name] = glyph
    glyph.recalcBounds(glyf)
    hmtx[name] = (hmtx[parts[0][0]][0], glyph.xMin)
    for table in font["cmap"].tables:
        if table.isUnicode():
            for codepoint in codepoints:
                table.cmap[codepoint] = name
    if "GDEF" in font and font["GDEF"].table.GlyphClassDef:
        font["GDEF"].table.GlyphClassDef.classDefs[name] = 1  # a base glyph


def alias(font, codepoint, glyph):
    for table in font["cmap"].tables:
        if table.isUnicode():
            table.cmap[codepoint] = glyph


def build_hanken(font):
    """Add what Hanken's own drawing can make: ṣ Ṣ, ₦ and ʼ."""
    hmtx, glyf = font["hmtx"], font["glyf"]
    for base, name, codepoint in (("s", "uni1E63", 0x1E63), ("S", "uni1E62", 0x1E62)):
        dx, dy = mark_offset(font, base, "dotbelowcomb")
        add_composite(font, name, [codepoint], [(base, 0, 0, (1, 1)), ("dotbelowcomb", dx, dy, (1, 1))])

    # ₦: its N, crossed by two bars from its own equals sign, stretched to run a
    # little past both stems and set across the middle of the capital.
    n = glyf["N"]
    n.recalcBounds(glyf)
    equal = glyf["equal"]
    equal.recalcBounds(glyf)
    overshoot = 0.06 * (n.xMax - n.xMin)
    stretch = ((n.xMax - n.xMin) + 2 * overshoot) / (equal.xMax - equal.xMin)
    dx = (n.xMin - overshoot) - equal.xMin * stretch
    dy = (n.yMax / 2) - (equal.yMin + equal.yMax) / 2
    add_composite(font, "uni20A6", [0x20A6], [("N", 0, 0, (1, 1)), ("equal", dx, dy, (stretch, 1))])

    alias(font, 0x02BC, "quoteright")


def cut(font, codepoints, *, features):
    from fontTools import subset

    options = subset.Options()
    options.layout_features = features
    options.notdef_outline = True
    options.name_IDs = [0, 1, 2, 3, 4, 5, 6, 13, 14]
    options.name_legacy = True
    options.glyph_names = False
    options.hinting = False
    options.flavor = "woff2"
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=sorted(set(codepoints)))
    subsetter.subset(font)
    return font


def ranges(codepoints):
    """CSS `unicode-range` tokens for a set of code points, adjacent ones joined."""
    points = sorted(set(codepoints))
    out, start, previous = [], None, None
    for point in points:
        if start is None:
            start = previous = point
        elif point == previous + 1:
            previous = point
        else:
            out.append((start, previous))
            start = previous = point
    if start is not None:
        out.append((start, previous))
    return ", ".join(f"U+{a:X}" if a == b else f"U+{a:X}-{b:X}" for a, b in out)


def write(font, path):
    font.flavor = "woff2"
    font.save(path)
    return Path(path).stat().st_size


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("hanken", help="HankenGrotesk[wght].ttf")
    parser.add_argument("noto", help="NotoSans[wdth,wght].ttf")
    parser.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "static" / "web" / "fonts"))
    args = parser.parse_args(argv)
    out = Path(args.out)

    for label, path in (("hanken", args.hanken), ("noto", args.noto)):
        expected = SOURCES[label]
        if expected and sha256(path) != expected:
            raise SystemExit(f"{path} is not the file this script was written against ({sha256(path)})")

    hanken_range = None
    for weight, style in ((400, "Regular"), (700, "Bold")):
        font = instance(args.hanken, weight)
        build_hanken(font)
        cmap = font.getBestCmap()
        wanted = [c for c in LATIN + NIGERIAN if c in cmap]
        missing = sorted(set(NIGERIAN) - set(wanted))
        if missing:
            raise SystemExit(f"Hanken still lacks {[hex(c) for c in missing]}")
        cut(font, wanted, features=HANKEN_FEATURES)
        size = write(font, out / f"hanken-grotesk-{weight}.woff2")
        hanken_range = ranges(wanted)
        print(f"hanken-grotesk-{weight}.woff2  {size} bytes  {len(wanted)} characters")

    for weight in (400, 700):
        font = instance(args.noto, weight, wdth=100)
        cut(font, HAUSA, features=[])
        size = write(font, out / f"noto-sans-hausa-{weight}.woff2")
        print(f"noto-sans-hausa-{weight}.woff2  {size} bytes  {len(HAUSA)} characters")

    print("\nHanken Grotesk unicode-range:\n  " + hanken_range)
    print("Noto Sans unicode-range:\n  " + ranges(HAUSA))


if __name__ == "__main__":
    main(sys.argv[1:])
