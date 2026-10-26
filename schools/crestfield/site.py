"""Crestfield's public website, the starter theme, published as its principal would.

Through `schoolsite.services`, the same calls a principal's clicks make, so the
demo's site is a real draft, a real publish and a real line in the log. Never
indexed (`schoolsite.views._may_be_indexed`). Every figure is made up.
"""

from schoolsite import services
from schoolsite.models import Page

HERO = {
    "heading": "Learning with character in Abeokuta",
    "subheading": "A day secondary school for boys and girls, JSS 1 to SS 3. This is Classnode's demo school.",
    "buttons": [{"label": "Admissions", "link": "/admissions/"}, {"label": "Visit us", "link": "/contact/"}],
}
MOTTO = {"motto": "Imo ati iwa", "language": "yo", "translation": "Knowledge and character", "founded": 2004}
MESSAGE = {
    "name": "Dr Funmilayo Adeyemi",
    "title": "Principal",
    "message": (
        "Welcome to Crestfield College. We teach the full Nigerian curriculum from JSS 1 to SS 3, "
        "and we ask every child to work hard, speak up and look after one another.\n\n"
        "Parents see results, attendance and fees on their phones, the week they happen."
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


def publish(principal, school):
    """Fill the starter site and publish it. On the school's schema."""

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
    return services.publish_as(principal, school, note="Our website")


__all__ = ["publish"]
