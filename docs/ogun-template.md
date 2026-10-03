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

## Part 2: choosing the template, and what it sets up

`ReportCardSettings.template`, `"standard"` (the One Blue card, every
school's default) or `"ogun"`, with a check constraint naming the two. Chosen
on the setup page under "Report card template"
(`PUT /api/academics/card/template/`), by the principal or an administrator.
`results.ogun.set_template_as()` is the one writer; choosing Ogun runs
`apply_presets()` in the same transaction and the answer says what it did.

| preset | what it sets |
| --- | --- |
| assessments | 1st Test 10, 2nd Test 10, Assignment 10, Exam 70, per active subject, for the current term and every term starting after it (with no current term: every term that has not ended). A term an Ogun school opens later gets them as it is opened. |
| traits | Affective: Punctuality, Neatness, Honesty, Self-Control, Attentiveness in Class, Leadership. Psychomotor: Handwriting, Games & Sports, Fluency, Handling of Tools, Drawing & Painting, Crafts. In that order, both sections switched on. |
| scale | 5 Excellent, 4 Good, 3 Average, 2 Below Average, 1 Unsatisfactory. Labels only: the numbers ratings store do not move. |

### Never over a mark or a rating

- **A subject with a mark in a term keeps its papers** as they are and is
  reported as kept. A subject with papers and no marks has them replaced.
  The subject's papers are locked before the marks are counted, and entering
  a mark takes a key-share lock on its paper, so the two cannot interleave.
  A released term is covered by the same rule: its subject lines exist only
  where the class was marked, and its marks cannot be deleted
  (`gradebook/0002`).
- **A trait that has ever been rated is never hidden**, even when the sheet
  does not print it; it is reported as kept and stays at the end of its
  section. Unrated lines the sheet does not print are hidden, never deleted.
- Seeded lines that are the sheet's line under another spelling are
  renamed (`ogun.RENAMES`: "Attentiveness in class", "Games/Sports",
  "Handling of tools and equipment"). A rename keeps every rating, and a
  released card keeps its frozen name.

Choosing Ogun again applies the presets again (how a school picks up a subject
added since) and changes nothing that is already right. Going back to
Standard changes the layout only and undoes nothing.

**There is no screen for subjects or assessments** in Classnode today; a school
gets them from whoever set it up. The presets work on the subjects that
exist.

### Tests and controls

`results/tests/test_ogun_template.py` (two schools; Grace is untouched by
every choice at St Mary's), and the template tests in `tests/js/setup.test.js`.

| broken | what went red |
| --- | --- |
| the marks check in `apply_assessments()` removed | the three tests with a mark in (errors: `Score`'s PROTECT key refuses the delete, so a mark was never at risk; the preset would have failed whole) |
| the rated-trait check in `apply_traits()` removed | `test_a_rated_trait_the_sheet_does_not_print_stays_on_the_sheet` |
| `set_template_as()`'s authority check removed | `test_the_service_refuses_a_teacher_without_the_route` |

## Part 3: physical development and health

`results.HealthRecord`, one row per child per term, in the school's own schema:
height in metres and weight in kilograms at the beginning and end of term
(two and one decimal places; 0.50 to 2.50 m and 5 to 250 kg by constraint),
days absent through illness (0 to 200), and the nature of the illness (120
characters). Every box may be blank.

**Sensitive children's health data, with four readers** (`results.health.may_see()`):

| reader | sees it |
| --- | --- |
| the class teacher of the class the child sat in that term | yes, and **writes** it, until the card goes home |
| the principal, a school administrator | yes, read only |
| the child's guardians | yes, for a term whose card has been released to them |
| anyone else: another teacher, the vice principal, the bursar, the child's own login, a result-checker PIN, another parent, another school | **no**, a flat 404 |

It has its own routes, `GET`/`PUT /api/results/health/<child>/` (`?term_id=`
to read another term), on its own router (`results/health_api.py`), imported
by no other surface. The remarks page's child view is served to every
teacher, so the record is fetched separately when a child is opened and drawn
only where it came back (`static/comments`), and only for an Ogun template
school.

**It is in nothing else:** not the card payload (served to every card reader,
PIN holders included), not the stored PDF, not a broadsheet, a class list or an
export. `results/tests/test_health.py`'s `NowhereElseTests` look for a marker
illness in the raw bytes of each.

**It stops changing when the card goes home.** The service refuses (423), and a
trigger (`results_health_stops_at_release`, migration `0029`) refuses INSERT,
UPDATE and DELETE for a (child, term) with a `ReleasedCard`: the artefact rule.
So the card can read the row live and still say what it said.

The privacy notice (`/privacy/`) lists it under "What we collect" and has a
"Health records" part under children's data saying who can see it.

### Tests and controls

`results/tests/test_health.py` (18 tests, two schools), `tests/js/comments_health.test.js`.
Heights and weights are rounded half up to their places (`1.445` is `1.45`).

| broken | what went red |
| --- | --- |
| guardians served before release | `test_a_guardian_sees_it_once_the_card_has_gone_home_and_not_before` |
| the office check widened to every role at the school | the other teacher, the vice principal and the bursar subtests, the class teacher of another class, the child herself, another parent (7 failures) |
| `_is_class_teacher()` true for any teacher | `test_another_teacher_..._get_a_404` (the other teacher), `test_the_class_teacher_of_another_class_sees_nothing_of_this_one` |
| the release trigger never created | `test_the_database_refuses_a_change_after_release` (update, delete and insert) |
