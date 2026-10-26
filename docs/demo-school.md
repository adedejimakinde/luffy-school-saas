# The demo school: Crestfield College, Abeokuta (Demo)

Classnode's own school for sales visits, on the **production** server beside the
real schools, at `https://crestfield.classnode.co/`. Made once with
`manage.py crestfield create` and put back to the same state with
`manage.py crestfield reset` before each visit. The code is `schools/crestfield/`;
its tests are `schools/tests/test_crestfield.py`.

This is not the demo server (`docs/demo-server.md`), which holds nothing real
and runs `load_demo`. Crestfield lives where real schools live, so everything
below is about keeping it apart from them.

## What is in it

A day secondary school in Abẹ́òkúta at the end of its first term. All of it is
made up; any match with a real person is chance.

| | |
|---|---|
| Classes | JSS 1A to SS 3B, two arms a year, 25 students each (300) |
| People | Yorùbá, Igbo and Hausa names with their tone marks, dotted vowels and hooked letters; one guardian per family, some with two children here |
| Staff | principal, vice principal (academic), administrator, bursar, 15 teachers; who teaches what is set per class, so marking is narrowed |
| Term | twelve weeks ending on the day of the reset, less two days of mid-term; a register for every school day |
| Results | the Ogun State sheet, every paper marked, both conduct sections rated, remarks written. Released: JSS 1A, JSS 2A, SS 1A (with result-checker slips printed). Waiting on the principal: six classes. Still open with the class teacher: JSS 2B, SS 3A, SS 3B |
| Fees | every class billed (tuition and two levies); about half paid in full, a third part-paid, the rest owing |
| CBT | the vice principal named exam officer; JSS 3A's exam slips printed |
| Website | the starter theme with the school's details, published |
| Setup | finished, with the contact email and the crest in the setup log |

**Not in it, and why.** The CBT question bank is CBT step 3, which is not built:
there is no table to put questions in. Thirty questions written for Crestfield
(Mathematics, Basic Science, English; nothing from WAEC, NECO or JAMB) are in
`schools/crestfield/questions.py`, ready for step 3 to load. There are no
notices to families: the only notices Classnode has are messages, and this
school sends none. There is no noticeboard feature to fill.

## Sign-ins

Three logins can sign in, all at `https://app.classnode.co/staff-sign-in/` with a
password: `cfc.principal` (Dr Fúnmiláyọ̀ Adéyẹmí), `cfc.teacher` (Mrs Tèmítọ́pẹ́
Àlàbí: JSS mathematics, class teacher of JSS 2B, whose sheet is still open) and
`cfc.parent` (Mrs Adéọlá Bámidélé: Ìfẹ́olúwa in JSS 2A and Ọlámidé in SS 1A, both
released). Nobody else at the school has a password.

The passwords are in one file on the server and nowhere else: not in this
repository, not in a chat, not in the command's output. The command reads them
from its environment and never prints them.

## Keeping it apart from the real schools

- **The demo-name guard is not loosened.** `schools/demo_slugs.py` refuses
  `*-demo` names on production, so the slug is `crestfield`, which is not one.
  What marks the school is `School.sales_demo`, and a database constraint lets
  only the slug `crestfield` carry it.
- **Nothing is sent** (`schools/quiet.py`). Inviting staff is refused before
  anything is written; the Notices page will not switch anything on; a notice,
  receipt or alert that got written anyway is recorded as "switched off" and
  never handed to the provider; the daily money summary is skipped; a guardian's
  code is not sent when this school asked for it, or when this school is all the
  guardian belongs to. And the addresses are reserved for fiction: staff at
  `example.com`, guardians on North American 555-01xx numbers, which the SMS
  provider refuses outright (`messaging/reserved.py`).
- **Never listed or indexed.** Its published pages go out `noindex`, its
  `robots.txt` disallows everything and it has no sitemap. Classnode's own
  sitemap lists no schools. (Platform staff still see it on `/platform/`.)
- **It cannot see or touch another school**: the same membership checks as any
  school, shown by the tests in both directions.
- **Reset touches Crestfield and nothing else.** It refuses unless the school
  called `crestfield` carries the flag and names the schema `crestfield`; it drops
  that one schema and builds it again; in the shared tables it changes only rows
  of this school or of the `cfc.` logins. Memberships are never deleted: anyone
  a visit added is ended, as a school would end them.

## On the server

From `/opt/classnode/deploy`, with the running release's tag in the shell, as
every `docker compose` command there needs (`docs/deployment.md`):

```bash
cd /opt/classnode/deploy && export CLASSNODE_TAG=$(cat deployed-sha)
```

**Once: the passwords.** Choose three, at least twelve characters each, and
keep them in your password manager too. The file is root's, mode 600:

```bash
umask 077
cat > /etc/classnode/crestfield.env <<'EOF'
CRESTFIELD_PRINCIPAL_PASSWORD=<choose one>
CRESTFIELD_TEACHER_PASSWORD=<choose one>
CRESTFIELD_PARENT_PASSWORD=<choose one>
EOF
chmod 600 /etc/classnode/crestfield.env
```

**Once: make the school** (a few minutes):

```bash
set -a; . /etc/classnode/crestfield.env; set +a
docker compose run --rm -e CRESTFIELD_PRINCIPAL_PASSWORD -e CRESTFIELD_TEACHER_PASSWORD \
  -e CRESTFIELD_PARENT_PASSWORD web python manage.py crestfield create
unset CRESTFIELD_PRINCIPAL_PASSWORD CRESTFIELD_TEACHER_PASSWORD CRESTFIELD_PARENT_PASSWORD
```

**Before each visit: reset it** (a few minutes; the school's pages fail while
it runs, other schools are not affected):

```bash
docker compose run --rm web python manage.py crestfield reset
```

Reset keeps the passwords. To change them, edit the file and run the reset with
the variables passed, as `create` takes them.

A reset that stops half way (a deploy, a lost connection) leaves the school
broken but alone; run it again.

## Brochure screenshots

`docs/brochure/`, taken by `scripts/brochure_shots.mjs` from a **local** copy,
never production: it prints a lost result-checker slip and reprints JSS 3A's
exam slips, which mint PINs. Phone screens are 390 CSS pixels wide at 2x (780
by 1688); the report card is also taken at desk width, and the printed slips are an A4 page at 300 dpi.

```bash
export PLATFORM_DOMAIN=classnode.co DJANGO_DEBUG=1 CRESTFIELD_PRINCIPAL_PASSWORD=... \
  CRESTFIELD_TEACHER_PASSWORD=... CRESTFIELD_PARENT_PASSWORD=...
python manage.py migrate_schemas --shared && python manage.py setup_portal
python manage.py crestfield create && python manage.py collectstatic --noinput
python manage.py runserver 0.0.0.0:80 &          # the browser maps *.classnode.co here
node scripts/brochure_shots.mjs
```

| file | screen |
|---|---|
| `01-home.png` | the principal's home |
| `02-marking-sheet.png` | JSS 2B mathematics exam, as its teacher marks it |
| `03-report-card-ogun.png` | the Ogun State sheet, the parent's view, at the subjects |
| `04-result-check.png`, `04b-result-check-card.png` | the result checker: admission number and PIN, then the card |
| `05-fees.png` | JSS 2A's fees, each child's account |
| `06-attendance-register.png` | JSS 2B's register |
| `07-school-website.png` | the school's website home |
| `08-exam-slips-page.png`, `09-exam-slip.png` | the exam slips page, and a printed sheet of slips |
| `10-report-card-desktop.png` | the whole report card at desk width |

There is no question bank screenshot: the bank is not built (above).
