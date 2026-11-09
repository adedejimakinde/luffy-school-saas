"""The price and the contact email: one setting, read by every public page.

`settings.PRICE_PER_STUDENT_NAIRA` is the only place the number is written. The
homepage, the pricing page, the FAQ, the terms, `/llms.txt`, every page's
description and the structured data all read it through here, on every request.
"""

from django.conf import settings

CONTACT_EMAIL = "hello@classnode.co"


def figure():
    """"₦1,500": the naira sign and the comma, never "₦1500"."""
    return f"₦{settings.PRICE_PER_STUDENT_NAIRA:,}"


def sentence():
    return f"The first term is free, then {figure()} per student, per term. No setup fee."


def terms_sentence():
    return (
        f"A school's first term is free. After that, schools pay {figure()} per student, per term. "
        "There is no setup fee."
    )


def context():
    """What a template reads: `{{ price.figure }}`, `{{ price.sentence }}`."""
    return {
        "figure": figure(),
        "amount": settings.PRICE_PER_STUDENT_NAIRA,
        "sentence": sentence(),
        "terms": terms_sentence(),
    }
