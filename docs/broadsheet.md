# The master broadsheet

One table for one class and one term: every child in a row, every subject in
columns, split into its papers, then the child's total, average, position, how
many of each grade, and what happened to them at the end of the year. It is on
the screen, as a landscape PDF on A3 or A4, and as an Excel file. Code:
`results/broadsheet.py` (the numbers), `results/broadsheet_api.py` (HTTP),
`results/broadsheet_files.py` (the PDF and the Excel file), `static/master/`
(the page) and `results/templates/results/broadsheet_print.html` (the paper).
Tests: `results/tests/test_broadsheet.py` and `tests/js/master.test.js`.

It is not the older **Broadsheets** page (`/broadsheet/`, `results/api.py`),
which stays: that one is for any teacher, shows subject percentages and ranks,
and compares classes. The results page's "Broadsheet" link on a class row goes
to this one for the people who may open it (below), and to the older one for
everybody else.

## It computes nothing the report cards do not

A broadsheet that worked its own total or position out would be a second answer
to "what did Ada get". So:

| the class is | every figure comes from |
| --- | --- |
| released | the frozen cards that went home (`class_print.released_cards()`, the rule a family's page uses): the card's total, average and position, each subject line's percentage and letter, each paper's mark |
| not released | `positions.class_results()`, which is what a release freezes, through the same helpers (`cards._assessments_for`, `cards._scores_for`, `grades.grade_for`) |

`TheNumbersAreTheCardsTests` builds the sheet live, releases the class, builds it
again, and requires the two to be identical in every cell, footer figure,
position and grade count, and equal to the `ReleasedCard` rows.

## The columns

| template | columns per subject |
| --- | --- |
| Standard | **CA**, **Exam**, **%** |
| Ogun State | each continuous-assessment paper (1st Test, 2nd Test, Assignment), then **CA**, **Exam**, **%** |

CA is every paper but the one named Exam, added up; Exam is that paper
(`ogun_card._split`, the Ogun sheet's own rule); **%** is the subject's
percentage, the figure the card ranks, grades and averages. Each header says
what it is out of. After the subjects: **Total** (the card's marks obtained),
**Average** (the card's), **Position** (when the school prints one), a column
for each letter in the school's grading scale with how many subjects earned it,
and **Promotion** (`ogun_card._promotion_line`, the same sentence the Ogun card
prints: promoted to a class, repeating, promoted on trial, withdrawn; "-" before
the year's decision).

**Footer**: for every column, the **highest**, the **lowest** and the **class
average** of the figures shown. A child with no figure is not in the average and
is not a zero in it.

## A paper not marked is "-"

`gradebook` keeps "not marked" apart from nought by having no `Score` row, and
the sheet keeps it apart in every cell:

- a paper with no mark is "-";
- a CA with a paper missing is "-" (a total over two of three tests is not the
  child's CA); an Exam with no mark is "-";
- a subject with any paper missing has no **%**, no letter, and is not in that
  subject's footer or the child's average, as on the card
  (`positions`, "A subject with a paper unmarked");
- a child with no whole subject has no **Total**, no **Average** and no
  **Position**.

Nothing is ranked on a subject the child did not sit, because the ranks are
`positions`' and it ranks only whole subjects.

## Position, and the tie rule

The school's **show position** setting (`ReportCardSettings.show_position`,
the one the cards read) decides the column. When it is off, **the field is not
in the API payload, the column is not in the PDF or the file**, and the rows are
in name order, because rows in rank order would print the position anyway.
When it is on, rows are in rank order (ties by name, the unranked last) and the
position is the card's.

The tie rule is `positions.dense_positions()` (1, 2, 2, 3): the one place it is
decided, so the sheet and the card cannot break a tie two ways. There is no
per-school tie setting yet. When there is, it is that function that reads it.

## Who

| who | may read, print and export |
| --- | --- |
| principal, vice principal (academic), administrator | any class |
| class teacher | their own class, for the term they are its class teacher |
| a subject teacher, bursar, parent, student, anybody else | nothing |

`broadsheet.may_see()` is `class_print.may_print()`, the people who may print the
class's report cards: the sheet carries the same material. It is asked **on the
server** on the view, on starting a PDF, on starting an Excel file, and on the
status and download of either (`print_api._my_job`). The routes answer 403 to
somebody with no standing, asked before either lookup, and the same 403 to a
class teacher for a class that is not theirs *or that does not exist*, so a
teacher cannot list the school's classes by trying ids. The chain's
`master_broadsheet_url` only decides whether the link is drawn.

## The PDF and the Excel file: the report-card print path

Not a second path. A broadsheet job is a `ClassCardPrint` row whose `kind` is
`broadsheet_pdf` or `broadsheet_xlsx` (and `paper` is `A3` or `A4`), made by the
same Celery task (`build_class_cards`: `class_print.build()` claims the job the
same way, then hands a broadsheet to `broadsheet_files.make()`):

- **Off the request**: `POST /api/results/master-broadsheet/<class>/<term>/files/`
  writes the row and queues the task once it commits; the page asks
  `GET /api/results/print-jobs/<job>/` every two seconds. Pressing twice is one
  job; the claim, heartbeat and "ask again" are `class_print`'s.
- **Private, for one person, for a day**: kept by `files.service.keep_made()`
  as `Kind.CLASS_BROADSHEET` (no `readers`, so `/files/` never sends it), sent
  only to the person who asked, refused from the moment it is 24 hours old (410)
  and removed by the hourly `check_storage`. The PDF is at
  `/api/results/print-jobs/<job>/pdf/` and the Excel file at `.../file/`.
- **Logged**: the row is the print log and is kept after the file goes: who
  (id, name, roles), which class and term, what (kind and paper), how many
  children, preview or released, when. Each also writes an `INFO` line.
- **Preview**: an unreleased class's PDF is stamped **PREVIEW, NOT RELEASED**
  on every page by `class_print.stamp_pages()`, the stamp the cards use, drawn
  into the page's own content at the page's own size (so it crosses a landscape
  A3 as it crosses a portrait A4), and the filename and the PDF's title say
  "preview not released". The Excel file says it in its second row and in its
  print header. After release, none of it.

The PDF is HTML drawn by WeasyPrint on `A3 landscape` or `A4 landscape`, with
the header row repeated on every page. The type is sized so that every column
fits the paper's width (between 4 and 9 pt), so a wide Ogun sheet is smaller on
A4 than on A3: pick A3 for a class with many subjects.

### The Excel file

One sheet, "Broadsheet". Row 1 is the title, row 2 says "Released results." or
**PREVIEW, NOT RELEASED**, row 3 has the subject names (merged over their
columns), row 4 is the header (`broadsheet_files.header_labels()`, the PDF's
columns, with each paper's maximum in brackets), then one row per child, then
Highest, Lowest and Class average. Figures are numbers, so a school can add to
them; a missing paper is the text "-". Text is written as text, so a name that
begins with "=" is a name, not a formula. The panes are frozen under the header
and beside the name.

## On a phone

The first column is the child's name and stays fixed while the table scrolls
sideways (the shared `.scroll` table rule, `web/design.css`; the name cell is in
both header rows so that the pinned cell is always the name's). It may wrap, so
it is about a third of a phone's width.

## Two schools

Every row and file is in the school's own schema and directory; the job id is
looked up there only. The tests that hold the authority half are
`TwoSchoolsTests.test_a_principal_elsewhere_who_is_a_parent_here_cannot_see_print_or_export`
(a principal at Grace who is a parent at St Mary's passes the middleware on St
Mary's host, so only `may_see()` asking roles *here* stops them) and
`WhoMaySeeTests`. With `class_print.may_print()` changed to ask roles at every
school, the first fails (200 and 202 where 403 is wanted).
