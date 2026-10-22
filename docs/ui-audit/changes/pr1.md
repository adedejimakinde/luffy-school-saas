# PR 1: a doctype and a language on every page, before and after

Every screen of the audit (94 screens and 15 drill-down states) was photographed at 375 and 1280 px on `main` and again on this change, against the same demo data, and compared pixel by pixel (colour differences under 10% ignored).

- **109 screens and states, each at both widths: 99 are identical at both.** Quirks mode went from **72 screens to 0** (the one left, `write-preview`, is the bare 405 answer to a GET, not a page) and `<html lang>` is set on all of them.
- Moving to standards mode changed how forms and tables are laid out: quirks mode gave every `form` a 1em bottom margin and made every `table` start over (browser type, `line-height: normal`). The first comparison (before the fix in `design.css`) showed **46 captures changed**: tables 10 to 15% taller (timetable, broadsheet, absences, fee lists, report card and checker sheet), forms 16px shorter. Restoring those two defaults for the pages that had them (`html.was-quirks`, at the weakness the browser's own rules had) brought it to the table below.
- Left as they are: a 1 to 3px difference per row in a few lists where a smaller-type line sits inside a larger one (the line box now includes the parent's strut, as the standard says). Nothing overlaps, clips, wraps differently or scrolls sideways; the largest total is 8px on a 976px page.

| Screen | 375 px | 1280 px |
|---|---|---|
| `admin-help` | height 976 to 984 px | pixels differ |
| `bursar-fees--account` | identical | pixels differ |
| `bursar-help` | pixels differ | pixels differ |
| `platform-handover` | height 2151 to 2154 px | height 1039 to 1042 px |
| `platform-home` | height 1020 to 1024 px | identical |
| `principal-fees--account` | identical | pixels differ |
| `principal-help` | pixels differ | pixels differ |
| `principal-results` | pixels differ | pixels differ |
| `site-home` | pixels differ | pixels differ |
| `teacher-help` | pixels differ | pixels differ |

`site-home` differs by a few hundred pixels in its animated hero between any two photographs (it already had a doctype and is untouched).

## Photographs

Each is the screen before (left) and after (right); 1280 px images are shown at half size.

### `admin-help`

![admin-help at 375](pr1/admin-help-375.webp)

![admin-help at 1280](pr1/admin-help-1280.webp)

### `principal-help`

![principal-help at 375](pr1/principal-help-375.webp)

![principal-help at 1280](pr1/principal-help-1280.webp)

### `platform-home`

![platform-home at 375](pr1/platform-home-375.webp)

![platform-home at 1280](pr1/platform-home-1280.webp)

### `platform-handover`

![platform-handover at 375](pr1/platform-handover-375.webp)

![platform-handover at 1280](pr1/platform-handover-1280.webp)

### `principal-results`

![principal-results at 375](pr1/principal-results-375.webp)

![principal-results at 1280](pr1/principal-results-1280.webp)

### `bursar-fees--account`

![bursar-fees--account at 375](pr1/bursar-fees--account-375.webp)

![bursar-fees--account at 1280](pr1/bursar-fees--account-1280.webp)

### `principal-fees--account`

![principal-fees--account at 375](pr1/principal-fees--account-375.webp)

![principal-fees--account at 1280](pr1/principal-fees--account-1280.webp)

### `principal-timetable`

![principal-timetable at 375](pr1/principal-timetable-375.webp)

![principal-timetable at 1280](pr1/principal-timetable-1280.webp)

### `principal-broadsheet`

![principal-broadsheet at 375](pr1/principal-broadsheet-375.webp)

![principal-broadsheet at 1280](pr1/principal-broadsheet-1280.webp)

### `principal-absences`

![principal-absences at 375](pr1/principal-absences-375.webp)

![principal-absences at 1280](pr1/principal-absences-1280.webp)

### `checker-result`

![checker-result at 375](pr1/checker-result-375.webp)

![checker-result at 1280](pr1/checker-result-1280.webp)

### `admin-roll-import`

![admin-roll-import at 375](pr1/admin-roll-import-375.webp)

![admin-roll-import at 1280](pr1/admin-roll-import-1280.webp)

### `principal-home`

![principal-home at 375](pr1/principal-home-375.webp)

![principal-home at 1280](pr1/principal-home-1280.webp)

### `teacher-marking`

![teacher-marking at 375](pr1/teacher-marking-375.webp)

![teacher-marking at 1280](pr1/teacher-marking-1280.webp)

### `sign-in`

![sign-in at 375](pr1/sign-in-375.webp)

![sign-in at 1280](pr1/sign-in-1280.webp)

### `parent-cards`

![parent-cards at 375](pr1/parent-cards-375.webp)

![parent-cards at 1280](pr1/parent-cards-1280.webp)
