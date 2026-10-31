"""Pictures: decoded once, checked, and drawn again into what is kept.

Nothing of the uploaded file survives. It is decoded by Pillow (and by
`pillow-heif` for an iPhone's HEIC), turned the right way up from its EXIF
orientation, converted to sRGB from whatever colour profile it carried, and
then every output is encoded afresh from those pixels with **no metadata at
all**: no EXIF (so no GPS location, camera serial or time), no XMP, no
embedded colour profile, no comment, and nothing hidden after the image.
`info` is emptied before any save, because some of Pillow's writers copy an
ICC profile or EXIF block across from the source image if it is left there.

The checks before decoding are the ones `results.look` always made: the byte
size, then the format by the file's own bytes, then the pixel count from the
header. A decompression bomb is refused at the header, a few kilobytes in.
"""

import io

from .kinds import Family, Profile

#: Visually lossless at the sizes made, and inside §4.1's byte budgets.
#: AVIF's scale is libavif's (0-100); 60 at speed 6 is indistinguishable at
#: viewing size from WebP 82 and about a third smaller.
AVIF_QUALITY = 60
AVIF_SPEED = 6
WEBP_QUALITY = 82
JPEG_QUALITY = 85
MASTER_JPEG_QUALITY = 90
#: The blog's, unchanged from `blog.images`.
BLOG_WEBP_QUALITY = 80


class Refused(Exception):
    """An upload this cannot use. The message is for the person who sent it."""


_heif_registered = False


def _register_heif():
    global _heif_registered
    if not _heif_registered:
        import pillow_heif

        pillow_heif.register_heif_opener()
        _heif_registered = True


def _names(formats) -> str:
    names = {"JPEG": "JPG", "PNG": "PNG", "WEBP": "WebP", "HEIF": "HEIC"}
    listed = [names[f] for f in ("JPEG", "PNG", "WEBP", "HEIF") if f in formats]
    return ", ".join(listed[:-1]) + f" or {listed[-1]}" if len(listed) > 1 else listed[0]


def header(raw_or_file, profile: Profile):
    """`(format, width, height)` from the header alone, or `Refused`.

    The cheap half of the checks, run in the request so a wrong file is told
    so at once rather than after a trip through the queue.
    """
    from PIL import Image, UnidentifiedImageError

    _register_heif()
    source = raw_or_file
    if isinstance(raw_or_file, (bytes, bytearray)):
        source = io.BytesIO(raw_or_file)
    else:
        source.seek(0)
    try:
        with Image.open(source) as image:
            fmt, (width, height) = image.format, image.size
    except Image.DecompressionBombError:
        raise Refused(f"That picture is far larger than {profile.noun.lower()} needs. Save it smaller and try again.")
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise Refused(
            f"That file is not a picture this can read. {profile.noun} is a {_names(profile.formats)} file."
            + (" SVG files are not accepted." if _looks_like_svg(raw_or_file) else "")
        )
    finally:
        if not isinstance(raw_or_file, (bytes, bytearray)):
            raw_or_file.seek(0)
    if fmt not in profile.formats:
        hint = " Use a short video for anything that moves." if fmt == "GIF" else ""
        raise Refused(f"{profile.noun} is a {_names(profile.formats)} file.{hint}")
    if width * height > profile.max_pixels:
        raise Refused(f"That picture is far larger than {profile.noun.lower()} needs. Save it smaller and try again.")
    return fmt, width, height


def _looks_like_svg(raw_or_file) -> bool:
    if isinstance(raw_or_file, (bytes, bytearray)):
        head = bytes(raw_or_file[:512])
    else:
        raw_or_file.seek(0)
        head = raw_or_file.read(512)
        raw_or_file.seek(0)
    return b"<svg" in head.lower()


def _to_srgb(image):
    """Pixels in sRGB, whatever profile the camera or editor attached."""
    from PIL import ImageCms

    icc = image.info.get("icc_profile")
    if not icc:
        return image
    try:
        source = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        target = ImageCms.createProfile("sRGB")
        mode = "RGBA" if image.mode in ("RGBA", "LA", "PA") else "RGB"
        return ImageCms.profileToProfile(image.convert(mode), source, target, outputMode=mode)
    except (ImageCms.PyCMSError, OSError, ValueError):
        # A broken profile is ignored, as a browser would ignore it.
        return image


def decode(raw: bytes, profile: Profile, *, size_hint=None):
    """The upload as clean pixels: RGB, or RGBA where it has transparency."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    if len(raw) > profile.max_bytes:
        raise Refused(f"{profile.noun} can be at most {profile.max_mb} MB. Save it smaller and try again.")
    header(raw, profile)
    try:
        image = Image.open(io.BytesIO(raw))
        if size_hint and image.format == "JPEG":
            image.draft("RGB", size_hint)
        image = ImageOps.exif_transpose(image)
        image.load()
        image = _to_srgb(image)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError):
        raise Refused(f"That file is not a picture this can read. {profile.noun} is a {_names(profile.formats)} file.")
    has_alpha = image.mode in ("RGBA", "LA", "PA") or (image.mode == "P" and "transparency" in image.info)
    clean = image.convert("RGBA" if has_alpha else "RGB")
    if has_alpha and clean.getextrema()[3][0] == 255:
        clean = clean.convert("RGB")  # an alpha channel that hides nothing
    clean.info.clear()
    return clean


# -- encoders: every one starts from `info` emptied ----------------------------


def _encode(image, fmt, **options) -> bytes:
    image.info.clear()
    out = io.BytesIO()
    image.save(out, format=fmt, **options)
    return out.getvalue()


def jpeg(image, quality=JPEG_QUALITY) -> bytes:
    flat = _flatten(image)
    return _encode(flat, "JPEG", quality=quality, optimize=True, progressive=True)


def webp(image, quality=WEBP_QUALITY) -> bytes:
    return _encode(image, "WEBP", quality=quality, method=6)


def avif(image, quality=AVIF_QUALITY) -> bytes:
    return _encode(image, "AVIF", quality=quality, speed=AVIF_SPEED)


def png(image) -> bytes:
    return _encode(image, "PNG", optimize=True)


def _flatten(image):
    """On white: JPEG has no transparency."""
    from PIL import Image

    if image.mode == "RGB":
        return image
    base = Image.new("RGB", image.size, (255, 255, 255))
    base.paste(image, mask=image.getchannel("A") if "A" in image.getbands() else None)
    return base


def fit_long_side(image, side):
    """Never larger, and at most `side` on the long side."""
    from PIL import Image

    if not side or max(image.size) <= side:
        return image.copy()
    scale = side / max(image.size)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.LANCZOS)


def to_width(image, width):
    from PIL import Image

    if image.width <= width:
        return image.copy()
    height = max(1, round(image.height * width / image.width))
    return image.resize((width, height), Image.LANCZOS)


def widths_for(source_width, widths):
    """The widths a source this wide can give, never upscaled; at least one."""
    made = [w for w in widths if w <= source_width]
    return made or [source_width]


def dominant_colour(image) -> str:
    """The single most common colour after reduction, as `#RRGGBB`."""
    small = _flatten(image).copy()
    small.thumbnail((64, 64))
    quantised = small.quantize(colors=6)
    palette = quantised.getpalette()
    counts = sorted(quantised.getcolors(), reverse=True)
    index = counts[0][1]
    r, g, b = palette[index * 3: index * 3 + 3]
    return f"#{r:02X}{g:02X}{b:02X}"


#: A border this close to white is paper, or an export's background.
WHITE_ENOUGH = 235


def trim(image):
    """Cut away a transparent border, or a white one the way a scan leaves it.

    Only those two: a crest drawn on a solid colour that runs to its edges is
    left whole, because a dot on blue and a blue square with a dot in it are
    the same pixels, and only one of them is the school's crest.
    """
    from PIL import Image, ImageChops

    if "A" in image.getbands():
        box = image.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
        if box:
            image = image.crop(box)
    rgb = _flatten(image)
    width, height = rgb.size
    corners = [rgb.getpixel(p) for p in ((0, 0), (width - 1, 0), (0, height - 1), (width - 1, height - 1))]
    if not all(min(c) >= WHITE_ENOUGH for c in corners):
        return image
    background = Image.new("RGB", rgb.size, (255, 255, 255))
    ink = ImageChops.difference(rgb, background).convert("L").point(lambda v: 255 if v > 255 - WHITE_ENOUGH else 0)
    box = ink.getbbox()
    if box and box != (0, 0, width, height):
        image = image.crop(box)
    return image


def fit_in_frame(image, width, height):
    """Inside `width` x `height`, centred, on transparency: a crest's square."""
    from PIL import Image

    inside = image.copy()
    inside.thumbnail((width, height), Image.LANCZOS)
    frame = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    rgba = inside.convert("RGBA")
    frame.paste(rgba, ((width - inside.width) // 2, (height - inside.height) // 2), rgba)
    return frame


def _meta(image, data):
    return {"bytes": len(data), "width": image.width, "height": image.height}


# -- the families --------------------------------------------------------------


def portrait(raw: bytes, profile: Profile):
    """A master for printing, and passport frames for the card and a phone."""
    from PIL import ImageOps

    source = decode(raw, profile, size_hint=(profile.master_side, profile.master_side))
    master = _flatten(fit_long_side(source, profile.master_side))
    out = {"master.jpg": (master, jpeg(master, MASTER_JPEG_QUALITY))}
    for name, width, height in profile.frames:
        framed = ImageOps.fit(master, (width, height), centering=(0.5, 0.4))
        out[f"{name}.webp"] = (framed, webp(framed))
        if name == "card":
            # What WeasyPrint prints, and what a browser without WebP is sent.
            out["card.jpg"] = (framed, jpeg(framed, MASTER_JPEG_QUALITY))
    return _result(out, master, "master.jpg")


def site_photo(raw: bytes, profile: Profile, *, prefix=""):
    """A 2400 px master, and phone-to-desktop widths in AVIF and WebP, JPEG fallback."""
    source = decode(raw, profile, size_hint=(profile.master_side, profile.master_side))
    return site_photo_from(source, profile, prefix=prefix)


def site_photo_from(source, profile: Profile, *, prefix=""):
    master = _flatten(fit_long_side(source, profile.master_side))
    out = {f"{prefix}master.jpg": (master, jpeg(master, MASTER_JPEG_QUALITY))}
    widths = widths_for(master.width, profile.widths)
    for width in widths:
        sized = to_width(master, width)
        out[f"{prefix}{width}.avif"] = (sized, avif(sized))
        out[f"{prefix}{width}.webp"] = (sized, webp(sized))
    # JPEG for the old Android browsers and Opera Mini common here: at the
    # phone width and the largest, which is what a `<picture>` falls back to.
    for width in sorted({min(828, widths[-1]), widths[-1]}):
        sized = to_width(master, width)
        out[f"{prefix}{width}.jpg"] = (sized, jpeg(sized))
    result = _result(out, master, f"{prefix}master.jpg")
    result["colour"] = dominant_colour(master)
    return result


def mark(raw: bytes, profile: Profile):
    """Trimmed lossless PNG: a master, and the frames each place draws it in."""
    source = trim(decode(raw, profile))
    master = fit_long_side(source, profile.master_side)
    out = {"master.png": (master, png(master))}
    for name, width, height in profile.frames:
        framed = fit_in_frame(master, width, height)
        out[f"{name}.png"] = (framed, png(framed))
    result = _result(out, master, "master.png")
    result["colour"] = dominant_colour(master)
    return result


def blog(raw: bytes, profile: Profile):
    """`blog.images`' rules: the full picture and one half as wide, both WebP."""
    from PIL import Image, ImageOps

    source = decode(raw, profile)
    if profile.frames:
        _, width, height = profile.frames[0]
        full = ImageOps.fit(source, (width, height), centering=(0.5, 0.5))
    else:
        full = to_width(source, profile.widths[0])
    half_width = max(1, full.width // 2)
    small = full.resize((half_width, max(1, round(full.height * half_width / full.width))), Image.LANCZOS)
    out = {
        "full.webp": (full, webp(full, BLOG_WEBP_QUALITY)),
        "small.webp": (small, webp(small, BLOG_WEBP_QUALITY)),
    }
    return _result(out, full, "full.webp")


def predicted_blog_size(width, height, profile: Profile):
    """What `blog()` will make from a picture this size, without decoding it.

    The blog writes width and height into its HTML as soon as a picture is
    uploaded, before the worker has drawn it.
    """
    if profile.frames:
        _, w, h = profile.frames[0]
        return (w, h), (max(1, w // 2), max(1, round(h * max(1, w // 2) / w)))
    full_w = min(width, profile.widths[0])
    full_h = max(1, round(height * full_w / width))
    half_w = max(1, full_w // 2)
    return (full_w, full_h), (half_w, max(1, round(full_h * half_w / full_w)))


def _result(out, master, master_name):
    return {
        "variants": {name: _meta(image, data) for name, (image, data) in out.items()},
        "data": {name: data for name, (image, data) in out.items()},
        "master": master_name,
        "width": master.width,
        "height": master.height,
    }


PROCESSORS = {
    Family.PORTRAIT: portrait,
    Family.SITE_PHOTO: site_photo,
    Family.MARK: mark,
    Family.BLOG: blog,
}


__all__ = [
    "PROCESSORS",
    "Refused",
    "avif",
    "blog",
    "decode",
    "dominant_colour",
    "header",
    "jpeg",
    "mark",
    "png",
    "portrait",
    "predicted_blog_size",
    "site_photo",
    "site_photo_from",
    "trim",
    "webp",
]
