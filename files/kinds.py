"""What may be uploaded, how much of it, who may see it, and what is kept.

Every upload on the platform names one `Kind`, and the kind decides everything
else: the largest file looked at, the formats accepted (read from the file's
own bytes, never from its name or the browser's word for it), whether the
result is public on the school's host or private to its office, and which
processing profile turns the upload into what is kept (`files.processing`).

The numbers are the owner's (docs/school-sites.md §9, decided 31 October
2026) and they exist to keep a 100 GB server small:

- **Photos** keep one master and two or three sizes for phones. No original is
  kept. A portrait's master is 1200 px on its long side, which is about four
  times what a report card prints; a website photo's is 2400 px, for print.
- **Crests, logos, signatures and stamps** are trimmed lossless PNG. SVG is
  refused everywhere: it can carry script, and a PNG does the job.
- **PDFs** are optimised losslessly; scanned pages are brought down to 200 dpi.
- **Video** is a short muted hero loop only, at most about ten seconds and
  3 MB once encoded. Anything longer is a YouTube or Vimeo link.
"""

from dataclasses import dataclass, field
from typing import FrozenSet, Tuple

from django.db import models

MB = 1024 * 1024


class Kind(models.TextChoices):
    STUDENT_PHOTO = "student_photo", "Student photo"
    STAFF_PHOTO = "staff_photo", "Staff photo"
    CREST = "crest", "Crest"
    LOGO = "logo", "Logo"
    SIGNATURE = "signature", "Principal's signature"
    STAMP = "stamp", "School stamp"
    HERO_IMAGE = "hero_image", "Website hero image"
    GALLERY_IMAGE = "gallery_image", "Website gallery image"
    HERO_VIDEO = "hero_video", "Website hero video"
    #: The principal's portrait in the website's "From the principal" section.
    SITE_PORTRAIT = "site_portrait", "Website portrait"
    DOCUMENT = "document", "Document"
    #: Classnode's own blog (`blog`), on the platform's schema, not a school's.
    BLOG_COVER = "blog_cover", "Blog cover"
    BLOG_IMAGE = "blog_image", "Blog picture"


class Family(models.TextChoices):
    """Which processing a kind gets. Kinds in one family differ in sizes only."""

    PORTRAIT = "portrait"
    SITE_PHOTO = "site_photo"
    MARK = "mark"
    DOCUMENT = "document"
    VIDEO = "video"
    BLOG = "blog"


#: Raster formats Pillow decodes for us, by the name Pillow gives them. GIF is
#: not here (use a video), nor SVG, which Pillow cannot open at all.
PHOTO_FORMATS = frozenset({"JPEG", "PNG", "WEBP", "HEIF"})
MARK_FORMATS = frozenset({"PNG", "JPEG", "WEBP"})

#: The office: who may see a private file through the generic route. Kinds a
#: feature serves through its own route (a child's photo on the roll) keep that
#: route's rule; this is the floor for everything else.
OFFICE = frozenset({"principal", "admin"})


@dataclass(frozen=True)
class Profile:
    kind: str
    family: str
    noun: str
    max_bytes: int
    #: Read from the header before a pixel is decoded: a decompression bomb is
    #: refused while it is still a few kilobytes.
    max_pixels: int = 60_000_000
    formats: FrozenSet[str] = PHOTO_FORMATS
    #: Public files are served on the school's own host to anybody, with a
    #: year's cache. Private ones only on the portal path, to `readers`.
    public: bool = False
    readers: FrozenSet[str] = OFFICE
    #: The long side of the master kept for printing, in pixels.
    master_side: int = 0
    #: Widths made for screens, never wider than the master.
    widths: Tuple[int, ...] = ()
    #: Fixed-size variants (name, width, height) where a frame is fitted.
    frames: Tuple[Tuple[str, int, int], ...] = field(default_factory=tuple)
    #: About what one processed upload of this kind keeps, for the quota check
    #: made before anything is processed. The real size is checked afterwards.
    typical_bytes: int = 200 * 1024

    @property
    def max_mb(self) -> int:
        return self.max_bytes // MB


PROFILES = {
    p.kind: p
    for p in (
        # A passport frame, 7:9, at the size a card prints (23 mm at 300 dpi
        # is 272 px), and half that for a list on a phone.
        Profile(
            Kind.STUDENT_PHOTO, Family.PORTRAIT, "A photo", 15 * MB,
            master_side=1200, frames=(("card", 280, 360), ("small", 140, 180)),
            typical_bytes=200 * 1024,
        ),
        Profile(
            Kind.STAFF_PHOTO, Family.PORTRAIT, "A photo", 15 * MB,
            master_side=1200, frames=(("card", 280, 360), ("small", 140, 180)),
            typical_bytes=200 * 1024,
        ),
        # The card prints the crest 21 mm square (248 px at 300 dpi); the
        # website draws it 96 CSS px, so 128 keeps it sharp at 1.33x and the
        # 256 serves 2x screens.
        Profile(
            Kind.CREST, Family.MARK, "A crest", 5 * MB, max_pixels=4096 * 4096,
            formats=MARK_FORMATS, public=True, master_side=1024,
            frames=(("card", 256, 256), ("site", 128, 128)), typical_bytes=300 * 1024,
        ),
        Profile(
            Kind.LOGO, Family.MARK, "A logo", 5 * MB, max_pixels=4096 * 4096,
            formats=MARK_FORMATS, public=True, master_side=1024,
            frames=(("card", 256, 256), ("site", 128, 128)), typical_bytes=300 * 1024,
        ),
        # About 40 x 15 mm on a card at 300 dpi.
        Profile(
            Kind.SIGNATURE, Family.MARK, "A signature", 5 * MB, max_pixels=4096 * 4096,
            formats=MARK_FORMATS, master_side=1200,
            frames=(("card", 600, 200),), typical_bytes=150 * 1024,
        ),
        # About 25 mm across on a card at 300 dpi.
        Profile(
            Kind.STAMP, Family.MARK, "A stamp", 5 * MB, max_pixels=4096 * 4096,
            formats=MARK_FORMATS, master_side=1024,
            frames=(("card", 300, 300),), typical_bytes=200 * 1024,
        ),
        # The hero is drawn full-bleed up to 1920 px; the gallery's lightbox
        # at most 1600. 480 and 828 are the phone widths (§4.2).
        Profile(
            Kind.HERO_IMAGE, Family.SITE_PHOTO, "A photo", 15 * MB,
            master_side=2400, widths=(480, 828, 1920), typical_bytes=1500 * 1024,
        ),
        Profile(
            Kind.GALLERY_IMAGE, Family.SITE_PHOTO, "A photo", 15 * MB,
            master_side=2400, widths=(480, 828, 1600), typical_bytes=1300 * 1024,
        ),
        # Drawn about 8 rem (128 CSS px) wide beside the principal's message, so
        # 320 and 640 serve 1x to 3x screens; a 1200 px master, as for any portrait.
        Profile(
            Kind.SITE_PORTRAIT, Family.SITE_PHOTO, "A photo", 15 * MB,
            master_side=1200, widths=(320, 640), typical_bytes=400 * 1024,
        ),
        Profile(
            Kind.HERO_VIDEO, Family.VIDEO, "A video", 50 * MB,
            formats=frozenset(), widths=(480, 828, 1920), typical_bytes=3 * MB,
        ),
        Profile(
            Kind.DOCUMENT, Family.DOCUMENT, "A document", 20 * MB,
            formats=frozenset(), typical_bytes=2 * MB,
        ),
        # The blog's own rules, as `blog.images` had them: a cover is cut to
        # 1200 x 630, the shape of a shared link's card; a picture in a post is
        # at most 1600 wide. Both WebP, and half as wide for a phone. The blog
        # is served by its own views, which check the post is published.
        Profile(
            Kind.BLOG_COVER, Family.BLOG, "A picture", 10 * MB, max_pixels=40_000_000,
            formats=MARK_FORMATS, frames=(("full", 1200, 630),), typical_bytes=300 * 1024,
        ),
        Profile(
            Kind.BLOG_IMAGE, Family.BLOG, "A picture", 10 * MB, max_pixels=40_000_000,
            formats=MARK_FORMATS, widths=(1600,), typical_bytes=300 * 1024,
        ),
    )
}

#: The video rules, separate because no other kind has a duration.
VIDEO_MAX_SECONDS = 10.5
VIDEO_MAX_OUTPUT_BYTES = 3 * MB
VIDEO_MAX_HEIGHT = 720
VIDEO_MAX_FPS = 30

#: The document rules.
PDF_MAX_PAGES = 200
#: Images in a PDF above this many dots per inch are brought down to
#: `PDF_TARGET_DPI`. Measured against the page's width, so an image drawn
#: smaller than the page is reckoned *less* dense than it is, and is left
#: alone sooner, not later: the safe direction.
PDF_DOWNSAMPLE_ABOVE_DPI = 300
PDF_TARGET_DPI = 200


def profile_for(kind) -> Profile:
    try:
        return PROFILES[str(kind)]
    except KeyError:
        raise ValueError(f"No such kind of upload: {kind!r}")


__all__ = [
    "Family",
    "Kind",
    "MB",
    "OFFICE",
    "PDF_DOWNSAMPLE_ABOVE_DPI",
    "PDF_MAX_PAGES",
    "PDF_TARGET_DPI",
    "PROFILES",
    "Profile",
    "VIDEO_MAX_FPS",
    "VIDEO_MAX_HEIGHT",
    "VIDEO_MAX_OUTPUT_BYTES",
    "VIDEO_MAX_SECONDS",
    "profile_for",
]
