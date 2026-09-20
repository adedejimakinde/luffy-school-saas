"""The report card, as a family reads it. Snapshot only, and no staff field has a slot.

This module is separate from `results.api` on purpose, and the separation is
structural rather than tidy. `results.api` serves the broadsheet, whose whole
subject is `position` and `class_average`; this one serves a card to the child
it is about and to their parent. Issue #21 asks that the family-facing surfaces
be *built from their own schemas rather than by filtering the staff ones*, and
the way that requirement fails in practice is a family route importing a schema
somebody wrote for staff and trusting a filter to hold. There is nothing here to
import: every schema below is defined in this file and none of them has a field
for a staff-only number.

## Two rules, and both are about a field having nowhere to go

**Excluded at the serializer, not at the template.** A field omitted from a
printed page while the JSON still carries it has not been omitted — the browser
received it and anybody can read it. `ReleasedCard.position` says so on the
model itself. So the exclusions are enforced by the *shape of the response*:

| never here | where it lives | why |
| --- | --- | --- |
| `position`, `roster_size` | `ReleasedCard` | where the child came in the class |
| `subject_position` | `ReleasedSubjectResult` | where they came in that subject |
| `first/second/third_absence` | `ReleasedSessionResult` | *why* a term averaged nothing |
| `suggested` | `PromotionDecision` | what the arithmetic proposed |

**And the payload does not branch on who is asking.** A member of staff reading
this endpoint gets byte-for-byte what the parent gets, because the question it
answers is "what went home?" and there is exactly one answer to that. A role
branch here would be a second shape of this response that only staff ever
exercise in tests, which is how a leak survives review. Staff who want position
have the broadsheet, behind its own authority check.

Note that `position` is **not** a staff-only field everywhere it appears, and
this is the trap the module is most likely to fall into later.
`ReleasedSubjectResult.position` is *where the line prints*, smallest first, and
so are the `position` columns on the frozen assessment cells and trait ratings.
The rank in a subject is `subject_position`, a different column on the same
table. A future reader deleting every field called `position` from this module
would remove the print order and keep nothing dangerous; a future reader adding
`position` back "because the other tables have it" would publish a class rank.

## Snapshot only, and what that rules out

Every number below is read from the frozen tables through the card's own
`card_id`. In particular this module must **not** call
`ratings.card_sections()` or `comments.card_comments()`, which are the
draft-or-frozen readers used by the school's own screens: both fall back to live
configuration when a child has no frozen rows, which is correct for a draft card
and wrong here. A card that went home says what it said, including where what it
said was nothing.

`positions` is not imported at all. Nothing on this page is recomputed.

## The marks grid is assembled here too, and for `card_payload()`'s reason

`card_columns()` and `card_rows()` turn one payload's subject lines into the
header and the aligned rows a marks table prints. They were `_columns()` and
`_rows()` in `results.pdf`, which left half of "what a card says" — which
papers are columns, and in what order they print — assembled inside the
renderer. That is the drift `card_payload()` was extracted to stop, and the
grid had escaped it: a second surface growing a marks table derives its own
columns, and the day the two disagree about which paper prints first they
disagree on a document a parent already has in their hand.

Neither function reaches past `ReportCardOut`, so the exclusions above hold for
the grid as well — there is no `subject_position` in scope to be aligned into a
column by accident.

## The same card as a file, and why the file route is here rather than anywhere else

`report_card_pdf()` serves the PDF of the card `report_card()` serves as JSON.
It asks the identical authority question — the same four calls, in the same
order — because **a PDF of a card you may read is not a second permission**.
Inventing one would mean two answers to "may this person have this card", and
the day they disagreed the wrong one would be the one nobody had tested.

It does not render anything. The file is made by a worker (`results.tasks`) and
the route hands over what is stored, or says what state the card is in and how
that state came about. Rendering in the request was the alternative and it is
refused in `results.tasks`: WeasyPrint takes a few hundred milliseconds a card,
and results week is every parent of a class arriving at once.

**The one live read, and the model sanctions it.** `PromotionDecision` is not
part of the snapshot and is deliberately not frozen — it is append-only and
already freezes its own inputs at decision time, so the hazard that drives
freezing everything else (a later configuration edit reaching backwards) cannot
apply to a table nothing edits. `ReleasedCard`'s docstring settles this. A
decision usually does not exist when the card is released, which is the other
half of why freezing it would be wrong: the card would permanently say
"undecided" about a year the school later decided.
"""

import enum
from decimal import Decimal
from typing import List, Optional

from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from ninja import Router, Schema

from academics.models import Term, TermName
from accounts.models import Guardianship, Membership, Role
from accounts.session import session_auth

from . import cards, renders, withholding
from .withholding import CardWithheld
from .models import (
    CommentAuthor,
    PdfState,
    PromotionDecision,
    ReleasedCard,
    ReleasedComment,
    ReleasedSessionResult,
    ReleasedTraitRating,
    TraitGroup,
)

router = Router(auth=session_auth)


#: Staff who may read any card at their own school.
#:
#: Deliberately **not** imported from `results.api.POSITION_VIEWING_ROLES`: that
#: constant answers "who may see a position", this one answers "who may see what
#: went home to a family". Tying them together would mean a later widening of
#: one silently widened the other, and these are not the same question.
#:
#: **A bursar is here on purpose, and must never be added to
#: `results.api.POSITION_VIEWING_ROLES`.** The comment this replaces predicted
#: this edit — "a bursar could reasonably be added here one day and must never
#: be added there" — and the fee gate is the day. A bursar deciding whether to
#: hold a card back cannot do the job without seeing the document they are
#: holding, and the narrower alternative — a staff screen showing only *that* a
#: card exists and is withheld — is a second surface answering a question the
#: first one already answers. That shape is what produced four answers to "did a
#: card go home" and the PR #35 bug with them.
#:
#: The widening stops here. Nothing in this module has a slot for a position for
#: it to reach: `ReportCardOut` carries no position field, so this cannot leak a
#: rank even by accident. That is the property that makes it a one-line change
#: rather than a judgement call repeated at every serializer.
CARD_VIEWING_ROLES = frozenset(
    {
        Role.TEACHER.value,
        Role.VICE_PRINCIPAL_ACADEMIC.value,
        Role.PRINCIPAL.value,
        Role.ADMIN.value,
        Role.BURSAR.value,
    }
)


class CardClaim(enum.Enum):
    """*How* a reader has a claim on this card. `None` where they have none.

    The gate needs this and not a boolean, because staff always see a withheld
    card — a bursar who cannot see what they are withholding cannot do the job —
    so it has to know which of the three readers is asking.

    Never stored and never serialised. A plain `enum.Enum` rather than
    `TextChoices` for exactly that reason: nothing here crosses the database, so
    the values are internal and identity comparison is the safe kind.
    """

    SELF = "self"
    GUARDIAN = "guardian"
    STAFF = "staff"


#: The two claims a *family* holds, and the only ones the fee gate applies to.
#:
#: **Not `accounts.FAMILY_ROLES`.** A claim is not a role: a guardian's claim
#: comes from `Guardianship`, which links a login to *one child*, while holding
#: PARENT at a school says only that somebody is *a* parent there. That
#: distinction is the whole reason `_may_read()` is a function and not a role
#: test, and this constant must not blur it.
FAMILY_CLAIMS = frozenset({CardClaim.SELF, CardClaim.GUARDIAN})


# -- what a family sees ------------------------------------------------------


class AssessmentCellOut(Schema):
    """One mark in one subject — "Test 1: 18 / 20", frozen as it was printed.

    `assessment_name` and `max_score` are the copied ones: an assessment renamed
    or re-weighted next term must not relabel a column on a card already in a
    parent's hand.
    """

    assessment_name: str
    max_score: int
    score: Optional[int]


class SubjectLineOut(Schema):
    """One subject's row on the card.

    No `subject_position`. That is the child's rank in the subject and it is
    staff-only for the same reason the class position is — see the module
    docstring, and note that this schema deliberately has no field it could be
    assigned to even by accident.

    `percentage` is a string rather than a float. It is `Decimal` everywhere
    behind this, and handing it to JSON as a float would round it at the last
    step, on the one number a parent is most likely to check with a calculator.
    """

    subject_name: str
    subject_code: str
    total_scored: int
    total_available: int
    percentage: Optional[str]
    grade_letter: str
    grade_remark: str
    assessments: List[AssessmentCellOut]


class TraitOut(Schema):
    """One line of the conduct section.

    `score` is `Optional` because a frozen section records the traits nobody
    rated as well as the ones somebody did — what was frozen is the *section*,
    and "nothing was recorded here" is a thing the card has to go on saying.
    """

    trait_name: str
    score: Optional[int]
    score_label: str


class SectionOut(Schema):
    """A conduct group — affective or psychomotor — and its lines."""

    group: str
    group_label: str
    traits: List[TraitOut]


class CommentOut(Schema):
    """A signed remark. Two signatories, fixed in code."""

    author: str
    author_label: str
    body: str


class SessionLineOut(Schema):
    """The three-term summary, third term only.

    **No `*_absence`.** Those columns say *why* a term contributed nothing —
    the child was not enrolled, or nobody entered marks, or the school never
    created the term — and `TermAbsence` states on the model that they are
    staff-only: a parent reading "no marks were entered" is being shown the
    school's filing rather than their child's year. A term that averaged
    nothing arrives here as a null average, which is what the card prints.

    The weights are absent for a narrower reason: they are the audit of how the
    year was averaged, they belong to the school's screen, and no Nigerian
    report card prints them.
    """

    session: str
    first_average: Optional[str]
    second_average: Optional[str]
    third_average: Optional[str]
    session_average: Optional[str]


class PromotionOut(Schema):
    """What the school *decided*, and never what the arithmetic suggested.

    `PromotionDecision` stores both, and the gap between them is the whole
    record: a child the numbers promote and the school holds back, or the
    reverse. `suggested` is the school's internal reasoning about a child and
    has no place on the card — it would tell a family that the system wanted a
    different answer from the one a person gave, which is a conversation for the
    school to have, not a field.

    There is no "undecided" value. A child nobody has decided about has no row,
    and this whole object is absent from the response.
    """

    status: str
    status_label: str


class CardPdfNotReadyOut(Schema):
    """The 202 body: this card exists and its file does not, and why.

    Not a 404, which would say the card is not there when it is — the JSON of
    the very same card is being served from the route beside this one. Not a
    500, because nothing has gone wrong from the caller's side. 202 is the code
    for "accepted, not finished", and the body says which of the two unfinished
    states this is, because they need different things from the reader: one
    needs a minute, the other needs somebody at the school.

    **`error` is deliberately not a field here.** It holds a Python exception's
    class and message, written by a worker for whoever debugs the render, and a
    parent reading `TemplateSyntaxError` learns nothing they can act on. This
    module's other rule applies as well — the payload does not branch on who is
    asking — so it is absent for staff too, who can read the row.
    """

    state: str
    state_label: str
    detail: str


class ReportCardOut(Schema):
    """One child's card for one term, exactly as it was released.

    Every string here is a **copy** taken at release rather than a reach through
    a foreign key: `school_name`, `student_name`, `class_group_name`,
    `subject_name`. A school that renames itself, a child whose name is
    corrected, a class regrouped next session — none of them may relabel a card
    that has gone home.

    `own_average` is the child's own average across the subjects they were
    marked in. It is null where they were marked in nothing, which prints blank
    rather than as a zero that would claim they sat exams and scored none.

    Attendance is nullable until Phase 2 and prints blank meanwhile.

    `session` and `promotion` are third-term only and absent otherwise. A
    first-term card carrying a session average would be showing the first term's
    average wearing a session's name.
    """

    school_name: str
    student_name: str
    class_group_name: str
    academic_session: str
    term_name: str
    term_label: str

    #: **Identity, where the two fields above are labels.** `term_name` is the
    #: choice value and `term_label` is what it is called on the page; neither
    #: one identifies a row, and a session has three terms carrying the same
    #: pair year after year. A client holding this card and wanting the term
    #: beside it had to guess an integer, which is the gap `card_index()` and
    #: this field close together.
    #:
    #: Not a staff-only disclosure. The reader already holds this card, and the
    #: id is the argument they used in the URL to fetch it — there is nothing
    #: here they did not send.
    term_id: int
    version: int

    #: Task 8. **The word "Revised" on the page, and the only source of it.**
    #: `ReleasedCard.is_revised` decides — `version > 1`, not "an audit row
    #: exists" — so that a child placed into a term after it was released, whose
    #: only card is issued through the revision path at version 1, is not told
    #: her card is a correction of something she never received.
    #:
    #: Sent to families as well as staff, deliberately. It is not a staff-only
    #: field like `position`: a parent holding two cards for one term has to be
    #: able to tell which one supersedes the other, and being told that in the
    #: office rather than on the page is how the wrong card gets believed. What
    #: is *not* here is the reason or who signed it — `CardRevision` is the
    #: school's audit, and "why was this corrected" is a conversation, not a
    #: field on a page a child carries home.
    is_revised: bool

    total_scored: int
    total_available: int
    own_average: Optional[str]

    days_present: Optional[int]
    days_absent: Optional[int]
    days_open: Optional[int]

    subjects: List[SubjectLineOut]
    sections: List[SectionOut]
    comments: List[CommentOut]
    session: Optional[SessionLineOut] = None
    promotion: Optional[PromotionOut] = None


class WithheldOut(Schema):
    """What a family is told when their school is holding the card. The 403 body.

    Three fields, and the interesting part is the two that are missing.

    **Not the amount.** Balances are staff-only in this phase: a parent-facing
    number is a support burden and a correctness risk, because a family will
    dispute a figure the bursar has not reconciled. It is additive later.

    **Not the reason.** `WithholdingDecision.reason` is the bursar's internal
    note and may be unguarded about a family. It is staff-only in the sense
    `ReleasedCard.position` is — excluded at the serializer, not merely absent
    from the page — because a field left out of the template while it sits in
    the JSON has not been left out.

    `school_name` is the card's **frozen** copy, never a live join to `School`.

    `contact` is the entire reason `withholding_contact` and its constraint
    exist. A refusal that sends a parent nowhere is the dead end this design is
    about; the constraint is what makes this field non-empty whenever the switch
    that produces this response is on.
    """

    school_name: str
    contact: str
    detail: str


class ListedCardOut(Schema):
    """One card in the index: enough to choose it, and nothing off the card.

    **No marks, no averages, no comments, no conduct, no attendance.** This
    object names a card; it does not serve one. That distinction is the whole
    reason a withheld card can appear here at all — see `card_index()` — and it
    is held by this schema having no slot for any of it rather than by a view
    remembering not to fill one, which is the same technique `ReportCardOut`
    uses against `position`.

    `is_withheld` is the lever made visible. A family whose card is being held
    is told so at the moment they look for it, and told by the same predicate
    that will refuse them if they open it — `_is_withheld_from()`, not a second
    reading of the withholding tables. What it deliberately does *not* carry is
    the contact line: that belongs to the refusal, which is a sentence addressed
    to somebody who has just been stopped, and repeating it against every row of
    a list is not the same act.

    `version` and `is_revised` are here for the reason `ReportCardOut` carries
    them: a parent holding two cards for one term has to be able to tell which
    supersedes the other, and a list that showed neither would be the place that
    confusion starts.
    """

    term_id: int
    term_name: str
    term_label: str
    academic_session: str
    version: int
    is_revised: bool
    is_withheld: bool


class ListedChildOut(Schema):
    """One child this caller stands for, and the cards that went home for them.

    `student_name` is the **live** membership name, and that is a deliberate
    departure from the frozen-copy rule every field on `ReportCardOut` follows.
    The rule is about a card: what a card said when it went home must not be
    relabelled by an edit made afterwards. This is navigation — a parent picking
    which of their children to look at — and a child whose name the office has
    since corrected should be findable under the corrected one. The card they
    then open still says what it said.

    `cards` is empty for a child with no released card at this school. The child
    is still listed: "your daughter is enrolled here and no card has gone home
    yet" is an answer, and an index that dropped her would look identical to one
    that had lost her.
    """

    student_membership_id: int
    student_name: str
    cards: List[ListedCardOut]


class CardIndexOut(Schema):
    """Every card this caller can reach at this school, as a family member.

    Empty `children` is an ordinary 200 rather than a 404. A signed-in member of
    staff with no children here, and a guardian whose children are all at the
    school next door, both get it — and it discloses nothing either way, which
    is the property that lets this route answer honestly where the card routes
    answer 404. There is no school name and no term calendar here: this is a
    directory of artefacts, and everything descriptive belongs to the card the
    reader is about to open.
    """

    children: List[ListedChildOut]


# -- who may read one --------------------------------------------------------


def _school_of(request):
    """The school whose schema this request is already on.

    `None` is the portal host, where these tables do not exist — a 404 rather
    than a 403, the same answer `results.api` and `gradebook.api` give, and for
    the same reason: on the portal there is no such route because there is no
    such card.
    """
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("No report cards on this host.")
    return school


def _the_child(school, student_membership_id: int) -> Membership:
    """The child this card is about, scoped to this school and to STUDENT.

    Both halves of that scoping are in the lookup rather than checked after,
    which is what stops a membership id belonging to another school — or to a
    teacher at this one — from resolving here at all.
    """
    return get_object_or_404(
        Membership,
        pk=student_membership_id,
        school=school,
        role=Role.STUDENT,
    )


def _may_read(actor, school, child: Membership) -> Optional[CardClaim]:
    """The child themselves, a guardian of theirs, or staff at this school.

    Three readers, and they are checked cheapest first. The guardian check is a
    query and is the reason this is a function rather than a role test: a parent
    holds a PARENT membership at the school, which says they are *a* parent
    there and nothing about *whose*. Guardianship is what links a login to one
    child, and without consulting it every parent at a school could read every
    child's card.

    **Returns which claim, not whether there is one**, so that the fee gate at
    the serving edge can spare staff without asking any of these questions a
    second time. The three checks keep their order and their reasoning; only the
    return type changed.

    A **guardian who is also staff** comes back `STAFF`, because the role check
    runs before the guardianship query — so a bursar is served their own child's
    withheld card. That is a consequence of "staff always see a withheld card"
    rather than an exception to it, and it is written down here because a reader
    who found it themselves would reasonably file it as a leak. If a school ever
    wants the other answer, the change is to ask the guardianship question first
    *for the gate*, not to reorder this function — that would change who may
    read a card, which is a different question from who is served one.
    """
    if not getattr(actor, "is_authenticated", False):
        return None

    # The child reading their own card. `Membership.user_id`, not the child's
    # membership id — a student's login is the thing being compared.
    if child.user_id == actor.pk:
        return CardClaim.SELF

    if set(actor.roles_at(school)) & CARD_VIEWING_ROLES:
        return CardClaim.STAFF

    if Guardianship.objects.filter(guardian=actor, student=child).exists():
        return CardClaim.GUARDIAN

    return None


def _require_may_read(actor, school, child: Membership) -> CardClaim:
    """A flat 404 for every refusal, matching this API's disclosure convention.

    Not a 403. A 403 says "this card exists and you may not have it", which
    tells a stranger enumerating membership ids which children are enrolled at a
    school and in which term they were released — the existence oracle
    `gradebook.api`'s tests settled for this codebase. The refusal a caller who
    may not read this card gets is indistinguishable from the one they get for a
    child who does not exist.

    Returns the claim, which `_require_servable()` needs.
    """
    claim = _may_read(actor, school, child)
    if claim is None:
        raise Http404("No such report card.")
    return claim


def _children_of(actor, school) -> List[Membership]:
    """The children this caller stands for at this school. Never staff's roster.

    Two of `_may_read()`'s three readers, and the omission of the third is the
    design. `STAFF` is a claim on *every* card at the school, and an index built
    from it would be eight hundred children — a staff directory, which is a
    different surface answering a different question, and one this router has no
    business growing by accident. A member of staff calling this gets the
    children they are a parent or guardian of, which for most of them is none.

    That also keeps this route's cost a function of a family rather than of a
    roll, which is what makes it safe to serve without pagination.

    **Ended memberships are included**, and deliberately: `_the_child()` scopes
    on `school` and `role` and says nothing about status, so a card route serves
    a graduated or transferred child's card to their guardian. An index that
    filtered to live memberships would hide exactly the cards whose only copy is
    now this platform's — the year a family most needs to reach back into.

    Ordered explicitly rather than on `Meta.ordering`, following
    `cards.card_for()`'s rule: a queryset without a total order resolves ties
    however the plan happens to come back, and a list of children that reshuffles
    between two loads is a list a parent stops trusting.
    """
    mine = Membership.objects.filter(
        school=school, role=Role.STUDENT, user=actor
    )
    theirs = Membership.objects.filter(
        school=school, role=Role.STUDENT, guardianships__guardian=actor
    )
    return list(
        (mine | theirs).distinct().order_by("user__full_name", "pk")
    )


def _cards_of(actor, school, child: Membership) -> List[ListedCardOut]:
    """Every term this child has a card for, newest first.

    **The card named here is the card `report_card()` would serve**, because it
    is fetched with the same call. `cards.card_for()` resolves "which row is the
    card" — the earliest release, then its highest version — and that rule is
    subtle enough that a second, bulk implementation of it would be a second
    answer waiting to disagree. Two queries a term is the price of there being
    one rule, and a family's index is a few terms, not a school's.

    A term is listed **iff** the card route would answer for it. `card_for()`
    returning `None` is skipped rather than listed-and-broken: an index entry a
    parent taps and gets a 404 from is worse than no entry, because the first
    one blames them for the tap.
    """
    claim = _may_read(actor, school, child)
    if claim is None:
        # Unreachable by construction — `_children_of()` returns only children
        # this caller has a claim on. Skipping rather than listing is the safe
        # direction anyway: the alternative is `_is_withheld_from()` answering
        # `False` for a reader who has no claim, which would print "available"
        # against a card nobody is going to be served.
        return []

    released = (
        ReleasedCard.objects.filter(student_membership_id=child.pk)
        .values_list("term_id", flat=True)
        .distinct()
    )
    terms = Term.objects.filter(pk__in=list(released)).order_by(
        "-session", "-starts_on", "-pk"
    )

    listed = []
    for term in terms:
        card = cards.card_for(child, term)
        if card is None:
            continue
        listed.append(
            ListedCardOut(
                term_id=term.pk,
                term_name=card.term_name,
                term_label=TermName(card.term_name).label,
                academic_session=card.session,
                version=card.version,
                is_revised=card.is_revised,
                is_withheld=_is_withheld_from(claim, card),
            )
        )
    return listed


def _require_servable(claim: CardClaim, card):
    """403 for a family reader whose school is holding this card over fees.

    **One helper, called identically from both serving surfaces.** It is not a
    clause bolted into each view, and that is the whole design rather than
    tidiness: `report_card_pdf()`'s docstring already argued that a PDF of a card
    you may read is not a second permission, *reachable by adding four
    characters to a URL*. This makes the same sentence true of being served one,
    and it stays true only while there is one function to change.

    **It takes the card, not `(child, term)`.** The body has to carry
    `school_name` from the card's frozen copy — operating rule 2, no live join to
    `School` — and a helper handed only a child and a term has neither the frozen
    name nor the card row. The alternative is calling `cards.card_for()` a second
    time, which is a second answer to the deliberately order-sensitive question
    of *which* card this is. The caller already holds it by the time this runs;
    the child and the term are on it.

    **Staff are spared before anything is read.** `withholding.is_withheld()` is
    two queries, and a staff caller has already been established as one who sees
    a withheld card, so there is nothing for those queries to decide.

    ## This helper is the only door

    **A new way to put card content in a family's hands is a change to this
    design rather than an addition to it.** That is the promise, and it is
    stated here rather than in a test name because a coverage claim in prose
    goes stale (`operating-rules.md` rule 7) and this is the one place a person
    adding the third surface is certain to read.

    `test_withholding.AThirdServingSurfaceCannotBeAddedUngated` enumerates
    `router.path_operations` and drives every one of them as the guardian of a
    withheld child, so a third route on *this* router is covered the day it is
    written. Its reach stops at the router: a surface serving card content from
    somewhere else — a staff export in `results/api.py`, an emailed attachment,
    a management command — is outside it, because the only thing tying this
    helper to a route is that the route calls it, and no test can enumerate
    code in a module it does not know to look at.
    """
    if not _is_withheld_from(claim, card):
        return

    raise CardWithheld(
        school_name=card.school_name,
        contact=withholding.settings().withholding_contact,
    )


def _is_withheld_from(claim: Optional[CardClaim], card) -> bool:
    """Would `_require_servable()` refuse this card to this claim?

    Extracted so that the index can mark a card withheld **by asking the
    question the serving path asks**, rather than by asking a similar one. The
    two answers have to agree on every card: an index that marks a card withheld
    and a route that then serves it is a school telling a family two things, and
    the family believes the one that suits them. Equally, an index that says
    nothing about a card the route refuses sends a parent into a dead end it
    could have named.

    The staff-sparing half is the part that would have drifted. A guardian who
    is also staff at this school holds `STAFF` — `_may_read()` checks the role
    before the guardianship — so the gate spares them and the route serves their
    own child's withheld card. An index that had reached for
    `withholding.is_withheld()` directly would have marked that same card
    withheld, correctly by the books and wrongly about what happens next.

    `claim` is `Optional` only because `_may_read()` returns `None` for a caller
    with no claim at all. Such a caller reaches neither surface — the index does
    not enumerate them a child and `_require_may_read()` 404s them — and the
    answer here is `False` for the reader who has no card rather than a refusal
    about somebody else's.
    """
    if claim not in FAMILY_CLAIMS:
        return False

    return withholding.is_withheld(card.student_membership_id, card.term_id)


# -- reading the snapshot ----------------------------------------------------


def _as_text(value) -> Optional[str]:
    """`Decimal` to string, preserving `None`.

    Null is not the same as "0.00" on any number on this page: it is the
    difference between a child who was marked in nothing and one who scored
    nothing, and between a term that did not happen and a term that was failed.
    """
    return None if value is None else str(value)


def _subject_lines(card) -> List[SubjectLineOut]:
    """The subject table, in the order it was frozen to print in.

    `cards.card_lines()` returns `(line, cells)` pairs already grouped, in two
    queries whatever the card's size. `ReleasedSubjectResult.Meta.ordering`
    carries the frozen print order — `position`, which on this table means where
    the line prints and *not* a rank.
    """
    return [
        SubjectLineOut(
            subject_name=line.subject_name,
            subject_code=line.subject_code,
            total_scored=line.total_scored,
            total_available=line.total_available,
            percentage=_as_text(line.percentage),
            grade_letter=line.grade_letter,
            grade_remark=line.grade_remark,
            assessments=[
                AssessmentCellOut(
                    assessment_name=cell.assessment_name,
                    max_score=cell.max_score,
                    score=cell.score,
                )
                for cell in cells
            ],
        )
        for line, cells in cards.card_lines(card)
    ]


def _sections(card) -> List[SectionOut]:
    """The conduct section, grouped, read by `card_id` and nothing else.

    Deliberately **not** `ratings.card_sections()`. That reader falls back to
    live configuration for a child with no frozen rows, which is right for a
    draft card on the school's screen and wrong for a card that has gone home:
    it would print this term's trait list onto last term's card. Here, no frozen
    rows means no section, which is the truthful answer — a school that froze
    nothing published a card with no conduct section.

    Groups come out in `TraitGroup` declaration order rather than alphabetically,
    so affective precedes psychomotor as it does on the printed page.
    """
    rows = ReleasedTraitRating.objects.filter(card=card)

    by_group: dict[str, List[TraitOut]] = {}
    for row in rows:
        by_group.setdefault(row.group, []).append(
            TraitOut(
                trait_name=row.trait_name,
                score=row.score,
                score_label=row.score_label,
            )
        )

    return [
        SectionOut(
            group=group.value,
            group_label=group.label,
            traits=by_group[group.value],
        )
        for group in TraitGroup
        if group.value in by_group
    ]


def _comments(card) -> List[CommentOut]:
    """The signed remarks, in signatory order rather than write order.

    A card prints the class teacher above the principal whichever was typed
    first, so the order comes from `CommentAuthor` rather than from `created_at`.
    A remark that was never written has no row and prints as absent, which is
    what an unsigned card looks like.
    """
    by_author = {row.author: row for row in ReleasedComment.objects.filter(card=card)}
    return [
        CommentOut(
            author=author.value,
            author_label=author.label,
            body=by_author[author.value].body,
        )
        for author in CommentAuthor
        if author.value in by_author
    ]


def _session_line(card) -> Optional[SessionLineOut]:
    """The three-term summary, or `None` where none was frozen.

    Only third-term releases freeze one, so `None` here is the ordinary state of
    a first- or second-term card rather than a fault.
    """
    row = ReleasedSessionResult.objects.filter(card=card).first()
    if row is None:
        return None
    return SessionLineOut(
        session=row.session,
        first_average=_as_text(row.first_average),
        second_average=_as_text(row.second_average),
        third_average=_as_text(row.third_average),
        session_average=_as_text(row.session_average),
    )


def _promotion(card) -> Optional[PromotionOut]:
    """The recorded decision for this child's session, if a person has made one.

    Read live, which is the one thing on this page that is not from the
    snapshot — see the module docstring for why `ReleasedCard` sanctions it.

    Keyed on `(student, session)` and not on the card, because the decision is
    about the *year* rather than about the term whose release wrote this row.
    Absent where no row exists, because undecided is the absence of a row rather
    than a value.
    """
    if card.term_name != TermName.THIRD:
        return None
    decision = PromotionDecision.objects.filter(
        student_membership_id=card.student_membership_id, session=card.session
    ).first()
    if decision is None:
        return None
    return PromotionOut(
        status=decision.status,
        status_label=decision.get_status_display(),
    )


# -- the endpoints -----------------------------------------------------------


@router.get("/cards/", response=CardIndexOut, tags=["results"])
def card_index(request):
    """Which cards this family can reach, and which of them are being held.

    **Without this route a parent could not reach a card at all.** Both card
    routes are keyed on `(student_membership_id, term_id)` and nothing in this
    API ever handed a family either number: sign-in answers with a list of
    *schools*, and `ReportCardOut` carried labels rather than a term id. The
    page existed and the only way to open it was to type integers into a URL.

    ## A withheld card is listed, and marked

    It would have been one line to leave it out, and that line would have broken
    two things.

    It would defeat the point of withholding. A school holds a card back to
    prompt a conversation about fees — `docs/withholding.md`, "403, and why the
    convention is broken here", is the argument that the refusal has to name
    somebody to ring. A card that simply never appears prompts nothing: the
    family does not know there is anything to ring about, and the lever moves
    nobody.

    And it would put an oracle where there is nothing to protect. The flat-404
    convention on the card routes exists because a *stranger* enumerating
    membership ids must not learn which children are enrolled and which terms
    were released. This route enumerates nothing — it answers only about
    children the caller already stands for, and a parent knows their own child
    exists and knows the term happened. Hiding it from them is not disclosure
    control, it is a school being evasive with a family.

    So the honest answer is the one a school would give at the counter: the card
    exists, we are holding it, here is who to speak to. The last clause is the
    refusal's and stays there — `ListedCardOut` says why.

    ## It is not a third serving surface

    `_require_servable()`'s docstring promises it is the only door through which
    card *content* reaches a family, and this route does not open a second one.
    It serves no mark, no average, no remark, no rating, no attendance: the
    schema has no slot for any of them. What it serves is the existence of a
    card and whether it is being held, which is the gate's own answer rather
    than a way around it.

    `test_withholding.AThirdServingSurfaceCannotBeAddedUngated` enumerates this
    router and demands a 403 from every operation, so this route necessarily
    failed it. The test was widened rather than relaxed — it now sorts routes
    into those that must refuse and those that may only *name* a card, and holds
    this one to the harder half of that bargain: no card content, and the
    withheld mark actually set. That amendment is part of this change and is the
    place to look first if this route ever starts serving more than it does now.

    No pagination. The list is a family's children and their terms — single
    digits — and a page parameter here would be a knob nobody turns standing in
    for a limit nobody needs.
    """
    school = _school_of(request)
    return CardIndexOut(
        children=[
            ListedChildOut(
                student_membership_id=child.pk,
                student_name=child.name,
                cards=_cards_of(request.user, school, child),
            )
            for child in _children_of(request.user, school)
        ]
    )


@router.get(
    "/cards/{int:student_membership_id}/{int:term_id}/",
    response={200: ReportCardOut, 403: WithheldOut},
    tags=["results"],
)
def report_card(request, student_membership_id: int, term_id: int):
    """One child's released card for one term.

    404 for every way this can fail to produce a card — no such child, no card
    released, or a caller with no claim on this one. They are one answer on
    purpose: see `_require_may_read()`.

    The single 403 is the fee gate, and **it runs last on purpose**. The claim
    check going first is what keeps the flat-404 convention intact for everyone
    it was written for: a stranger still learns nothing, and a family reader who
    has already proven a guardianship claim knows their child exists and knows
    the term happened. Answering *them* with a 404 would be a lie — the school
    did release the card — and it sends a parent to the school angry about the
    wrong thing.

    **`403: WithheldOut` has to be declared here**, not only handled in `api.py`.
    django-ninja raises `ConfigError` on a status the route did not declare, so
    without it the exception handler is unreachable on this route and the
    cheapest thing left for an implementer is a plain-string 403 — which drops
    `contact`.
    """
    school = _school_of(request)
    child = _the_child(school, student_membership_id)
    claim = _require_may_read(request.user, school, child)

    term = get_object_or_404(Term, pk=term_id)
    card = cards.card_for(child, term)
    if card is None:
        raise Http404("No such report card.")

    _require_servable(claim, card)

    return card_payload(card)


def card_payload(card) -> ReportCardOut:
    """One released card as the family sees it. **The only assembly of one.**

    Extracted from the view above when task 7 needed the same thing to render a
    PDF from. It is deliberately not "the view's version and the renderer's
    version": every staff-only exclusion this module argues for — `position`,
    `roster_size`, `subject_position`, the term-absence reasons, the promotion
    *suggestion* — is held by there being no slot for them in these schemas, and
    a second assembly is a second place for a slot to appear. A template that
    reached into `ReleasedCard` directly would have every one of those fields in
    hand and nothing but care standing between them and the page.

    Takes no `request` and asks no authority question. Who may read a card is
    `_require_may_read()`'s, asked by each caller against the surface it is
    serving — a Celery worker rendering a PDF has no request to ask it of, and a
    payload builder that pretended otherwise would be answering with whatever
    the last caller happened to leave behind.
    """
    return ReportCardOut(
        school_name=card.school_name,
        student_name=card.student_name,
        class_group_name=card.class_group_name,
        academic_session=card.session,
        term_name=card.term_name,
        term_label=TermName(card.term_name).label,
        term_id=card.term_id,
        version=card.version,
        is_revised=card.is_revised,
        total_scored=card.total_scored,
        total_available=card.total_available,
        own_average=_as_text(card.own_average),
        days_present=card.days_present,
        days_absent=card.days_absent,
        days_open=card.days_open,
        subjects=_subject_lines(card),
        sections=_sections(card),
        comments=_comments(card),
        session=_session_line(card),
        promotion=_promotion(card),
    )


# -- the marks grid ----------------------------------------------------------


def card_columns(payload) -> list[dict]:
    """Every assessment on this card, once, in the order first seen.

    **The union, not the first subject's row.** `AssessmentCellOut`s hang off
    each `SubjectLineOut`, and an assessment belongs to a subject — so two
    subjects in one term need not have the same ones. A header row taken from
    the first subject would label Mathematics' columns and then print English's
    marks underneath them. This takes the ordered union, and `card_rows()`
    aligns every line against it.

    Keyed on `(name, max_score)` and **not on the name alone**. An assessment
    belongs to a subject — `uniq_assessment_term_subject_name` is per
    `(term, subject, name)` — so Mathematics' "Exam" and English's "Exam" are
    two different assessments and may be out of two different totals. One column
    headed "Exam" would print 45-out-of-60 and 45-out-of-100 as the same mark,
    on the document a parent is most likely to query with a teacher. The header
    carries the maximum for the same reason.

    `dict` rather than a `set`: the order is the frozen print order and a set
    would replace it with whatever the hash happened to be, which is the kind of
    ordering bug that agrees with itself until the day it does not.

    The order is the one the cells were frozen to print in, and it is not
    decided here. `ReleasedAssessmentScore.Meta.ordering` leads with the cell's
    own `position`, copied at release from `Assessment.position` — the school's
    own answer to where a paper prints, which is what closed **issue #42**.
    Before `position` existed the freeze ordered by `(subject name, assessment
    id)` — creation order — and `cards._assessments_for()` carries that history.
    Nothing is re-sorted here on purpose: re-sorting would be a second place
    deciding a print order, and a card in a parent's hand prints the order it
    went out with.

    *Across* subjects the header is first-seen order, so where two subjects
    disagree about the order of names they share, the first subject read wins
    and the second one's row is printed in the header's order rather than its
    own. One row of columns cannot honour two orders at once, and `position` is
    what settles it: two subjects that disagree are two subjects whose papers
    were given different positions.
    """
    seen = {}
    for line in payload.subjects:
        for cell in line.assessments:
            seen.setdefault((cell.assessment_name, cell.max_score), None)
    return [{"name": name, "max_score": max_score} for name, max_score in seen]


def card_rows(payload, columns) -> list[dict]:
    """Each subject line with its cells aligned to `columns`; `None` for a gap.

    A `None` is a subject that had no such assessment at all, which prints as a
    gap and is a different thing from a cell whose `score` is null — that is an
    assessment this child was not marked in, and it prints as a dash. Two
    absences that mean different things must not look the same on a card
    somebody is going to ask a teacher about.
    """
    rows = []
    for line in payload.subjects:
        by_key = {
            (cell.assessment_name, cell.max_score): cell for cell in line.assessments
        }
        rows.append(
            {
                "line": line,
                "cells": [
                    by_key.get((column["name"], column["max_score"]))
                    for column in columns
                ],
            }
        )
    return rows


# -- the same card as a file -------------------------------------------------


#: What a caller who cannot have the file is told, by the state of the row.
#:
#: Two sentences with two different readers. `PENDING` is addressed to somebody
#: who should simply come back — the render is owed and asking again is what
#: recovers a job that never ran. `FAILED` is addressed to somebody who will
#: wait for ever if they are not told to stop: nothing re-queues a failed card,
#: because what it needs is a person reading `error` off the row.
_NOT_READY = {
    PdfState.PENDING: (
        "This card's file is still being prepared. Try again in a minute."
    ),
    PdfState.FAILED: (
        "This card's file could not be made. The school has a record of what "
        "went wrong — ask the school office."
    ),
}


def _the_pdf(card, marker) -> HttpResponse:
    """The stored bytes, named for the child rather than for a primary key.

    `inline` rather than `attachment`, because a parent following a link wants
    to look at the card; a frontend that wants a save dialog can ask for one.
    The name is what a browser writes into a Downloads folder, so it is the
    child, the term and the session rather than `48213.pdf`.

    `slugify` does two jobs here and the second is the one that matters:
    `class_group_name` and `student_name` are typed by a school, and this string
    is going inside a quoted header value. What comes out of `slugify` is ASCII
    letters, digits and hyphens, so there is no quote to close and no newline to
    inject — the filename cannot be a way to write a second header.

    The version appears only when there is more than one, which is exactly the
    case where two files for the same child and term can sit in one folder and
    the superseded one must not be mistaken for the card that stands.
    """
    parts = [
        card.student_name,
        TermName(card.term_name).label,
        # A session reads "2025/2026", and a slug of that is "20252026". The
        # hyphen is put in before `slugify` can take the slash out.
        card.session.replace("/", "-"),
    ]
    if card.version > 1:
        parts.append(f"v{card.version}")

    response = HttpResponse(bytes(marker.content), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'inline; filename="{slugify(" ".join(parts))}.pdf"'
    )
    return response


@router.get(
    "/cards/{int:student_membership_id}/{int:term_id}/pdf/",
    response={200: None, 202: CardPdfNotReadyOut, 403: WithheldOut},
    tags=["results"],
)
def report_card_pdf(request, student_membership_id: int, term_id: int):
    """One child's released card for one term, as the file a family keeps.

    The four lines of authority below are `report_card()`'s — the same calls in
    the same order — because a PDF of a card you may read is not a second
    permission. Every refusal is that route's flat 404, including "no card for
    this term": a file route that answered otherwise would be the existence
    oracle the JSON route refuses to be, reachable by adding four characters to
    a URL.

    **`200: None` in the declaration does not mean an empty body.** django-ninja
    hands a view's `HttpResponse` back untouched, so the PDF goes out as itself;
    the declaration is only what the schema says, and there is no way to spell
    "some hundreds of kilobytes of application/pdf" as a pydantic model. The 202
    beside it is a real schema and is validated like any other.

    **Nothing is rendered here**, which is the decision issue #56 left open and
    the reason this is three lines rather than a call into `results.pdf`.
    WeasyPrint takes a few hundred milliseconds a card and results week is every
    parent of a class arriving at once; putting that in the request path is what
    moving the render to a worker was for. What this route does instead is ask
    again — `renders.enqueue_if_pending()` holds the debounce — so a card whose
    release-time job never reached a worker is recovered by the person who
    actually wants the file, rather than by a sweep nobody wrote.

    **The fee gate is the same call in the same position as `report_card()`'s**,
    and the docstring above is the argument for why it has to be. A withholding
    fitted to the JSON route alone is exactly the bug this route was written to
    refuse: a family refused the card appends `/pdf/` and is handed the file.
    The existing sentence predicted the shape of it before the feature existed,
    which is the strongest possible reason to take it literally.

    **The gate sits above the marker.** Today's 202 carries `state`,
    `state_label` and a detail string, so a withheld family reaching that code
    would learn whether their child's card has been rendered — and be told the
    file is "still being prepared", which is a worse lie than the 404 this
    design already rejects, because it promises a document that is never coming.

    **The file is still built for a withheld card.** Nothing in
    `results.renders` changes and nothing here makes a render conditional:
    `docs/report-card-pdf.md` writes the marker inside the release transaction
    precisely so that "released and never rendered" is a positive fact rather
    than an absence somebody infers, and making it conditional on fees would
    reintroduce through the fee door the hole that closed. It is also the
    practical answer — a school that lifts a withholding the morning after a
    family pays wants the file to exist already, not to start a render the
    family waits on.
    """
    school = _school_of(request)
    child = _the_child(school, student_membership_id)
    claim = _require_may_read(request.user, school, child)

    term = get_object_or_404(Term, pk=term_id)
    card = cards.card_for(child, term)
    if card is None:
        raise Http404("No such report card.")

    _require_servable(claim, card)

    marker = renders.marker_for(card)
    if marker.state == PdfState.BUILT:
        return _the_pdf(card, marker)

    renders.enqueue_if_pending(marker)
    return 202, CardPdfNotReadyOut(
        state=marker.state,
        state_label=PdfState(marker.state).label,
        detail=_NOT_READY[marker.state],
    )


__all__ = [
    "router",
    "card_index",
    "CARD_VIEWING_ROLES",
    "CardClaim",
    "FAMILY_CLAIMS",
    "WithheldOut",
    "card_payload",
    "card_columns",
    "card_rows",
]
