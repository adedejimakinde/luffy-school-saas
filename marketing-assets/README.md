# Classnode marketing assets

Screenshots of **Crestfield College, Abeokuta (Demo)**, the sales-demo school (all names are made up), and the brand font files. Taken with Playwright from a local copy of `main`, using the existing `manage.py crestfield create` seed. **No app code was changed.**

- **Clock:** the local server and the browser were set to **Friday 20 November 2026, about 10:20 Lagos time**, so the dashboard says "Good morning", it is Week 12 of 12 of First term 2026/2027, and today's registers are taken (96.7% present).
- **Demo state:** 6 classes waiting for the principal's approval; 3 released (JSS 1A, JSS 2A, SS 1A); fees 65.9% collected (₦20,751,000 of ₦31,500,000).
- **Theme:** light. No browser chrome, no dev toolbars, no cursor.
- **Phone:** viewport 390x844, deviceScaleFactor 3, so PNGs are **1170 px wide**. "Full page" files are the whole scrolling page (the bottom tab bar sits at the end, not mid-page). `-card` files are tight crops of the main card; `-top` / `-screen` files are one screen (1170x2532).
- **Desktop:** viewport 1440x900, deviceScaleFactor 2, so PNGs are **2880 px wide**.

## phone/

| File | Shows |
|---|---|
| `phone-01-principal-dashboard.png` | Principal's Home (Dr Funmilayo Adeyemi): fees collected, students, present today, 6 classes waiting to approve, attention list, attendance week, recent activity. Full page. |
| `phone-01-principal-dashboard-card.png` | Crop: the Fees collected card. (See known issue 1.) |
| `phone-02-results-approval-queue.png` | Results page, the approval queue for all 12 classes: released, "Checked by vice principal" with Approve / Send back, and draft classes. Full page. |
| `phone-02-results-approval-queue-card.png` | Crop: JSS 1B's row (Approve, Send back). |
| `phone-03-class-approval-chain.png` | The same Results page opened on one class, JSS 1B (`/results/?class=2`), its row highlighted. Full page. |
| `phone-03-class-approval-chain-card.png` | Crop: JSS 1B's row. |
| `phone-04-report-card-ogun.png` | Released Ogun State continuous-assessment report sheet, Ifeoluwa Bamidele (JSS 2A), as the parent sees it: learner box, subjects, attendance, 83%, position 3rd of 25, affective and psychomotor ratings, remarks. Full page. |
| `phone-04-report-card-ogun-top.png` | The same, first screen only. |
| `phone-05-broadsheet-jss1a.png` | Master broadsheet for JSS 1A (released, 25 of 25 ranked). Full page. |
| `phone-05-broadsheet-jss1a-top.png` | The same, first screen only. |
| `phone-06-cbt-exam-mid-test.png` | CBT exam screen mid-test (JSS 2 Mathematics): timer, question grid (1-3 answered, 3 current), question 3 of 10 with option B selected, "Answer saved". Full page. |
| `phone-06-cbt-exam-mid-test-screen.png` | The same, first screen. |
| `phone-06-cbt-exam-mid-test-card.png` | Crop: the question card. |
| `phone-07-cbt-offline-answers-saved.png` | CBT "You're offline. Your answers are saved on this device and will send when you reconnect." Browser network switched off mid-test; question 4 with a naira-sign word problem, option A selected. Full page. |
| `phone-07-cbt-offline-answers-saved-screen.png` | The same, first screen. |
| `phone-07-cbt-offline-answers-saved-card.png` | Crop: the question card. |
| `phone-08-fees-overview.png` | Fees overview: outstanding (all terms) ₦10,749,000, 159 children owe, then every class with amount billed, outstanding and % collected. Full page. |
| `phone-08-fees-overview-top.png` | The same, first screen. |
| `phone-09-teacher-register-today.png` | Teacher's register for today, JSS 2B (Mrs Temitope Alabi), already taken, with Submit register. Full page. |
| `phone-09-teacher-register-today-top.png` | The same, first screen. |
| `phone-10-id-cards-screen.png` | Student ID cards page with the print panel open for JSS 2A (first screen). |
| `phone-10-student-id-card-front.png` | The printed ID card, front (Adeola Adeyinka, JSS 2A), cut from the PDF the app makes at 450 dpi. 1515x960, not phone-sized, because it is a print asset. |
| `phone-10-student-id-card-back.png` | The same card, back: QR code, "Scan to check this card is valid". |
| `phone-11-school-website-top.png` | Crestfield website homepage, Modern Campus theme, phone, top section (first screen). |
| `phone-11-school-website-full.png` | The whole homepage on a phone. |

## desktop/

| File | Shows |
|---|---|
| `desktop-01-principal-dashboard.png` | Principal's dashboard, first screen (1440x900). |
| `desktop-01-principal-dashboard-full.png` | Principal's dashboard, full page. |
| `desktop-02-broadsheet-jss1a.png` | JSS 1A broadsheet (Released), first screen. |
| `desktop-02-broadsheet-jss1a-full.png` | JSS 1A broadsheet, full page. |
| `desktop-03-school-website-top.png` | Homepage, Modern Campus theme, first screen. |
| `desktop-03-school-website-full.png` | Homepage, full page. |

## fonts/

Copied unchanged from `static/web/fonts/`. These are the custom cuts built by `scripts/fonts.py`.

| File | What |
|---|---|
| `hanken-grotesk-400.woff2` | Hanken Grotesk Regular, with ₦, ṣ/Ṣ and ʼ drawn from the font's own shapes (Yoruba and Igbo letters and tone marks included). |
| `hanken-grotesk-700.woff2` | Bold, same character set. |
| `hanken-grotesk-800.woff2` | ExtraBold, the school websites' headings. |
| `noto-sans-hausa-400.woff2`, `noto-sans-hausa-700.woff2` | Companion face for Hausa's hooked letters (ɓ ɗ ƙ ƴ) and ǹ. Used only through `unicode-range`. |
| `OFL.txt`, `OFL-noto-sans.txt` | SIL Open Font License 1.1 for each family. |

**No ttf/otf is in the repository.** Only the shipped woff2 files are. The custom cut is made from Google Fonts' variable `HankenGrotesk[wght].ttf` (and `NotoSans[wdth,wght].ttf`), which `scripts/fonts.py` checks by SHA-256 and cuts. To get a ttf/otf of the naira-sign cut, install `fonttools` and `brotli` and convert a woff2 (`fonttools ttLib.woff2 decompress`). Say if you want that done.

## Known issues in the app (visible in some shots, not fixed because app code was off limits)

1. **The "Outstanding (all terms)" tile on the dashboard has two lines of text drawn on top of each other** ("159 students owe" over "of which this term: ₦10,749,000"). It shows in `phone-01-principal-dashboard.png`, `-card.png` and both desktop dashboard shots. The markup is `home/templates/home/parts/fees.html`, lines 33-34.
2. The demo school has no phone number, so the ID card's back says "contact the school office", and the ID cards page shows a red "no phone number on record" warning (visible in `phone-10-id-cards-screen.png`).
3. ID cards printed today say "Valid until 20 November 2026" (the demo session ends today). Children have initials, not photos.
