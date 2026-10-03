"""Turn `scripts/site_shots.mjs`'s PNGs into the homepage's WebP files.

    python scripts/site_shots.py shots/ static/website/shots/

Phones are drawn about 270px wide and the laptop about 640px, so each file is
cut to twice that: sharp on a phone's screen, and no heavier than it needs to
be. The page's `<img>` tags carry these same sizes as `width` and `height`.
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


if __name__ == "__main__":
    main(*sys.argv[1:3])
