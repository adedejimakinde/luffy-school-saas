# Phone-width sweep: small phones and a large system font

The people who use Classnode most open it on budget Android phones (a Redmi 13C,
an Oukitel C66: 360px or narrower), often with the system font turned up. This
sweep photographed every screen at those sizes, listed what did not fit, fixed
it at the root, and photographed everything again.

**Rule for the fix: fit and wrap only.** No colour, no layout style and nothing
a screen shows was changed. Where a value used to break in the middle, it now
moves to the next line whole; where a box ran off the screen, it now fits it.

## How it was swept

- **Script:** `scripts/phone_sweep.mjs` (Playwright, Chromium). It photographs
  each screen and measures it in the page.
- **Data:** the demo, served as CI's `screens` job serves it, plus **Crestfield**
  (`manage.py crestfield create`). Every role was signed in: principal, vice
  principal (exam officer), administrator, bursar, teacher, parent. A student
  sat Crestfield's open CBT test with a printed admission number and PIN.
  The public pages were opened signed out: Classnode's own site, the portal's
  doors, Crestfield's and Harbour's school websites, the result checker, the
  test-score door and the exam door. A few screens only the demo has (a
  released CBT result, ID-card checks) came from Sunrise.
- **Widths:** 320, 360, 390 and 412px.
- **Text:** 100% and 130%. 130% raises the browser's default font size from
  16px to 21px, which scales every `rem` the design uses, as a system font of
  130% does in Chrome on Android. Every size in Classnode's CSS is a `rem`.
- **Size of it:** 99 screens (pages and their states after a tap) × 4 widths ×
  2 text sizes = **792 screenshots**.
- **What counts as a fault:** the page scrolls sideways; something runs past
  the screen's edge outside a scroller; a button wider than the screen; text
  cut off by its box; two lines of text drawn over each other; a table
  running out of its card; a wide table whose box gives no sign that it
  scrolls; and an amount, a date, a class name, an admission number or a PIN
  broken across two lines.

Not a fault, and left alone: a row that scrolls sideways on purpose (the
homepage's tour tabs, the exam's strip of question numbers), text kept for a
screen reader, and a menu laid over the page while it is open.

**The viewport.** All 87 page templates say
`width=device-width, initial-scale=1` and none sets `user-scalable=no` or a
`maximum-scale`, so a reader can always pinch to zoom and the system font
applies. `tests/test_design.py` now holds every template to that.

## Before: what was found

**24 problems**, seen as 103 distinct faults on 177 of the 792 screenshots.
"320/130" means 320px wide with text at 130%.

| # | Screen (role) | Problem | Where it showed |
|---|---|---|---|
| 1 | The phone's tab bar, every staff page (principal, vice principal, administrator, teacher) | Labels cut off: "Absenc…", "Broads…", "Exam sl…", "Promot…", "Timeta…"; "Who teaches what" at every size | 320/130; "Broadsheets" to 390/130; "Who teaches what" at all 8 |
| 2 | Home, every role | The date in the term chip broken: "Fri 27 / Nov" | 320/130 |
| 3 | Results (principal, vice principal) | Class names broken: "JSS / 1B", "SS / 2B" | 320/130, 360/130 |
| 4 | Tests list (principal, vice principal, teacher; Sunrise's results list) | Opening and closing dates broken ("27 Nov / 2026"); class name "JSS / 2B" | 320 to 412, at both sizes |
| 5 | A test's sitting (principal) | Dates broken in the sitting line, the hint and each student's log: "Fri 27 / Nov", "Sat 28 / Nov" | 320/130 to 412/130 |
| 6 | Exam slips (principal, administrator) | Dates broken in the print log, each class's last print and the officer list; "JSS / 3A" in the log | 320 to 412, both sizes |
| 7 | Who teaches what (principal) | Dates broken in Recent changes; "SS / 2B", "SS / 3A" in its lines | 320 to 412, both sizes |
| 8 | Start here (principal, administrator) | The page scrolls sideways by a pixel; the date in the change list broken | 320/130, 360/130 |
| 9 | Website editor (principal) | "27 Nov / 2026" in the published line; "JSS / 1" in a section's summary | 320 to 390 at 130; 320/100 |
| 10 | Setup (administrator) | Term dates and the cut-off hint's date broken; "SS / 2B" in the class hint | 320 to 412 |
| 11 | Roll import (administrator) | The list of this term's classes breaks inside names: "JSS / 2B" | 360 and 412 at 100; 320 to 412 at 130 |
| 12 | Fees (bursar) | A class row's amounts drawn over its words: "₦585,000.00 outstanding" over "76% collected" | 320/130 |
| 13 | A family's fee account (bursar) | The payment form is wider than the screen: the page scrolls sideways (325px in 320) | 320/130 |
| 14 | Register (teacher) | "Fri 27 / Nov" under the class name | 320/130 |
| 15 | Marking (teacher) | Class names broken in the list of papers; on the marks sheet each child's total runs off the screen and the page scrolls sideways (345px in 320) | 320/130, 360/130 |
| 16 | Broadsheet (principal) | A 1,504px table scrolls in its box with no edge to say there is more | every width and size |
| 17 | Report card, Ogun State sheet (parent) | The page scrolls sideways (368px in 320 and in 360): Attendance and Summary are a grid whose columns are at least 16rem; the Affective table runs out of the card; the subjects grid scrolls with no edge; "Monday 14 December / 2026" broken | 320 to 412 at 130; the grid's edge and the date at every size |
| 18 | The exam, CBT (student) | The bottom bar's "Calculator" button is cut off to "Calculato" | 320/100; 320 to 412 at 130 |
| 19 | ID cards, choosing children (principal) | Each child's admission number is drawn over the next child's name | 320 to 412 at 130 |
| 20 | Test scores (parent); a test's results (principal) | "Fri 27 / Nov" broken | 320/130 to 390/130 |
| 21 | School websites: Crestfield and Harbour (public) | Class ranges broken in the hero, the principal's message and the admissions band: "JSS / 1", "SS / 3", "SSS / 1" | 320 to 412, both sizes |
| 22 | Classnode's terms (public) | "Last updated 9 November / 2026" | 320/130 |
| 23 | Classnode's result-computation page (public) | "JSS / 1" broken | 390/100 |
| 24 | Classnode's Excel comparison page (public) | The table's two column headings drawn over each other: "Excel result template" over "Classnode" | every width and size |

What was **not** found anywhere: a button wider than the screen, a table
bursting out of a card on a staff page, an amount (₦10,749,000.00), an
admission number (CFC/2025/070) or a PIN (0105 7149) broken across lines, or
overlapping text on the sign-in pages, the exam door, the result checker or
Classnode's homepage.
