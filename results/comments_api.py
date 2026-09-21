"""HTTP for the two remarks on a card, and the conduct grid beside them.

A third backend with no door. `results/comments.py` and `results/ratings.py`
have had `write_as`, `clear_as`, `rate_as`, the phrase bank and the trait
scale since their own PRs, and nothing exposed any of it.

## Two signatories, and they are not two rows of one list

`CommentAuthor` has exactly two values and declaration order is print order: a
card carries the class teacher's remark and the principal's, one under the
other, each labelled. They are written by different people, refused to
different people, and read as two different judgements.

So **both are always served and only one is ever editable**. Hiding the other
would make a half-written card look finished, and a principal opening a class
she does not teach has to be able to read what the teacher wrote before adding
her own line.

## Ratings are the class teacher's alone, and only where switched on

`ratings.rate_as()` requires `_require_the_class_teacher()` — narrower than
comments, where the principal signs her own remark for any child. And the
whole section is absent unless the school has switched a group on:
`ReportCardSettings.affective_enabled` / `psychomotor_enabled`, read through
`ratings.enabled_groups()`. A school with both off never sees the grid, which
is why `sections` is a list and not two nullable fields.

## The list costs no child a query

`comments.missing()` is two queries for a whole class — the roster, then the
remarks that exist — and returns `student -> the authors still outstanding`.
The list serves that and nothing else. Per-child detail, the phrase bank and
the ratings grid are loaded when a child is opened, which is the shape decided
for the chain list and for the same reason.
"""

from typing import Dict, List, Optional

from django.http import Http404
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from academics.models import ClassGroup, ClassPlacement, Term
from accounts.models import Membership, Role
from accounts.session import session_auth

from . import comments as comments_service
from . import ratings as ratings_service
from .models import CommentAuthor, Trait, TraitGroup

router = Router(auth=session_auth)


class MessageOut(Schema):
    detail: str


class ChildRowOut(Schema):
    """One child on the class list, and what is still outstanding for them.

    `outstanding` carries author **values**, not labels, so the screen can key
    on them — `comments.missing()` returns values for exactly this reason.
    """

    student_membership_id: int
    student: str
    outstanding: List[str]


class ClassListOut(Schema):
    class_group_id: int
    class_group: str
    term_id: int
    term: str
    rows: List[ChildRowOut]


class RemarkOut(Schema):
    """One signatory's remark, and whether this login may sign it.

    `may_edit` is a convenience for the screen and **not** the gate:
    `comments.write_as()` asks again, and asks it against the placement it then
    writes with. A page that hid a box would be a restriction a POST bypasses.
    """

    author: str
    author_label: str
    body: str
    may_edit: bool


class TraitOut(Schema):
    trait_id: int
    name: str
    score: Optional[int] = None


class SectionOut(Schema):
    """One switched-on ratings group, with its traits in print order."""

    group: str
    group_label: str
    traits: List[TraitOut]


class ScalePointOut(Schema):
    value: int
    label: str


class ChildOut(Schema):
    """Everything one child's comment screen needs, in one trip.

    `sections` is empty where the school has switched both groups off, and
    `may_rate` is false for anybody but that class's teacher — the two are
    different reasons for the same absence and the screen says each one.
    """

    student_membership_id: int
    student: str
    class_group_id: int
    class_group: str
    term_id: int
    term: str
    locked: bool
    locked_reason: Optional[str] = None
    remarks: List[RemarkOut]
    #: Stock remarks for the author this login may sign, keyed by author value.
    #: Never both banks: a teacher picking a remark must not be shown one
    #: written for a principal to sign, which is why `comments.phrases()`
    #: refuses to answer without being told whose.
    phrases: Dict[str, List[str]]
    may_rate: bool
    sections: List[SectionOut]
    scale: List[ScalePointOut]


class BodyIn(Schema):
    body: str


class ScoreIn(Schema):
    score: int


def _school_of(request):
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("No results on this host.")
    return school


#: One sentence for every refusal of authority here, so "may you write?" and
#: "does that child exist?" cannot be told apart by their wording.
_MAY_NOT_COMMENT = (
    "A card is signed by the class teacher and the principal of the school the "
    "child attends."
)

#: Who may open a comment screen at all. The union of the two signatories,
#: derived rather than written out so a change to either cannot leave this
#: behind. An ADMIN is deliberately absent: entering a paper mark is office
#: work, but signing a remark is putting a name to a judgement.
VIEWING_ROLES = frozenset({Role.TEACHER.value, Role.PRINCIPAL.value})


def _refuse_outsiders(request, school, roles):
    """Authority first, **before either lookup** — the oracle rule."""
    if not roles & VIEWING_ROLES:
        return 403, MessageOut(detail=_MAY_NOT_COMMENT)
    return None


def _current_term():
    return Term.objects.filter(is_current=True).first()


def _names_for(school, student_ids) -> dict:
    """`membership_id -> the child's name`, one query for the class.

    The school's own `display_name` first, for the reason `attendance.api
    ._names_for()` gives: it exists for schools that know a child by a
    different name than the one on their login, and this is a screen where the
    teacher needs the name she uses out loud.
    """
    return {
        row["pk"]: row["display_name"] or row["user__full_name"] or ""
        for row in Membership.objects.filter(
            school=school, role=Role.STUDENT.value, pk__in=list(student_ids)
        ).values("pk", "display_name", "user__full_name")
    }


@router.get("/comments/", response={200: ClassListOut, 403: MessageOut, 422: MessageOut})
def class_list(request, class_group_id: Optional[int] = None):
    """Who in this class still needs which remark.

    `class_group_id` is required and enforced **by hand**, not as a required
    query parameter: ninja validates those before the view runs, which would
    put the 422 in front of the host check and the authority check — telling a
    caller on the portal that the route is real and what it wants, and handing
    a parent a 422 where the honest answer is 403. The gradebook learned this
    the same way. Host, then authority, then the field.

    Two queries for the whole class and **not one per child**:
    `comments.missing()` reads the roster and the remarks that exist, and the
    names come back in one more. The phrase bank, the ratings grid and the
    remark bodies are loaded when a child is opened.
    """
    school = _school_of(request)
    roles = set(request.user.roles_at(school))
    refused = _refuse_outsiders(request, school, roles)
    if refused is not None:
        return refused
    if class_group_id is None:
        return 422, MessageOut(
            detail="A comment list is one class group's. Name the group with "
            "`class_group_id`."
        )

    term = _current_term()
    if term is None:
        return 422, MessageOut(
            detail="No term is open, so there are no remarks to write yet."
        )
    group = get_object_or_404(ClassGroup, pk=class_group_id)

    outstanding = comments_service.missing(group, term)
    roster = ClassPlacement.objects.student_ids(group, term)
    names = _names_for(school, roster)
    return ClassListOut(
        class_group_id=group.pk,
        class_group=group.name,
        term_id=term.pk,
        term=str(term),
        rows=[
            ChildRowOut(
                student_membership_id=sid,
                student=names.get(sid, ""),
                outstanding=outstanding.get(sid, []),
            )
            for sid in sorted(roster, key=lambda sid: names.get(sid, ""))
        ],
    )


def _may_sign(author, roles, is_their_class_teacher):
    """Mirrors `comments._require_signatory()`, and only mirrors it.

    The principal signs her own remark for any child in the school; the class
    teacher's remark is the class teacher's, which is issue #25's scope in a
    third module. Both are asked again by `write_as()` on the placement it
    writes with.
    """
    if author == CommentAuthor.PRINCIPAL.value:
        return Role.PRINCIPAL.value in roles
    return is_their_class_teacher


@router.get(
    "/comments/{int:student_membership_id}/",
    response={200: ChildOut, 403: MessageOut, 422: MessageOut},
)
def child(request, student_membership_id: int):
    """One child's two remarks, the phrase bank for the one this login may
    sign, and the conduct grid where the school has one.

    **Both remarks are always served.** Hiding the one this login cannot sign
    would make a half-written card look finished, and the principal has to read
    the teacher's line before adding hers.
    """
    from academics import services as academics

    school = _school_of(request)
    roles = set(request.user.roles_at(school))
    refused = _refuse_outsiders(request, school, roles)
    if refused is not None:
        return refused

    term = _current_term()
    if term is None:
        return 422, MessageOut(detail="No term is open.")

    membership = get_object_or_404(
        Membership, pk=student_membership_id, school=school, role=Role.STUDENT
    )
    placement = academics.placement_of(membership.pk, term)
    if placement is None:
        return 422, MessageOut(
            detail="This child is not in a class this term, so there is no "
            "card to sign."
        )
    group = placement.class_group

    teacher_membership_id = request.user.membership_id_at(school, Role.TEACHER)
    theirs = academics.is_class_teacher(teacher_membership_id, group, term)

    bodies = comments_service.comments_for(membership.pk, term)
    remarks = []
    banks = {}
    for author in CommentAuthor:
        may = _may_sign(author.value, roles, theirs)
        remarks.append(
            RemarkOut(
                author=author.value,
                author_label=author.label,
                body=bodies.get(author.value, ""),
                may_edit=may,
            )
        )
        if may:
            banks[author.value] = [p.text for p in comments_service.phrases(author.value)]

    # Ratings are the class teacher's alone — narrower than comments, where the
    # principal signs her own remark for anybody.
    #
    # **One read of this child's scores for the whole grid**, hoisted out of
    # the trait loop it was first written inside. `ratings_for()` is a query,
    # and a school printing two sections of a dozen traits would have paid
    # twenty-four of them for one screen.
    scores = ratings_service.ratings_for(membership.pk, term)
    sections = [
        SectionOut(
            group=g,
            group_label=TraitGroup(g).label,
            traits=[
                TraitOut(trait_id=t.pk, name=t.name, score=scores.get(t.pk))
                for t in ratings_service.traits(g)
            ],
        )
        for g in ratings_service.enabled_groups()
    ]

    locked_reason = _locked_reason(group, term)
    return ChildOut(
        student_membership_id=membership.pk,
        student=membership.display_name or membership.user.full_name or "",
        class_group_id=group.pk,
        class_group=group.name,
        term_id=term.pk,
        term=str(term),
        locked=locked_reason is not None,
        locked_reason=locked_reason,
        remarks=remarks,
        phrases=banks,
        may_rate=theirs,
        sections=sections,
        scale=[ScalePointOut(value=p.value, label=p.label) for p in ratings_service.scale()],
    )


def _locked_reason(group, term):
    """Why this card cannot be written on, or `None`.

    Read **before anybody types**, for the reason the marking sheet's
    `SheetOut.locked` exists: a screen that saves on submit and learns from the
    refusal afterwards tells a teacher her paragraph is gone at the worst
    possible moment.
    """
    from . import services as results_services

    # `sheet_for()` and **not** `locked_sheet_for()`: this is a read. The
    # locking reader takes `SELECT ... FOR UPDATE`, which needs a transaction
    # and would hold a row for the length of a page load. Its own docstring
    # draws that line — rendering a card must not lock the chain.
    sheet = results_services.sheet_for(group, term)
    if results_services.is_open_for_writing(sheet):
        return None
    return (
        f"{group.name} — {term} is {sheet.get_state_display().lower()}, so its "
        f"remarks cannot be changed here."
    )


def _student_here(school, student_membership_id):
    return get_object_or_404(
        Membership, pk=student_membership_id, school=school, role=Role.STUDENT
    )


def _write_refusals(fn):
    """Map this app's refusals onto the statuses that say which kind they are.

    **403** for standing — the wrong role, or another teacher's class.
    **423** for a sheet that has left draft: the caller's authority has not
    changed and is not the problem, and no reload reopens a released term —
    which is the distinction `gradebook/api.py` drew for `MarksLocked` and the
    reason it is neither a 403 nor a 409.
    **422** for a body the column will not take: blank, or too long. The
    request is well formed and the caller is allowed; the text is the problem,
    and it is one they can retype.
    """

    def run(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except comments_service.NotAllowedToComment:
            # Not the exception's own text, which names the actor and the
            # school; that belongs in a log, not a response body.
            return 403, MessageOut(detail=_MAY_NOT_COMMENT)
        except ratings_service.NotAllowedToRate:
            return 403, MessageOut(
                detail="Conduct is rated by the teacher answerable for the class."
            )
        except (comments_service.CommentsLocked, ratings_service.RatingsLocked) as exc:
            return 423, MessageOut(detail=str(exc))
        except (comments_service.CommentsError, ratings_service.RatingsError) as exc:
            return 422, MessageOut(detail=str(exc))

    return run


_WRITE_RESPONSES = {
    200: MessageOut,
    403: MessageOut,
    422: MessageOut,
    423: MessageOut,
}


@router.put(
    "/comments/{int:student_membership_id}/{author}/", response=_WRITE_RESPONSES
)
def write_remark(request, student_membership_id: int, author: str, payload: BodyIn):
    """Record one signatory's remark. An upsert — rewriting is a correction.

    The author is a path segment rather than a field, because it is part of
    *which* remark this is: `one_comment_per_author_per_student_per_term` keys
    on it, and a body carrying it would let a client change which line it was
    editing halfway through.
    """
    school = _school_of(request)
    roles = set(request.user.roles_at(school))
    refused = _refuse_outsiders(request, school, roles)
    if refused is not None:
        return refused
    term = _current_term()
    if term is None:
        return 422, MessageOut(detail="No term is open.")
    membership = _student_here(school, student_membership_id)

    @_write_refusals
    def go():
        comments_service.write_as(
            request.user, term, membership, author, payload.body
        )
        return 200, MessageOut(detail="Saved.")

    return go()


@router.delete(
    "/comments/{int:student_membership_id}/{author}/", response=_WRITE_RESPONSES
)
def clear_remark(request, student_membership_id: int, author: str):
    """Take a remark back. Not the same as writing a blank one, which the
    column refuses — an absent remark and an empty one are different states."""
    school = _school_of(request)
    roles = set(request.user.roles_at(school))
    refused = _refuse_outsiders(request, school, roles)
    if refused is not None:
        return refused
    term = _current_term()
    if term is None:
        return 422, MessageOut(detail="No term is open.")
    membership = _student_here(school, student_membership_id)

    @_write_refusals
    def go():
        comments_service.clear_as(request.user, term, membership, author)
        return 200, MessageOut(detail="Cleared.")

    return go()


@router.put(
    "/ratings/{int:student_membership_id}/{int:trait_id}/", response=_WRITE_RESPONSES
)
def rate(request, student_membership_id: int, trait_id: int, payload: ScoreIn):
    """Score one trait for one child.

    Refused to anybody but that class's teacher, which is narrower than the
    remarks beside it — `ratings.rate_as()` requires
    `_require_the_class_teacher()` where a principal signs her own remark for
    any child in the school.
    """
    school = _school_of(request)
    roles = set(request.user.roles_at(school))
    refused = _refuse_outsiders(request, school, roles)
    if refused is not None:
        return refused
    term = _current_term()
    if term is None:
        return 422, MessageOut(detail="No term is open.")
    membership = _student_here(school, student_membership_id)
    trait = get_object_or_404(Trait, pk=trait_id)

    @_write_refusals
    def go():
        ratings_service.rate_as(request.user, term, trait, membership, payload.score)
        return 200, MessageOut(detail="Saved.")

    return go()
