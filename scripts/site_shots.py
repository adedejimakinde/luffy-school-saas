"""Cut `scripts/site_shots.mjs`'s PNGs into the homepage slider's WebP files.

    python scripts/site_shots.py shots/ static/website/shots/

Four screens, each at a desk's shape (1280 by 700, drawn about 600px wide) and
a phone's (390 by 565, drawn the width of the phone), at 1x and 2x: the
principal's home, the strong student's Ogun State report sheet, the bursar's
fee collection, and the register, which is a phone in every size (300 and 600
wide). The page's `<img>` and `<source>` tags carry these sizes.

The cuts are boxes in the PNGs' own pixels (twice the CSS pixels). They were
set against the showcase as `schools/showcase.py` makes it; a change to the
showcase or to a page's layout is a reason to look at the output again.
"""

import sys
from pathlib import Path

from PIL import Image

GREY = (245, 246, 248)  # --bg
QUALITY = {"big": 74, "small": 72}
DESK, PHONE = ((1280, 700), (640, 350)), ((780, 1130), (390, 565))


def fit(image, size, pad):
    """The image, scaled to fit inside `size` less `pad`, centred on the grey."""
    width, height = size
    canvas = Image.new("RGB", size, GREY)
    scale = min((width - 2 * pad) / image.width, (height - 2 * pad) / image.height)
    image = image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
    canvas.paste(image, ((width - image.width) // 2, (height - image.height) // 2))
    return canvas


def stack(image, boxes):
    """Cuts from one long screenshot, one under the other."""
    parts = [image.crop(box) for box in boxes]
    out = Image.new("RGB", (max(p.width for p in parts), sum(p.height for p in parts)), GREY)
    top = 0
    for part in parts:
        out.paste(part, (0, top))
        top += part.height
    return out


def save(image, target, name, sizes):
    for (width, height), quality in zip(sizes, (QUALITY["big"], QUALITY["small"])):
        out = target / f"slide-{name}-{width}.webp"
        image.resize((width, height), Image.LANCZOS).save(out, "WEBP", quality=quality, method=6)
        print(f"{out}  {width}x{height}  {out.stat().st_size} bytes")


def main(source, target):
    source, target = Path(source), Path(target)
    target.mkdir(parents=True, exist_ok=True)
    png = lambda name: Image.open(source / f"{name}.png").convert("RGB")  # noqa: E731

    save(png("home-desk").crop((0, 0, 2560, 1400)), target, "home-desk", DESK)
    save(png("home-phone").crop((0, 0, 780, 1130)), target, "home-phone", PHONE)
    # The sheet's head, the learner box and the subjects.
    save(fit(png("card-desk").crop((380, 180, 2180, 1420)), (2560, 1400), 70), target, "report-desk", DESK)
    sheet = stack(png("card-phone"), [(0, 170, 780, 410), (0, 560, 780, 812), (0, 1300, 780, 2100)])
    save(fit(sheet, (780, 1130), 0), target, "report-phone", PHONE)
    # The bursar's money: what is owed, the latest payments and the term's collection.
    save(fit(png("bursar-desk").crop((520, 330, 2520, 1490)), (2560, 1400), 60), target, "fees-desk", DESK)
    save(png("bursar-phone").crop((0, 0, 780, 1130)), target, "fees-phone", PHONE)
    register = png("register")
    for width, quality in ((600, QUALITY["big"]), (300, QUALITY["small"])):
        height = round(register.height * width / register.width)
        out = target / f"slide-register-phone-{width}.webp"
        register.resize((width, height), Image.LANCZOS).save(out, "WEBP", quality=quality, method=6)
        print(f"{out}  {width}x{height}  {out.stat().st_size} bytes")


if __name__ == "__main__":
    main(*sys.argv[1:3])
