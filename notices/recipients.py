"""Who may be sent a school's message, and on which channel. `docs/messaging.md` D4.

Only a guardian **live at the sending school** (their PARENT membership there is
ACTIVE), and only on a channel that is **verified, not revoked, and not a
dormant phone**. The only message an unverified channel ever gets is its own
channel check, which is `messaging.codes`' business, not this module's.

**One channel per guardian, never two** (M6, #111): the phone if it qualifies,
otherwise the email. A guardian with neither is *unreachable*, and the school is
told how many there were rather than sent to anyone else.

Asked twice: when a school asks for its notices, and again by the worker at the
moment of sending, because a guardian can be suspended or a phone go dormant
overnight between the two.
"""

from accounts import guardian_contacts
from accounts.models import (
    ContactChannel,
    GuardianAccount,
    Guardianship,
    Membership,
    MembershipStatus,
    Role,
)


def channel_for(guardian_user):
    """The one channel a school's message to this guardian may use, or None."""
    account = GuardianAccount.objects.filter(user=guardian_user).first()
    if account is None:
        return None
    usable = [
        contact
        for contact in account.live_contacts()
        if contact.is_live
        and not (contact.channel_type == ContactChannel.PHONE and guardian_contacts.is_dormant(contact))
    ]
    return usable[0] if usable else None


def is_live_at(guardian_user_id, school) -> bool:
    return Membership.objects.filter(
        user_id=guardian_user_id,
        school=school,
        role=Role.PARENT,
        status=MembershipStatus.ACTIVE,
    ).exists()


def for_child(student_membership_id, school):
    """`(reachable, unreachable)` for a child: `[(guardian user, contact)]` and a count.

    A guardian not live at `school` is neither: they are not this school's to
    reach yet (#135), and counting them would tell the office they exist.
    """
    reachable, unreachable = [], 0
    links = Guardianship.objects.filter(
        student_id=student_membership_id, student__school=school
    ).select_related("guardian")
    for link in links:
        if not is_live_at(link.guardian_id, school):
            continue
        contact = channel_for(link.guardian)
        if contact is None:
            unreachable += 1
        else:
            reachable.append((link.guardian, contact))
    return reachable, unreachable


def still_reachable(notice, school) -> bool:
    """D4 again, at the moment of sending, for the channel the notice chose.

    **The link as well as the membership.** A guardian unlinked from this child
    overnight is still live here if another child of theirs is, and the notice
    names this one.
    """
    if not is_live_at(notice.guardian_user_id, school):
        return False
    if not Guardianship.objects.filter(
        guardian_id=notice.guardian_user_id, student_id=notice.student_membership_id
    ).exists():
        return False
    from accounts.models import GuardianContact

    contact = GuardianContact.objects.filter(pk=notice.contact_id).first()
    if contact is None or not contact.is_live:
        return False
    return not (contact.channel_type == ContactChannel.PHONE and guardian_contacts.is_dormant(contact))
