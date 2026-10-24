# Who teaches what (`/subject-teachers/`)

The principal says which teacher teaches which subject to which class, per term. Once a
term has had any of these, a teacher's marking is narrowed to the pairs they hold, until
the principal deliberately opens it again. A new term starts with the last one's
assignments copied in. Phase 2, step 1 of the CBT plan (`docs/cbt.md`), and
its follow-up; nothing else from that plan.

## Decisions

| | |
| --- | --- |
| Who changes them | The principal alone (`gradebook.assignments.ASSIGNING_ROLES`). |
| Who reads them | The principal, the vice principal and the administrator (`VIEWING_ROLES`). The administrator cannot change them. |
| Shape | Many to many. One teacher teaches many pairs, and one pair can have more than one teacher, so `SubjectTeacher` is unique on (term, class, subject, teacher). `docs/cbt.md` first drew it unique on the pair; the decision of 23 October 2026 widened it, and the note now says so. |
| When marking narrows | From the paper's own term's first assignment. Before the first, any teacher marks any paper, exactly as before. **Taking the last one away opens nothing** (decided 23 October 2026): the term stays restricted, and a teacher holding nothing marks nothing and is told to ask the principal. |
| Opening it again | Only by the principal's switch on `/subject-teachers/`, "Open marking to all teachers", which first says what will happen and does it on the second tap. "Restrict marking again" is the same switch the other way. While open, adding an assignment does not restrict it again: neither direction happens silently. The vice principal and the administrator see where the switch stands and cannot turn it. Before a term's first assignment there is nothing to switch (422). |
| Where a term stands | A fold over the log, never a column (`assignments.marking_in()`, `docs/operating-rules.md` rule 4): the principal's latest switch row if there is one, else restricted once the term has had an `added` row, else "not yet". |
| A new term | When the current term moves on to a later one (`PUT /api/academics/terms/{id}/current/`), the term that was current until then has its assignments copied in, in the same transaction (`assignments.carry_forward()`). Only into a term that has never had an assignment of its own, and only forward, so switching back and forth copies nothing twice. If the last term had none, nothing at all is written and the new term marks exactly as today. If the principal had opened the last term, the new one starts open too, so a new term never quietly narrows what the principal opened. |
| What is not copied | A teacher who has left or no longer has teacher access here (an ended or suspended membership, or no TEACHER membership at this school), a subject no longer taught and a closed class, the same rules `assign_as()` keeps. Each is written down as `skipped` with its reason (rule 8: a skip leaves nothing else behind). |
| The copy's record | Every copied row writes an `added` change naming nobody (`by_id` empty: the system) and the term it came from (`from_term`, and its name as it read then). A constraint allows an empty `by_id` only on such a row. |
| The review card | After a copy, the principal's Home shows "Assignments copied from last term, review them" (`home/parts/carried.html`), saying how many were copied and how many were not. It goes when the principal opens `/subject-teachers/` in that term (the overview read marks `SubjectTeacherCarry.seen_at`) or presses Dismiss (`POST /subject-teachers/seen/`, the principal's alone). The vice principal or the administrator opening the page does not count. |
| Who is never narrowed | The principal, the vice principal and the administrator (`UNNARROWED_ROLES`). The principal and the administrator mark as before. The vice principal still has no marking role of their own (decided 23 October 2026: no new access in this change), so this matters only to one who also teaches. |
| The prompt | The principal's Home shows "Say who teaches what" while the current term has never had an assignment, read live, so it goes with the first one and does not come back when the last is taken away. |
| The log | Every add, every removal, every copy and every turn of the switch writes a `SubjectTeacherChange` (who, when, and the names as they read then) in the same transaction. A trigger refuses UPDATE and DELETE on it. |
| Released results | Untouched. Nothing here reads or writes a released row, and a released card refuses a mark whoever is assigned. |

Placed in `gradebook`, not `academics` as `docs/cbt.md` first had it, because the row names a
`Subject` and `gradebook` already depends on `academics`.

## Where it is enforced

On the server, on every path to a mark:

- `services.set_score_as()` and `services.clear_score_as()` call `_require_assigned()`,
  which raises `NotAssignedToMark` (a `NotAllowedToMark`, so a 403) when the term is
  restricted and the child's class in that term, with the paper's subject, is not one of
  the actor's pairs. A teacher holding no pair holds none of them. A child in no class
  that term cannot be marked by a narrowed teacher.
- `api.marking_sheet()` answers 403 for a pair that is not theirs.
- `api.where_to_mark()` sends a narrowed teacher one entry per paper and class they hold,
  each naming its class, and no class list, so the page cannot offer a paper from one pair
  with the class of another. The list is a courtesy; the two points above are the rule.
  A narrowed teacher holding nothing gets an empty list and "No subjects for you yet. Ask
  the principal to give you your subjects and classes." (`static/marking/states.js`).
  (The page is within a few dozen bytes of its 150 KB budget, `tests/test_budget.py`, which
  is why the server builds that list rather than the page. After this change it weighs
  153,583 bytes of 153,600.)
- The switch: `assignments_api.set_marking()` (`PUT /api/subject-teachers/marking/`) asks
  `can_assign()` before anything else, and `assignments.set_open_as()` asks it again.
- The copy: `academics.api.set_current_term()`, behind `SETUP_ROLES` as before, calls
  `carry_forward()` with the request's school; the copy reads teachers from that school's
  memberships alone, so a row naming anybody else is skipped, never copied.

A queued write in a teacher's outbox that is refused this way is held as final, like any
403 (`docs/offline.md` D6).

## The screen

`gradebook/views.subject_teachers_page`, `static/subject-teachers/`, routes in
`gradebook/assignments_api.py` under `/api/subject-teachers/`. One overview read; every
write answers with the whole overview. Every route asks who is asking before it looks
anything up. The principal gets a three-select form (teacher, subject, class) and a
Remove button per row that asks twice, and the switch under the sentence saying where
marking stands, which also asks twice; the vice principal and the administrator get the
same list and the same sentence with none of them. A term that began with a copy says
so, and from which term. Recent changes, newest first, sit at the foot, the copied and the
not-copied lines among them. It reuses
`setup/setup.css`, with a few layout lines in `subject-teachers.css`, and is checked at
320 px and with text at 200% in `tests/ui/screens.test.js`.

## Tests

`gradebook/tests/test_subject_teachers.py` (two schools on their own hosts, whose first
paper, subject and class share an id; the carry-forward tests move both to a second term), `tests/js/subject_teachers.test.js`, the narrowed
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

### The follow-up: carry-forward, the switch, no silent opening

The same method, run over the whole of `test_subject_teachers.py` (76 tests) with the
break applied in a separate worktree and restored with `git checkout` after each run.

| the claim | the break | what failed |
| --- | --- | --- |
| Taking the last assignment away does not open marking | `marking_in()` reads only today's rows, not the log ("while it has one") | 6: every test in `ATermThatHasHadOneStaysRestrictedTests` that asks the term, the teacher's page, the server (open, save, clear) and the Home prompt |
| Only the principal turns the switch | the route asks `can_view()` instead of `can_assign()` | **green, 0.** `set_open_as()` asks again and refused. Rerun with both (below) |
| (both) | also drop `_require_assigning_authority()` from `set_open_as()` | 6 (subtests of `test_only_the_principal_turns_it`): the vice principal and the administrator opened marking |
| Each turn of the switch is written down | `set_open_as()` writes no row | 8 (7 failures, 1 error): every switch test, because the row is the state (`marking_in()`), so an unwritten turn is also a turn that did not happen |
| The carry-forward never copies across schools | read the rows' teachers from every school's memberships, not this one's | 1: `test_a_row_naming_another_schools_teacher_is_never_copied`. The schema check in `why_not_a_teacher_here()` still kept the row out; what failed is the other school's teacher's name written into this school's log |
| (both) | also skip `why_not_a_teacher_here()` in `_why_not_copied()` | 1: the same test, now because the other school's teacher was copied into this school's new term |
| A teacher who has left or lost teacher access is not copied | drop `with_access()` from the copy's teacher lookup | 1: `test_a_teacher_who_has_left_or_lost_teacher_access_is_not_copied` |
| A teacher holding nothing in a restricted term is refused a save and a clear (server) | `_require_assigned()` lets a teacher who holds no pair through | 14: the teacher given nothing, the restricted term's open/save/clear, the switch tests that restrict again, the other school's newcomer, and both released-card tests |
| A teacher holding nothing is refused the sheet (server) | `may_mark()` answers true for a teacher who holds no pair | 3: the teacher given nothing, and the restricted term's open/save/clear (two subtests) |
| If the last term had none, nothing changes | `carry_forward()` goes on with no rows | 1: `test_with_none_last_term_nothing_at_all_changes` (a carry row and its card appeared) |
| A term the principal opened starts the next one open | never carry the switch | 1: `test_a_term_the_principal_had_opened_starts_open` |
| Only the principal dismisses the card | the dismiss view asks nothing but the host | 3 (subtests of `test_only_the_principal_dismisses_it`) |
| Only the principal's look clears the card | `seen_as()` asks nothing | 1: `test_the_vice_principal_or_the_administrator_opening_it_does_not_count` |
| The copy runs forward, once | drop the forward and never-had-one checks | 2 (1 failure, 1 error): going back copies into the earlier term, and going forward again copies twice (the unique constraint refuses it) |
| Opening marking never opens a released card | `set_score()` skips both of its release guards | 2 errors: both released-card tests, where the database's own trigger (`gradebook/0002_a_released_mark_stays_released`) refused the write instead of a 423 |

Every control was restored with `git checkout`, the tree was checked clean after each,
and the module passes again (76 tests).
