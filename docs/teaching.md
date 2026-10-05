# Subjects, papers and class teachers (`/teaching/`)

The office's screen for what a school teaches. Until it existed, a subject, a paper (an
`Assessment`: First CA, Exam) and a class teacher could only be made by `seed_demo` or the shell,
so a real school could not start a term. Found by the first-school pilot run
(`docs/handover.md`, 2026-10-05).

**Who:** a principal or an administrator (`academics.services.SETUP_ROLES`, the same set that
sets up the calendar and the class groups, and the same set `CLASS_TEACHER_ROLES` names). Nobody
else sees the link, and every route refuses everybody else with one sentence, **before** it looks
anything up (the oracle rule).

**Where:** page `gradebook/views.teaching_page` and `static/teaching/`; routes
`gradebook/teaching_api.py` under `/api/teaching/`; every rule in `gradebook/curriculum.py`.
One overview read, and every write answers with the whole overview, so the page redraws from the
school's answer. It reuses `setup/setup.css`; there is no new design.

## What it does

| | |
| --- | --- |
| Class teachers | One select per active class, saved as it is chosen; "No class teacher" clears. For the **current term** (`ClassTeacher` is per class and term). Only an active TEACHER membership of this school can be chosen. |
| Subjects | List, add (name, short code), edit (name, code, "no longer taught"), remove. |
| Papers | This term's papers of one subject: list, add (name, out of), edit, remove. Added after the others. |

## The rules

- **A subject is removed only while no paper in any term names it.** One that has been taught is
  marked "no longer taught" (`Subject.is_active`), which keeps old marks readable.
- **A paper's "out of" is the denominator of every percentage built on it**, so it changes, and the
  paper is removed, only while nobody has a mark in it. Renaming is always allowed (a released card
  keeps the name it printed, `docs/operating-rules.md` rule 2).
- **Names and codes are unique without regard to capitals**, a sentence rather than a 500.
- **No current term:** papers and class teachers cannot be added, and the page says where to set it.
- **Removing asks twice.**
- Teachers are not assigned to subjects: any teacher may mark any paper
  (`gradebook.services.can_enter_marks`). The one assignment is the class teacher, who submits the
  class's results.

## Tests

`gradebook/tests/test_teaching.py` (access for every role on the read and every write, with a
refused write changing nothing; the rules; two schools whose first subject, paper and class share
an id), `tests/js/teaching.test.js`, `tests/ui/teaching.test.js` (an administrator builds a subject,
a paper and a class teacher at 360px, a teacher finds the paper on the marking page, and it is put
back) and the page in `tests/ui/screens.test.js`.

**Control for the access check** (broken, seen red, restored): `curriculum.can_shape` was made to
admit a teacher as well; `WhoMayOpenIt` failed for the teacher on the writes and on the sameness of the refusal
(first six failures seen), and passed again with the check restored.
