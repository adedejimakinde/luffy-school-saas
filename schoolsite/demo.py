"""A published website for one demo school, so the screens and their speed check have one.

Called by `seed_demo` (development and CI's `screens` job only) for Harbour Demo
College, through the same services a principal's clicks will go through, so the
demo's site is a real draft, a real publish and a real log line. Sunrise is left
unpublished, so the demo keeps today's page at a school root as well.
"""

from . import services
from .models import Page

HERO = {
    "heading": "Every child known, every child stretched",
    "subheading": "A day and boarding secondary school in Lagos, JSS 1 to SSS 3.",
    "buttons": [{"label": "Admissions", "link": "/admissions/"}, {"label": "Visit us", "link": "/contact/"}],
}
MOTTO = {"motto": "Ìmọ̀ ni agbára", "language": "yo", "translation": "Knowledge is power", "founded": 1987}
MESSAGE = {
    "name": "Mrs Adebola Okonkwo-Bello",
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
FOOTER = {"social": [{"network": "facebook", "url": "https://www.facebook.com/harbourdemocollege"}],
          "address_line": "Off Ozumba Mbadiwe Avenue, Victoria Island, Lagos"}


def publish_demo_site(principal, school):
    """Build and publish Harbour's website as its principal would. On the school's schema."""

    def add(key, kind, data):
        version = Page.objects.get(key=key).version
        services.add_section_as(principal, school, key, version=version, kind=kind, data=data)

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
    return services.publish_as(principal, school, note="Our new website")


__all__ = ["publish_demo_site"]
