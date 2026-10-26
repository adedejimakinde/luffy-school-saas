"""Start again: clear a school's setup while it has no real records yet.

A school trying Classnode out adds classes, a term, a roll, and then wants to
begin from a clean page. This is that, and only that.

## Who, and when

- **The principal only**, by their active membership (`roles_at()`), not the
  administrator and not platform staff. It is the one setup act that undoes
  other people's work, so it belongs to whoever answers for the school.
- **Only while the school has no real records**: no marks (and no report card
  comments or ratings), no attendance, no fees charged, paid or excused, and no
  released results. Each of those is history somebody relies on, and none of
  it is ever cleared here; the page says which one stops it.
- **Typed confirmation**: the school's name, exactly (ignoring case and
  spaces), and the plan the page showed must still be the plan when it runs
  (`Plan.fingerprint`), so what was listed is exactly what is cleared.

## What it clears, and what it never touches

Cleared: terms, classes, the students on the roll (their membership here is
ended, as a transfer ends it, and their details at this school go), subjects
and their papers, fee items, class and subject teachers, and the timetable.

Never touched: the school itself and its details (name, contact email, crest,
colour, website), every member of staff and their account, staff invitations,
the report card's choices, and the setup log. A term or a class that a
permanent record names (the record of who taught what, printed exam PINs) is
kept, and the page says so and why.

One transaction, logged inside it (`audit.log.record()`): it all happens and
is written down, or none of it does.
"""

import hashlib
import json
from dataclasses import dataclass, field

from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.utils import timezone

from accounts.models import LIVE_STATUSES, Membership, Role
from accounts.services import release_student
from audit import log

#: Who may start the setup again.
AGAIN_ROLES = frozenset({Role.PRINCIPAL.value})


class NotAllowedToStartAgain(Exception):
    """The caller is not this school's principal."""


class StartAgainRefused(Exception):
    """The school has real records, the name was not typed, or the plan moved on."""


@dataclass
class Plan:
    #: Sentences, one per kind of real record found. Any at all and nothing is cleared.
    blockers: list = field(default_factory=list)
    #: `(label, count, names)` for each kind of setup item that will be cleared.
    clears: list = field(default_factory=list)
    #: `(what, why)` for each setup item that stays.
    keeps: list = field(default_factory=list)
    #: Ids, for the clearing to act on exactly what was listed.
    term_ids: list = field(default_factory=list)
    class_ids: list = field(default_factory=list)
    subject_ids: list = field(default_factory=list)
    student_ids: list = field(default_factory=list)

    @property
    def possible(self) -> bool:
        return not self.blockers

    @property
    def anything(self) -> bool:
        return any(count for _, count, _ in self.clears)

    @property
    def fingerprint(self) -> str:
        body = json.dumps(
            [self.blockers, self.clears, self.keeps, self.term_ids, self.class_ids,
             self.subject_ids, self.student_ids],
            sort_keys=True, default=str,
        )
        return hashlib.sha256(body.encode()).hexdigest()[:20]


def may_start_again(actor, school) -> bool:
    if not getattr(actor, "is_authenticated", False):
        return False
    return bool(set(actor.roles_at(school)) & AGAIN_ROLES)


# -- what the school holds -------------------------------------------------------


def _count(sql) -> int:
    with connection.cursor() as cursor:
        cursor.execute(sql)
        return cursor.fetchone()[0]


#: The real records, each a reason in plain words. Read in the school's schema.
_BLOCKERS = (
    ("SELECT count(*) FROM gradebook_score", "marks have been entered"),
    (
        "SELECT (SELECT count(*) FROM results_reportcardcomment) + (SELECT count(*) FROM results_traitrating)",
        "report card comments or ratings have been written",
    ),
    ("SELECT count(*) FROM attendance_register", "a register has been taken"),
    (
        "SELECT (SELECT count(*) FROM fees_feeledgerentry) + (SELECT count(*) FROM fees_feeconcession)"
        " + (SELECT count(*) FROM fees_unmatchedpayment) + (SELECT count(*) FROM fees_virtualaccount)",
        "fees have been charged, paid, excused or given an account number",
    ),
    (
        "SELECT (SELECT count(*) FROM results_releasedcard)"
        " + (SELECT count(*) FROM results_resultsheet WHERE state = 'released')"
        " + (SELECT count(*) FROM results_releasedsessionresult)"
        " + (SELECT count(*) FROM results_promotiondecision)",
        "results have been released",
    ),
)


def _cleared_models():
    """The setup items cleared before terms, classes and subjects go: anything
    pointing at one of those from here does not keep it."""
    from academics.models import ClassPlacement, ClassTeacher
    from fees.models import FeeSchedule, FeeScheduleLine
    from gradebook.models import Assessment, SubjectTeacher, SubjectTeacherCarry
    from timetable.models import Period, TimetableSlot

    return (
        TimetableSlot, Period, SubjectTeacher, SubjectTeacherCarry, ClassTeacher,
        ClassPlacement, FeeScheduleLine, FeeSchedule, Assessment,
    )


def _sheets_cleared():
    """Result sheets nobody has done anything with: opened by being looked at,
    still in draft, with no step taken. Any other sheet is history."""
    from results.models import ResultSheet, SheetState

    return ResultSheet.objects.filter(state=SheetState.DRAFT, transitions__isnull=True)


#: Why a permanent record keeps a term, a class or a subject, by model.
_KEPT_BECAUSE = {
    "gradebook.SubjectTeacherChange": "the record of who taught what in it is kept for good",
    "cbt.ExamPin": "exam PINs were printed for it",
    "cbt.PinSlipPrint": "exam PINs were printed for it",
    "notices.Notice": "messages to families name it",
    "results.ResultSheet": "its results have started through approval",
}


def _held(model) -> dict:
    """`{id: reason}` for the rows of `model` something permanent still names.

    Every relation into `model` is asked, hidden ones included, except those
    from the setup items this clears: so a table added later that points at a
    term keeps it here without anybody remembering to say so."""
    from results.models import ResultSheet

    cleared = set(_cleared_models())
    held = {}
    for rel in model._meta.get_fields(include_hidden=True):
        if not (rel.auto_created and not rel.concrete and (rel.one_to_many or rel.one_to_one)):
            continue
        source = rel.related_model
        if source in cleared:
            continue
        rows = source._base_manager.all()
        if source is ResultSheet:
            rows = rows.exclude(pk__in=_sheets_cleared().values("pk"))
        why = _KEPT_BECAUSE.get(source._meta.label, f"{source._meta.verbose_name_plural} name it")
        for pk in rows.values_list(rel.field.attname, flat=True).distinct():
            if pk is not None:
                held.setdefault(pk, why)
    return held


def plan(school) -> Plan:
    """What starting again would clear at `school` now, and what stops it.

    Read in the school's own schema: the caller is on the school's host."""
    from academics.models import ClassGroup, ClassPlacement, ClassTeacher, Term
    from fees.models import FeeScheduleLine
    from gradebook.models import Assessment, Subject, SubjectTeacher
    from timetable.models import Period, TimetableSlot

    if connection.schema_name != school.schema_name:
        raise RuntimeError(f"Asked about {school.schema_name} on {connection.schema_name}.")

    p = Plan()
    p.blockers = [why for sql, why in _BLOCKERS if _count(sql)]

    held_terms, held_classes, held_subjects = _held(Term), _held(ClassGroup), _held(Subject)
    terms = list(Term.objects.order_by("starts_on", "pk"))
    classes = list(ClassGroup.objects.order_by("level", "name", "pk"))
    subjects = list(Subject.objects.order_by("name", "pk"))
    p.term_ids = [t.pk for t in terms if t.pk not in held_terms]
    p.class_ids = [c.pk for c in classes if c.pk not in held_classes]
    p.subject_ids = [s.pk for s in subjects if s.pk not in held_subjects]
    p.student_ids = list(
        Membership.objects.filter(school=school, role=Role.STUDENT, status__in=LIVE_STATUSES)
        .order_by("pk").values_list("pk", flat=True)
    )

    def names(rows, ids):
        return [str(r) for r in rows if r.pk in ids]

    p.clears = [
        ("Terms", len(p.term_ids), names(terms, p.term_ids)),
        ("Classes", len(p.class_ids), [c.name for c in classes if c.pk in p.class_ids]),
        ("Students on the roll, and their details here", len(p.student_ids), []),
        ("Subjects", len(p.subject_ids), [s.name for s in subjects if s.pk in p.subject_ids]),
        ("Papers, such as First CA and Exam", Assessment.objects.count(), []),
        ("Fee items", FeeScheduleLine.objects.count(), []),
        ("Class teachers and subject teachers", ClassTeacher.objects.count() + SubjectTeacher.objects.count(), []),
        ("Class places for this and other terms", ClassPlacement.objects.count(), []),
        ("Timetable periods and lessons", Period.objects.count() + TimetableSlot.objects.count(), []),
    ]
    p.keeps = [
        ("Your school, its name, contact email, crest, colour and website", "These are your school, not its setup."),
        ("Every member of staff, their accounts, and invitations still waiting", "Staff are never removed by starting again."),
        ("Your report card choices", "The card, its traits and its grades stay as you chose them."),
        ("The record of setup changes", "Starting again is written down there too."),
    ]
    for t in terms:
        if t.pk in held_terms:
            p.keeps.append((f"The term {t}", f"Kept because {held_terms[t.pk]}."))
    for c in classes:
        if c.pk in held_classes:
            p.keeps.append((f"The class {c.name}", f"Kept because {held_classes[c.pk]}."))
    for s in subjects:
        if s.pk in held_subjects:
            p.keeps.append((f"The subject {s.name}", f"Kept because {held_subjects[s.pk]}."))
    return p


def _same_name(typed, school) -> bool:
    def norm(text):
        return " ".join(str(text or "").split()).casefold()

    return bool(norm(typed)) and norm(typed) == norm(school.name)


def start_again_as(actor, school, *, typed_name, fingerprint) -> Plan:
    """Clear `school`'s setup as `plan()` lists it, or refuse and change nothing."""
    from academics.models import ClassGroup, ClassPlacement, ClassTeacher, StudentDetails, Term
    from fees.models import FeeSchedule, FeeScheduleLine
    from gradebook.models import Assessment, Subject, SubjectTeacher, SubjectTeacherCarry
    from schools.models import School
    from timetable.models import Period, TimetableSlot

    if not may_start_again(actor, school):
        raise NotAllowedToStartAgain(f"{actor} may not start {school}'s setup again. Only its principal may.")
    if not _same_name(typed_name, school):
        raise StartAgainRefused(f"Type your school's name, {school.name}, to start again.")

    with transaction.atomic():
        # One start-again at a time per school: the second waits here and then
        # finds the plan it was shown has moved on.
        School.objects.select_for_update().filter(pk=school.pk).first()
        p = plan(school)
        if not p.possible:
            raise StartAgainRefused(
                "Your school cannot start again, because " + "; ".join(p.blockers)
                + ". Those records are kept for good."
            )
        if p.fingerprint != fingerprint:
            raise StartAgainRefused(
                "Something changed since this page was opened. Check the list again before you start again."
            )
        try:
            with transaction.atomic():
                TimetableSlot.objects.all().delete()
                Period.objects.all().delete()
                SubjectTeacher.objects.all().delete()
                SubjectTeacherCarry.objects.all().delete()
                ClassTeacher.objects.all().delete()
                ClassPlacement.objects.all().delete()
                _sheets_cleared().delete()
                FeeScheduleLine.objects.all().delete()
                FeeSchedule.objects.all().delete()
                Assessment.objects.all().delete()
                Subject.objects.filter(pk__in=p.subject_ids).delete()
                ClassGroup.objects.filter(pk__in=p.class_ids).delete()
                Term.objects.filter(pk__in=p.term_ids).delete()
                StudentDetails.objects.filter(student_membership_id__in=p.student_ids).delete()
                for student in Membership.objects.filter(pk__in=p.student_ids).select_related("user", "school"):
                    release_student(student)
        except (ProtectedError, IntegrityError) as exc:
            raise StartAgainRefused(
                "Something else at your school still uses one of these, so nothing was cleared. "
                "Contact Classnode support and we will look."
            ) from exc

        School.objects.filter(pk=school.pk).update(setup_completed_at=None)
        school.setup_completed_at = None
        cleared = [f"{count} {label.lower()}" for label, count, _ in p.clears if count]
        log.record(
            actor, school,
            action="started-again", kind="setup",
            item_name=school.name,
            summary="Started the setup again. Cleared " + (", ".join(cleared) if cleared else "nothing") + ".",
            before={
                "clears": [{"what": label, "count": count, "names": names} for label, count, names in p.clears],
                "kept": [{"what": what, "why": why} for what, why in p.keeps],
                "at": timezone.now().isoformat(),
            },
        )
    return p


__all__ = [
    "AGAIN_ROLES",
    "NotAllowedToStartAgain",
    "Plan",
    "StartAgainRefused",
    "may_start_again",
    "plan",
    "start_again_as",
]
