# The timetable

Who teaches which subject to which class, and when. T1, decided 2026-09-24.

The API is at `/api/timetable/` (`timetable/api.py`), the page is at
`/timetable/`, and the rules are in `timetable/services.py`, so an import and a
management command meet the same rules as the screen.

## What was decided, and where each decision holds

| decision | where it holds |
| --- | --- |
| **One bell schedule per school.** The same periods every weekday, for every class and every term. A break is the gap between two periods, not a row | `Period`; `periods_do_not_overlap`, an exclusion constraint on `[starts_at, ends_at)` |
| **A subject and a teacher per slot.** A double period is two slots; a free period is no slot at all | `TimetableSlot`; `one_lesson_per_class_per_slot` |
| **A clash is refused unless it is the same subject.** A teacher may take two classes at once only when both are having the same lesson, a combined class | `a_teacher_teaches_one_subject_at_a_time`, an exclusion constraint with `subject WITH <>` |
| **A timetable per term, with copy-last-term** | `TimetableSlot.term`; `services.copy_last_term()` |
| **Every teacher reads it; the administrator and the vice principal (academic) edit it** | `services.may_read()` / `may_edit()`, asked by every route |

T2, limiting marks entry to the timetabled teacher, is
[issue #142](https://github.com/adedejimakinde/luffy-school-saas/issues/142).

## The clash rule is in the database

Two rows conflict when they share the term, the weekday, the period and the
teacher **and differ in subject**. The `<>` is the whole of the combined-lesson
rule: without it the constraint would say "a teacher is in one room at a
time", and a school that teaches JSS 1A and JSS 1B mathematics together in the
hall could not record it. Both halves have a test that writes rows straight
into the table, past the service.

The service catches the refusal and turns it into a sentence that names the
other lesson ("That teacher is teaching Mathematics to JSS 1B in that
period"). The sentence is a second read after the refusal, so if the other row
has gone in between, the refusal still stands and the sentence is vaguer.

The clash is keyed on the **period**, not on clock times. That is correct only
because there is one bell schedule per school and periods cannot overlap, so
one period is one stretch of time. A second bell schedule (a shorter Friday,
say) would break that equivalence, and the constraint would need to compare
times instead.

`<>` on an integer needs `btree_gist`. Migration 0001 installs it into
`public` by name, and its docstring says why that matters: the migration runs
once per school, and a bare `CREATE EXTENSION` would put it in the first
school's schema, where no other school can see it.

## Periods

A period has a start, an end and an optional name ("Period 1", "Assembly").
The periods are ordered by when they start. There is no stored number, because
a number would be a second answer to "which comes first" that could disagree
with the clock.

Ranges are half-open, `[)`, so 08:00–08:40 and 08:40–09:20 share an instant
and no time. A closed range would refuse every school's back-to-back periods.

Changing a period's times moves it for every term, past ones included. The
timetable is a working record: last term's lessons were in "Period 3" whatever
time the bell now rings for it. A period that has lessons in it cannot be
removed; clear the lessons first, so nobody's timetable loses a row without
somebody deciding it.

## Copying last term

`copy_last_term()` fills an **empty** term from the term that started most
recently before it. It never writes over a term that already has lessons
(`TimetableNotEmpty`, a 409): a copy that wrote over lessons somebody had
already set would destroy work nobody asked to lose. The target term's row is
locked first, so two copies into one term cannot both see it empty.

It copies only what still exists. A lesson whose class or subject has been
retired, or whose teacher no longer teaches at the school, is left behind and
counted, and the page says how many and why. The teacher read is scoped to the
schema being written, so a row naming another school's teacher is left behind
too.

## Who

| | reads | edits |
| --- | --- | --- |
| every teacher | yes | no, told so in a sentence (403) |
| principal | yes | no, told so in a sentence (403) |
| vice principal (academic) | yes | yes |
| administrator | yes | yes |
| anybody else | flat 404 before any lookup | flat 404 |

Access-scoped, like every authority question here: an invited or suspended
teacher reads nothing. The landing page offers the link on the same predicate
(`may_see_timetable`), so a bursar is not sent to a page that answers with a
404.

**The teacher is looked up with `school=` in the query.** The teacher is a bare
membership id into the shared table, so a lookup without the school would find
another school's teacher. They are not found and not named; the answer is
"Choose one of the school's teachers."

## The routes

| route | who | what |
| --- | --- | --- |
| `GET /?term_id=` | readers | the terms, classes, periods and days; for an editor, the subjects and teachers a lesson can be made of |
| `GET classes/<id>/?term_id=` | readers | one class's week |
| `PUT classes/<id>/lessons/` | editors | set a slot; 201 if it was free, 200 if a lesson was replaced, 409 on a clash |
| `DELETE classes/<id>/lessons/?term_id=&weekday=&period_id=` | editors | make a slot a free period |
| `POST terms/<id>/copy/` | editors | copy last term into this empty one |
| `POST periods/`, `PUT periods/<id>/`, `DELETE periods/<id>/` | editors | the bell schedule |

## The page

One class's week for one term: periods down, days across, the way a school
pins one to a classroom wall. It prints on one sheet with the forms hidden. A
double period is drawn as two cells that say the same thing, because that is
what is stored. After every write the page fetches the week again rather than
patching it, so what it shows is what the database holds, which matters most
when a write was refused.

## Not built

- **No teacher's own week.** A teacher reads each class's timetable; there is
  no "my week" view across classes yet.
- **No rooms.** A combined lesson is recorded as two slots with one teacher
  and one subject, and nothing says where it happens.
- **No Saturday.** A Saturday lesson would be a sixth `Weekday` value and a
  change to `a_weekday_is_a_school_day`, not a second table.
