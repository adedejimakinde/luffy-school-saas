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
from accounts import services as accounts_services
from accounts.models import Membership, Role
from accounts.session import session_auth

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
