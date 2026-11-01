"""Crestfield's public website, in Modern Campus, published as its principal would.

Through `schoolsite.services` and `schoolsite.pictures`, the same calls a
principal's clicks make, so the demo's site is a real draft, a real publish and
a real line in the log. Never indexed (`schoolsite.views._may_be_indexed`).
Every figure is made up.

**The photos are drawn here** (`schoolsite.demo._scene`: sky, buildings, trees,
no people, so no child is ever shown) and processed in the same process, so
`manage.py crestfield create` and `reset` need no media worker and publish a
site whose pictures are ready. Drawing them takes some seconds.
"""

from django.test.utils import override_settings

from schoolsite import pictures, services
from schoolsite.demo import _scene
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

#: The hero's slideshow: generated scenes with no people in them, each described.
SLIDES = (
    (21, "The front of Crestfield College on a bright morning"),
    (22, "The classroom blocks around the assembly ground"),
    (23, "The playing field and the trees behind it"),
)
ALBUM = {"title": "Our school grounds", "description": "A walk round Crestfield College, Ibara, Abeokuta."}
ALBUM_PHOTOS = ("The main gate", "The science laboratory block", "The library", "The sports field")


def _pictures(principal, school):
    """The slideshow's photos and an album of the grounds, drawn and processed here."""
    with override_settings(FILES_PROCESS_INLINE=True):
        slides = [pictures.upload_as(principal, school, "hero", [_scene((2400, 1600), seed)], consent=True, alt=alt)[0]
                  for seed, alt in SLIDES]
        album = pictures.create_album_as(principal, school, title=ALBUM["title"])
        album = pictures.save_album_as(principal, school, album.pk, version=album.version,
                                       description=ALBUM["description"])
        photos = pictures.upload_as(principal, school, "gallery",
                                    [_scene((2000, 1500), 30 + n) for n in range(len(ALBUM_PHOTOS))],
                                    consent=True, album_id=album.pk)
    for photo, alt in zip(photos, ALBUM_PHOTOS):
        photo.refresh_from_db()
        pictures.save_picture_as(principal, school, photo.pk, version=photo.version, alt=alt)
    album.refresh_from_db()
    pictures.publish_album_as(principal, school, album.pk, version=album.version)
    return slides, album


def publish(principal, school):
    """Fill the site and publish it. On the school's schema."""

    def add(key, kind, data):
        version = Page.objects.get(key=key).version
        services.add_section_as(principal, school, key, version=version, kind=kind, data=data)

    slides, album = _pictures(principal, school)
    for key in ("about", "admissions", "gallery", "contact"):
        services.save_page_as(principal, school, key, version=Page.objects.get(key=key).version, enabled=True)
    # Modern Campus's home page: hero, facts, the principal, the gallery, the
    # admissions band and Visit us. The motto is on About.
    add("home", "hero", {**HERO, "slides": [{"picture": p.pk} for p in slides]})
    add("home", "facts", FACTS)
    add("home", "principal_message", MESSAGE)
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
