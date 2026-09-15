"""One fixture, shared: a guardian whose link is actually live.

`services.link_guardian()` grants a PARENT membership INVITED until the
guardian holds a verified contact channel — D9's "the guardian link does not go
live until it comes back", gated in code as of PR C. Every test that signs a
parent in, or asserts they can reach a school, therefore needs a channel behind
them; without one they get a relationship and no access, and the failure looks
nothing like its cause.

**That failure is worth describing, because it is what this module exists to
stop being rediscovered.** `SchoolAccessMiddleware` refuses the request, so the
symptom is a 403 from the middleware — which a test asserting `assertNotEqual(
403)` about *withholding* reports as "a balance withheld a card that nobody
decided to withhold". The status is right, the accusation is at the wrong
subsystem, and the test that says so is in another app.

## Why this goes through the real services

It would be shorter to write the rows directly, or shorter still to set
`status=ACTIVE` on the membership and skip the channel. Both would make these
tests stop asking the question the gate exists to answer: a fixture that grants
access by fiat cannot notice when the gate stops granting it. So this mints a
real code, answers it, and lets `confirm_verification()` promote the membership
the way production will — which also means every test using it exercises
`activate_guardian_links()` in passing.
"""

from accounts import guardian_contacts
from accounts.models import ContactChannel, GuardianContact

#: An arbitrary Nigerian mobile, normalized to E.164 on the way into the column.
#: Callers sharing one handset between two guardians pass the same value twice
#: on purpose — `GuardianContact.value` carries no unique constraint precisely
#: so a household with one phone can have two guardians behind it.
DEFAULT_CHANNEL_VALUE = "08030000001"


def give_verified_channel(
    user,
    value=DEFAULT_CHANNEL_VALUE,
    *,
    channel_type=ContactChannel.PHONE,
    recorded_by=None,
):
    """Record a channel for `user` and answer the code, returning the contact.

    Any PARENT membership they are already waiting on goes ACTIVE, because that
    is what `confirm_verification()` does. So this may be called before or after
    `link_guardian()` and the guardian ends up live either way — which matters,
    since D10's order puts the channel last and most fixtures put it first.

    `recorded_by` is the admin who typed it. It defaults to the guardian
    themselves, which is not a state production produces — `record_contact_as()`
    requires an actor with authority — and is harmless here because `created_by`
    is an audit column that no rule reads. A test asserting anything *about*
    that column should pass a real admin and use the service.
    """
    account = guardian_contacts.guardian_account_for(user)
    contact = GuardianContact(
        guardian=account,
        channel_type=channel_type,
        value=value,
        created_by=recorded_by or user,
    )
    contact.full_clean(validate_constraints=False)
    contact.save()

    _, raw_code = guardian_contacts.request_verification(contact)
    assert guardian_contacts.confirm_verification(contact, raw_code), (
        "the fixture's own code did not verify the channel"
    )
    contact.refresh_from_db()
    return contact
