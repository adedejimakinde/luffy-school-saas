"""Crestfield's public website, in Modern Campus, published as its principal would.

Through `schoolsite.services` and `schoolsite.pictures`, the same calls a
principal's clicks make, so the demo's site is a real draft, a real publish and
a real line in the log. Never indexed (`schoolsite.views._may_be_indexed`).
Every figure is made up.

**The photos are the three on Classnode's own public site** (`static/website/photos/`:
a principal, a teacher and a bursar, all adults; none shows a child). They are
licensed stock photos, used here for the demo only (`docs/demo-school.md`). Every
create and reset loads them again through the upload service, the same call a
principal's upload makes, so each is checked, stripped of metadata and drawn
again in sizes for phones, and they survive every reset: a reset drops the
school's schema and its files, and these come back with it. They are processed
in the same process, so `manage.py crestfield create` and `reset` need no media
worker and publish a site whose pictures are ready.
"""

from pathlib import Path

from django.test.utils import override_settings

from schoolsite import pictures, services
from schoolsite.models import Page

HERO = {
    "heading": "A day secondary school in Abeokuta, JSS 1 to SS 3",
    "subheading": "Boys and girls, two arms in every year, off the Ibara road. This is Classnode's demo school.",
    "buttons": [{"label": "Admissions", "link": "/admissions/"}, {"label": "Visit us", "link": "/contact/"}],
}
MOTTO = {"motto": "Imo ati iwa", "language": "yo", "translation": "Knowledge and character", "founded": 2004}
MESSAGE = {
    "name": "Dr Funmilayo Adeyemi",
    "title": "Principal",
    "message": (
        "Welcome to Crestfield College. We teach the Nigerian curriculum from JSS 1 to SS 3, "
        "with two arms in every year.\n\n"
        "Parents see results, attendance and fees on their phones in the week they are recorded."
    ),
    "signature": "With warm regards,",
}
FACTS = {"items": [
    {"figure": "300", "label": "students, JSS 1 to SS 3"},
    {"figure": "12", "label": "classes, two arms in every year"},
    {"figure": "15", "label": "subject teachers"},
    {"figure": "2004", "label": "the year we opened"},
]}
ADMISSIONS = {
    "heading": "Admissions for the new session",
    "text": "Entrance examinations hold on Saturdays from March. Day places are open in JSS 1 and SS 1.",
    "button": "How to apply",
    "open": True,
}
ABOUT = {
    "heading": "Our story",
    "body": (
        "Crestfield College opened in 2004 with sixty students in two classrooms off the Ibara road.\n\n"
        "Today we teach science and arts streams in the senior school, with clubs for debate, "
        "coding, football and the press. Crestfield is a made-up school: Classnode uses it to show "
        "what a school's website, report cards and fees look like."
    ),
}
CONTACT = {"hours": "Monday to Friday, 7:30am to 4pm", "latitude": 7.1475, "longitude": 3.3619}
FOOTER = {"address_line": "Ibara, Abeokuta, Ogun State"}

#: Where the photos are: the ones Classnode's own homepage serves.
PHOTO_DIR = Path(__file__).resolve().parents[2] / "static" / "website" / "photos"

#: One entry per photo, in the order the slideshow shows them. `file` is the
#: largest size the public site keeps; `focal` is where every crop centres, as
#: fractions across and down, set on each face so a 4:3 phone crop, the near
#: square desk crop, the album's square tiles and the 4:5 portrait all keep the
#: head (checked in `schools/tests/test_crestfield.py`). `alt` describes it for
#: people who cannot see it; `caption` is the album's.
PHOTOS = (
    {
        "file": "principal-600.webp",
        "focal": {"x": 0.56, "y": 0.15},
        "alt": "A school principal smiling at her desk in front of a whiteboard",
        "caption": "The principal at her desk",
    },
    {
        "file": "teacher-880.webp",
        "focal": {"x": 0.55, "y": 0.1},
        "alt": "A teacher at her desk holding a phone, with a world map and a globe behind her",
        "caption": "A teacher in her classroom",
    },
    {
        "file": "bursar-880.webp",
        "focal": {"x": 0.7, "y": 0.1},
        "alt": "A school bursar in a suit checking papers at a laptop with a calculator",
        "caption": "The bursar checking the fees",
    },
)
#: The principal's message shows this one, cropped to 4:5.
PORTRAIT = PHOTOS[0]
PORTRAIT_ALT = "Dr Funmilayo Adeyemi, the principal, smiling at her desk in front of a whiteboard"
ALBUM = {"title": "Around the school", "description": "Staff at work at Crestfield College, Ibara, Abeokuta."}


def _bytes(photo):
    return (PHOTO_DIR / photo["file"]).read_bytes()


def _pictures(principal, school):
    """The slideshow's photos, the principal's portrait and an album, all through the upload service."""
    with override_settings(FILES_PROCESS_INLINE=True):
        slides = [pictures.upload_as(principal, school, "hero", [_bytes(p)], consent=True, alt=p["alt"])[0]
                  for p in PHOTOS]
        (portrait,) = pictures.upload_as(principal, school, "portrait", [_bytes(PORTRAIT)], consent=True,
                                         alt=PORTRAIT_ALT)
        album = pictures.create_album_as(principal, school, title=ALBUM["title"])
        album = pictures.save_album_as(principal, school, album.pk, version=album.version,
                                       description=ALBUM["description"])
        photos = pictures.upload_as(principal, school, "gallery", [_bytes(p) for p in PHOTOS], consent=True,
                                    album_id=album.pk)
    for picture, photo in zip(slides, PHOTOS):
        _describe(principal, school, picture, focal=photo["focal"])
    _describe(principal, school, portrait, focal=PORTRAIT["focal"])
    for picture, photo in zip(photos, PHOTOS):
        _describe(principal, school, picture, alt=photo["caption"], caption=photo["caption"], focal=photo["focal"])
    album.refresh_from_db()
    pictures.publish_album_as(principal, school, album.pk, version=album.version)
    return slides, portrait, album


def _describe(principal, school, picture, **fields):
    picture.refresh_from_db()
    pictures.save_picture_as(principal, school, picture.pk, version=picture.version, **fields)


def publish(principal, school):
    """Fill the site and publish it. On the school's schema."""

    def add(key, kind, data):
        version = Page.objects.get(key=key).version
        services.add_section_as(principal, school, key, version=version, kind=kind, data=data)

    slides, portrait, album = _pictures(principal, school)
    for key in ("about", "admissions", "gallery", "contact"):
        services.save_page_as(principal, school, key, version=Page.objects.get(key=key).version, enabled=True)
    # Modern Campus's home page: hero, facts, the principal, the gallery, the
    # admissions band and Visit us. The motto is on About.
    add("home", "hero", {**HERO, "slides": [{"picture": p.pk} for p in slides]})
    add("home", "facts", FACTS)
    add("home", "principal_message", {**MESSAGE, "portrait": portrait.pk})
    add("home", "gallery", {"album": album.pk, "count": 3})
    add("home", "admissions_cta", ADMISSIONS)
    add("home", "contact_map", CONTACT)
    add("about", "crest_motto", MOTTO)
    add("about", "text", ABOUT)
    add("about", "facts", FACTS)
    add("admissions", "admissions_cta", ADMISSIONS)
    add("contact", "contact_map", CONTACT)
    services.save_footer_as(principal, school, FOOTER, version=0)
    return services.publish_as(principal, school, note="Our website")


__all__ = ["publish"]
