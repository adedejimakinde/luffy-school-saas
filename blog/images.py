"""A picture for a post: opened, checked, drawn again as WebP, and kept small.

`results.look`'s rule for a school's crest, for the blog: what is kept is a
fresh picture drawn from the upload and nothing of the original, so its
metadata, anything hidden after the image, and a file that only claims to be
a picture never reach classnode.co.

- **What may be sent**: PNG, JPEG or WebP, at most `MAX_UPLOAD_BYTES`, with
  the pixel count read from the header and refused before a pixel is decoded
  when it is past `MAX_SOURCE_PIXELS`. A phone's photo is turned the right way
  up first (EXIF orientation).
- **A cover** is cut to 1200 x 630 from its middle, the shape a shared link's
  card is drawn at, because the cover *is* the post's Open Graph image.
- **A picture in the body** is at most 1600 pixels wide, never made larger.
- **Both** are written as WebP at quality `QUALITY`, and a copy half as wide
  (`small`) for a phone's `srcset`.
"""

import io

from django.db import transaction

from .models import BlogImage

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_SOURCE_PIXELS = 40_000_000
COVER_SIZE = (1200, 630)
BODY_MAX_WIDTH = 1600
QUALITY = 80


class ImageRefused(Exception):
    """An upload this cannot use. The message is for the person who sent it."""


def _open(raw: bytes):
    from PIL import Image, ImageOps, UnidentifiedImageError

    if not raw:
        raise ImageRefused("Choose a picture to upload.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ImageRefused("A picture can be at most 10 MB. Save it smaller and try again.")
    try:
        source = Image.open(io.BytesIO(raw))
        if source.format not in ("PNG", "JPEG", "WEBP"):
            raise ImageRefused("A picture is a JPG, PNG or WebP file.")
        width, height = source.size
        if width * height > MAX_SOURCE_PIXELS:
            raise ImageRefused("That picture is far larger than a post needs. Save it smaller and try again.")
        source = ImageOps.exif_transpose(source)
        source.load()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError):
        raise ImageRefused("That file is not a picture this can read. Use a JPG, PNG or WebP file.")
    has_alpha = source.mode in ("RGBA", "LA") or (source.mode == "P" and "transparency" in source.info)
    return source.convert("RGBA" if has_alpha else "RGB")


def _webp(picture) -> bytes:
    out = io.BytesIO()
    picture.save(out, format="WEBP", quality=QUALITY, method=6)
    return out.getvalue()


def _cover(source):
    from PIL import ImageOps

    return ImageOps.fit(source, COVER_SIZE, centering=(0.5, 0.5))


def _body(source):
    from PIL import Image

    if source.width > BODY_MAX_WIDTH:
        height = round(source.height * BODY_MAX_WIDTH / source.width)
        return source.resize((BODY_MAX_WIDTH, height), Image.LANCZOS)
    return source


def _half(picture):
    from PIL import Image

    width = max(1, picture.width // 2)
    height = max(1, round(picture.height * width / picture.width))
    return picture.resize((width, height), Image.LANCZOS)


def draw(raw: bytes, *, cover: bool):
    """`(full, small)` as Pillow images, or `ImageRefused`."""
    source = _open(raw)
    full = _cover(source) if cover else _body(source)
    return full, _half(full)


@transaction.atomic
def store(post, raw: bytes, *, cover: bool, by) -> BlogImage:
    """Draw the upload and keep it as one of `post`'s pictures."""
    full, small = draw(raw, cover=cover)
    return BlogImage.objects.create(
        post=post,
        uploaded_by=by,
        is_cover=cover,
        width=full.width,
        height=full.height,
        data=_webp(full),
        small_width=small.width,
        small_height=small.height,
        small=_webp(small),
    )
