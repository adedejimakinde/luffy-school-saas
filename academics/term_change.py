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
"""

from dataclasses import dataclass, field
from typing import List, Optional

from django.db import connection

from accounts.models import LIVE_STATUSES, Membership, Role

from . import services
from .models import ClassGroup, ClassPlacement, Term

#: Why a child on last term's list is not carried. The membership records that an
#: enrolment ended and not how, so one sentence covers a leaver and a graduate.
LEFT = "No longer at the school (left or graduated)"


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
    "LEFT",
    "NotCarried",
    "Review",
    "carry",
    "current_term",
    "review",
    "why_not_carried",
]
