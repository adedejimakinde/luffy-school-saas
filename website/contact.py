"""Classnode's contact details, read from one place: `settings`.

The support phone (`SITE_PHONE`), the LinkedIn page (`SITE_LINKEDIN_URL`), the
Google Business Profile (`SITE_GOOGLE_BUSINESS_URL`) and the `hello@` address.
The footer, the About page, the FAQ, `/llms.txt` and the structured data all
read them through `contact()`, so none of them types a number or an address.
A value that is not set is left out everywhere; a profile that is not an
`https://` address is never linked.
"""

import re

from django.conf import settings

from . import price

_NIGERIAN = re.compile(r"^\+234(\d{3})(\d{3})(\d{4})$")


def phone_display(number):
    """`+2349030269294` as `+234 903 026 9294`; any other number as it was given."""
    found = _NIGERIAN.match(re.sub(r"[\s-]", "", number))
    return "+234 " + " ".join(found.groups()) if found else number


def contact():
    """What a template or a text reads: email, phone, its `tel:` address, and the profiles."""
    phone = settings.SITE_PHONE
    https = lambda url: url if url.startswith("https://") else ""  # noqa: E731
    return {
        "email": price.CONTACT_EMAIL,
        "phone": phone_display(phone) if phone else "",
        "tel": "tel:" + re.sub(r"[^\d+]", "", phone) if phone else "",
        "linkedin": https(settings.SITE_LINKEDIN_URL),
        "google": https(settings.SITE_GOOGLE_BUSINESS_URL),
    }
