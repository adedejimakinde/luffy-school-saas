# Student ID cards

A credit-card sized card for each child, front and back, printed a class at a
time on A4: **Student ID cards** in the office menu, for the principal, the
vice principal (academic) and the administrator. Code: the `idcards` app
(`access.py`, `cards.py`, `render.py`, `printing.py`, `tasks.py`, `api.py`,
`views.py`), `Kind.ID_CARDS` in `files/kinds.py`, and the page in
`static/id-cards/`. Tests: `idcards/tests/`, `tests/js/id_cards.test.js`, and
the `id-cards` and `id-card-*` entries in `tests/ui/screens.test.js`.

It reuses what "Print report cards" ([class-print.md](class-print.md)) is made
of and changes none of it: a Celery job in the school's schema, a private file
in the upload service's store, removal a day after it is made, and a print log
that is the job's own row. Nothing in `results`, `fees`, `cbt` or the
placement code was edited; the app reads the roll, the placements and the
report card's look (`results.look`) and writes only its own two tables.

## The card

CR80, 85.6 x 54 mm. Nothing it prints is nearer than 3 mm to the edge.

| front | back |
| --- | --- |
| school crest (its initials in a circle when it has none), name and colour | school name and address |
| the child's photo, or a clean placeholder with their initials | a QR code that opens the verification page |
| full name, admission number, class, session | "In an emergency call the school: *the school's phone*" |
| "Valid until" the expiry date | the expiry date again, and who the card belongs to |

- **The emergency line is the school's phone, never a parent's.** The only
  number the card can print is `School.phone`. No guardian's contact is read
  anywhere in the app, and `test_a_parents_number_is_never_on_a_card` gives a
  mother a verified phone and proves it is not on the sheet. A school with no
  phone on record prints "In an emergency, contact the school office." and no
  number, and the page says so before anybody prints.
- **The photo** is the passport frame the roll keeps (`academics.details.photo_of`,
  the upload service's `card.jpg`), so it is the picture the report card uses
  and nothing is stored twice. A child with none gets a tile in a light tint of
  the school's colour with their initials in it.
- **The colour** is one thin rule, the school's name and the initials, as on the
  report card: a solid band of ink streaks on a cheap printer.
- **The expiry date** is the last day of the card's session: the end of the
  session's last term (`cards.session_ends_on`). Printing for any term of a
  session gives the same date, and the date is brought up to the session's end
  as it stands whenever a card is printed again.

## The sheet

A4 holds two columns of five, 171.2 x 270 mm, centred, which leaves 19.4 mm at
the sides and 13.5 mm top and bottom for the cut marks. The cards touch, so one
cut along a mark parts two of them. Hairline marks, 4 mm long and 1.5 mm clear
of the card area, sit past both ends of every cut line (three vertical, six
horizontal); `test_the_geometry_fits_a_4_and_cut_marks_sit_clear_of_every_card`
fails if a mark would print on a card.

Each sheet of fronts is followed by the sheet of backs for the same ten
children, with the backs' **columns mirrored**, so that printed double-sided
and flipped on the long edge (what an office printer's "two-sided" means) a
child's back lands behind their front. A margin caption says which sheet it is
and, on the backs, how to print it. The page tells the person to print at 100%,
not "fit to page", because a scaled card is not credit-card size.

The class is a worker job, ten children to a render, each sheet written to disk
before the next and joined at the end with a bookmark per sheet, so memory is a
sheet and not a class.

## Who, and what is checked

| who | may print |
| --- | --- |
| principal, vice principal (academic), administrator | any class |
| class teacher (their own class included), subject teacher, bursar, parent, student | nothing |

`access.may_print()` is the one rule and asks `roles_at(school)`: this school's
roles only, so a principal at another school who is a parent here prints
nothing here (`test_a_principal_elsewhere_who_is_a_parent_here_cannot_print`).
Every route asks it first, on the server: the overview, the roll to choose
from, the start, the status and the download. The class routes answer **403**
before any lookup, so the answer does not say whether a class exists. The two
job routes answer a flat **404** to anybody but the person who asked, and to
that person once they may no longer print. The menu's link and the page's
button are drawn from the same set, and `tests/test_menu.py` holds that every
link shown opens and every page not shown refuses.

## The print log, and a day

The job row (`IdCardPrint`) is the print log and is kept: who asked, in which
roles, which class and term, which children (none for the whole class), how many
cards, and when. The page lists the last fifteen. The file goes through
`files.service.keep_made` (private, no readers on the generic `/files/` route),
is refused at 24 hours even before the hourly check, and is removed by that
check (`files.service.sweep`); the row stays. A second press by the same person
for the same cards while one is being made is the same job.

## The QR code, and the page it opens

`/verify/<token>/` on **the school's own host** (`https://<its host>/verify/<token>/`).
Printing makes one `IdCard` row per child per session, a random 96-bit token and
a date, and **reuses it on every reprint**, so the code on a reprinted card is
the one already in the child's bag. The table is in the school's own schema.

The page is public, for anybody with a phone, signed in at another school or at
none (`/verify/` is a door in `schools.paths`). It says **Valid** or **Expired**
and shows:

| card is | shows |
| --- | --- |
| valid | the child's name, their class now, their photo |
| expired (past its date, withdrawn, or the child no longer on the roll) | the name, "Expired", and a sentence that the card is no longer valid; no photo, no class |
| not issued by this school | "We cannot confirm this card" (a 404); no name |

Nothing else: no admission number, no date of birth, no learner's ID, no
contact, no expiry date, no other child, no school phone. That is held twice:
the template is handed a `Verification` with exactly four fields and nothing
else in scope, and a test reads the bytes of both pages against a child who has
every kind of record the roll can keep (`NothingBeyondTheAllowedFieldsTests`),
with a control that shows the same strings are on the card.

A card is valid while it is not withdrawn, today is no later than its expiry
and the child is on this school's roll. An expired card says only that it is no
longer valid, not why, so the page does not tell a stranger that a child has
left. The page is never cached, never indexed, sends no referrer and answers
only GET and HEAD.

### Another school's card is refused

Two layers, each with its own tests, so that removing one leaves the other's red
(`idcards/tests/test_isolation.py`):

1. **The token's own schema.** The row is in the school that printed it. The
   page reads the school this *host* is, so another school's token finds no row.
2. **The child is this school's.** The print and the page both check that the
   child's membership is a student of *this* school, so a row that named another
   school's child (a bad import, a forged placement) still prints and verifies
   nothing.

The check made for the pull request: layer two's two `school=school` filters
removed, two tests red; layer one's cross-school token lookup added as well,
seven red including `test_another_schools_card_is_refused_here_and_names_nobody`;
both put back, all green.

## What is not here

- **No "lost card" button.** `IdCard.revoked_at` exists and a revoked card reads
  as expired, so that button needs no migration of every school's schema, but
  nothing sets it yet.
- **No rate limit on `/verify/`.** A token is 96 bits, so guessing one is not a
  threat the way a 4-digit PIN is; the page costs a few indexed reads.
- **No per-card file or one-up layout.** A class, or the children ticked, on A4
  sheets of ten.
- **The QR code is decoded by hand, not in the suite.** No QR reader is a
  dependency of this project. The suite holds that the code drawn is the code for
  the card's own address and that the address opens the card's page; the code
  printed in a real PDF was rasterised at 300 dpi and decoded for the pull request.

## New dependency

`segno` (BSD, pure Python, no dependencies of its own on Python 3.10+) draws the
code as SVG paths, which WeasyPrint prints sharp at any size. Pinned with hashes
in `requirements.txt`.
