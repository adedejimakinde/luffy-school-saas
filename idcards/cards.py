"""What one ID card says, read from the school's own records. `docs/id-cards.md`.

Everything a card prints is assembled here, once, so the printed card and the
page its QR code opens cannot drift apart: a `Face` is the front and the back
of one child's card, and `verification()` is the page's whole answer.

## Whose children

A child is printable only if their membership is **this school's**, a student's,
and still live. The class's placements name children by bare id (the roll is in
the shared schema), so every id is checked against `Membership` here and one
that is not this school's student is simply not a card.

## The emergency line is the school's phone

Never a parent's number. The only number the card can print is
`School.phone`, which the office sets (`schools.contact`); no guardian's
contact is read anywhere in this module.

## The QR code points at a row, not at a child

`IdCard` holds a random token per child per session. The page it opens reads
the child live (name, class, photo) and says only valid or expired.
"""

import base64
import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from academics.models import ClassPlacement, Term
from accounts.models import LIVE_STATUSES, Membership, Role
from schools.hosts import current_school_host

from .models import IdCard, new_token

#: The photo frame on the card, in mm: a passport shape, as `academics.details`
#: crops it, so the picture fills it without being stretched.
PHOTO_MM = (21, 27)


class NoAddress(Exception):
    """The school has no web address, so a QR code would point nowhere."""


# -- who ------------------------------------------------------------------------


def students_of(school, class_group, term, only=None):
    """`[{id, name, admission_number}]` for the class this term, by name.

    `only` (a set of membership ids) narrows it to those children. Placements
    are read first and each id is then checked against this school's live
    student memberships, so a stray id from anywhere else is not here.
    """
    ids = ClassPlacement.objects.student_ids(class_group, term)
    if only:
        wanted = set(only)
        ids = [i for i in ids if i in wanted]
    rows = Membership.objects.filter(
        pk__in=ids, school=school, role=Role.STUDENT, status__in=LIVE_STATUSES
    ).values("pk", "display_name", "reference", "user__full_name")
    children = [
        {
            "id": row["pk"],
            "name": row["display_name"] or row["user__full_name"] or "",
            "admission_number": row["reference"] or "",
        }
        for row in rows
    ]
    children.sort(key=lambda c: (c["name"].casefold(), c["id"]))
    return children


# -- the dates --------------------------------------------------------------------


def session_ends_on(session: str) -> Optional[date]:
    """The last day of the session's last term, or None if it has no terms."""
    return Term.objects.filter(session=session).aggregate(last=Max("ends_on"))["last"]


# -- the school ---------------------------------------------------------------------


@dataclass(frozen=True)
class SchoolFace:
    name: str
    colour: str
    #: A light tint of the colour, for the photo placeholder's ground.
    tint: str
    crest: Optional[str]
    initials: str
    phone: str
    address: str


def _tint(colour: str, strength: float = 0.88) -> str:
    """`colour` mixed with white, as six hex digits. `colour` is `#RRGGBB`, checked at its source."""
    channels = [int(colour[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(c + (255 - c) * strength):02X}" for c in channels)


def school_face(school) -> SchoolFace:
    """The crest, colour and name the report card wears, plus the phone and address."""
    from results import look

    seen = look.for_card(school.name)
    colour = seen["colour"]
    return SchoolFace(
        name=school.name,
        colour=colour,
        tint=_tint(colour),
        crest=seen["crest"],
        initials=seen["initials"],
        phone=(school.phone or "").strip(),
        address=(school.address or "").strip(),
    )


# -- one card -----------------------------------------------------------------------


@dataclass(frozen=True)
class Face:
    name: str
    initials: str
    admission_number: str
    class_name: str
    session: str
    expires_on: date
    #: The passport photo as a data URL, or None for the initials placeholder.
    photo: Optional[str]
    verify_url: str
    #: The QR code as an SVG data URL.
    qr: str


def initials_of(name: str) -> str:
    """"AO" for Ada Obi, "A" for Ada, "?" for no name: the first and last words' first letters."""
    words = [w for w in re.split(r"[\s\-]+", name or "") if w[:1].isalpha()]
    if not words:
        return "?"
    letters = words[0][0] + (words[-1][0] if len(words) > 1 else "")
    return letters.upper()


def require_address() -> str:
    """This school's host, or `NoAddress`: asked before a print starts, not halfway through it."""
    host = current_school_host()
    if not host:
        raise NoAddress("This school has no web address yet, so a card's QR code would have nowhere to point.")
    return host


def verify_url_for(token: str) -> str:
    """`https://<the school's host>/verify/<token>/`. The scheme is http only under DEBUG."""
    host = require_address()
    scheme = "http" if settings.DEBUG else "https"
    return f"{scheme}://{host}/verify/{token}/"


def qr_data_uri(url: str) -> str:
    """The QR code for `url` as an SVG data URL: vector, so it prints sharp at any size.

    Error correction M, which survives a scuff or a crease on a card that lives
    in a school bag, and still keeps the code small enough to scan at 20 mm.
    """
    import segno

    code = segno.make(url, error="m", micro=False)
    return code.svg_data_uri(scale=1, border=0, dark="#000000", light="#ffffff", xmldecl=False)


def _photo_uri(membership_id: int) -> Optional[str]:
    from academics import details

    jpeg = details.photo_of(membership_id)
    return f"data:image/jpeg;base64,{base64.b64encode(jpeg).decode()}" if jpeg else None


def issue(membership_id: int, session: str, expires_on: date, by_id: Optional[int]) -> IdCard:
    """This child's card for `session`: the one that exists, or a new one.

    Reused on every reprint, so the QR code on a reprinted card is the one on
    the card already in the bag. The expiry is brought up to the session's end
    as it now stands. A **withdrawn** card is not brought back: printing again
    gives that child a new token, so the withdrawn card's code stops finding a
    card at all and the new one is valid.
    """
    try:
        with transaction.atomic():
            card, made = IdCard.objects.get_or_create(
                student_membership_id=membership_id,
                session=session,
                defaults={"expires_on": expires_on, "issued_by_id": by_id},
            )
    except IntegrityError:  # two prints at once: the other one made it
        card, made = IdCard.objects.get(student_membership_id=membership_id, session=session), False
    if made:
        return card
    fields = []
    if card.revoked_at is not None:
        card.token, card.revoked_at = new_token(), None
        fields += ["token", "revoked_at"]
    if card.expires_on != expires_on:
        card.expires_on = expires_on
        fields.append("expires_on")
    if fields:
        card.save(update_fields=fields)
    return card


def face_for(child: dict, *, class_name: str, session: str, expires_on: date, by_id: Optional[int]) -> Face:
    card = issue(child["id"], session, expires_on, by_id)
    url = verify_url_for(card.token)
    return Face(
        name=child["name"] or "A child with no name on record",
        initials=initials_of(child["name"]),
        admission_number=child["admission_number"],
        class_name=class_name,
        session=session,
        expires_on=card.expires_on,
        photo=_photo_uri(child["id"]),
        verify_url=url,
        qr=qr_data_uri(url),
    )


# -- the page the QR code opens ---------------------------------------------------------


@dataclass(frozen=True)
class Verification:
    """The whole of what the verification page may say. There is no other field."""

    valid: bool
    name: str
    #: Only when valid.
    class_name: str = ""
    photo: Optional[str] = None


def verification(token: str, school, today: Optional[date] = None) -> Optional[Verification]:
    """The answer for a card's token at this school, or None if there is no such card here.

    Read in this school's schema, so a token that was issued at another school
    is not found. A card is valid while it is not withdrawn, today is no later
    than its expiry, and the child is still on this school's roll. An expired
    card names the child and says so, and shows nothing more.
    """
    card = IdCard.objects.filter(token=token or "").first()
    if card is None:
        return None
    today = today or timezone.localdate()
    row = (
        Membership.objects.filter(pk=card.student_membership_id, school=school, role=Role.STUDENT)
        .values("display_name", "user__full_name", "status")
        .first()
    )
    if row is None:
        return None
    name = row["display_name"] or row["user__full_name"] or ""
    valid = card.revoked_at is None and today <= card.expires_on and row["status"] in LIVE_STATUSES
    if not valid:
        return Verification(valid=False, name=name)
    return Verification(
        valid=True,
        name=name,
        class_name=_class_name(card, today),
        photo=_photo_uri(card.student_membership_id),
    )


def _class_name(card: IdCard, today: date) -> str:
    """The class the child sits in now: this term's, else the latest of the card's session."""
    placement = (
        ClassPlacement.objects.filter(student_membership_id=card.student_membership_id, term__session=card.session)
        .select_related("class_group", "term")
        .order_by("-term__starts_on")
    )
    current = placement.filter(term__starts_on__lte=today).first() or placement.first()
    return current.class_group.name if current is not None else ""


__all__ = [
    "Face",
    "NoAddress",
    "SchoolFace",
    "Verification",
    "face_for",
    "initials_of",
    "issue",
    "qr_data_uri",
    "require_address",
    "school_face",
    "session_ends_on",
    "students_of",
    "verification",
    "verify_url_for",
]
