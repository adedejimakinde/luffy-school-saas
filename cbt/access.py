"""Who may do what in CBT: steps 2 and 3. `docs/cbt.md`, "Who sees what".

One module so that every route and every service asks the same question, and the menu
reads the same role sets (`menu.py`). Each answer reads the roles the login holds **at
this school** (`User.roles_at()`), this school's own `ExamOfficerGrant` rows for an exam
officer, and this school's own `SubjectTeacher` rows for a teacher's reach, so a role,
a grant or an assignment at one school is nothing at another.

| | exam slips | exam officers | banks and questions | tests |
| --- | --- | --- | --- | --- |
| Principal | prints, any class | names and ends | reads and writes all | sets any; **approves** |
| Vice principal | no, unless named | no | reads all | reads all, and their questions; **approves and sends back** |
| Teacher | no, unless named | no | reads and writes their own subjects at their own levels | sets and reads their own subjects for their own classes |
| Administrator | prints, any class | sees who they are | **never**, named officer or not | title, classes, window, size and code state; **never a question** |
| Exam officer (named) | prints, any class | sees who they are | nothing beyond their own as a teacher | nothing beyond their role, in this step |
| Bursar, parent, student | no | no | never | never |

**A teacher's own** are the (subject, class) pairs the principal gave them this term
(`gradebook.assignments.pairs_of()`); their banks are those subjects at those classes'
levels. A teacher with no assignment this term has no bank and no test. The marking
switch ("Open marking to all teachers") opens marking, not banks.

**Approving** a test, or sending it back with a reason, is the principal's and the vice
principal's (decided 7 November 2026, CBT step 4). The vice principal reads every bank and
every test and their questions, writes none and sets none.

**A login holding the administrator role never reads a bank or a question**, whatever
else it holds, and being named exam officer adds nothing (decided 20 October 2026).
"""

from django.db import connection
from django.db.models import QuerySet

from dataclasses import dataclass, field

from accounts.models import Membership, Role

from .models import ExamOfficerGrant

#: Who prints exam slips by their role alone. An exam officer prints them too.
PRINTING_ROLES = frozenset({Role.PRINCIPAL.value, Role.ADMIN.value})

#: Who names and ends exam officers: the principal alone.
NAMING_ROLES = frozenset({Role.PRINCIPAL.value})

#: Whom the principal may name: a teacher, the vice principal or the administrator.
OFFICER_ROLES = frozenset(
    {Role.TEACHER.value, Role.VICE_PRINCIPAL_ACADEMIC.value, Role.ADMIN.value}
)

#: Who reads question banks, each within their own reach (`reach()`): the
#: principal and the vice principal all, a teacher their own. **Never the
#: administrator**, who runs sittings and not their content (decided 20 October 2026),
#: and being named exam officer does not change that.
BANK_ROLES = frozenset(
    {Role.PRINCIPAL.value, Role.VICE_PRINCIPAL_ACADEMIC.value, Role.TEACHER.value}
)


def _roles(actor, school) -> set:
    if not getattr(actor, "is_authenticated", False):
        return set()
    return set(actor.roles_at(school))


def _here(school) -> bool:
    """Is the connection on this school's schema? The grants read are the connection's."""
    return school is not None and connection.schema_name == school.schema_name


def officer_memberships(membership_ids) -> set:
    """Which of these memberships' latest grant, in this schema, names them an exam officer.

    `membership_ids` is a list or a query of ids. One statement either way: Postgres's
    DISTINCT ON keeps each membership's newest row, and a query is a subquery.
    """
    if isinstance(membership_ids, QuerySet):
        ids = membership_ids
    else:
        ids = list(membership_ids)
        if not ids:
            return set()
    latest = (
        ExamOfficerGrant.objects.filter(membership_id__in=ids)
        .order_by("membership_id", "-id")
        .distinct("membership_id")
        .values_list("membership_id", "kind")
    )
    return {mid for mid, kind in latest if kind == ExamOfficerGrant.Kind.NAMED}


def _officer_ids_of(actor, school):
    """The actor's memberships here that a grant could name and that can act now, as a query."""
    return (
        Membership.objects.with_access()
        .filter(user=actor, school=school, role__in=OFFICER_ROLES)
        .values("pk")
    )


def is_exam_officer(actor, school) -> bool:
    """Has the principal named one of this login's memberships here, and not ended it?

    A membership that is suspended or ended is no officer while it is so: `with_access()`
    leaves it out, as `roles_at()` does.
    """
    if not getattr(actor, "is_authenticated", False) or not _here(school):
        return False
    return bool(officer_memberships(_officer_ids_of(actor, school)))


def can_print(actor, school) -> bool:
    """May this login print exam slips here? The principal, the administrator, an exam officer."""
    if _roles(actor, school) & PRINTING_ROLES:
        return True
    return is_exam_officer(actor, school)


def can_name(actor, school) -> bool:
    """May this login name and end exam officers here? The principal alone."""
    return bool(_roles(actor, school) & NAMING_ROLES)


def can_read_banks(actor, school) -> bool:
    """Could this login read a question bank here, by its roles? Never a login holding the
    administrator role, and being named exam officer adds nothing.

    The role half of the rule. Which banks is `reach()`: a teacher with no assignment
    this term holds the role and reads none.
    """
    roles = _roles(actor, school)
    if Role.ADMIN.value in roles:
        return False
    return bool(roles & BANK_ROLES)


#: Who opens the Tests page at all: everybody who reads banks, and the administrator,
#: who sees what is set and when, and never a question.
TEST_ROLES = BANK_ROLES | frozenset({Role.ADMIN.value})

#: Who writes into banks and sets tests, each within their reach.
WRITING_ROLES = frozenset({Role.PRINCIPAL.value, Role.TEACHER.value})

#: Who approves a test, which publishes it, or sends it back: the principal and the vice
#: principal (decided 7 November 2026). Neither the teacher who set it nor the office.
APPROVING_ROLES = frozenset({Role.PRINCIPAL.value, Role.VICE_PRINCIPAL_ACADEMIC.value})


@dataclass(frozen=True)
class Reach:
    """What one login reaches in banks and tests here, for one term. Ask it, never the roles.

    `class_pairs` are the (subject id, class group id) pairs the login teaches that
    term, and `bank_pairs` the (subject id, level) pairs those make. A principal reads
    and writes all; a vice principal reads all; an administrator, a bursar, a parent and
    a student reach nothing, and `sees_tests` says whether the administrator's summary
    of the tests is theirs.
    """

    reads_all: bool = False
    writes_all: bool = False
    approves: bool = False
    #: The administrator: the Tests page, with no question on it.
    sees_test_summaries: bool = False
    class_pairs: frozenset = field(default_factory=frozenset)
    bank_pairs: frozenset = field(default_factory=frozenset)

    @property
    def reads_any_bank(self) -> bool:
        return self.reads_all or bool(self.bank_pairs)

    @property
    def opens_tests(self) -> bool:
        return self.reads_any_bank or self.sees_test_summaries or self.writes_all

    @property
    def writes_any(self) -> bool:
        return self.writes_all or bool(self.bank_pairs)

    def reads_bank(self, subject_id, level) -> bool:
        return self.reads_all or (subject_id, level) in self.bank_pairs

    def writes_bank(self, subject_id, level) -> bool:
        return self.writes_all or (subject_id, level) in self.bank_pairs

    def teaches(self, subject_id, class_group_id) -> bool:
        """May this login set a test of this subject for this class?"""
        return self.writes_all or (subject_id, class_group_id) in self.class_pairs


NOBODY = Reach()


def may_open_tests(actor, school) -> bool:
    """Does this login hold a role the Tests page answers? Roles only; no query."""
    return _here(school) and bool(_roles(actor, school) & TEST_ROLES)


def reach(actor, school, term) -> Reach:
    """What this login reaches in banks and tests here, in `term` (the test's own term).

    A login holding the administrator role reaches no bank and no question whatever else
    it holds, and only the tests' summaries. Asks the database only for a teacher's
    assignments, and only when the login holds the teacher role.
    """
    roles = _roles(actor, school)
    if not _here(school) or not roles & TEST_ROLES:
        return NOBODY
    if Role.ADMIN.value in roles:
        return Reach(sees_test_summaries=True)
    principal = Role.PRINCIPAL.value in roles
    reads_all = principal or Role.VICE_PRINCIPAL_ACADEMIC.value in roles
    class_pairs = frozenset()
    bank_pairs = frozenset()
    if Role.TEACHER.value in roles and not principal and term is not None:
        from academics.models import ClassGroup
        from gradebook import assignments

        class_pairs = frozenset(assignments.pairs_of(actor, school, term))
        levels = dict(
            ClassGroup.objects.filter(pk__in={c for _, c in class_pairs}).values_list("pk", "level")
        )
        bank_pairs = frozenset((s, levels[c]) for s, c in class_pairs if c in levels)
    return Reach(
        reads_all=reads_all,
        writes_all=principal,
        approves=bool(roles & APPROVING_ROLES),
        class_pairs=class_pairs,
        bank_pairs=bank_pairs,
    )


# -- sittings: step 4 -------------------------------------------------------------------
#
# `docs/cbt.md`, "The administrator", "Extra time" and "Exam officers". A **teacher of the
# test** is one whose reach teaches its subject to one of its classes in its term
# (`setting.teaches_it()`); the principal teaches every test. What each may do with a
# sitting:
#
# | | test code, open and close by hand | extra time | retake | the sitting log |
# | --- | --- | --- | --- | --- |
# | Teacher of the test, principal | yes | yes | yes | yes |
# | Administrator | yes | yes | no, unless named exam officer | yes, with no answer in it |
# | Exam officer | no (decided: "nothing else") | yes, any test | yes, any test | yes |
# | Vice principal | no | no, unless named | no, unless named | yes |
# | Anybody else | no | no | no | no |


def teaches_test(actor, school, test) -> bool:
    """Is this login a teacher of this test here (or the principal)? Never the office."""
    from . import setting

    reach_ = reach(actor, school, test.term)
    if reach_.sees_test_summaries:
        return False
    return reach_.writes_all or (bool(reach_.class_pairs) and setting.teaches_it(reach_, test))


def runs_sitting(actor, school, test) -> bool:
    """Sets the code, opens and closes the sitting by hand: its teachers, the principal and
    the administrator (`docs/cbt.md`, "The administrator")."""
    if not _here(school):
        return False
    if Role.ADMIN.value in _roles(actor, school):
        return True
    return teaches_test(actor, school, test)


def gives_extra_time(actor, school, test) -> bool:
    """A teacher of the test, an exam officer or the administrator (and the principal)."""
    if not _here(school):
        return False
    if Role.ADMIN.value in _roles(actor, school):
        return True
    return teaches_test(actor, school, test) or is_exam_officer(actor, school)


def grants_retake(actor, school, test) -> bool:
    """A teacher of the test or an exam officer (and the principal). Not the administrator
    by role (`docs/cbt.md`, "Settled in interpretation")."""
    if not _here(school):
        return False
    return teaches_test(actor, school, test) or is_exam_officer(actor, school)


def reads_sitting_log(actor, school, test) -> bool:
    """Who reads the sitting log: who runs it or gives time, the vice principal."""
    if not _here(school):
        return False
    roles = _roles(actor, school)
    if roles & {Role.ADMIN.value, Role.VICE_PRINCIPAL_ACADEMIC.value, Role.PRINCIPAL.value}:
        return True
    return teaches_test(actor, school, test) or is_exam_officer(actor, school)



# -- marking, CA and release: step 5 -----------------------------------------------------
#
# `docs/cbt.md`, "Who sees what", where it and the request that built step 5 differ the
# note is followed (said in the PR):
#
# | | results, item analysis | correct a key, close the test | send to CA | release | restore |
# | --- | --- | --- | --- | --- | --- |
# | Teacher of the test | their classes | yes | their classes | their classes | no |
# | Principal | all | yes | all | all | **yes, alone** |
# | Vice principal | all, read | no | no | no | no |
# | Administrator | **released scores only**, no answer and no item | no | no | no | no |
# | Exam officer | nothing beyond their role | no | no | no | no |
# | Bursar, parent, student | no | no | no | no | no |
#
# A student sees their own released score, and a parent their own child's, on
# `/test-scores/` (`cbt.release`), never here.

#: Who restores a release: the principal alone (`docs/cbt.md`, "TestReleaseRestore").
RESTORING_ROLES = frozenset({Role.PRINCIPAL.value})


def marks_test(actor, school, test) -> bool:
    """Corrects its keys, closes it, sends to CA and releases: a teacher of the test, the
    principal. Never the vice principal, the office or an exam officer as such."""
    if not _here(school):
        return False
    return teaches_test(actor, school, test)


def reads_results(actor, school, test) -> bool:
    """Reads its results with the answers and the item analysis: who marks it, and the vice
    principal (read). Not the administrator, who sees released scores only."""
    if not _here(school):
        return False
    roles = _roles(actor, school)
    if Role.ADMIN.value in roles:
        return False
    if Role.VICE_PRINCIPAL_ACADEMIC.value in roles or Role.PRINCIPAL.value in roles:
        return True
    return marks_test(actor, school, test)


def reads_released_only(actor, school, test) -> bool:
    """The administrator: a test's scores once released, with no answer and no item."""
    return _here(school) and Role.ADMIN.value in _roles(actor, school)


def restores(actor, school) -> bool:
    return _here(school) and bool(_roles(actor, school) & RESTORING_ROLES)


def classes_of(actor, school, test, audience) -> set:
    """Which of the test's classes (`audience`, ids) this login's results reach: all of
    them for the principal and the vice principal, a teacher's own for that subject."""
    from . import setting

    reach_ = reach(actor, school, test.term)
    if reach_.reads_all:
        return set(audience)
    subject_id, _ = setting.subject_and_level(test)
    return {c for c in audience if reach_.teaches(subject_id, c)}


def menu_keys(roles, actor, school) -> frozenset:
    """Links a login holds by a permission rather than a role: the exam slips page for an
    exam officer whose roles alone would not show it (`menu.py`).

    Asks the database only for a login that could be named and does not already print
    by role, so the principal, the administrator, a bursar and a parent cost nothing.
    """
    roles = set(roles)
    if not roles & OFFICER_ROLES or roles & PRINTING_ROLES:
        return frozenset()
    return frozenset({"exam-slips"}) if is_exam_officer(actor, school) else frozenset()


__all__ = [
    "APPROVING_ROLES",
    "BANK_ROLES",
    "NOBODY",
    "Reach",
    "TEST_ROLES",
    "WRITING_ROLES",
    "NAMING_ROLES",
    "OFFICER_ROLES",
    "PRINTING_ROLES",
    "RESTORING_ROLES",
    "can_name",
    "classes_of",
    "marks_test",
    "reads_released_only",
    "reads_results",
    "restores",
    "can_print",
    "can_read_banks",
    "gives_extra_time",
    "grants_retake",
    "is_exam_officer",
    "reads_sitting_log",
    "runs_sitting",
    "teaches_test",
    "may_open_tests",
    "menu_keys",
    "officer_memberships",
    "reach",
]
