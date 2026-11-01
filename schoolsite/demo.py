"""A published website for one demo school, so the screens and their speed check have one.

Called by `seed_demo` (development and CI's `screens` job only) for Harbour Demo
College, through the same services a principal's clicks will go through, so the
demo's site is a real draft, a real publish and a real log line. Sunrise is left
unpublished, so the demo keeps today's page at a school root as well.

`publish_demo_pictures` then gives it pictures (PR 5): a hero photo, the
principal's portrait and a published album, through the upload service, so the
screens job's Slow 4G check measures a page whose largest paint is a photograph.
The pictures are drawn here, so nothing binary is committed; they are busier
than most photographs (fine detail and grain), so they cost more bytes, not fewer.
"""

import io
import random

from . import pictures, services
from .models import Page, PageKey, SiteSettings

HERO = {
    "heading": "Every child known, every child stretched",
    "subheading": "A day and boarding secondary school in Lagos, JSS 1 to SSS 3.",
    "buttons": [{"label": "Admissions", "link": "/admissions/"}, {"label": "Visit us", "link": "/contact/"}],
}
MOTTO = {"motto": "Ìmọ̀ ni agbára", "language": "yo", "translation": "Knowledge is power", "founded": 1987}
MESSAGE = {
    "name": "Mrs Ọláòlúwa Adéṣínà",
    "title": "Principal",
    "message": (
        "Welcome to Harbour Demo College. For nearly forty years we have taught young people to "
        "think clearly, work hard and look after one another.\n\n"
        "Our students sit WAEC, NECO and the BECE with us, and they leave ready for university and "
        "for life. We would be glad to show you round."
    ),
    "signature": "With warm regards,",
}
FACTS = {"items": [
    {"figure": "98%", "label": "WAEC credit passes in five subjects or more", "source": "WAEC, May/June 2025"},
    {"figure": "1,240", "label": "students, JSS 1 to SSS 3"},
    {"figure": "₦125,000", "label": "day fees a term, with books and lunch"},
    {"figure": "1987", "label": "the year we opened"},
]}
ADMISSIONS = {
    "heading": "Admissions for the new session",
    "text": "Entrance examinations hold on Saturdays in March and April. Day and boarding places are open.",
    "button": "How to apply",
    "session": "2027/2028",
    "open": True,
    "closes": "2027-04-30",
}
ABOUT = {
    "heading": "Our story",
    "body": (
        "Harbour Demo College opened in 1987 with forty students and four teachers.\n\n"
        "Today we teach the full Nigerian curriculum from JSS 1 to SSS 3, with science, arts and "
        "commercial streams, a boarding house for boys and girls, and clubs from debate to robotics."
    ),
}
CONTACT = {"whatsapp": "0803 000 0000", "hours": "Monday to Friday, 7:30am to 4pm", "latitude": 6.4541,
           "longitude": 3.3947}
#: Two pages of Harbour's own (§2.1.1): enough, with the four fixed ones on, to
#: put a "More" in the menu on a phone (`render.MENU_ON_A_PHONE`).
BOARDING = {
    "title": "Boarding",
    "hero": {"heading": "Boarding at Harbour",
             "subheading": "Two houses on the school grounds, for students from JSS 1.",
             "buttons": [{"label": "Apply for a place", "link": "/admissions/"}]},
    "text": {"heading": "Life in the houses",
             "body": ("Each house has a housemaster or housemistress who lives on site, a matron, and "
                      "supervised prep every evening.\n\nBoarders go home for the mid-term break and at "
                      "the end of each term.")},
    "facts": {"items": [{"figure": "2", "label": "boarding houses, one for boys and one for girls"},
                        {"figure": "180", "label": "boarders"}]},
}
SPORTS = {
    "title": "Sports and clubs",
    "text": {"heading": "After the last bell",
             "body": "Football, athletics, table tennis, debate, drama, the press club and robotics."},
}
FOOTER = {"social": [{"network": "facebook", "url": "https://www.facebook.com/harbourdemocollege"}],
          "address_line": "Off Ozumba Mbadiwe Avenue, Victoria Island, Lagos"}


def publish_demo_site(principal, school):
    """Build and publish Harbour's website as its principal would. On the school's schema."""

    def add(ref, kind, data):
        version = (Page.objects.get(key=ref) if ref in PageKey.values else Page.objects.get(slug=ref)).version
        services.add_section_as(principal, school, ref, version=version, kind=kind, data=data)

    for key in ("about", "admissions", "contact"):
        services.save_page_as(principal, school, key, version=Page.objects.get(key=key).version, enabled=True)
    add("home", "hero", HERO)
    add("home", "crest_motto", MOTTO)
    add("home", "facts", FACTS)
    add("home", "principal_message", MESSAGE)
    add("home", "admissions_cta", ADMISSIONS)
    add("about", "text", ABOUT)
    add("about", "facts", FACTS)
    add("admissions", "admissions_cta", ADMISSIONS)
    add("contact", "contact_map", CONTACT)
    services.save_footer_as(principal, school, FOOTER, version=0)
    for page in (BOARDING, SPORTS):
        version = SiteSettings.objects.get(pk=1).version
        slug = services.create_page_as(principal, school, version=version, title=page["title"]).slug
        for kind in ("hero", "text", "facts"):
            if kind in page:
                add(slug, kind, page[kind])
        services.save_page_as(principal, school, slug, version=Page.objects.get(slug=slug).version, enabled=True)
    # The boarding page beside the About page in the menu, not last.
    order = ["home", "about", "boarding", "admissions", "sports-and-clubs", "news", "gallery", "contact"]
    services.order_menu_as(principal, school, order, version=SiteSettings.objects.get(pk=1).version)
    return services.publish_as(principal, school, note="Our new website")


def _scene(size, seed, *, portrait=False):
    """A photograph-like JPEG: sky, ground, buildings or a figure, trees, and grain."""
    from PIL import Image, ImageDraw, ImageFilter

    rng = random.Random(seed)
    w, h = size
    image = Image.new("RGB", size)
    draw = ImageDraw.Draw(image)
    horizon = int(h * (0.62 if portrait else 0.55))
    for y in range(h):
        if y < horizon:
            t = y / horizon
            colour = (int(70 + 90 * t), int(130 + 70 * t), int(200 + 40 * t))
        else:
            t = (y - horizon) / max(1, h - horizon)
            colour = (int(120 - 40 * t), int(105 - 30 * t), int(70 - 20 * t))
        draw.line([(0, y), (w, y)], fill=colour)
    if portrait:
        draw.ellipse([w * 0.3, h * 0.18, w * 0.7, h * 0.52], fill=(92, 58, 38))
        draw.rectangle([w * 0.18, h * 0.5, w * 0.82, h], fill=(24, 60, 120))
    else:
        for _ in range(4):
            left = rng.randrange(0, w - w // 4)
            top = rng.randrange(int(h * 0.25), horizon - h // 10)
            right, bottom = left + rng.randrange(w // 6, w // 3), horizon + rng.randrange(0, h // 12)
            draw.rectangle([left, top, right, bottom], fill=(rng.randrange(170, 235), rng.randrange(150, 210), 140))
            for x in range(left + 12, right - 24, 38):
                for y in range(top + 14, bottom - 30, 46):
                    draw.rectangle([x, y, x + 20, y + 26], fill=(40, 60, 80))
        for _ in range(60):
            x, y = rng.randrange(w), rng.randrange(horizon, h)
            r = rng.randrange(6, 26)
            draw.ellipse([x, y - 3 * r, x + r, y], fill=(rng.randrange(20, 90), rng.randrange(40, 120), rng.randrange(60, 180)))
    for _ in range(14):
        x, r = rng.randrange(w), rng.randrange(h // 14, h // 6)
        draw.ellipse([x - r, horizon - 2 * r, x + r, horizon], fill=(30, rng.randrange(90, 130), 40))
    image = image.filter(ImageFilter.GaussianBlur(1.2))
    grain = Image.effect_noise(size, 28).convert("RGB")
    image = Image.blend(image, grain, 0.08)
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=92)
    return out.getvalue()


ALBUM = {"title": "Inter-house sports, 2026", "description": "Blue House took the cup on a hot February afternoon."}
ALBUM_CAPTIONS = ("The 4 x 100 m relay", "Long jump", "Blue House with the cup", "March past", "The tug of war",
                  "Prize giving")


def publish_demo_pictures(principal, school):
    """Give Harbour's published site a hero photo, a portrait and an album, as its principal would.

    Drawn in the request (the screens job has no media worker), and published.
    """
    from django.test.utils import override_settings

    with override_settings(FILES_PROCESS_INLINE=True):
        (hero,) = pictures.upload_as(principal, school, "hero", [_scene((2400, 1600), 1)], consent=True,
                                     alt="The main block at Harbour Demo College, with trees along the yard")
        (portrait,) = pictures.upload_as(principal, school, "portrait", [_scene((960, 1200), 2, portrait=True)],
                                         consent=True, alt="Mrs Ọláòlúwa Adéṣínà, the principal")
        album = pictures.create_album_as(principal, school, title=ALBUM["title"])
        album = pictures.save_album_as(principal, school, album.pk, version=album.version,
                                       description=ALBUM["description"])
        photos = []
        for start in (0, 3):
            photos += pictures.upload_as(principal, school, "gallery",
                                         [_scene((2000, 1500), 10 + n) for n in range(start, start + 3)],
                                         consent=True, album_id=album.pk)
    for photo, caption in zip(photos, ALBUM_CAPTIONS):
        photo.refresh_from_db()
        pictures.save_picture_as(principal, school, photo.pk, version=photo.version, alt=caption, caption=caption)
    album.refresh_from_db()
    pictures.publish_album_as(principal, school, album.pk, version=album.version)

    home = Page.objects.get(key=PageKey.HOME)
    for section in home.sections.all():
        if section.kind == "hero":
            services.save_section_as(principal, school, section.pk, version=section.version,
                                     data={**section.data, "image": hero.pk})
        elif section.kind == "principal_message":
            services.save_section_as(principal, school, section.pk, version=section.version,
                                     data={**section.data, "portrait": portrait.pk})
    services.add_section_as(principal, school, "home", version=Page.objects.get(key=PageKey.HOME).version,
                            kind="gallery", data={"album": album.pk, "count": 3})
    gallery = Page.objects.get(key=PageKey.GALLERY)
    services.save_page_as(principal, school, "gallery", version=gallery.version, enabled=True)
    return services.publish_as(principal, school, note="Photos for the website")


__all__ = ["publish_demo_pictures", "publish_demo_site"]
