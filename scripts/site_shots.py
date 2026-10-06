"""Turn `scripts/site_shots.mjs`'s PNGs into the homepage's WebP files.

    python scripts/site_shots.py shots/ static/website/shots/

Phones are drawn about 270px wide and the laptop about 640px, so each file is
cut to twice that: sharp on a phone's screen, and no heavier than it needs to
be. The two laptop shots also get a phone-sized crop (`CROPS`). The page's `<img>` tags carry these same sizes as `width` and `height`.
"""

import sys
from pathlib import Path

from PIL import Image

#: name: pixel width of the WebP.
WIDTHS = {
    "marks": 540,
    "fees": 540,
    "register": 540,
    "card": 540,
    "broadsheet": 1280,
    "home": 1280,
}
QUALITY = 74

#: Phone-sized crops of the two laptop shots, cut from the WebP files above
#: (so run this after the loop that writes them): name: (source, boxes). Each
#: box is (left, top, right, bottom) in the source's own pixels; several boxes
#: are stacked, centred, on the app's grey. A phone shows these at about 360px
#: wide, where the whole 1280px screen would be unreadable.
CROPS = {
    # The broadsheet: the class, then position, name and the first two subjects.
    "broadsheet-phone": ("broadsheet", [(288, 148, 760, 214), (288, 288, 760, 700)]),
    # The proprietor's home: what came in (the two middle figures), then today's
    # timed steps under its heading.
    "home-phone": ("home", [(533, 170, 1004, 366), (934, 396, 1248, 450), (934, 562, 1248, 760)]),
}
GREY = (245, 246, 248)  # --bg


def main(source, target):
    source, target = Path(source), Path(target)
    target.mkdir(parents=True, exist_ok=True)
    for name, width in WIDTHS.items():
        image = Image.open(source / f"{name}.png").convert("RGB")
        height = round(image.height * width / image.width)
        image = image.resize((width, height), Image.LANCZOS)
        out = target / f"{name}.webp"
        image.save(out, "WEBP", quality=QUALITY, method=6)
        print(f"{out}  {width}x{height}  {out.stat().st_size} bytes")
    for name, (source_name, boxes) in CROPS.items():
        source_image = Image.open(target / f"{source_name}.webp").convert("RGB")
        pieces = [source_image.crop(box) for box in boxes]
        width = max(piece.width for piece in pieces)
        height = sum(piece.height for piece in pieces) + 16 * (len(pieces) - 1)
        image = Image.new("RGB", (width, height), GREY)
        top = 0
        for piece in pieces:
            image.paste(piece, ((width - piece.width) // 2, top))
            top += piece.height + 16
        out = target / f"{name}.webp"
        image.save(out, "WEBP", quality=QUALITY, method=6)
        print(f"{out}  {width}x{height}  {out.stat().st_size} bytes")


if __name__ == "__main__":
    main(*sys.argv[1:3])
