"""Cut `scripts/landing_shots.mjs`'s PNGs into the solution pages' WebP files.

    python scripts/landing_shots.py shots/ static/website/shots/

Each desk screen is 1280 by 800 CSS pixels (drawn at most about 560px wide on
a page), saved at 640 by 400 and 1280 by 800; each phone screen is the 390 by
844 phone the script uses, saved at 300 by 649 and 600 by 1298, the homepage
slider's phone size (`scripts/site_shots.py`). `website/landing.py` names them.

The cuts are boxes in the PNGs' own pixels (twice the CSS pixels), set against
the demo as the script's header says to make it. The website's two are stacked
from its header and one section each, so neither prints the demo school's
address.
"""

import sys
from pathlib import Path

from PIL import Image

QUALITY = {"big": 72, "small": 74}
DESK = ((1280, 800), (640, 400))
PHONE = ((600, 1298), (300, 649))
#: One whole screen in the PNGs' pixels.
DESK_SCREEN = (2560, 1600)
PHONE_SCREEN = (780, 1688)


def stack(image, boxes):
    """Cuts from one long screenshot, one under the other."""
    parts = [image.crop(box) for box in boxes]
    out = Image.new("RGB", (max(p.width for p in parts), sum(p.height for p in parts)), (255, 255, 255))
    top = 0
    for part in parts:
        out.paste(part, (0, top))
        top += part.height
    return out


def save(image, target, name, sizes):
    for (width, height), quality in zip(sizes, (QUALITY["big"], QUALITY["small"])):
        out = target / f"landing-{name}-{width}.webp"
        image.resize((width, height), Image.LANCZOS).save(out, "WEBP", quality=quality, method=6)
        print(f"{out}  {width}x{height}  {out.stat().st_size} bytes")


def main(source, target):
    source, target = Path(source), Path(target)
    target.mkdir(parents=True, exist_ok=True)
    png = lambda name: Image.open(source / f"{name}.png").convert("RGB")  # noqa: E731

    for name in ("broadsheet", "chain", "fee-class", "roll-import", "sit"):
        save(png(name).crop((0, 0, *DESK_SCREEN)), target, name, DESK)
    for name in ("checker", "checker-card", "sit-phone"):
        save(png(name).crop((0, 0, *PHONE_SCREEN)), target, name, PHONE)
    # The website on a desk: its header, then the school's facts and the principal's message.
    save(stack(png("website"), [(0, 0, 2560, 132), (0, 1400, 2560, 2868)]), target, "website", DESK)
    # On a phone: its header, then "Around the school", the album's photos.
    save(stack(png("website-phone"), [(0, 0, 780, 150), (0, 4040, 780, 5578)]), target, "website-phone", PHONE)


if __name__ == "__main__":
    main(*sys.argv[1:3])
