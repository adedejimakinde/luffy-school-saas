"""What a school teaches: its subjects, this term's papers, and who is class teacher.

The office's three small writes, each of which had a model, a constraint and no writer: only
`seed_demo` could make a subject or a paper, so a real school could not start a term. Every
function here asks **who is asking** first, as `academics.services` does, and the set it asks
is `academics.services.SETUP_ROLES` (a principal or an administrator), for that module's
reason: this is office work, and a teacher who could make a paper could change what every
child's total is out of.

## What may change, and what may not

- A subject can be renamed, recoded and retired at any time. It can be **removed** only while
  no paper, in any term, names it: a paper's marks name the subject, and `PROTECT` says so in
  the database. A subject that has been taught is retired, not removed.
- A paper belongs to the **current term**. It can be renamed whenever (a released card keeps
  the name it printed, `docs/operating-rules.md` rule 2). What it is **out of** is the
  denominator of every percentage built on it, so that changes only while nobody has a mark
  in it, and it is removed only then too.
- Teachers do not teach subjects here: any teacher may mark any paper (`gradebook.services`).
  The one assignment is the class teacher, per class and term, who submits the class's results.
"""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Max

from academics import services as academics
from academics.models import ClassGroup, Term

from .models import Assessment, Score, Subject


class NotAllowedToShapeTheCurriculum(Exception):
    """The caller is not a principal or an administrator of this school."""


class CurriculumRefused(Exception):
    """The request is well formed and the school's own rules say no. The message is the reason."""


def can_shape(actor, school) -> bool:
    """May `actor` make, change or remove subjects and papers at `school`?"""
    return academics.can_set_up(actor, school)


def _require_authority(actor, school):
    if not can_shape(actor, school):
        raise NotAllowedToShapeTheCurriculum(
            f"{actor} may not change the subjects and papers at {school}. That is done by "
            f"a principal or an administrator of the school."
        )


def _clean(row, what):
    """`full_clean()` and a unique-name collision, as one sentence."""
    try:
        row.full_clean()
        with transaction.atomic():
            row.save()
    except ValidationError as exc:
        raise CurriculumRefused((exc.messages or [str(exc)])[0]) from exc
    except IntegrityError as exc:
        raise CurriculumRefused(f"That {what} is already in use.") from exc
    return row


def _text(value, what, longest):
    text = " ".join(str(value or "").split())
    if not text:
        raise CurriculumRefused(f"A {what} needs a name." if what == "subject" else "A paper needs a name.")
    if len(text) > longest:
        raise CurriculumRefused(f"A {what} name is at most {longest} characters.")
    return text


def _code(value):
    code = "".join(str(value or "").split()).upper()
    if not code:
        raise CurriculumRefused("A subject needs a short code, like MTH.")
    if len(code) > 16:
        raise CurriculumRefused("A subject code is at most 16 characters.")
    return code


def _taken(model, field, value, *, besides=None):
    rows = model.objects.filter(**{f"{field}__iexact": value})
    if besides is not None:
        rows = rows.exclude(pk=besides)
    return rows.exists()


# -- subjects ---------------------------------------------------------------------------------


def create_subject_as(actor, school, name, code):
    _require_authority(actor, school)
    name, code = _text(name, "subject", 100), _code(code)
    if _taken(Subject, "name", name):
        raise CurriculumRefused(f"{name} is already a subject here.")
    if _taken(Subject, "code", code):
        raise CurriculumRefused(f"The code {code} is already used by another subject.")
    return _clean(Subject(name=name, code=code), "subject")


def update_subject_as(actor, school, subject, name, code, is_active):
    _require_authority(actor, school)
    name, code = _text(name, "subject", 100), _code(code)
    if _taken(Subject, "name", name, besides=subject.pk):
        raise CurriculumRefused(f"{name} is already a subject here.")
    if _taken(Subject, "code", code, besides=subject.pk):
        raise CurriculumRefused(f"The code {code} is already used by another subject.")
    subject.name, subject.code, subject.is_active = name, code, bool(is_active)
    return _clean(subject, "subject")


def delete_subject_as(actor, school, subject):
    _require_authority(actor, school)
    with transaction.atomic():
        if Assessment.objects.select_for_update().filter(subject=subject).exists():
            raise CurriculumRefused(
                f"{subject.name} has papers, so it cannot be removed. Mark it as no longer taught instead."
            )
        subject.delete()


# -- papers (this term's assessments) ---------------------------------------------------------


def current_term():
    return Term.objects.filter(is_current=True).first()


def _marks_in(assessment) -> int:
    return Score.objects.filter(assessment=assessment).count()


def _out_of(value):
    try:
        out_of = int(value)
    except (TypeError, ValueError):
        raise CurriculumRefused("What a paper is out of is a whole number, like 20.")
    if not 1 <= out_of <= 1000:
        raise CurriculumRefused("A paper is out of at least 1 and at most 1000 marks.")
    return out_of


def create_paper_as(actor, school, subject, name, max_score):
    _require_authority(actor, school)
    term = current_term()
    if term is None:
        raise CurriculumRefused("No term is open, so there is nothing to add a paper to. Set the current term first.")
    name, out_of = _text(name, "paper", 64), _out_of(max_score)
    if Assessment.objects.filter(term=term, subject=subject, name__iexact=name).exists():
        raise CurriculumRefused(f"{subject.name} already has a paper called {name} this term.")
    with transaction.atomic():
        last = Assessment.objects.filter(term=term, subject=subject).aggregate(m=Max("position"))["m"]
        paper = Assessment(
            term=term, subject=subject, name=name, max_score=out_of,
            position=0 if last is None else last + 10,
        )
        return _clean(paper, "paper")


def update_paper_as(actor, school, paper, name, max_score):
    _require_authority(actor, school)
    name, out_of = _text(name, "paper", 64), _out_of(max_score)
    with transaction.atomic():
        paper = Assessment.objects.select_for_update().get(pk=paper.pk)
        if (
            Assessment.objects.filter(term=paper.term, subject=paper.subject, name__iexact=name)
            .exclude(pk=paper.pk)
            .exists()
        ):
            raise CurriculumRefused(f"{paper.subject.name} already has a paper called {name} this term.")
        if out_of != paper.max_score and _marks_in(paper):
            raise CurriculumRefused(
                f"{paper.name} already has marks, so what it is out of cannot change. "
                f"You can still rename it."
            )
        paper.name, paper.max_score = name, out_of
        return _clean(paper, "paper")


def delete_paper_as(actor, school, paper):
    _require_authority(actor, school)
    with transaction.atomic():
        paper = Assessment.objects.select_for_update().get(pk=paper.pk)
        if _marks_in(paper):
            raise CurriculumRefused(f"{paper.name} already has marks, so it cannot be removed.")
        paper.delete()


# -- class teachers ---------------------------------------------------------------------------


def teachers_of(school):
    """The school's teachers who can act now: `[(membership, name)]`, by name."""
    from accounts.models import Membership, Role

    rows = (
        Membership.objects.with_access()
        .filter(school=school, role=Role.TEACHER)
        .select_related("user")
    )
    named = [(m, m.display_name or m.user.full_name or m.user.username) for m in rows]
    return sorted(named, key=lambda pair: pair[1].lower())


def class_teacher_ids(term):
    """`{class_group_id: teacher_membership_id}` for the term."""
    from academics.models import ClassTeacher

    return dict(
        ClassTeacher.objects.filter(term=term).values_list("class_group_id", "teacher_membership_id")
    )


def assign_class_teacher_as(actor, school, class_group, membership):
    term = current_term()
    if term is None:
        raise CurriculumRefused("No term is open, so there is no one to be class teacher of. Set the current term first.")
    try:
        return academics.assign_class_teacher_as(actor, class_group, term, membership)
    except academics.NotAllowedToAssignClassTeachers as exc:
        raise NotAllowedToShapeTheCurriculum(str(exc)) from exc
    except academics.NotThisSchoolsTeacher as exc:
        raise CurriculumRefused("That is not one of this school's teachers.") from exc


def clear_class_teacher_as(actor, school, class_group):
    term = current_term()
    if term is None:
        return False
    try:
        return academics.unassign_class_teacher_as(actor, school, class_group, term)
    except academics.NotAllowedToAssignClassTeachers as exc:
        raise NotAllowedToShapeTheCurriculum(str(exc)) from exc


__all__ = [
    "CurriculumRefused",
    "NotAllowedToShapeTheCurriculum",
    "assign_class_teacher_as",
    "can_shape",
    "clear_class_teacher_as",
    "class_teacher_ids",
    "create_paper_as",
    "create_subject_as",
    "current_term",
    "delete_paper_as",
    "delete_subject_as",
    "teachers_of",
    "update_paper_as",
    "update_subject_as",
]
