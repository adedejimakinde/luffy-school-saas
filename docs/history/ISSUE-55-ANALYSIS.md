# Issue #55 — which of (a)/(b)/(c) the codebase actually permits

Analysis only. No code written. Against `main` at `2b322ae`.

---

## Short answer

- **(a) is blocked in the database.** Not a preference — it is the single
  operation `0018` exists to refuse.
- **(b) is blocked, but by one line of Python**, and that distinction matters.
- **(c) exists, and the code already committed to it in writing** — then never
  did it. `results/api.py:180` says a released term must be served from the
  snapshot once task 3 lands. Task 3 landed in #44. The broadsheet was never
  switched.

The consequence of that last point: **the two disagreeing rankings already exist
today**, with no revision at all and without #54.

---

## (a) Re-rank all forty-five, position updated in place on the forty-four

**Blocked, in the database.**

`results/migrations/0018_a_frozen_card_is_append_only.py` installs a
`BEFORE UPDATE OR DELETE` trigger on `results_releasedcard` that raises
`restrict_violation`. The same on `results_releasedsubjectresult` (which carries
`subject_position`) and on `results_releasedassessmentscore`.

"Updating `position` in place on a released card" is precisely and only what
that trigger refuses. Its docstring gives the reason it lives in the database
rather than in `save()`:

> the import, the `psql` session and the bulk `.update()` never go near a model
> method, and every one of those is a real way a school's data gets edited in
> anger.

So (a) is not a design choice that could be revisited under pressure. It is the
thing 0018 is for. **Your reading is correct.**

---

## (b) New versions for all forty-five, badge only on the corrected child

**Blocked — but the blocker is a property definition, not a constraint.**

`ReleasedCard.is_revised` (`results/models.py:2043`) is `version > 1`, and its
docstring calls it **"The only source of that word."** Bumping forty-four cards
to version 2 therefore stamps "Revised" on forty-four families' cards over a
change to somebody else's child. **Your reading is correct.**

Why it reads `version > 1` rather than "a `CardRevision` row points at this
card": the issue-#31 child. Her *first* card arrives through the revision path,
at version 1, with a `CardRevision` row recording who gave it to her and why.
Keying the badge on the audit row would stamp "Revised" across the only card she
has ever had.

**Worth noting, because it changes what kind of blocker this is.** That case
does not uniquely force `version > 1`. A per-card boolean set at INSERT would
satisfy her equally — her flag would simply be `False` — and INSERT is exactly
what `0018` deliberately leaves open ("On UPDATE and DELETE, never on INSERT").

So (b) is *available*, at the price of redefining "Revised" from *"this version
supersedes an earlier one"* to *"this card's content changed"*. Not recommended
below, but it is a choice rather than a wall, and it should be recorded as one.

---

## (c) What the code already implies

`results/api.py:180`, the broadsheet endpoint's own docstring:

> **Read from live marks.** There is no frozen snapshot yet — that is task 3 —
> and once there is, a *released* term must be served from it rather than from
> here, because a position recomputed after release can silently disagree with
> the card a parent is holding.

**Task 3 shipped in #44. The broadsheet was never switched.** It still calls
`positions.class_results(class_group, term)`, which calls
`roster(class_group, term)`, which reads current `ClassPlacement` rows with no
as-of-release filter.

### What that means concretely

Marks are safe: `gradebook/services.py:210` (`_require_the_sheet_is_open`) locks
mark writing at release. That is why #54 exists and why a revision cannot yet
change a mark.

**The roster is not safe.** A child placed into a released term — issue #31 —
changes the live roster. The broadsheet then ranks forty-six children and
reports `roster_size` 46, while all forty-five frozen cards still say 45.

So #55 is mis-framed as *"a revision creates a second ranking."* It is:

> **The live ranking and the frozen ranking were never reconciled, and a
> revision is one of several ways they drift** — the roster being the one that
> is already drifting today.

The revision is a symptom of an unfinished migration, not the cause.

### The third answer

**Serve a released term's broadsheet from the snapshot, and leave every card
alone.**

- No card is updated in place → (a)'s trigger is never approached.
- No card gets a new version → (b)'s collision never arises.
- One ranking per released term, and it is the frozen one, which is the artefact.
- A mark-changing revision (#54) still eventually needs a class-wide re-freeze —
  but that decision belongs with #54, when there is something concrete to
  re-freeze, rather than being pre-committed now.

---

## Check 1 — what the class-average decision implies

`positions.class_average()` (`results/positions.py:433`) states both halves in
one breath:

> a stored copy is a fact about forty-five other children, and a later revision
> to any one of them would leave a released card carrying a number that
> disagrees with the rows it claims to summarise. **Position is the opposite
> case and *is* frozen at release** — it depends on everyone else's scores at
> that moment and cannot be recomputed later without changing.

**The two clauses do not actually oppose each other.**

- The reason given for *not* freezing `class_average` — "a fact about forty-five
  other children" — is true of `position` verbatim. `results/cards.py:245` says
  so in almost the same words: *"`position` and `roster_size` are statements
  about the other forty-four children."*
- The reason given for freezing `position` — "cannot be recomputed later without
  changing" — argues that the release-time rank is **unrecoverable**. That is a
  reason to keep it *if something needs it*. It is not a reason that keeping it
  is safe.

So the asymmetry rests on exactly one real difference: **`class_average` is
never on a card; `position` is.**

Under (c) the asymmetry resolves without being overturned. For a released term,
`class_average` can be derived from the frozen cards' own `own_average` values —
still never stored, just read from the same generation as the positions. Both
numbers then come from the same forty-five rows and cannot disagree.

---

## Check 2 — does anything a parent sees read position off a released card?

**No.** Confirmed at four surfaces:

| surface | result |
| --- | --- |
| `ReportCardOut` (`results/card_api.py`) | no slot for `position`, `roster_size` or `subject_position` |
| PDF (`results/pdf.py:91`) | built from `card_payload()` — the same object the page is served from, so the exclusion is structural rather than repeated in a template |
| `results/templates/results/report_card.html` | no position field; only a comment recording why |
| broadsheet (`results/api.py`) | gated by `_require_position_authority` |

No CSV or export path exists. The only `Content-Disposition` in the codebase is
the PDF download (`results/card_api.py:640`), which goes through the same
payload.

### So the severity does change

No family can see the disagreement today. It is **staff-side**: a school reads a
rank off the broadsheet and tells a parent.

I would still keep `must-fix-before-release`. The pilot's premise is that the
school's screen and the card agree, and this is exactly that failure — but the
mechanism is a person relaying a number, not a wrong page. That is worth stating
accurately in the issue, because it changes what a fix has to be fast enough to
beat.

---

## One caveat for whoever implements (c)

The trap named at `results/card_api.py:34` goes live under (c). **`position`
means two different things:**

- on `ReleasedCard` — the child's **rank in the class** (staff-only);
- on `ReleasedSubjectResult`, and on the frozen assessment cells and trait
  ratings — **where the line prints**, smallest first (not sensitive).

The rank *in a subject* is `subject_position`, a different column on the same
table. Anything that moves the broadsheet onto the snapshot has to read the
right one, and the names will not help.
