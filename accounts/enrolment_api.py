"""HTTP for admitting a child and putting them in a class.

Two acts, and they are deliberately not one route.

**Admission writes shared tables.** A `User` is the platform's, not a school's —
a child transferring next year keeps the same login — and a STUDENT
`Membership` is the row that ties them to this school. Both live in the public
schema.

**Placement writes a tenant table.** `ClassPlacement` is per schema and per
term, and a child enrolled in August who joins a class in September is the
ordinary case rather than an unfinished one.

## Two authorities, and they are not the same set

`enroll_student_as()` goes through `_require_grant_authority()` —
`MEMBERSHIP_GRANTING_ROLES`, which is **ADMIN alone**. A principal is
deliberately absent: handing out memberships is the office's act, and
`accounts/models.py` says to add principals there if that ever changes rather
than widening it here.

`place_student_as()` goes through `PLACEMENT_ROLES`, which is **principal and
admin**. So a principal may move a child between classes and may not admit one,
and this module must not flatten that into a single "is the office" check. Each
route asks the question its own service asks.

## The handle is the school's

`User.username` is globally unique and school-issued — "STM/2026/0042" is the
model's own example. This does not generate one: a scheme the school did not
choose is one it has to live with on every register and every card.

A handle already in use is refused **without saying where**. It is unique
across the platform, so "taken" would otherwise tell a St Mary's administrator
that somebody at Grace holds it — and which children exist at another school is
not theirs to learn from a form.
"""

from typing import List, Optional

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from academics import services as academics
from academics.models import ClassGroup, ClassPlacement, Term
from accounts import bulk, guardian_contacts
from accounts import services as accounts_services
from accounts.models import (
    LIVE_STATUSES,
    ContactChannel,
    GuardianAccount,
    GuardianContact,
    Guardianship,
    Membership,
    Relationship,
    Role,
)
from accounts.session import session_auth
from messaging import codes as message_codes

router = Router(auth=session_auth)


class MessageOut(Schema):
    detail: str


class EnrolledChildOut(Schema):
    """One child on the roll, and where they sit this term.

    `class_group_id` is null for a child admitted and not yet placed — a real
    state, and a different one from "placed in a group that no longer exists".
    """

    student_membership_id: int
    student: str
    username: str
    reference: str
    class_group_id: Optional[int] = None
    class_group: Optional[str] = None


class ClassChoiceOut(Schema):
    class_group_id: int
    name: str


class RollOut(Schema):
    """The roll, and the classes a child can be put in.

    `classes` is here rather than fetched from `/api/academics/setup/` because
    this screen already reads `ClassGroup` for the names on each row — serving
    it costs nothing more, and a second round trip to another router would
    couple this page to a route with its own, *narrower* authority.

    Only groups still taught are offered. An inactive group is kept because old
    placements name it, and putting a new child into one would be recording
    something the school has said it no longer does.
    """

    term_id: Optional[int]
    term: Optional[str]
    children: List[EnrolledChildOut]
    classes: List[ClassChoiceOut]
    may_admit: bool
    may_place: bool


class AdmitIn(Schema):
    full_name: str
    username: str
    reference: str = ""
    #: Optional: place them as they are admitted. Absent means admitted and
    #: unplaced, which is what August looks like at most schools.
    class_group_id: Optional[int] = None


class PlaceIn(Schema):
    class_group_id: int


class BulkIn(Schema):
    """The file's text, not a multipart upload.

    The page reads the file with `FileReader` and posts its contents, which
    keeps every request on this platform JSON and behind ninja's own CSRF
    check. A multipart route would be the one exception to that, for no gain
    on a file an office pastes or picks.
    """

    csv: str


def _school_of(request):
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("No roll on this host.")
    return school


#: One sentence for each refusal, so "may you?" and "does that child exist?"
#: cannot be told apart by their wording.
_MAY_NOT_ADMIT = (
    "Children are admitted by an administrator of the school."
)
_MAY_NOT_PLACE = (
    "Children are put in classes by a principal or an administrator of the school."
)
_MAY_NOT_LINK = "Guardians are linked by an administrator of the school."
_NO_SUCH_CHILD = "There is no such child on this school's roll."
_NO_SUCH_LINK = "That guardian is not linked to this child."


def _first(exc) -> str:
    """One sentence out of a `ValidationError`, which carries a list.

    The first is the one about the field the caller got wrong; joining them all
    would put a paragraph in a toast. `academics/api.py._first_message()` makes
    the same choice for the same reason.
    """
    messages = getattr(exc, "messages", None) or [str(exc)]
    return messages[0]


def _current_term():
    return Term.objects.filter(is_current=True).first()


def _refuse_outsiders(request, school):
    """Authority **before either read** — the oracle rule this codebase keeps.

    Admitted on the *wider* of the two sets, because looking at the roll is
    neither admitting nor placing. What each write needs is asked again by its
    own route, against its own service's set, so a principal sees the roll and
    is refused an admission.
    """
    if not (
        accounts_services.can_grant_memberships(request.user, school)
        or academics.can_place_students(request.user, school)
    ):
        return 403, MessageOut(detail=_MAY_NOT_PLACE)
    return None


@router.get("/roll/", response={200: RollOut, 403: MessageOut})
def roll(request):
    """Every child enrolled here, and where they sit this term.

    Three queries, and **not one per child**: the memberships, this term's
    placements, and the groups those name. A screen that read a child's
    placement per row would be a query per row on the one page an office
    refreshes while admitting a class.

    Children with no placement are listed too. A child admitted in August and
    placed in September is the ordinary case, and a roll that hid them would
    make the office think the admission had failed.
    """
    school = _school_of(request)
    refused = _refuse_outsiders(request, school)
    if refused is not None:
        return refused

    term = _current_term()
    memberships = list(
        Membership.objects.filter(school=school, role=Role.STUDENT)
        .live()
        .select_related("user")
    )
    groups = list(ClassGroup.objects.all())
    group_names = {g.pk: g.name for g in groups}
    placements = {}
    if term is not None:
        placements = dict(
            ClassPlacement.objects.filter(term=term).values_list(
                "student_membership_id", "class_group_id"
            )
        )

    children = [
        EnrolledChildOut(
            student_membership_id=m.pk,
            student=m.display_name or m.user.full_name or m.user.username,
            username=m.user.username,
            reference=m.reference,
            class_group_id=placements.get(m.pk),
            class_group=group_names.get(placements.get(m.pk)),
        )
        for m in sorted(
            memberships,
            key=lambda m: (m.display_name or m.user.full_name or m.user.username),
        )
    ]
    return RollOut(
        term_id=term.pk if term else None,
        term=str(term) if term else None,
        children=children,
        classes=[
            ClassChoiceOut(class_group_id=g.pk, name=g.name)
            for g in groups
            if g.is_active
        ],
        may_admit=accounts_services.can_grant_memberships(request.user, school),
        may_place=academics.can_place_students(request.user, school),
    )


@router.post("/roll/", response={201: EnrolledChildOut, 403: MessageOut, 409: MessageOut, 422: MessageOut})
def admit(request, payload: AdmitIn):
    """Create a child's login and enrol them. Optionally place them too.

    **One transaction over all of it.** Admission is two writes to two shared
    tables, and placement is a third to a tenant one; a failure part-way
    through would leave an account belonging to no school, or a child enrolled
    into a class the request had already been refused. Either the child is
    admitted and placed as asked, or nothing happened.

    **409 for a handle already in use, and it does not say where.** The
    username is unique across the platform, so naming the school that holds it
    would tell an administrator at St Mary's which children exist at Grace.
    """
    school = _school_of(request)
    if not accounts_services.can_grant_memberships(request.user, school):
        return 403, MessageOut(detail=_MAY_NOT_ADMIT)

    term = _current_term()
    if payload.class_group_id is not None:
        if term is None:
            return 422, MessageOut(
                detail="No term is open, so there is no class to place a child in."
            )
        if not academics.can_place_students(request.user, school):
            return 403, MessageOut(detail=_MAY_NOT_PLACE)

    try:
        with transaction.atomic():
            user, membership = accounts_services.admit_student_as(
                request.user,
                school,
                payload.full_name,
                payload.username,
                reference=payload.reference,
            )
            group = None
            if payload.class_group_id is not None:
                group = get_object_or_404(ClassGroup, pk=payload.class_group_id)
                academics.place_student_as(
                    request.user, group, term, membership, by=request.user
                )
    except ValidationError as exc:
        # `User.save()` checks the handle and raises this; the unique index
        # below is the backstop for the race two admissions can lose. Both are
        # a 409, and **the message is the model's own** — "already in use by
        # another account" names no school, which is the property that matters
        # here and one a sentence written at this layer could quietly lose.
        return 409, MessageOut(detail=_first(exc))
    except IntegrityError:
        # The same refusal arriving from Postgres, for the pair of admissions
        # that both passed the check above. Deliberately not a
        # lookup-then-create, which is a race with a check in front of it.
        return 409, MessageOut(
            detail=f"The handle {payload.username!r} is already in use."
        )
    except accounts_services.NotPermitted:
        return 403, MessageOut(detail=_MAY_NOT_ADMIT)
    except academics.NotAllowedToPlace:
        return 403, MessageOut(detail=_MAY_NOT_PLACE)
    except academics.AcademicsError as exc:
        return 422, MessageOut(detail=str(exc))
    except accounts_services.MembershipError as exc:
        return 422, MessageOut(detail=str(exc))

    return 201, EnrolledChildOut(
        student_membership_id=membership.pk,
        student=membership.display_name or user.full_name or user.username,
        username=user.username,
        reference=membership.reference,
        class_group_id=group.pk if group else None,
        class_group=group.name if group else None,
    )


@router.put(
    "/roll/{int:student_membership_id}/class/",
    response={200: EnrolledChildOut, 403: MessageOut, 422: MessageOut},
)
def place(request, student_membership_id: int, payload: PlaceIn):
    """Put a child in a class, or move them to another one.

    **Placing and moving are one route and two services.** `place_student()`
    refuses a child already placed this term — including into the very group
    they are in, because two administrators both believing they made the
    placement is a real disagreement — and `move_student()` is the one that
    expects an existing row. Which is which is a fact about the child, not
    about the caller's intent, so this asks `placement_of()` rather than making
    the screen declare it.
    """
    school = _school_of(request)
    if not academics.can_place_students(request.user, school):
        return 403, MessageOut(detail=_MAY_NOT_PLACE)

    term = _current_term()
    if term is None:
        return 422, MessageOut(detail="No term is open, so there is no class to join.")

    membership = get_object_or_404(
        Membership, pk=student_membership_id, school=school, role=Role.STUDENT
    )
    group = get_object_or_404(ClassGroup, pk=payload.class_group_id)

    try:
        if academics.placement_of(membership.pk, term) is None:
            academics.place_student_as(request.user, group, term, membership, by=request.user)
        else:
            academics.move_student_as(request.user, group, term, membership, by=request.user)
    except academics.NotAllowedToPlace:
        return 403, MessageOut(detail=_MAY_NOT_PLACE)
    except academics.AcademicsError as exc:
        return 422, MessageOut(detail=str(exc))

    return 200, EnrolledChildOut(
        student_membership_id=membership.pk,
        student=membership.display_name or membership.user.full_name or membership.user.username,
        username=membership.user.username,
        reference=membership.reference,
        class_group_id=group.pk,
        class_group=group.name,
    )


# ---------------------------------------------------------------------------
# Admitting a class from a spreadsheet.
# ---------------------------------------------------------------------------


class RowProblemOut(Schema):
    """One thing wrong with one row, and where to find it.

    `line` is the line in **their file** — the header is 1, so the first child
    is 2. "Row 14" is something an office can find; "the third error" is not.
    """

    line: int
    column: str
    detail: str


class GuardianLinkOut(Schema):
    """One child linked to one guardian, by the line that asked for it.

    `guardian_contact` is the contact **as it was read** — `+2348031234567`
    for a row that said `0803 123 4567` — so an office can see a misread
    number rather than discover it when the code never arrives.

    `status` is `"pending verification"` for every new link, and `"live"` only
    for a guardian this school has already confirmed (#135): a guardian
    verified at another school waits here like anybody new, so the report
    says nothing about who is verified elsewhere.
    """

    line: int
    guardian_contact: str
    status: str


class BulkReportOut(Schema):
    """What a file did, or what is wrong with it.

    `admitted` is 0 whenever `problems` is non-empty, and that is the whole
    contract: **a file half-applies or it does not apply.** An office cannot
    tell which children landed without reading the roll against the
    spreadsheet by hand.

    `generated` is `line -> handle` for every child whose school left the
    column blank. Reported because a child cannot be handed a login nobody
    wrote down.

    `guardian_links` is every link made, by line, with its status. D9:
    a link is INVITED until the guardian answers this school, so an import that
    said nothing would leave the office believing it had finished.
    `guardians_pending` counts the ones that are not live.
    """

    admitted: int
    problems: List[RowProblemOut]
    generated: dict
    guardian_links: List[GuardianLinkOut]
    guardians_pending: int


@router.post(
    "/roll/import/",
    response={200: BulkReportOut, 403: MessageOut, 422: MessageOut},
)
def bulk_admit(request, payload: BulkIn):
    """Admit a whole class from a CSV, or none of it.

    A 200 carrying `problems` is the ordinary refusal — the file was read, every
    row was judged, and nothing was written. It is not a 422, because the
    request was well formed and the *file* is what disagrees; the body is the
    answer rather than the error.

    A 422 is for a file that cannot be read as a file at all: no header, a
    missing required column, or no current term to place anybody in.
    """
    school = _school_of(request)
    if not accounts_services.can_grant_memberships(request.user, school):
        return 403, MessageOut(detail=_MAY_NOT_ADMIT)
    if not academics.can_place_students(request.user, school):
        # A bulk import places every child, so it needs both authorities —
        # and an administrator holds both.
        return 403, MessageOut(detail=_MAY_NOT_PLACE)

    try:
        report = bulk.admit(request.user, school, _current_term(), payload.csv)
    except bulk.BulkError as exc:
        return 422, MessageOut(detail=str(exc))
    except ValidationError as exc:
        return 422, MessageOut(detail=_first(exc))
    except guardian_contacts.GuardianContactError as exc:
        # A contact two accounts answer to, found at write time. Nothing was
        # written: `admit()` holds the whole file in one transaction.
        return 422, MessageOut(detail=str(exc))

    return 200, BulkReportOut(
        admitted=len(report.planned) if report.ok else 0,
        problems=[
            RowProblemOut(line=p.line, column=p.column, detail=p.detail)
            for p in report.problems
        ],
        generated={str(line): handle for line, handle in report.generated.items()},
        guardian_links=[
            GuardianLinkOut(
                line=link.line, guardian_contact=link.guardian_contact, status=link.status
            )
            for link in report.guardian_links
        ],
        guardians_pending=sum(
            1 for link in report.guardian_links if link.status == guardian_contacts.PENDING
        ),
    )


# ---------------------------------------------------------------------------
# A child's guardians: who they are here, and whether they can see the child.
# ---------------------------------------------------------------------------


class GuardianOut(Schema):
    """One guardian of one child, **as this school is entitled to see them**.

    `name` and `contact` are what this school typed when it made the link
    (`Guardianship.entered_name`). A contact can resolve to a guardian who is
    somebody else's parent, and until they have answered *this* school their
    stored name and channel are not this school's to read — the same rule
    `InvitationOut` keeps. Once they are live here, a link with nothing typed
    on it falls back to the name they hold.

    `status` is the link as the office reads it: `pending verification` until
    the guardian answers this school, then `live` — or `suspended`, which is a
    school's decision that no code reverses.

    `channel` is said only once they are live here: `verified`, or `dormant`
    after D9's 180 quiet days. Before that it is `not verified here` whatever
    their channel is elsewhere, because "verified" on a screen would tell an
    office that a number belongs to a parent at another school.
    """

    link_id: int
    name: str
    contact: str
    relationship: str
    status: str
    channel: str
    #: The channels this school may see, each with what it can do about them.
    #: Before the guardian is live here that is only what this school typed
    #: (#135); once live, each channel they hold, an email and a phone at most
    #: (#111).
    channels: List["ChannelOut"] = []


class ChannelOut(Schema):
    """One channel on the panel, and whether this school can send it a code.

    `state` is in the office's words and follows `GuardianOut.channel`'s rule:
    `not verified here` until the guardian is live here, whatever the channel is
    elsewhere. `last_message` is what happened to the last code **this school**
    sent it, from `messaging.codes.last_message()`, or empty.
    """

    channel_type: str
    value: str
    state: str
    last_message: str = ""
    may_send: bool = False


GuardianOut.model_rebuild()


class GuardiansOut(Schema):
    student_membership_id: int
    student: str
    guardians: List[GuardianOut]
    #: ADMIN alone links and unlinks; a principal reads the panel.
    may_link: bool
    relationships: List[str]


class LinkIn(Schema):
    full_name: str
    contact: str
    relationship: str = Relationship.GUARDIAN


class SendCodeIn(Schema):
    #: Which of a live guardian's channels. Ignored before they are live here,
    #: when the only channel this school may address is the one it typed.
    channel_type: Optional[str] = None


class ContactIn(Schema):
    contact: str


def _child_here(school, student_membership_id):
    """A child on this school's roll, or None.

    **`school=` is the whole of the isolation here.** `Membership` is a shared
    table, so no tenant schema stands behind this filter: without it, an
    administrator at Grace could address a St Mary's child by id and read — or
    link — their guardians.
    """
    return (
        Membership.objects.select_related("user")
        .filter(
            pk=student_membership_id,
            school=school,
            role=Role.STUDENT,
            status__in=LIVE_STATUSES,
        )
        .first()
    )


def _typed_contact(link):
    """The guardian's unrevoked channel whose value is what this school typed, or None."""
    if not link.entered_contact:
        return None
    return (
        GuardianContact.objects.filter(
            guardian__user=link.guardian,
            value=link.entered_contact,
            revoked_at__isnull=True,
        )
        .order_by("created_at", "id")
        .first()
    )


def _channels_out(link, school, live):
    """`ChannelOut` rows for this link, as this school may see them."""
    if not live:
        typed = _typed_contact(link)
        if typed is None:
            return []
        return [
            ChannelOut(
                channel_type=typed.channel_type,
                value=link.entered_contact,
                state="not verified here",
                last_message=message_codes.last_message(typed, school.pk),
                may_send=True,
            )
        ]
    account = GuardianAccount.objects.filter(user=link.guardian).first()
    rows = []
    for contact in account.live_contacts() if account is not None else []:
        dormant = contact.verified_at is not None and guardian_contacts.is_dormant(contact)
        if dormant:
            state = "dormant"
        elif contact.verified_at is not None:
            state = "verified"
        else:
            state = "not verified"
        rows.append(
            ChannelOut(
                channel_type=contact.channel_type,
                value=contact.value,
                state=state,
                last_message=message_codes.last_message(contact, school.pk),
                # A live, current channel needs nothing from the school: the
                # guardian asks for their own sign-in code.
                may_send=state != "verified",
            )
        )
    return rows


def _guardian_out(link, school) -> GuardianOut:
    status = guardian_contacts.link_status_at(link.guardian, school)
    live = status == guardian_contacts.LIVE
    channels = _channels_out(link, school, live)
    if not live:
        name, contact = link.entered_name, link.entered_contact
        channel = "not verified here" if contact else "no contact recorded here"
    else:
        name = link.entered_name or link.guardian.full_name
        # A read, not `guardian_account_for()`: that one creates the account,
        # and a GET that writes a row is a GET nobody can reason about.
        first = channels[0] if channels else None
        contact = link.entered_contact or (first.value if first else "")
        channel = first.state if first else "no contact recorded"
    return GuardianOut(
        link_id=link.pk,
        name=name,
        contact=contact,
        relationship=link.relationship,
        status=status,
        channel=channel,
        channels=channels,
    )


def _guardians_of(child, school, may_link) -> GuardiansOut:
    links = Guardianship.objects.filter(student=child).select_related("guardian").order_by("pk")
    return GuardiansOut(
        student_membership_id=child.pk,
        student=child.display_name or child.user.full_name or child.user.username,
        guardians=[_guardian_out(link, school) for link in links],
        may_link=may_link,
        relationships=list(Relationship.values),
    )


@router.get(
    "/roll/{int:student_membership_id}/guardians/",
    response={200: GuardiansOut, 403: MessageOut, 404: MessageOut},
)
def guardians(request, student_membership_id: int):
    """A child's guardians. Principal or administrator, asked **before** the
    child is looked up, so "may you?" and "is there such a child?" cannot be
    told apart by somebody with no part in the roll."""
    school = _school_of(request)
    refused = _refuse_outsiders(request, school)
    if refused is not None:
        return refused
    child = _child_here(school, student_membership_id)
    if child is None:
        return 404, MessageOut(detail=_NO_SUCH_CHILD)
    return 200, _guardians_of(
        child, school, accounts_services.can_grant_memberships(request.user, school)
    )


@router.post(
    "/roll/{int:student_membership_id}/guardians/",
    response={201: GuardiansOut, 403: MessageOut, 404: MessageOut, 422: MessageOut},
)
def link(request, student_membership_id: int, payload: LinkIn):
    """Link a guardian to a child by name and contact — D10's standalone action.

    Through `guardian_contacts.link_by_contact_as()`, the same code path the
    bulk import takes, so a guardian entered here and one entered in a file are
    one record with one channel. The link starts **pending verification** and
    stays so until the guardian answers this school (#135); `send_code()`
    below is how this school asks.

    Answers with the whole panel, because a link can change what the rest of
    it says — a sibling's guardian becoming this child's too.
    """
    school = _school_of(request)
    if not accounts_services.can_grant_memberships(request.user, school):
        return 403, MessageOut(detail=_MAY_NOT_LINK)
    child = _child_here(school, student_membership_id)
    if child is None:
        return 404, MessageOut(detail=_NO_SUCH_CHILD)

    name = payload.full_name.strip()
    if not name:
        return 422, MessageOut(detail="A guardian needs a name.")
    if payload.relationship not in Relationship.values:
        return 422, MessageOut(detail=f"{payload.relationship!r} is not a relationship.")

    try:
        with transaction.atomic():
            guardian_contacts.link_by_contact_as(
                request.user,
                child,
                name,
                payload.contact,
                relationship=payload.relationship,
            )
    except guardian_contacts.GuardianContactError as exc:
        return 422, MessageOut(detail=str(exc))
    except accounts_services.MembershipError as exc:
        return 422, MessageOut(detail=str(exc))
    except ValidationError as exc:
        return 422, MessageOut(detail=_first(exc))

    return 201, _guardians_of(child, school, True)


def _link_here(child, link_id):
    return (
        Guardianship.objects.select_related("guardian")
        .filter(pk=link_id, student=child)
        .first()
    )


_NOTHING_TYPED = (
    "This school has no phone number or email typed for this guardian, so there "
    "is nowhere to send a code. Remove the link and link them again with one."
)
_LIVE_ALREADY = (
    "They are live here already. They sign in with a code they ask for "
    "themselves, on the sign-in page."
)


@router.post(
    "/roll/{int:student_membership_id}/guardians/{int:link_id}/send-code/",
    response={200: GuardiansOut, 403: MessageOut, 404: MessageOut, 422: MessageOut, 429: MessageOut},
)
def send_code(request, student_membership_id: int, link_id: int, payload: SendCodeIn):
    """Send a guardian this school's code. ADMIN alone. `docs/messaging.md` D8.

    **Which code is the channel's own state, and the office is not asked.** An
    unverified channel gets a channel check (door one), a dormant phone a
    reactivation code (door three), and a proved channel whose guardian has not
    yet answered this school gets this school's own code (door four, #135).
    Answering any of them at the sign-in page turns the link live here.

    **Before the guardian is live here, the only channel addressable is the one
    this school typed**, and the answer does not say which door was used: the
    difference would tell an office whether a number belongs to a parent
    somewhere else, which #135 keeps from it.

    The code is sent after this commits (`messaging.codes`), so the panel that
    comes back says "waiting to be sent" rather than the outcome.
    """
    school = _school_of(request)
    if not accounts_services.can_grant_memberships(request.user, school):
        return 403, MessageOut(detail=_MAY_NOT_LINK)
    child = _child_here(school, student_membership_id)
    if child is None:
        return 404, MessageOut(detail=_NO_SUCH_CHILD)
    link = _link_here(child, link_id)
    if link is None:
        return 404, MessageOut(detail=_NO_SUCH_LINK)

    live = guardian_contacts.link_status_at(link.guardian, school) == guardian_contacts.LIVE
    if live:
        account = GuardianAccount.objects.filter(user=link.guardian).first()
        channel_type = payload.channel_type or ContactChannel.PHONE
        if channel_type not in ContactChannel.values:
            return 422, MessageOut(detail=f"{channel_type!r} is not a kind of contact.")
        contact = account.live_contact(channel_type) if account is not None else None
    else:
        contact = _typed_contact(link)
    if contact is None:
        return 422, MessageOut(detail=_NOTHING_TYPED)

    try:
        with transaction.atomic():
            if contact.verified_at is None:
                guardian_contacts.request_verification_as(request.user, contact, school=school)
            elif guardian_contacts.is_dormant(contact):
                guardian_contacts.request_reactivation_as(request.user, contact, school=school)
            elif not live:
                guardian_contacts.request_school_answer_as(request.user, contact, school=school)
            else:
                return 422, MessageOut(detail=_LIVE_ALREADY)
    except guardian_contacts.VerificationRateLimited as exc:
        minutes = max(1, round(exc.retry_after / 60))
        return 429, MessageOut(
            detail=f"Too many codes have gone out to this contact or from this school "
            f"just now. Try again in {minutes} minute{'s' if minutes != 1 else ''}."
        )
    except accounts_services.NotPermitted:
        return 403, MessageOut(detail=_MAY_NOT_LINK)
    except guardian_contacts.GuardianContactError as exc:
        return 422, MessageOut(detail=str(exc))
    return 200, _guardians_of(child, school, True)


@router.post(
    "/roll/{int:student_membership_id}/guardians/{int:link_id}/contacts/",
    response={201: GuardiansOut, 403: MessageOut, 404: MessageOut, 422: MessageOut},
)
def add_contact(request, student_membership_id: int, link_id: int, payload: ContactIn):
    """Give a live guardian their other channel: an email beside a phone, or the reverse. #111.

    **Live here only.** Before the guardian has answered this school, what they
    hold is not this school's to know, and "they already have an email" would
    tell it. A second channel of a type they hold is refused: replacing one is
    D11's change flow, not this.
    """
    school = _school_of(request)
    if not accounts_services.can_grant_memberships(request.user, school):
        return 403, MessageOut(detail=_MAY_NOT_LINK)
    child = _child_here(school, student_membership_id)
    if child is None:
        return 404, MessageOut(detail=_NO_SUCH_CHILD)
    link = _link_here(child, link_id)
    if link is None:
        return 404, MessageOut(detail=_NO_SUCH_LINK)
    if guardian_contacts.link_status_at(link.guardian, school) != guardian_contacts.LIVE:
        return 422, MessageOut(
            detail="They have to answer this school before another contact can be added."
        )
    read = guardian_contacts.read_contact(payload.contact)
    if read is None:
        return 422, MessageOut(detail=f"{payload.contact!r} is neither a phone number nor an email address.")

    try:
        with transaction.atomic():
            guardian_contacts.record_contact_as(request.user, link.guardian, *read)
    except guardian_contacts.GuardianContactError as exc:
        return 422, MessageOut(detail=str(exc))
    except accounts_services.NotPermitted:
        return 403, MessageOut(detail=_MAY_NOT_LINK)
    except ValidationError as exc:
        return 422, MessageOut(detail=_first(exc))
    return 201, _guardians_of(child, school, True)


@router.post(
    "/roll/{int:student_membership_id}/guardians/{int:link_id}/remove/",
    response={200: GuardiansOut, 403: MessageOut, 404: MessageOut, 422: MessageOut},
)
def unlink(request, student_membership_id: int, link_id: int):
    """Remove one guardian from one child. ADMIN alone.

    D11 calls this "an authority decision … whoever the school designates", and
    `unlink_guardian_as()` designates the administrator. The page asks for a
    second click before it sends this; the route does not, because a confirm
    step is about a person's hand slipping, not about who they are.

    If that was the guardian's last child here, their PARENT membership here
    ends too (`unlink_guardian()`). A sibling's link is untouched.
    """
    school = _school_of(request)
    if not accounts_services.can_grant_memberships(request.user, school):
        return 403, MessageOut(detail=_MAY_NOT_LINK)
    child = _child_here(school, student_membership_id)
    if child is None:
        return 404, MessageOut(detail=_NO_SUCH_CHILD)
    link = (
        Guardianship.objects.select_related("guardian")
        .filter(pk=link_id, student=child)
        .first()
    )
    if link is None:
        return 404, MessageOut(detail=_NO_SUCH_LINK)

    try:
        with transaction.atomic():
            accounts_services.unlink_guardian_as(request.user, link.guardian, child)
    except accounts_services.MembershipError as exc:
        # `unlink_guardian_as()` refuses on its own authority too. Unreachable
        # past the check above, and mapped anyway so a refusal is never a 500.
        return 422, MessageOut(detail=str(exc))
    return 200, _guardians_of(child, school, True)
