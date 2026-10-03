# The Ogun State template

A school switches it on in setup and gets the report sheet Ogun State's
Ministry of Education, Science and Technology (MOEST) and OGSERA ask for: the
JSS first-term sheet is the reference. Five parts, one PR each.

The reference sheet, in the order it prints:

- **Header:** the ministry's name; the school's name with its LGA; Learner's
  ID, admission number, learner's name, sex, date of birth and a passport
  photo.
- **Subjects:** a grid with rows for Cont. Assess Scores (30), Exam Scores (70)
  and Weighted Average (100).
- **Attendance:** times school opened, present, absent.
- **Affective and psychomotor traits,** ticked on a 1 to 5 grid with totals,
  and the key: 5 Excellent, 4 Good, 3 Average, 2 Below Average,
  1 Unsatisfactory.
- **Physical development and health.**
- **Summary:** marks obtainable, obtained, percentage, class position.
- Class teacher's comment, principal's remark, signature, school stamp, date.

## Part 1: the child's details and the school's LGA

### What a school records about a child

`academics.StudentDetails`, one row per child **in the school's own schema**:

| field | rule |
| --- | --- |
| `learner_id` | the state's ID for the child. Optional. Unique at the school when present, **ignoring case** (`one_child_per_learner_id_per_school`, a unique index on `UPPER(learner_id)` where it is not blank). The same ID at another school is no obstacle. |
| `sex` | `female`, `male` or blank (`a_childs_sex_is_female_male_or_unsaid`). The service reads F, M, Female, Male, girl, boy in any case. |
| `date_of_birth` | a date, not in the future (the service) and not before 1950 (the constraint; "today" is not something a constraint can read). Typed day first: `02/03/2014` is the 2nd of March, never February. ISO is read too. |
| `photo` | a passport photo, see below. |

Not on `accounts.Membership`, which is shared: a child's date of birth and face
are one school's records, and an ID unique *per school* is said by a table in
that school's schema. A child with no row has none of it; the row is made the
first time anything is set. `student_membership_id` is a bare id, checked
against the school by `details.student_here()` (school and STUDENT role in the
lookup), the policy `ClassPlacement` follows.

**Who:** the office, principal or administrator (`PLACEMENT_ROLES`), the
people who already keep the roll. Teachers and bursars are refused reading and
writing.

### The photo is redrawn, as a crest is

`results.look.open_picture()` is now the one decoder for both: file size before
opening, PNG or JPG only, pixel count from the header before decoding, EXIF
rotation applied. The crest's limits are unchanged (1 MB, 16 megapixels); a
photo may be 5 MB and 52 megapixels because it comes off a phone, and a JPEG is
decoded at reduced scale (`Image.draft`). It is then cropped (not stretched,
not padded) to a passport frame of 280 by 360 pixels, centred a little above
the middle where a face is, flattened onto white and saved as a new JPEG. No
metadata survives. Stored as bytes in the school's schema, like the crest.

Listing reads defer the bytes (`details.details_for()`), so a list of children
never reads their photos.

### Routes

Under `/api/enrolment/roll/<id>/`: `GET`/`PUT details/`, and `GET`/`POST`/`DELETE
photo/` (multipart `photo`). Host, then authority, then the child: a child of
another school is a 404 from the other school's host, and the other school's
office is a 403 on this one's. The roll (`GET /api/enrolment/roll/`) carries
each child's `learner_id`.

The roll page has a **Details** button per child, beside Guardians: the photo,
the three fields and the photo upload, in a panel. A refused save keeps what
was typed.

### The import

Three optional columns, "Learner ID", "Sex" and "Date of birth", in the
template and read by the import. Checked by row like every other column: a
learner's ID twice in the file or already at the school, a sex that is not
one, a date that is not one or is in the future. The whole file or nothing, as
before. In the template the learner's ID is a text column (leading zeros
survive), sex is a Female/Male drop-down and the date column is formatted
`DD/MM/YYYY`. A row with none of the three makes no details row.

**Photos are not imported.** A spreadsheet is the wrong carrier for forty
pictures; they are added on the roll, one child at a time.

### The LGA

`School.lga`, shared (the school's own row), set on the setup page by whoever
may set the school up (`schools.contact.set_lga_as()`, `PUT /api/academics/lga/`).
Free text up to 60 characters; the page offers Ogun's twenty LGAs as the
person types (`contact.OGUN_LGAS`), and a school elsewhere types its own.

### Tests and controls

`academics/tests/test_student_details.py` (two schools throughout) and
`accounts/tests/test_roll_import.py`'s `TheChildsDetailsTests`;
`tests/js/roll_details.test.js` and the LGA tests in `tests/js/setup.test.js`.
The `screens` job photographs the roll's details panel.

| broken | what went red |
| --- | --- |
| `student_here()` without `school=` | `test_the_other_schools_admin_cannot_reach_this_schools_child_from_her_own_host` |
| the details routes' authority check removed | `test_a_teacher_and_a_bursar_are_refused_reading_and_writing` (both subtests) |
