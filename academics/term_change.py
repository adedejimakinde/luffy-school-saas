"""Moving the school on to a new term: the class lists go with it (audit finding G-01).

A child's class is a row per term (`ClassPlacement`). Until this module, making a
term current carried the subject teachers forward and nothing else, so the first
day of every term was a school with no class lists: registers refused, marking
sheets and bills were empty, and the office had to place every child again by hand.

**What happens now.** When a later term **of the same session** is made current,
every class list of the term that was current is copied into it, in the transaction
that makes it current (`academics.api.set_current_term()`), by
`services.carry_forward_placements()`, which already existed and which nothing
called. Its rules are unchanged and are the whole of the behaviour:

- each child goes into **the same class** they were in. It does not promote;
- a child **already placed** in the new term is left exactly where the office put
  them;
- a child whose enrolment has **ended** (left, transferred, graduated) is not
  carried;
- **running it twice changes nothing**: the second run finds everybody placed.

**What does not happen.** Nothing is carried into a term of **another session**.
Moving from the third term to next session's first term is promotion
(`academics.promotion`), a separate step in which the office says who moves up, who
repeats and who has left; `promote()` refuses when it finds children already placed
in that first term, so carrying them here would break it. Nothing is carried when
the school steps **back** to an earlier term either: that term has its own lists.

**The review.** `review()` says, before anything is changed, what making a term
current would do: each class, how many children would be carried into it, how many
are already placed, and by name every child who would not be carried and why. It
writes nothing. The setup page shows it and asks before it switches.

**The route requires it.** The review carries a `token`, a digest of everything it
says, and `PUT .../current/` takes that token back as `seen`. Inside the
transaction that would make the term current, the review is worked out again and
its token compared: with no token, or one for a review that no longer holds (a
child placed, moved or taken off the roll since), the term is not changed and the
caller is told to look again. So the switch that happens is the switch that was
shown, and a caller that never read the review cannot make it.

**It says how a child left.** A child not carried was taken off the roll by the
principal (`Departure`, with the day), or graduated or left at the end of a
session on the principal's decision (`results.PromotionDecision`). Where neither
record exists (an enrolment ended before either was kept, or by a transfer), it
says only that they are no longer at the school.

**Leaving a third term with children not promoted** is said, with the number:
they will be in no class in the new session until Promotion is run or they are
placed by hand.
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import List, Optional

from django.db import connection

from accounts.models import LIVE_STATUSES, Membership, Role

from . import services
from .models import ClassGroup, ClassPlacement, Departure, Term, TermName

#: Why a child on last term's list is not carried, where no record says how the
#: enrolment ended: neither a `Departure` nor a decision at promotion.
LEFT = "No longer at the school"
GRADUATED = "Graduated"
LEFT_AT_PROMOTION = "Left the school at the end of the session"


@dataclass
class NotCarried:
    membership_id: int
    name: str
    reference: str
    why: str = LEFT


@dataclass
class ClassLine:
    class_group_id: int
    name: str
    #: Children on the old term's list who would be copied into the new term.
    carried: int = 0
    #: Children of this list who already have a class in the new term (this one or
    #: another). They are left where they are.
    already_placed: int = 0
    not_carried: List[NotCarried] = field(default_factory=list)


@dataclass
class Review:
    term: Term
    from_term: Optional[Term]
    #: Whether making `term` current copies the class lists into it.
    carries: bool
    #: Why not, in a sentence for the person; "" when it does.
    why_not: str = ""
    classes: List[ClassLine] = field(default_factory=list)
    #: How many children the new term's lists hold already, however they got there.
    in_new_term: int = 0
    #: Leaving a third term for another session: how many children on its class
    #: lists are still at the school and have no class in the new term. They are
    #: who Promotion has not moved.
    not_promoted: int = 0

    @property
    def token(self) -> str:
        """A digest of everything this review says, for `require_seen()`.

        Whatever a person was shown and agreed to is in it: which term replaces
        which, whether the lists are carried and why not, each class's counts,
        each child not carried and the reason given, and the two totals. Not
        a secret and not a signature: it proves what was *seen*, and authority
        is asked separately.
        """
        said = {
            "term": self.term.pk,
            "from": self.from_term.pk if self.from_term else None,
            "carries": self.carries,
            "why_not": self.why_not,
            "in_new_term": self.in_new_term,
            "not_promoted": self.not_promoted,
            "classes": [
                [
                    line.class_group_id,
                    line.carried,
                    line.already_placed,
                    [[child.membership_id, child.why] for child in line.not_carried],
                ]
                for line in self.classes
            ],
        }
        return hashlib.sha256(json.dumps(said, sort_keys=True).encode()).hexdigest()

    @property
    def carried(self) -> int:
        return sum(line.carried for line in self.classes)

    @property
    def already_placed(self) -> int:
        return sum(line.already_placed for line in self.classes)

    @property
    def not_carried(self) -> int:
        return sum(len(line.not_carried) for line in self.classes)


def current_term() -> Optional[Term]:
    return Term.objects.filter(is_current=True).first()


def why_not_carried(was, term) -> str:
    """Why making `term` current, with `was` current until now, copies no class list.

    "" when it does: a later term of the same session.
    """
    if was is None:
        return "No term is current yet, so there are no class lists to carry into it."
    if was.pk == term.pk:
        return f"{term} is already the current term."
    if was.session != term.session:
        return (
            f"{term} is in another session. Class lists are not carried from one "
            f"session into the next: children move up through Promotion, which is a "
            f"separate step. Run Promotion before making this term current, or its "
            f"classes will be empty until you do."
        )
    if term.starts_on <= was.starts_on:
        return (
            f"{term} is earlier than {was}. Its class lists stay as they are; nothing "
            f"is carried backwards."
        )
    return ""


def _name(member) -> str:
    return member.display_name or member.user.full_name or member.user.username


class ReviewNotSeen(services.AcademicsError):
    """The caller has not seen the review as it stands. Nothing was changed."""


def require_seen(term, seen) -> Review:
    """The review of making `term` current, if `seen` is its token. Else refuse.

    Called inside the transaction that makes the term current, after the current
    term's row is locked, so the review compared is the one the switch will act
    on. See the module docstring, "The route requires it".
    """
    found = review(term)
    if not seen:
        raise ReviewNotSeen(
            "Look at what making this term current will do before it is made "
            "current. The current term was not changed."
        )
    if seen != found.token:
        raise ReviewNotSeen(
            "The class lists changed since you looked. Look again at what making "
            "this term current will do. The current term was not changed."
        )
    return found


def _how_they_left(membership_ids) -> dict:
    """`{membership id: sentence}` for children whose enrolment ended on a record.

    The latest `Departure` (the principal took them off the roll, G-16), else the
    principal's latest decision at a promotion, if it was "graduated" or
    "withdrawn" (G-04). A child with neither is absent, and gets `LEFT`.
    """
    ids = list(membership_ids)
    if not ids:
        return {}
    from results.models import PromotionDecision, PromotionStatus

    how = {}
    for decision in PromotionDecision.objects.filter(
        student_membership_id__in=ids,
        status__in=[PromotionStatus.GRADUATED, PromotionStatus.WITHDRAWN],
    ).order_by("student_membership_id", "-decided_at", "-id"):
        how.setdefault(
            decision.student_membership_id,
            GRADUATED if decision.status == PromotionStatus.GRADUATED else LEFT_AT_PROMOTION,
        )
    # A departure is the later and the more particular record, so it wins.
    for departure in Departure.objects.filter(student_membership_id__in=ids).order_by(
        "created_at", "id"
    ):
        how[departure.student_membership_id] = (
            f"Left the school on {departure.left_on.day} {departure.left_on:%B %Y}"
        )
    return how


def _not_promoted(was, term) -> int:
    """Children on `was`'s lists, still at the school, with no class in `term`."""
    placed = set(
        ClassPlacement.objects.filter(term=term).values_list("student_membership_id", flat=True)
    )
    waiting = set(
        ClassPlacement.objects.filter(term=was).values_list("student_membership_id", flat=True)
    ) - placed
    return Membership.objects.filter(
        pk__in=waiting,
        role=Role.STUDENT,
        status__in=LIVE_STATUSES,
        school__schema_name=connection.schema_name,
    ).count()


def review(term) -> Review:
    """What making `term` current would do to the class lists. **Writes nothing.**"""
    was = current_term()
    why_not = why_not_carried(was, term)
    result = Review(
        term=term,
        from_term=was,
        carries=not why_not,
        why_not=why_not,
        in_new_term=ClassPlacement.objects.filter(term=term).count(),
    )
    if why_not:
        if was is not None and was.name == TermName.THIRD and was.session != term.session:
            result.not_promoted = _not_promoted(was, term)
            if result.not_promoted:
                result.why_not = (
                    f"{why_not} {result.not_promoted} "
                    f"{'child' if result.not_promoted == 1 else 'children'} of {was} "
                    f"{'has' if result.not_promoted == 1 else 'have'} not been promoted "
                    f"and will be in no class in {term}."
                )
        return result

    source = list(ClassPlacement.objects.filter(term=was))
    already = set(
        ClassPlacement.objects.filter(term=term).values_list("student_membership_id", flat=True)
    )
    # The same question, asked the same way, as `carry_forward_placements()`: a
    # student of this school whose enrolment has not ended.
    members = {
        m.pk: m
        for m in Membership.objects.filter(
            pk__in=[p.student_membership_id for p in source], role=Role.STUDENT
        ).select_related("user", "school")
    }
    groups = {g.pk: g for g in ClassGroup.objects.filter(pk__in={p.class_group_id for p in source})}
    how = _how_they_left(
        p.student_membership_id
        for p in source
        if (m := members.get(p.student_membership_id)) is None
        or m.status not in LIVE_STATUSES
    )
    lines = {}
    for placement in source:
        group = groups[placement.class_group_id]
        line = lines.setdefault(group.pk, ClassLine(class_group_id=group.pk, name=group.name))
        member = members.get(placement.student_membership_id)
        still_ours = (
            member is not None
            and member.status in LIVE_STATUSES
            and member.school.schema_name == connection.schema_name
        )
        if not still_ours:
            line.not_carried.append(
                NotCarried(
                    membership_id=placement.student_membership_id,
                    name=_name(member) if member is not None else "A student who has left",
                    reference=(member.reference or "") if member is not None else "",
                    why=how.get(placement.student_membership_id, LEFT),
                )
            )
        elif placement.student_membership_id in already:
            line.already_placed += 1
        else:
            line.carried += 1
    for line in lines.values():
        line.not_carried.sort(key=lambda child: child.name.casefold())
    result.classes = sorted(lines.values(), key=lambda l: (groups[l.class_group_id].level, l.name))
    return result


def carry(was, term, *, by=None) -> int:
    """Copy `was`'s class lists into `term`, if this change of term carries them.

    Called inside the transaction that makes `term` current. Returns how many
    placements were made: 0 when nothing is carried (another session, a step back,
    no term before) and 0 on a second run.

    `services.ResultsInTheChain` propagates: a class of the new term whose results
    are already with a signatory takes nobody new (audit F-01), and the caller's
    transaction then leaves the current term where it was.
    """
    if why_not_carried(was, term):
        return 0
    return services.carry_forward_placements(was, term, by=by)


__all__ = [
    "ClassLine",
    "GRADUATED",
    "LEFT",
    "LEFT_AT_PROMOTION",
    "NotCarried",
    "Review",
    "ReviewNotSeen",
    "carry",
    "current_term",
    "require_seen",
    "review",
    "why_not_carried",
]
