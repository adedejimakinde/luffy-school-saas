#!/usr/bin/env python
"""Draw Classnode's icons into `webroot/`, the files served at the root of every host.

The mark is `i-brand-mark` (templates/design/icons.html), the site header's
logo: a One Blue rounded square (`--brand`, #143D8C, in static/web/design.css)
with three white nodes joined in a triangle. Drawn from the same numbers, with
the symbol's 1-unit margin cropped off (a 22-unit square, viewBox `1 1 22 22`),
so the square fills the icon and a 16px tab icon spends no pixel on margin.

  favicon.ico            16, 32 and 48 inside, each drawn at its own size
  favicon.svg            the mark itself, for browsers that take an SVG
  apple-touch-icon.png   180 x 180, square to the edge and opaque: iOS rounds
                         the corners itself and draws transparency as black
  icon-192.png           192 x 192, for site.webmanifest
  icon-512.png           512 x 512, for site.webmanifest and the logo search
                         engines are given in the structured data

`site.webmanifest` is written by hand and lives beside them. From the
repository root:

  python scripts/favicons.py

Each PNG is drawn at least 4096 pixels across and then averaged down, which is
what anti-aliases its edges; Pillow has no SVG renderer.
"""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent / "webroot"

BRAND = "#143D8C"
WHITE = "#FFFFFF"

#: The mark in `i-brand-mark`'s own units, moved one unit up and left.
SIDE = 22
RADIUS = 6
NODES = ((6, 7), (16, 7), (11, 16))
NODE_RADIUS = 2.1
LINE = 1.3

SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="1 1 22 22">
<rect x="1" y="1" width="22" height="22" rx="6" fill="{BRAND}"/>
<path d="M7 8L17 8L12 17Z" fill="none" stroke="{WHITE}" stroke-width="1.3" stroke-linejoin="round"/>
<circle cx="7" cy="8" r="2.1" fill="{WHITE}"/>
<circle cx="17" cy="8" r="2.1" fill="{WHITE}"/>
<circle cx="12" cy="17" r="2.1" fill="{WHITE}"/>
</svg>
"""


def mark(size, rounded=True):
    """The mark, `size` pixels square: rounded with clear corners, or square to the edge."""
    scale = max(4, -(-4096 // size))
    big = size * scale
    unit = big / SIDE
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if rounded:
        draw.rounded_rectangle((0, 0, big - 1, big - 1), radius=RADIUS * unit, fill=BRAND)
    else:
        draw.rectangle((0, 0, big - 1, big - 1), fill=BRAND)
    points = [(x * unit, y * unit) for x, y in NODES]
    draw.line([*points, points[0]], fill=WHITE, width=round(LINE * unit))
    for x, y in points:
        r = NODE_RADIUS * unit
        draw.ellipse((x - r, y - r, x + r, y + r), fill=WHITE)
    # Averaged with alpha premultiplied, so the clear corners do not darken the edge.
    small = image.convert("RGBa").resize((size, size), Image.Resampling.BOX).convert("RGBA")
    return small if rounded else small.convert("RGB")


def main():
    ROOT.mkdir(exist_ok=True)
    (ROOT / "favicon.svg").write_text(SVG)
    sizes = (16, 32, 48)
    frames = [mark(size) for size in sizes]
    frames[-1].save(
        ROOT / "favicon.ico",
        sizes=[(size, size) for size in sizes],
        append_images=frames[:-1],
    )
    mark(180, rounded=False).save(ROOT / "apple-touch-icon.png", optimize=True)
    for size in (192, 512):
        mark(size).save(ROOT / f"icon-{size}.png", optimize=True)


if __name__ == "__main__":
    main()
