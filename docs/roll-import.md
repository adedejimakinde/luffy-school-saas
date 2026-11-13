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
  about now. Numbers are compared **without case** since G-14 ("jss/014" is
  "JSS/014", as at every door), and a number a child who has left still holds
  is not given to another.
- Classes are matched by name against this school's active classes. Two rows
  with one guardian contact are siblings with one guardian.

## Sending a file again (audit G-15)

**The same file sent twice admits nobody the second time**, with admission
numbers or without. Before anybody is admitted, each row is matched to a child
already on this school's roll, by the first of these it carries:

1. **Its admission number**: the child here who holds it (without case). If
   that child has left, or has another name, the row is refused: the number is
   theirs.
2. **Else its username**: the child here whose login it is. Another name, or a
   child who has left, is refused; a username somebody else on the platform
   holds is refused without saying whose, as before.
3. **Else its name**, also for a row whose number or username nobody holds yet:
   one enrolled child of the same name (no case, extra spaces ignored) who is
   in the row's class this term or in no class, and does not carry a different
   admission number from the row's. The same name in **another** class, or a
   name two children share, is refused with what to add: "give an admission
   number if this is a different child".

**A matched row never changes what the roll says.** It fills in only what the
roll has nothing for: an admission number, a class this term, a learner's ID,
sex, date of birth, a guardian not yet linked. Then it is **updated**; with
nothing to fill it is **skipped**. Anything the row says differently (another
class, another learner's ID) is left as the roll has it and shown as a note
("Kept in JSS 1A; move them on the roll."). An unmatched row is **new**.

To admit a second child with the same name as one already in the class, give
one of them an admission number first.

The preview shows each row's outcome, with what it fills and what it keeps, and
counts them: "2 new children, 1 child already on the roll to fill in, 40
children already on the roll, left as they are". A file that is all already in
says so and offers no button. A double press or a retry is the same file twice
at once: one import runs at a time per school, and the second is checked
against what the first wrote, so it reports every row skipped.

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
