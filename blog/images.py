"""A picture for a post: an upload like any other, kept as WebP and small.

It goes through the one upload service (`files.service`), on the platform's
own schema: checked by its own bytes in the request, then drawn by the media
worker. What is kept is a fresh picture drawn from the upload and nothing of
the original, so its metadata, anything hidden after the image, and a file that
only claims to be a picture never reach classnode.co.

- **What may be sent**: PNG, JPEG or WebP, at most `MAX_UPLOAD_BYTES`, with
  the pixel count read from the header and refused before a pixel is decoded
  when it is past `MAX_SOURCE_PIXELS`. A phone's photo is turned the right way
  up first (EXIF orientation).
- **A cover** is cut to 1200 x 630 from its middle, the shape a shared link's
  card is drawn at, because the cover *is* the post's Open Graph image.
- **A picture in the body** is at most 1600 pixels wide, never made larger.
- **Both** are written as WebP at quality `QUALITY`, and a copy half as wide
  (`small`) for a phone's `srcset`.

The width and height are known as soon as the picture is uploaded (from its
header, the right way up), so the post's HTML has them before the worker has
drawn it (`files.images.predicted_blog_size`).
"""

import io

from django.db import transaction

from files import images as drawing
from files.kinds import Kind, profile_for

from .models import BlogImage

MAX_UPLOAD_BYTES = profile_for(Kind.BLOG_IMAGE).max_bytes
MAX_SOURCE_PIXELS = profile_for(Kind.BLOG_IMAGE).max_pixels
COVER_SIZE = (1200, 630)
BODY_MAX_WIDTH = 1600
QUALITY = drawing.BLOG_WEBP_QUALITY


class ImageRefused(Exception):
    """An upload this cannot use. The message is for the person who sent it."""


def _kind(cover: bool):
    return Kind.BLOG_COVER if cover else Kind.BLOG_IMAGE


def _webp(picture) -> bytes:
    return drawing.webp(picture, QUALITY)


def draw(raw: bytes, *, cover: bool):
    """`(full, small)` as Pillow images, or `ImageRefused`. What the worker makes."""
    from PIL import Image, ImageOps

    if not raw:
        raise ImageRefused("Choose a picture to upload.")
    profile = profile_for(_kind(cover))
    try:
        source = drawing.decode(raw, profile)
    except drawing.Refused as exc:
        raise ImageRefused(str(exc))
    if cover:
        full = ImageOps.fit(source, COVER_SIZE, centering=(0.5, 0.5))
    else:
        full = drawing.to_width(source, BODY_MAX_WIDTH)
    width = max(1, full.width // 2)
    small = full.resize((width, max(1, round(full.height * width / full.width))), Image.LANCZOS)
    return full, small


def _oriented_size(raw_or_file):
    """The picture's size from its header, the way round EXIF says to show it."""
    from PIL import Image

    drawing._register_heif()
    source = io.BytesIO(raw_or_file) if isinstance(raw_or_file, (bytes, bytearray)) else raw_or_file
    if not isinstance(raw_or_file, (bytes, bytearray)):
        source.seek(0)
    with Image.open(source) as image:
        width, height = image.size
        orientation = image.getexif().get(0x0112, 1)
    if not isinstance(raw_or_file, (bytes, bytearray)):
        raw_or_file.seek(0)
    return (height, width) if orientation in (5, 6, 7, 8) else (width, height)


@transaction.atomic
def store(post, upload, *, cover: bool, by) -> BlogImage:
    """Check the upload, hand it to the media worker, and keep it as one of `post`'s pictures."""
    from files import service

    if not upload:
        raise ImageRefused("Choose a picture to upload.")
    profile = profile_for(_kind(cover))
    try:
        service.check(_kind(cover), upload)
        width, height = _oriented_size(upload)
        stored = service.accept(_kind(cover), upload, by=by, public=False)
    except service.UploadRefused as exc:
        raise ImageRefused(str(exc))
    if stored.state == "failed":
        raise ImageRefused(stored.error)
    (full_w, full_h), (small_w, small_h) = drawing.predicted_blog_size(width, height, profile)
    return BlogImage.objects.create(
        post=post,
        uploaded_by=by,
        is_cover=cover,
        file=stored,
        width=full_w,
        height=full_h,
        small_width=small_w,
        small_height=small_h,
    )
