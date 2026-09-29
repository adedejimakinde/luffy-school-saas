"""End-of-session promotion: each class moves up a class, all at once or not at all.

**What promotion is here.** A placement is per term (`ClassPlacement`), so
promoting a child means giving them a placement in the *first term of the next
session*: the next class up for a child who passes, the same class again for a
child who repeats. The last class of the school has no next class; its passing
children **graduate**, which ends their enrolment
(`accounts.services.release_student()`: the membership is kept as history, the
one-school slot is freed, and a parent with no other child here loses their
access), exactly as any other child who leaves.

**A child who is leaving** is the third choice beside promote and repeat, open
to a child of any class. It ends the enrolment the same way graduating does
(`release_student()`), inside the same all-or-nothing confirmation, but it is
counted as *left*, not *graduated*: a JSS 1 child who goes to another school is
not a graduate, and the office's summary must not say so.

**Nothing moves until confirmed, and then everything moves or nothing does.**
`review()` writes nothing. `promote()` checks the whole plan first and writes
inside one transaction, so a refusal at the hundredth child leaves the first
ninety-nine where they were.

**The plan has to name every child.** A confirmation that listed only some of a
class would let a child be left out by accident — a repeat by omission, or worse
a child who graduated without anybody choosing it. `promote()` therefore refuses
a plan that does not name exactly the children the school has in each class now:
one who joined or left since the page was drawn means the office has not seen
the class as it stands, and the answer is to look again.

**Only at the end of the third term.** The current term must be a third term,
and the next session's first term must already exist, because that is where the
placements go. Neither is created here: opening a term is the office's own act
(`create_term`), and a promotion that invented one would be guessing its dates.

**A child already placed in that first term is not overwritten** and is not
skipped either: the whole promotion is refused, naming how many. Somebody has
already started placing children by hand or carried a roster forward, and mixing
the two silently is how a class ends up with two rosters.
"""

import re
from dataclasses import dataclass, field

from django.db import connection, transaction

from accounts.models import LIVE_STATUSES, Membership, Role
from accounts.services import release_student

from .models import ClassGroup, ClassPlacement, Term, TermName
from .services import (
    AcademicsError,
    NotAllowedToPlace,
    _stamp,
    can_place_students,
)

PROMOTE = "promote"
REPEAT = "repeat"
#: The child is not coming back, whatever class they were in: their enrolment
#: ends as *left*, not as graduated.
LEAVE = "leave"
ACTIONS = (PROMOTE, REPEAT, LEAVE)


class PromotionError(AcademicsError):
    """The promotion was not made. The message is for the person and says what to do."""


class NotEndOfSession(PromotionError):
    """The current term is not a third term, so the session is not over."""


class NoFirstTermNext(PromotionError):
    """Next session's first term has not been opened, and that is where children go."""


class ReviewOutOfDate(PromotionError):
    """The plan does not name exactly the classes and children the school has now."""


class BadDestination(PromotionError):
    """A class was sent nowhere, somewhere that is not a class here, or to itself."""


class AlreadyPlacedNext(PromotionError):
    """Some children already have a place in next session's first term."""


@dataclass
class Child:
    membership_id: int
    name: str
    reference: str


@dataclass
class ClassReview:
    class_group: ClassGroup
    children: list
    #: The class this one would move up into, `None` when the school has no
    #: class above it (its children graduate) or when more than one qualifies
    #: and the office has to choose.
    suggested_class: ClassGroup = None
    #: True when there is no class above this one, so graduating is the default.
    suggested_graduate: bool = False


@dataclass
class Review:
    term: Term
    to_term: Term = None
    classes: list = field(default_factory=list)
    targets: list = field(default_factory=list)
    #: Why nothing can be promoted yet, in a sentence for the person; `None` when it can.
    problem: str = None


def next_session(session: str):
    """"2025/2026" -> "2026/2027", or `None` for a session not written that way."""
    match = re.fullmatch(r"(\d{4})/(\d{4})", session or "")
    if not match:
        return None
    return f"{int(match.group(1)) + 1}/{int(match.group(2)) + 1}"


def _arm(name):
    """The letter after a class's number — "A" in "JSS 1A" — or `None`."""
    match = re.search(r"\d\s*([A-Za-z]+)$", name.strip())
    return match.group(1).upper() if match else None


def _suggest(group, active):
    """(class, graduate) for `group`: the class above it, or graduation when none is.

    The school's own `level` decides "above". Several classes at the next level
    is several arms: the one with the same arm letter, if exactly one has it.
    Otherwise nothing is suggested and the office must choose, which is better
    than guessing which of JSS 2A and JSS 2B a JSS 1C child belongs in.
    """
    above = [g for g in active if g.level > group.level]
    if not above:
        return None, True
    nearest = min(g.level for g in above)
    candidates = [g for g in above if g.level == nearest]
    if len(candidates) == 1:
        return candidates[0], False
    same_arm = [g for g in candidates if _arm(g.name) and _arm(g.name) == _arm(group.name)]
    return (same_arm[0], False) if len(same_arm) == 1 else (None, False)


def _current_term():
    return Term.objects.filter(is_current=True).first()


def _first_term_next(term):
    following = next_session(term.session)
    if following is None:
        return None
    return Term.objects.filter(session=following, name=TermName.FIRST).first()


def _problem_with(term):
    """`(problem, to_term)`: why this term cannot be promoted from, or the term to promote into."""
    if term is None:
        return "No term is open, so there is nothing to promote from.", None
    if term.name != TermName.THIRD:
        return (
            f"Promotion happens at the end of the third term. The school is in "
            f"{term}.",
            None,
        )
    to_term = _first_term_next(term)
    if to_term is None:
        return (
            f"Open the first term of {next_session(term.session) or 'the next session'} "
            f"on the Setup page first: that is where the children go.",
            None,
        )
    return None, to_term


def _live_children(term):
    """`{class_group_id: [Membership, ...]}` for who sits in a class this term and is still ours."""
    placements = list(ClassPlacement.objects.filter(term=term))
    live = {
        m.pk: m
        for m in Membership.objects.filter(
            pk__in=[p.student_membership_id for p in placements],
            role=Role.STUDENT,
            status__in=LIVE_STATUSES,
            school__schema_name=connection.schema_name,
        ).select_related("user")
    }
    by_class = {}
    for placement in placements:
        member = live.get(placement.student_membership_id)
        if member is not None:
            by_class.setdefault(placement.class_group_id, []).append(member)
    return by_class


def _name(member):
    return member.display_name or member.user.full_name or member.user.username


def review() -> Review:
    """What promotion would look at, for the current term. **Writes nothing.**"""
    term = _current_term()
    problem, to_term = _problem_with(term)
    result = Review(term=term, to_term=to_term, problem=problem)
    if problem:
        return result

    active = list(ClassGroup.objects.filter(is_active=True))
    result.targets = active
    groups = {g.pk: g for g in ClassGroup.objects.all()}
    for group_id, members in sorted(
        _live_children(term).items(), key=lambda item: (groups[item[0]].level, groups[item[0]].name)
    ):
        group = groups[group_id]
        suggested, graduate = _suggest(group, active)
        result.classes.append(
            ClassReview(
                class_group=group,
                children=sorted(
                    (Child(m.pk, _name(m), m.reference) for m in members),
                    key=lambda c: c.name.lower(),
                ),
                suggested_class=suggested,
                suggested_graduate=graduate,
            )
        )
    return result


@dataclass(frozen=True)
class Outcome:
    promoted: int
    repeated: int
    graduated: int
    left: int = 0


def promote(plan, *, by=None) -> Outcome:
    """Carry out a confirmed plan, entirely or not at all.

    `plan` is a list of `{"class_group_id", "graduate", "destination_id",
    "children": {membership_id: "promote" | "repeat" | "leave"}}`, one entry for every
    class that has children and, in each, one choice for every child.
    """
    with transaction.atomic():
        # The term row is locked so two confirmations cannot interleave: the
        # second waits, then finds the children already moved and is refused
        # as out of date rather than moving them twice.
        current = _current_term()
        term = Term.objects.select_for_update().get(pk=current.pk) if current else None
        problem, to_term = _problem_with(term)
        if problem:
            raise (
                NoFirstTermNext
                if term is not None and term.name == TermName.THIRD
                else NotEndOfSession
            )(problem)

        eligible = _live_children(term)
        chosen = {}
        for entry in plan:
            if entry["class_group_id"] in chosen:
                raise ReviewOutOfDate("A class appears twice in the plan. Look at the page again.")
            chosen[entry["class_group_id"]] = entry
        if set(chosen) != set(eligible):
            raise ReviewOutOfDate(
                "The classes changed since this page was drawn. Look at it again; nothing was moved."
            )

        groups = {g.pk: g for g in ClassGroup.objects.all()}
        writes, leaving = [], []
        counts = {"promoted": 0, "repeated": 0, "graduated": 0, "left": 0}
        for group_id, members in eligible.items():
            entry = chosen[group_id]
            choices = {int(k): v for k, v in entry["children"].items()}
            if set(choices) != {m.pk for m in members}:
                raise ReviewOutOfDate(
                    f"{groups[group_id].name} changed since this page was drawn. "
                    f"Look at it again; nothing was moved."
                )
            if any(v not in ACTIONS for v in choices.values()):
                raise PromotionError("Each child is promoted, repeats or is leaving.")

            graduate, destination_id = bool(entry.get("graduate")), entry.get("destination_id")
            if graduate == (destination_id is not None):
                raise BadDestination(
                    f"Say where {groups[group_id].name} goes: a class, or graduated."
                )
            if not graduate:
                destination = groups.get(destination_id)
                if destination is None or not destination.is_active or destination.pk == group_id:
                    raise BadDestination(
                        f"{groups[group_id].name} cannot be promoted into that class."
                    )
            for member in members:
                if choices[member.pk] == LEAVE:
                    leaving.append(member)
                    counts["left"] += 1
                elif choices[member.pk] == REPEAT:
                    writes.append((group_id, member))
                    counts["repeated"] += 1
                elif graduate:
                    leaving.append(member)
                    counts["graduated"] += 1
                else:
                    writes.append((destination_id, member))
                    counts["promoted"] += 1

        placed = ClassPlacement.objects.filter(
            term=to_term, student_membership_id__in=[m.pk for _, m in writes]
        ).count()
        if placed:
            raise AlreadyPlacedNext(
                f"{placed} of these children already have a class in {to_term}. "
                f"Nothing was moved; clear those placements or place the rest by hand."
            )

        ClassPlacement.objects.bulk_create(
            ClassPlacement(
                class_group_id=class_id,
                term=to_term,
                student_membership_id=member.pk,
                placed_by_id=_stamp(by),
            )
            for class_id, member in writes
        )
        for member in leaving:
            release_student(member)
    return Outcome(**counts)


def promote_as(actor, school, plan):
    """`promote()` for a caller with a request behind it. Authority is the placement set's."""
    if not can_place_students(actor, school):
        raise NotAllowedToPlace(
            f"{actor} may not promote children at {school}. That is done by a "
            f"principal or an administrator of the school."
        )
    return promote(plan, by=actor)


__all__ = [
    "ACTIONS",
    "AlreadyPlacedNext",
    "BadDestination",
    "LEAVE",
    "NoFirstTermNext",
    "NotEndOfSession",
    "PROMOTE",
    "PromotionError",
    "REPEAT",
    "ReviewOutOfDate",
    "next_session",
    "promote",
    "promote_as",
    "review",
]
