# Who teaches what (`/subject-teachers/`)

The principal says which teacher teaches which subject to which class, per term. Once a
term has any of these, a teacher's marking is narrowed to the pairs they hold. Phase 2,
step 1 of the CBT plan (`docs/cbt.md` on PR #278), and nothing else from that plan.

## Decisions

| | |
| --- | --- |
| Who changes them | The principal alone (`gradebook.assignments.ASSIGNING_ROLES`). |
| Who reads them | The principal, the vice principal and the administrator (`VIEWING_ROLES`). The administrator cannot change them. |
| Shape | Many to many. One teacher teaches many pairs, and one pair can have more than one teacher, so `SubjectTeacher` is unique on (term, class, subject, teacher). `docs/cbt.md` drew it unique on the pair; the decision of 23 October 2026 widened it. |
| When marking narrows | While the paper's own term has at least one assignment. Before the first, any teacher marks any paper, exactly as before. Taking the last one away opens marking again. |
| Who is never narrowed | The principal, the vice principal and the administrator (`UNNARROWED_ROLES`). The principal and the administrator mark as before. The vice principal still has no marking role of their own (decided 23 October 2026: no new access in this change), so this matters only to one who also teaches. |
| The prompt | The principal's Home shows "Say who teaches what" while the current term has no assignment, read live, so it goes with the first one. |
| The log | Every add and every removal writes a `SubjectTeacherChange` (who, when, and the names as they read then) in the same transaction. A trigger refuses UPDATE and DELETE on it. |
| Released results | Untouched. Nothing here reads or writes a released row, and a released card refuses a mark whoever is assigned. |

Placed in `gradebook`, not `academics` as `docs/cbt.md` has it, because the row names a
`Subject` and `gradebook` already depends on `academics`.

## Where it is enforced

On the server, on every path to a mark:

- `services.set_score_as()` and `services.clear_score_as()` call `_require_assigned()`,
  which raises `NotAssignedToMark` (a `NotAllowedToMark`, so a 403) when the term has
  assignments and the child's class in that term, with the paper's subject, is not one of
  the actor's pairs. A child in no class that term cannot be marked by a narrowed teacher.
- `api.marking_sheet()` answers 403 for a pair that is not theirs.
- `api.where_to_mark()` sends a narrowed teacher one entry per paper and class they hold,
  each naming its class, and no class list, so the page cannot offer a paper from one pair
  with the class of another. The list is a courtesy; the two points above are the rule.
  (The page is within a few dozen bytes of its 150 KB budget, `tests/test_budget.py`, which
  is why the server builds that list rather than the page.)

A queued write in a teacher's outbox that is refused this way is held as final, like any
403 (`docs/offline.md` D6).

## The screen

`gradebook/views.subject_teachers_page`, `static/subject-teachers/`, routes in
`gradebook/assignments_api.py` under `/api/subject-teachers/`. One overview read; every
write answers with the whole overview. Every route asks who is asking before it looks
anything up. The principal gets a three-select form (teacher, subject, class) and a
Remove button per row that asks twice; the vice principal and the administrator get the
same list with neither. Recent changes, newest first, sit at the foot. It reuses
`setup/setup.css`, with a few layout lines in `subject-teachers.css`, and is checked at
320 px and with text at 200% in `tests/ui/screens.test.js`.

## Tests

`gradebook/tests/test_subject_teachers.py` (two schools on their own hosts, whose first
paper, subject and class share an id), `tests/js/subject_teachers.test.js`, the narrowed
cases in `tests/js/marking.test.js`, the page in `tests/test_menu.py`, `tests/test_pages.py`,
`tests/test_budget.py` and `tests/ui/screens.test.js`.

## Controls

Broken, seen red, restored, each run over the whole of `test_subject_teachers.py`
(`docs/operating-rules.md` rule 5).

| the claim | the break | what failed |
| --- | --- | --- |
| A teacher cannot save or clear a mark outside their pairs (server) | drop `_require_assigned()` from `set_score_as()` and `clear_score_as()` | 7: both "refused and nothing is written" tests, the clear, the teacher given nothing, the other school's newcomer, taking the last one away, and the released card (Kemi's write reached 423 instead of 403) |
| A teacher cannot open a sheet outside their pairs | skip the `may_mark()` check in `marking_sheet()` | 3: another subject, another class (two subtests), and the teacher given nothing |
| Until the term has an assignment, nothing changes | narrow with none: `in_force()` answers true for any term | 9 (8 failures, 1 error): every test in `UntilTheTermHasAnAssignmentNothingChanges`, the paper judged by its own term, the other school not narrowing this one, both prompt tests, and the Python rule |
| The principal is never narrowed | take the principal out of `UNNARROWED_ROLES` | 3 (2 failures, 1 error): the principal marking everything, the child with no class, and the principal's own write in the clear test |
| Only the principal changes assignments | add the administrator to `ASSIGNING_ROLES` | 8: the administrator's write and removal, its `may_change`, the same-refusal (oracle) test for both ids, and the Home prompt shown to the administrator |
| A removal is logged | skip the `SubjectTeacherChange` row in `unassign_as()` | 2 (1 failure, 1 error): who and when for both, and the page's newest-first list |
| The log cannot be edited or deleted | never create the trigger (`RunSQL` noop) | 1: `test_the_record_cannot_be_edited_or_deleted` |
| A teacher holds only their own pairs | `pairs_of()` reads every teacher's rows | 3: the teacher given nothing, the other school's newcomer, and the released card |
| Another school's teacher cannot be given a subject here | the API's `school=` filter and the service's school check, both dropped | **green, 0.** A third guard held: `accounts.staff.why_not_a_teacher_here()` refuses a membership from another schema. Rerun with all three dropped (below) |
| (all three) | also skip `why_not_a_teacher_here()` | 1: `test_the_principal_cannot_give_a_subject_to_the_other_schools_teacher`, `200 != 422` |
| A teacher at one school cannot see or mark the other | `can_enter_marks()` reads roles at any school | **green, 0.** `SchoolAccessMiddleware` refuses a login with no membership at the host's school before any view runs. Rerun with both broken (below) |
| (both) | also let the middleware pass a non-member | 1: `test_a_teacher_at_one_school_cannot_see_or_mark_the_other`, `200 != 403` (the other school's `/where/` answered) |

Every control was restored with `git checkout` and the module passes again (42 tests).
