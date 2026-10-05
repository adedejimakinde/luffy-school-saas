# Importing a roll from a spreadsheet

The office admits a whole class, or a whole school, from one file. The page is
`/roll/import/`, linked from the roll for anybody who may admit a child
(an administrator: admitting and placing are both needed, and ADMIN holds
both).

## What was already there, and is unchanged

`accounts/bulk.py` does the work, and its rules are the import's rules:

- **`check()` judges every row and writes nothing; `admit()` runs it first and
  writes the whole file or none of it**, in one transaction.
- Every problem names the **row number in the office's spreadsheet** and the
  column it is about.
- A duplicate admission number (`reference`) is a problem, in the file or
  against this school's roll, and **refuses the file**. It is not skipped.
  Two children sharing a number is a records problem the office wants told
  about now.
- Classes are matched by name against this school's active classes. Two rows
  with one guardian contact are siblings with one guardian.

## What the upload adds

- **Excel as well as CSV.** `bulk.read_upload()` reads either into the rows
  `check()` reads. The format comes from the file's first bytes, not its name;
  an old `.xls` is refused with how to save it as `.xlsx`. A row with nothing in
  it is skipped, because spreadsheets end in formatted, empty rows. Numbers
  typed into General cells come back as typed (`100`, not `100.0`). Formulas
  are read as the value Excel saved, never evaluated.
- **Bounds before opening.** At most 2 MB sent, at most 20 MB once unpacked
  (read from the zip directory before anything is inflated), and at most
  2,000 children in one file.
- **A preview.** `POST /api/enrolment/roll/import/check/` returns every row as
  read, with its problems. The page shows them all and offers **Admit** only
  when none has a problem. Admitting sends the same file to
  `POST /api/enrolment/roll/import/file/`, which checks it again, so a roll that
  changed in between is reported by row and nothing is written.
- **A template.** `GET /api/enrolment/roll/import/template/` is a workbook with
  the headings the import reads and no example row (an example left in would
  be admitted). Its class column is a drop-down of **this school's** classes.
  Reference, username and contact are formatted as text, so an admission number
  keeps its leading zeros. A second sheet says how to fill it in.
- Headings match with spaces read as underscores, so the template's "Full name"
  and a hand-made file's `full_name` are the same column.
- **A child's details** (since the Ogun template, `docs/ogun-template.md`):
  "Learner ID", "Sex" and "Date of birth" are optional columns, checked by
  row. A learner's ID is unique at a school, ignoring case, as an admission
  number is. Photos are added on the roll, not imported.

- **Who will get no email.** Absence alerts and payment receipts go by email only
  (`docs/messaging.md` D13), and an imported guardian usually has a phone and nothing else.
  `admit()` therefore reports, with the import's answer (`no_email`, `bulk.NoEmail`), every child
  whose guardian this school has no email for, with why: **"No guardian was given."** or **"A phone
  number only."** An email typed on the row is not a gap. A phone alone is, **unless the guardian is
  already live at this school and holds an email**: only what this school may know is used, so a
  guardian who has an email at another school (but has not answered this one) is still listed, and
  the report cannot be used to learn which numbers belong to a parent with an email elsewhere. A
  refused file lists nobody. The done screen shows the list and "Download this list (CSV)", built in
  the page from the report just shown: UTF-8 with a byte-order mark so Excel keeps dotted letters,
  every cell quoted, a cell that starts like a formula made plain text.

Every route asks who is asking before it reads the file (the oracle rule), and
answers only for the school whose host it is on.
`accounts/tests/test_roll_import.py` holds all of this with two schools.
