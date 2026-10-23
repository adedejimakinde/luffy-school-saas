# The school dashboard (`/home/`)

Every member of staff lands here. One page, drawn whole on the server: every
figure, both drawings and every link arrive in the first response, so there is
nothing to fetch after it and no script to run.

**Where:** view `home/views.py`, facts `home/facts.py`, who sees what
`home/dashboard.py`, drawings `home/charts.py`, template
`home/templates/home/dashboard.html` and its `parts/`, stylesheet
`static/home/dashboard.css`. Tests: `home/tests/test_dashboard.py`.

## What is on it

| | |
| --- | --- |
| Header | Greeting, the school's crest (or its initials), name, session, term and week. On a phone, one chip: term, week and date. |
| Tiles | Students enrolled, fees collected (naira and percent of what was billed, with a meter), attendance today, results waiting. A teacher gets attendance and scores entered for their own class instead. Each carries one change note against last week or last term where that exists. |
| Needs your attention | Up to five items, each a link to the page that fixes it: a register not taken, fees owed, results waiting on this login, papers half marked, remarks missing, staff invitations not accepted, no contact email. |
| Fee collection | Collected against billed, a sparkline of the term's weeks so far, the meter, and this week, outstanding and owing. |
| Attendance this week | Monday to Friday as bars, plus a Saturday or Sunday only if a register was taken on it. A day with no register yet is a dashed empty slot labelled "Not yet" (or "None" once it has passed), never a low bar. |
| Recent activity | The latest five lines from the logs the school already keeps (below). |
| Your next step | The administrator, until setup is first finished: one card at the top with the next of the eight setup steps and one button (`docs/onboarding.md`). While the school has no students it stands instead of the figures; the principal then sees how far the administrator has got. |
| First days | A teacher (register, marks) or a bursar (fees, a payment), until they have done both or for fourteen days after their first sign-in. |

## Attendance: one day, told three ways

The tile, the chart and the activity line describe the same day, so they
never disagree:

- If any register was taken **today**, whatever day of the week, the tile is
  "Attendance today", the chart has today's bar, and the feed says how many
  classes have taken it.
- If none was, the tile is "Attendance" and shows the **last day a register
  was taken**, labelled "Last school day: Fri 9 Oct". It never calls a day
  with no register "today". The chart says "No registers on a weekend" only
  when it is one and nobody has taken a register.
- The change note compares the day shown with the seven days before it.

`AttendanceTellsOneStoryTests` holds this for a Sunday with a register, a
Sunday without one, a school day before its register, and a teacher's class.

## Numbers and names

Every figure goes through `home.dashboard.figure()`: at most one decimal and
never a trailing ".0" (100%, 94.2%, +14 pts, ₦48.6m). The greeting uses the
login's short name or the first word of the full name, keeps an honorific with
the surname ("Mrs Adeyemi"), and drops any role word: a login called
"Administrator Sunrise" is greeted "Good morning".

## Three statements, cached per school

`home.facts.read()` runs three statements on one cursor, each a single
`json_build_object` row of aggregates: **people** (term, classes and
placements, the previous term's roll, staff counts, class teachers, three
weeks of registers, staff invitations, the crest), **money** (this term's ledger by
kind, by week and by family, and the last five payments) and **work** (results
sheets and their latest steps, papers with marks started, remarks written). The
count does not grow with the school; `ThreeStatementsAndThenNoneTests` holds
that.

The facts are the **school's**, not any reader's, and are cached for five
minutes (`CACHE_SECONDS`) under `home:facts:v1:<schema>:<school id>:<day>`. The
schema is the tenant the statements ran in; the id is there because a schema
name can be reused and an id never is. One cached copy serves every role at
one school; `home.dashboard.build()` narrows it to one login after it leaves
the cache. A school still being set up is read fresh every time. The setup steps are
not read from this cache at all: `onboarding.progress` reads them fresh, one
statement, so a step shows done the moment it is.

The cache is Django's default, per process. A shared cache (Redis is already
running for Celery) is a one-line `CACHES` setting if more workers ever make
the per-process copies worth sharing.

## Who sees what

Every tile and drawing is shown only where its page opens for the login, and
every attention item only where the login can take the step. The role sets are
imported from the modules that gate those pages, never written out again.

| | principal | vice principal | admin | bursar | teacher |
| --- | --- | --- | --- | --- | --- |
| Students enrolled | yes | | yes | | |
| Fees collected, fee collection | yes | yes | yes | yes | never |
| Attendance today | school | school | school | | own class |
| Results tile | "Approvals" (waiting on you) | "Checks" (waiting on you) | "Approvals" (with the principal) | | |
| Scores entered | | | | | own class |
| Fees owed | | | yes | yes | |
| Results waiting | approve, release | check | | | |
| Papers half marked | school | | school | | own class |
| Remarks missing | principal's | | | | class teacher's |
| Invitations not accepted | | | yes | | |
| Contact email | yes | | yes | | |
| Activity: results steps | school | school | school | | own class |
| Activity: payments | yes | yes | yes | yes | never |
| Activity: registers | today, school | today, school | today, school | | own class |
| Activity: staff joined | | | yes | | |

**A teacher's class** is the class they are class teacher of this term
(`ClassTeacher`). Subject assignments (`docs/subject-teachers.md`) narrow a
teacher's marking and not this page, so it still reads the class they
form-teach. A teacher who also holds a school-wide role sees the school.

**The principal's prompt to say who teaches what** is a card on Home while the
current term has never had a subject assignment, read live rather than from the
cached facts so it goes with the first one (`gradebook.assignments.prompt_for()`).
**"Assignments copied from last term, review them"** is the principal's card
after a new term began with the last one's subject teachers copied in, until
the principal opens `/subject-teachers/` in that term or dismisses it
(`gradebook.assignments.carried_for()`).

**Papers half marked** are papers where some children in a class have a mark
and some do not. A paper nobody has started is not flagged, because nothing
records which classes sit which subject.

**"Owe", not "overdue".** The fee book has no due dates, so nothing on the
dashboard calls a balance overdue.

## Recent activity: which logs feed it

No table of its own. It reads what is already written, each row stamped when
it was written:

- results steps: `results.ResultSheetTransition` (append-only);
- payments: `fees.FeeLedgerEntry` rows of kind payment (append-only);
- registers: `attendance.Register`, one line for the school's day or one per
  register for a teacher's class;
- staff who joined: `schools.Invitation` rows accepted.

## Controls

Rule 5 of `docs/operating-rules.md`: each claim broken on purpose, seen red,
and restored.

| What was broken | What failed | What that says |
| --- | --- | --- |
| The fees tile admitted `REGISTER_ROLES` as well as `fees.authority.READING_ROLES` | `test_the_teacher`, `test_no_fee_figure_payment_or_payer_reaches_a_teacher`, `test_a_teacher_with_no_class_has_no_attendance_or_scores_tile` | A teacher shown a fee figure fails three tests, one of them by reading the page for any naira sign. |
| The cache key without the schema (id and day kept) | `test_the_cache_key_names_the_schema_and_the_day` | The key is required to name the tenant schema. |
| The cache key without the schema or the id | `test_a_cached_school_is_never_served_to_the_next_school_that_asks`, `test_one_schools_figures_never_reach_the_other`, `test_the_cache_key_names_the_schema_and_the_day` | With a shared key, Grace was served St Mary's cached figures; the two-school tests see it. |

## What it costs

Measured on the demo and in `tests/test_budget.py`; the pull request that
built the page has the before and after.
