"""How many papers a class still has unmarked, per subject. Audit finding F-05.

`submit`, `check` and `approve` asked who was pressing and what state the sheet
was in, and never whether the marks were all there. A child with one paper
unmarked has no total and no grade in that subject and is not ranked
(`docs/positions.md`). That is the rule for a child who missed a paper, and it
is also what happens when a teacher has simply not finished, and the chain
could not tell the two apart or say that either was so.

## What is counted

One for every child on the class's roster and every paper of a subject, where
the child has no mark in that paper. So a class of forty with one paper not
entered at all counts forty, and one forgotten cell counts one.

**Only subjects the class has a mark in**, which is how `class_results()` draws
a class's subject list: there is no record of which class takes which subject
(audit finding F-03), so a subject nobody in the class has a mark in is not
known to be theirs. A subject taught to the class and not yet marked for
anybody is therefore not counted here. It is a blank column on the broadsheet,
which the signatory still reads.

Three queries whatever the size of the class: the roster, the term's papers by
subject, and the class's marks by subject.
"""

from dataclasses import dataclass

from django.db.models import Count

from academics.models import ClassPlacement
from gradebook.models import Assessment, Score


@dataclass(frozen=True)
class SubjectUnmarked:
    subject_id: int
    subject: str
    unmarked: int


def for_class(class_group, term) -> list[SubjectUnmarked]:
    """The subjects with papers still unmarked for this class, by name. Empty if none."""
    students = ClassPlacement.objects.student_ids(class_group, term)
    if not students:
        return []
    # `.order_by()` on both: each model's `Meta.ordering` would otherwise join
    # the GROUP BY, the trap `positions._subject_totals()` documents.
    marked = dict(
        Score.objects.filter(assessment__term=term, student_membership_id__in=students)
        .order_by()
        .values_list("assessment__subject_id")
        .annotate(n=Count("pk"))
    )
    if not marked:
        return []
    papers = (
        Assessment.objects.filter(term=term, subject_id__in=marked)
        .order_by()
        .values_list("subject_id", "subject__name")
        .annotate(n=Count("pk"))
    )
    found = [
        SubjectUnmarked(subject_id, name, n * len(students) - marked[subject_id])
        for subject_id, name, n in papers
    ]
    return sorted((s for s in found if s.unmarked > 0), key=lambda s: s.subject.lower())


def total(subjects) -> int:
    return sum(s.unmarked for s in subjects)


__all__ = ["SubjectUnmarked", "for_class", "total"]
