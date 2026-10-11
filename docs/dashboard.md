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
| Attendance this week | Monday to Friday as bars. A day with no register yet is a dashed empty slot labelled "Not yet" (or "None" once it has passed), never a low bar. |
| Recent activity | The latest five lines from the logs the school already keeps (below). |
| Set up your school | Instead of all the above while the school has no students: add classes, invite teachers, import students, each ticked off as it is done. |

## Three statements, cached per school

`home.facts.read()` runs three statements on one cursor, each a single
`json_build_object` row of aggregates: **people** (term, classes and
placements, the previous term's roll, staff counts, class teachers, two weeks
of registers, staff invitations, the crest), **money** (this term's ledger by
kind, by week and by family, and the last five payments) and **work** (results
sheets and their latest steps, papers with marks started, remarks written). The
count does not grow with the school; `ThreeStatementsAndThenNoneTests` holds
that.

The facts are the **school's**, not any reader's, and are cached for five
minutes (`CACHE_SECONDS`) under `home:facts:v1:<schema>:<school id>:<day>`. The
schema is the tenant the statements ran in; the id is there because a schema
name can be reused and an id never is. One cached copy serves every role at
one school; `home.dashboard.build()` narrows it to one login after it leaves
the cache. A school still being set up is read fresh every time, so its
checklist ticks the moment a step is done.

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
| Results tile | to approve | to check | awaiting approval | | |
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
(`ClassTeacher`). Teachers are not assigned to subjects (`docs/teaching.md`),
so there is no narrower "classes and subjects they teach" to read. A teacher
who also holds a school-wide role sees the school.

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
