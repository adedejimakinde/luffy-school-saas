# The fee schedule, and withholding a card for fees

**Design, not built.** No code exists for anything below. This is the document
to argue with; when it is implemented it splits in two — the billing half joins
`fees.md`, the withholding half becomes `withholding.md` — and this file goes
away. It is one file now because the two halves were settled in one pass and one
of them is only comprehensible next to the other.

Written against `main` at **`70062c6`**, and every file and line it cites was
read there. It leans on `operating-rules.md` by number rather than re-arguing:
**rule 1** (guard on the artefact, not current placement), **rule 2** (content
copied at write time, never joined to), **rule 3** (immutability lives in the
database), **rule 4** (an audit is append-only rows), and **rule 8**, which was
written out of this design.

Everything here follows from the nine domain answers it was written against,
plus three questions it originally left open which the review pass has since
closed — those are listed near the end, under *Settled in review*. Where a
decision was made *by the school* rather than by the code, it is marked
**ruled**; where the code chose, the reasoning is given and can be overturned.

---

## What is already true, and must stay true

Two of the four billing answers are satisfied by the ledger as built, and the
value of writing them down is that each names a plausible "improvement" that
would break them.

**Payment is against a child.** `FeeLedgerEntry.student_membership_id` is a
STUDENT membership, which pins the child and the school in one value. A parent
paying for three children produces three sets of entries and three balances, and
there is no family concept anywhere in `fees/`.

The consequence: one transfer covering three children is **three PAYMENT rows
sharing one `reference`** — the teller number. `reference` is free text and
non-unique, and it must stay non-unique. A future reader will want a unique index
there to stop a receipt being keyed twice; it would refuse the ordinary Nigerian
case. That belongs in the field's docstring before somebody tries it.

**Part-payment is the common case, and it already is one.** A balance is
`SUM(amount_kobo)`. Half now and half later is two PAYMENT rows and nothing
special. The thing to protect is the *absence* of allocation, which `fees.md`
lists as not built: allocation is the machinery that forces an answer to "which
charge does this half-payment settle?", and for a term fee the honest answer is
*none of them specifically — it reduces what is owed*. Part-payment being normal
is the argument for keeping allocation out, not for building it.

---

# Part 1 — Billing

## 1.1 `FeeSchedule` and `FeeScheduleLine`

One bill per class per term, itemised. **Ruled: lines, not a single amount.** The
argument is not that parents like breakdowns; it is that the ledger's only
correction is reverse-and-repost. With one lumped ₦140,000 charge, a school that
gets the PTA levy wrong must reverse the whole term's charge for every child in
the class and post it again. With lines they reverse the levy. Itemisation makes
corrections proportionate to the mistake, which is the reason the reversal model
exists at all. A school with one line has one line.

```
FeeSchedule                                          tenant schema
    term            FK -> academics.Term        PROTECT
    class_group     FK -> academics.ClassGroup  PROTECT
    created_at
    updated_at

FeeScheduleLine                                      tenant schema
    schedule        FK -> FeeSchedule           CASCADE
    description     what this line is for, in the school's words
    amount_kobo     positive whole kobo, a magnitude
    position        print order
    created_at
    updated_at
```

Both foreign keys on `FeeSchedule` are tenant → tenant, so they are real keys
that really protect — the same reason `FeeLedgerEntry.term` is a `ForeignKey`
while `student_membership_id` is a bare id. `PROTECT` on both: a term or a class
with a bill against it is not a row to delete out from under it.

`schedule` is `CASCADE` because a line has no meaning without its bill. That does
**not** make a used schedule deletable — see `source_line` below, which is
`PROTECT`, and Django resolves the protected relation before the cascade
completes.

### The schedule is a template. The entry is the artefact.

`fees.md` asks this and leaves it open: *does editing a schedule change past
charges? no — but then what does it change?*

The answer is the `ReleasedCard` answer. Applying a schedule posts CHARGE entries
that freeze the amount and the narration. Editing the schedule afterwards changes
only what a **future** application would post. A school that edits after applying
and wants the difference reflected reverses and re-posts, which the ledger
already does.

So `FeeSchedule` and `FeeScheduleLine` are **plain editable rows** — no
append-only `save()`, no trigger. They are not financial records. The entries
they produced are, and those are already append-only twice over.

This is **rule 8** doing its first piece of work: a decision that produces a
frozen artefact needs no log of its own. It cuts the other way too — because the
entries are append-only and freeze the amount and the wording, the template that
produced them is free to stay editable, which is what lets a bursar fix next
term's bill.

### Constraints

| constraint | what it refuses |
| --- | --- |
| `one_fee_schedule_per_class_per_term` | unique `(term, class_group)`. Two bills for JSS1's first term is not a school with options; it is a school about to charge twice |
| `a_bill_names_each_line_once` | unique `(schedule, description)`. Two "PTA levy" lines on one bill is a typo, and forbidding it is what makes the idempotency skip below legible |
| `a_schedule_line_charges_something` | `amount_kobo > 0`. Zero is a placeholder somebody meant to fill in; negative is a concession wearing a charge's clothes, and concessions have their own table |

`FeeScheduleLine.Meta.ordering = ["position", "id"]`. The `id` tiebreak is not
decoration — two lines at the same position must not swap between two reads of
the same bill, for `Trait.position`'s reason.

## 1.2 `FeeConcession`

**Ruled: fixed amounts only.** A percentage needs a rounding rule to the kobo
*and*, now that lines exist, an answer to "a percentage of which lines" — two
decisions bought for one convenience, when a 50% scholarship is expressible as a
fixed amount today. If schools ask for percentages that is a real feature request
with real answers, not a guess made now.

**Ruled: the exception is a DISCOUNT, not an override amount.** A staff child is
charged the full ₦150,000 and given a ₦150,000 concession, not billed ₦0. The
ledger already made this argument for itself — `discount()` exists as its own
kind because *"we waived it" and "they paid it" are different facts* — and an
override amount would erase the concession from the record entirely. The
consequence is that the per-child exception needs no change to the default shape
at all.

```
FeeConcession                                        tenant schema
    student_membership_id   bare id, indexed  -> accounts.Membership (STUDENT)
    amount_kobo             positive whole kobo, a magnitude
    reason                  "Staff child", "Bursary 2026" — becomes the narration
    is_active               a concession no longer granted. Kept, because entries name it
    granted_by_id           bare id, nullable -> accounts.User
    granted_at
    updated_at
```

Note what is **not** here: no `student_name` snapshot. The ledger entry freezes
identity because it is a record; this is a live instruction and freezing a name
onto it would be a second, staler answer to a question `accounts` already
answers.

**No window, no term key.** A concession applies to every application run while
`is_active`, and is switched off rather than end-dated. A school setting up a
future term with a concession that has since been withdrawn is the edge this
gives up, and the record of what actually happened is unaffected — that is the
dated DISCOUNT entries, one per term, which stand whatever happens to this row.

**Several concessions per child is allowed**, deliberately: a bursary and a
sibling discount are two facts and two DISCOUNT entries. There is therefore no
unique constraint on `student_membership_id`, and idempotency is keyed on the
concession rather than the child — see below.

| constraint | what it refuses |
| --- | --- |
| `a_concession_reduces_something` | `amount_kobo > 0` |
| `a_concession_says_why` | `reason` matching `\S`. **Not** `~Q(reason="")` — `results/models.py:285` records why: a reason of three spaces passes the empty-string test, is refused by the service, and renders blank on a screen. The regex is the form that agrees with the service |

## 1.3 Two new columns on `FeeLedgerEntry`, and one new kind

```
    source_line        FK -> FeeScheduleLine  PROTECT  null=True
    source_concession  FK -> FeeConcession    PROTECT  null=True
```

Both tenant → tenant, so real keys. `PROTECT` on both, for `term`'s reason: a
schedule line or a concession that has moved money is part of the story. A line
that has charged nobody stays freely deletable, which is the rule a bursar
actually needs — fix next term's bill freely, and never delete the one that
billed forty-five families.

**A reversal copies its target's source.** The reversal of a schedule charge
carries the same `source_line`, so "everything this line produced" returns the
mistake and the fix together, exactly as `reference` is already copied by
`reverse_entry()`.

### `REFUND`, the new kind

**Ruled: money is carried, not returned, as the default — and the ledger does not
enforce that.** A mid-term withdrawal posts entries like anything else; the
credit simply stands as a negative balance against the child, which requires no
machinery at all. What is new is that a school which *does* hand cash back has a
way to say so:

```
    REFUND = "refund", "Refund"
```

Its sign is **positive**, alongside `CHARGE`: a family in credit at −₦50,000 who
are handed ₦50,000 return to zero. So:

```
    INCREASES_DEBT = (FeeEntryKind.CHARGE, FeeEntryKind.REFUND)
```

and the existing check constraint generalises from `~Q(kind=CHARGE) | ...` to
`~Q(kind__in=INCREASES_DEBT) | ...`, renamed
`a_charge_or_refund_increases_what_is_owed`. The tuple-of-one was written to be
extended and this is the extension.

> **The tuple trap applies to every new `kind__in` constraint below.**
> `fees/models.py` records it: a `frozenset` in a `Q(kind__in=...)` inside a
> check constraint serialises in hash order, Python randomises string hashes per
> process, and `makemigrations --check` then goes red on a random subset of CI
> runs forever. `INCREASES_DEBT` and `REDUCES_DEBT` are tuples for that reason
> and any new constant here must be too.

A school that pro-rates a withdrawal posts a REVERSAL or a DISCOUNT by hand. The
ledger records what happened; it does not hold a refund policy.

### Constraints

| constraint | what it refuses |
| --- | --- |
| `a_schedule_line_charges_a_child_once` | unique `(student_membership_id, source_line)` where `source_line` is not null **and** `kind = CHARGE`. This is the idempotency backstop |
| `a_concession_discounts_a_child_once_per_term` | unique `(student_membership_id, term, source_concession)` where `source_concession` is not null **and** `kind = DISCOUNT` |
| `a_schedule_line_only_produces_charges` | `source_line` set on anything but a CHARGE or a REVERSAL |
| `a_concession_only_produces_discounts` | `source_concession` set on anything but a DISCOUNT or a REVERSAL |
| `an_entry_has_one_source` | both source columns set at once |

Two details in the first two rows carry weight.

**The schedule key needs no `term`; the concession key does.** A line belongs to
a schedule which belongs to exactly one term, so `(student, source_line)` is
already term-scoped and adding `term` would be a wider key that means the same
thing. A concession is standing and applies every term, so its key must name the
term or a scholarship would be granted once and never again.

**Both are conditioned on `kind`, and that is what lets a reversal keep its
source.** Without the `kind` half, reversing a schedule charge would collide with
the charge it reverses on the very index meant to stop double-billing.

### The re-post corner, stated so it is not filed as a bug

**Ruled.** A schedule charge that has been reversed **cannot be re-posted by
re-running the application.** The reversed original still exists — the ledger is
append-only, so it always will — and `a_schedule_line_charges_a_child_once` still
sees it.

That is correct rather than a limitation: deliberately undoing a charge and then
wanting it back is exceptional, and should require an explicit `charge()` rather
than being reachable by clicking the same button twice. It goes in the
constraint's own docstring, because the next reader will otherwise file it.

## 1.4 Applying a schedule — `fees/schedules.py`

```
apply_to_class(schedule, *, by, effective_on=None) -> AppliedSummary
```

**Idempotent by skipping, not by refusing.** Re-running is normal: a school
charges in week one, three children are admitted in week three, they run it again
and only the three are charged. So the service skips any child who already has a
CHARGE for `(child, line)`, and any child who already has a DISCOUNT for
`(child, term, concession)`.

The unique indexes are the backstop, not the mechanism. The service is what gives
a bursar "42 skipped, 3 charged" instead of an `IntegrityError`.

**One roster read.** The roster comes from `academics.ClassPlacement` for
`(class_group, term)`, read **once** and reused for both the charges and the
concessions. Issue #43 is the lesson: a release read the roster four times, the
office committed a placement between two of them, and the release died. The
hazard is smaller here — there is no dependent write chain — but "who is being
billed" should be decided once, and a second read is a second answer.

Read from `academics` directly rather than through `results.positions`; `fees`
has no business importing `results`, and `academics` sits under both.

**Locked on the schedule row.** Two bursars clicking "Charge JSS1" at the same
instant both pass an unlocked skip-check before either commits, which is
`reverse_entry()`'s race exactly. The application takes
`FeeSchedule.objects.select_for_update().get(pk=...)` first, which serialises
applications of the same bill and nothing else.

> `FeeSchedule.Meta.ordering` must sort by its own columns only. Commit `034b6b3`
> is the standing lesson: a joined `Meta.ordering` makes `select_for_update()`
> lock every joined table, so an ordering that reaches into `Term` would have the
> billing run locking the term row it never writes.

**One transaction for the whole class.** A half-applied bill is worse than none,
and a class is bounded.

**No run table.** Who applied a bill and when is already on every entry it
produced — `recorded_by_id`, `effective_on`, `recorded_at`. A run row would be a
second answer to a question the entries answer.

## 1.5 The class-keying note

The schedule keys on `ClassGroup`, but `ClassPlacement` is the row that says who
sits in JSS1, and it **rewrites** on a mid-term move — the premise trap #31, #33
and #34 all turned on. A child charged as JSS1 in week one who moves to JSS3 in
week four keeps the JSS1 charge unless a person acts.

That is correct: a posted charge is a fact. It has to be *stated*, because the
obvious repair is to recompute the charge from live placement, and that
recomputation is the same class of bug as keying a release on placement.

---

# Part 2 — Withholding a card

**Ruled: the card is always frozen at release for every child, unconditionally.
What fees gate is whether the card is SERVED.**

Nothing in Part 2 touches `release()`, `cards.freeze_for_release()`, or any
frozen table. Making the freeze conditional on payment would leave an unpaid
child with no frozen record of that term, permanently — the exact failure #31,
#33 and #34 converged on, and it must not come back through the fee door.

## 2.1 Policy: a switch, and the contact it requires

Two new columns on `results.ReportCardSettings` — the existing one-row-per-schema
settings table:

```
    withhold_for_fees_enabled   BooleanField(default=False)
    withholding_contact         CharField(blank=True)
```

**The default is off, and it is load-bearing** for the reason both trait sections
default to off: a school that has never heard of this feature must see no trace
of it. Without the off-default, every existing school acquires a fee gate on the
day this ships.

**`withholding_contact` is required whenever the switch is on**, and that is a
database constraint rather than a convention:

| constraint | what it refuses |
| --- | --- |
| `a_withholding_school_names_who_to_call` | `~Q(withhold_for_fees_enabled=True) \| Q(withholding_contact__regex=r"\S")` |

This exists because of a gap found while writing this document: **`schools.School`
has no contact fields at all** — `name`, `slug`, `is_active` and nothing else. The
403 below promises a family somebody to call, and without this the platform would
be making a promise it cannot keep, which is issue #53's shape exactly. Putting
the contact in the tenant settings row rather than on `School` also puts it where
the policy lives: the school that turns withholding on is precisely the school
that must say who a parent should ring.

**Ruled: `withholding_contact` is plain free text, and this PR invents no contact
model.** It holds what the school would say on the phone — *"Call the bursar's
office on 0803 …"* — and the constraint above is what makes it load-bearing
rather than decorative: the switch cannot be turned on without it. A school that
enables withholding without telling families who to call has built a dead end.

**The refusal is a constraint and not a form validator**, for the reason rule 3
gives: a validator is a promise kept by one code path, and the admin, a shell, a
data migration and a test fixture are four others. A dead end reachable by any of
them is still a dead end for the family standing at it. Structured contact fields
on `School` remain a real gap and a different PR; free text with a non-empty
constraint is the smallest thing that keeps *this* promise without inventing a
contact model inside a fees change.

> **The new columns sit outside `FIELD_FOR`.** That map is a trait-group-indexed
> API — `enabled(group)` refuses a group it does not know — and neither new
> column is a trait group. `enabled("withhold_for_fees")` must not become a
> thing.
>
> The alternative considered was a third settings singleton beside
> `ReportCardSettings` and `SessionSettings`. **Ruled: two columns here, no
> third singleton.** `SessionSettings` earned its own row because it holds
> arithmetic that `results.sessions` owns end-to-end, not because settings split
> by subject, and one boolean plus one string does not earn a table. The
> deciding reason is the reader's rather than the schema's: withholding is a
> property of *how this school handles report cards*, which is exactly what this
> table is, and a third singleton would be a third place to look for "how does
> this school behave" — while the switch's whole job is gating a card.

Read through `ratings.settings()`'s pattern — filter on `pk=1`, fall back to an
**unsaved default**, never write on a read path. The unsaved default has the
switch off, which is the right answer for a schema with no row.

## 2.2 Decision: `results.WithholdingDecision`

The `PromotionDecision` pattern, because this is the same kind of thing: one
recorded decision about one child, written once, never changed.

```
WithholdingDecision                                  tenant schema
    student_membership_id       bare id  -> accounts.Membership (STUDENT)
    term                        FK -> academics.Term  PROTECT
    status                      withheld | lifted
    reason                      why, in the school's words. STAFF-ONLY
    balance_kobo_at_decision    signed, nullable — what the books said, frozen
    decided_by_id               bare id, nullable -> accounts.User
    decided_at
```

**Keyed on `(child, term)`, not on the card row. Ruled, and it is a trap.** A
revision writes a new `ReleasedCard` at the next version, and there can already
be two cards in one term when a child moves class. A decision keyed on the card
would not cover a version made after it, so correcting a withheld child's mark
would serve the card the school had withheld.

**`term` is a real ForeignKey, unlike `PromotionDecision.session`.** That model
stores a string because a session is three terms and there is no session row to
point at. Here there is a term row, in the same schema, so the key is real and
`PROTECT` really protects.

**Status is `withheld` / `lifted`, not `withheld` / `released`.** "Released" is
taken by the academic act and a collision here would be genuinely confusing —
`SheetState.RELEASED` is what put the card in existence; this is about whether
the family gets it.

**Absence of a row means not withheld.** No `UNDECIDED`, no default status, no
current-state column anywhere. `PromotionDecision`'s argument transfers intact: a
status column defaulting to something is a school-wide policy performed by a
default value.

**More than one row per `(child, term)` is the feature**, so there is
deliberately **no unique constraint**. Withheld on the 3rd and lifted on the 12th
when the family paid is two rows and both stand — which is the whole reason this
is not a boolean. A boolean flipped twice has forgotten that it was ever
different, who changed it, and when, and that is precisely what a parent's
complaint six months later turns on.

**`balance_kobo_at_decision` is frozen, and there is deliberately no `suggested`
column.** `PromotionDecision` stores `suggested` beside `session_average` because
the arithmetic really did propose something. Here the arithmetic proposes
nothing: **the balance never gates.** A rule like *withhold while balance > 0*
would withhold from a family ₦500 short on a payment plan, and part-payment is
the normal case. The balance is frozen so the row reads on its own in a year —
not so it can be checked against the decision. A `suggested` column would invite
exactly that reading.

**Ruled: the balance frozen is everything outstanding, not this term only.** A
child carrying arrears from last term is exactly who a school withholds over. It
is `FeeLedgerEntry.objects.for_student(id).balance()` with no `for_term()`.

### Constraints and enforcement

| constraint | what it refuses |
| --- | --- |
| `a_withholding_says_why` | `~Q(status=WITHHELD) \| Q(reason__regex=r"\S")`. A withholding must say why; lifting may be silent. The shape and the name follow `a_revision_says_why` (`results/models.py:2413`) and `ResultSheetTransition`'s send-back rule (`:285`), including the regex rather than `~Q(reason="")` |

Append-only, enforced the two ways this codebase always does it:

- `save()` refuses an update and `delete()` refuses outright, raising
  `WithholdingDecisionsAreAppendOnly`. That is the error a developer sees.
- A **trigger** — `results_withholding_decisions_are_append_only()` on
  `results_withholdingdecision`, `BEFORE UPDATE OR DELETE FOR EACH ROW`,
  `ERRCODE = 'restrict_violation'`, created unqualified so it lands in each
  school's own schema. That is the error a `psql` session, a data import or a
  bulk `.update()` runs into.
- **Not on INSERT**, for migration `0013`'s reason: this table is written once by
  the code that owns it, and refusing INSERT would refuse the write that creates
  the row.

`Meta.ordering = ["student_membership_id", "term", "-decided_at", "-id"]`, and
the `-id` tiebreak is not decoration: `auto_now_add` can tie to the microsecond,
and "the latest decision" resolving arbitrarily between two rows is a card that
is served or withheld depending on nothing.

One index, `the_latest_withholding`, on those same four fields — leading pair is
the lookup, descending tail is the ordering, so one index answers both halves.

### No lock on the write

`reverse_entry()` locks because it defends an at-most-once rule. There is no such
rule here: two people deciding at the same instant write two rows, both stand,
and the ordering resolves which holds. Nothing to race on, so nothing to lock —
worth stating so the absence reads as a decision.

## 2.3 The read — `results/withholding.py`

```
is_withheld(student_membership_id, term) -> bool
```

1. `if not settings().withhold_for_fees_enabled: return False`
2. latest row for `(child, term)`; `None` → `False`
3. `row.status == WITHHELD`

**Step 1 before step 2 is the composition, and it is the point.** The switch
gates whether decisions are consulted at all. A school turning the feature off
serves every card immediately, without walking back four hundred rows; the rows
survive, so turning it back on restores the state rather than having lost it.

**This module imports nothing from `fees`.** At serve time the gate reads a
settings row and a decision row and never touches the books, so a ledger that is
locked, slow or mid-import cannot affect a single card. Only the *recording* of a
decision touches `fees`, and only to snapshot a number — see 2.5.

Putting the read here rather than in `card_api`'s private helpers is what makes
it reachable from **both** serving surfaces — and there are already two. See
2.4, which is the part of this design that changed most once it was checked
against `main` rather than against an older branch.

## 2.4 The gate at the edge — `results/card_api.py`

### `_may_read()` returns the claim, not a bool

This is the structural consequence. **Ruled: staff always see a withheld card** —
a bursar who cannot see what they are withholding cannot do the job — so the gate
has to know *which* of the three readers is asking, and `_may_read()` currently
collapses all three into a boolean.

```
CardClaim = SELF | GUARDIAN | STAFF          # None when there is no claim
FAMILY_CLAIMS = frozenset({SELF, GUARDIAN})
```

The three checks keep their order and their reasoning — cheapest first, the
guardianship query last. Only the return type changes, and
`_require_may_read()` returns the claim rather than nothing.

`FAMILY_CLAIMS` is **not** `accounts.FAMILY_ROLES`. A claim is not a role: a
guardian's claim comes from `Guardianship`, which links a login to *one child*,
while holding PARENT at a school says only that somebody is *a* parent there.
That distinction is the whole reason `_may_read()` is a function and not a role
test, and the new constant must not blur it.

### The gate is a separate check, not a clause inside `_may_read()`

`_may_read()` answers *does this person have a claim on this child's card*. Fees
answer *is this card being served to this family right now*. `card_api.py:105-112`
already makes this argument for why `CARD_VIEWING_ROLES` is not imported from
`POSITION_VIEWING_ROLES`: tying two questions together means a later widening of
one silently widens the other.

### There are two serving surfaces, not one, and that is a finding

This section is the part of the design that changed when it was checked against
`main`. **`results/card_api.py` now serves the same card twice:**

```
    GET /cards/{student}/{term}/         report_card()      line 530
    GET /cards/{student}/{term}/pdf/     report_card_pdf()  line 651
```

`report_card_pdf()`'s own docstring states the contract this gate has to satisfy:

> *The four lines of authority below are `report_card()`'s — the same calls in
> the same order — because a PDF of a card you may read is not a second
> permission. Every refusal is that route's flat 404 [...] a file route that
> answered otherwise would be the existence oracle the JSON route refuses to be,
> **reachable by adding four characters to a URL**.*

A withholding gate fitted to `report_card()` alone is exactly that: a family
refused the JSON card appends `/pdf/` and is handed the file. The existing
docstring predicted the shape of the bug before this feature existed, which is
the strongest possible argument for taking it literally.

**So the gate is one shared helper, called identically in both routes**, in the
same position in the same sequence:

```
def _require_servable(claim, child, term):
    """403 for a family reader whose school is withholding this card."""
```

Not a clause bolted into each view. The rule "a PDF of a card you may read is not
a second permission" becomes "a PDF of a card you may *be served* is not a second
permission", and it stays true only if there is one function to change.

### The order, which is the security property

Identical in both routes:

```
    school = _school_of(request)
    child  = _the_child(school, student_membership_id)        # 404
    claim  = _require_may_read(request.user, school, child)   # 404
    card   = cards.card_for(child, term)                      # 404 if none
    _require_servable(claim, child, term)                     # 403 if withheld
    ...                                                       # then, and only then,
                                                              # the payload or the file
```

- A **stranger** gets 404 and learns nothing — the existence oracle stays shut.
- A **guardian of a child with no released card** gets 404. Nothing was withheld,
  because nothing exists.
- A **guardian of a child whose card is withheld** gets 403, on both routes.
- **Staff** get the card, on both routes.

**On the PDF route the gate must sit before the marker is consulted.** Today the
route reads `renders.marker_for(card)` and answers either the file or a 202
carrying `state`, `state_label` and a detail string. A withheld family reaching
that code learns whether their child's card has been rendered, and a 202 telling
them the file is "still being prepared" is a worse lie than the 404 this design
already rejects — it promises a document that is never coming. The gate goes
above it.

### The PDF is still *built* for a withheld card

Freeze always, gate the serving — and render always, on the same reasoning.

`docs/report-card-pdf.md` records that the `ReleasedCardPdf` marker is written
**at release, inside the release transaction, before any job has run**, precisely
so that "released and never rendered" is a positive fact rather than an absence
somebody has to infer. Making the render conditional on fees would reintroduce
through the fee door the hole that design closed, in the same shape #31, #33 and
#34 closed for the card itself.

It is also the practical answer: a school that lifts a withholding the morning
after a family pays wants the file to exist already, not to start a render the
family waits on.

Nothing in `results.renders` changes. This is a sentence in the design, and a
test.

### 403, and why the convention is broken here

**Ruled.** This API answers every refusal with a flat 404 because a 403 tells a
stranger enumerating membership ids which children are enrolled. That reasoning
is sound and it does not apply to a reader who has already proven a guardianship
claim: they know their child exists and they know the term happened. A 404 would
tell them no card was released, which is a *lie* — the school did release it —
and it sends a parent to the school angry about the wrong thing.

The claim check running first is what keeps the disclosure convention intact for
everyone it was written for.

### What the 403 carries, and what it must not

```
WithheldOut
    school_name         from the card's frozen copy, not a live join   (rule 2)
    contact             ReportCardSettings.withholding_contact
    message             the school is holding this card; please contact them
```

The same body on both routes. The PDF route already returns JSON for its 202, so
a JSON 403 there is not a new shape — and a file route that answered a withheld
family with anything file-like would be answering a question it was refused.

**Not the amount. Ruled: balances are staff-only in this phase.** A
parent-facing balance is a support burden and a correctness risk — a family will
dispute a number the bursar has not reconciled — and it is additive later.

**Not `reason`.** The bursar's words are an internal note and may be unguarded
about a family. `reason` is staff-only in the sense `ReleasedCard.position` is
staff-only: **excluded at the serializer, not merely absent from the template**,
because a field left out of the page but sitting in the JSON has not been left
out.

### `CARD_VIEWING_ROLES` gains `BURSAR`

`card_api.py:111` wrote the prophecy: *"a bursar could reasonably be added here
one day and must never be added there"* — there being
`results.api.POSITION_VIEWING_ROLES`, which still exists at `results/api.py:58`.
This is that day. The two constants are deliberately not tied, so this is a
one-line widening that cannot leak a position, and `ReportCardOut` carries no
position field to leak.

**Ruled: take the widening.** The narrower alternative — a staff screen showing
only *that* a card exists and is withheld — is a second surface answering a
question the first one already answers, and that is the shape which produced four
answers to "did a card go home" and the PR #35 bug with them. One reader, one
answer. A bursar lifting a withholding wants to see the document they are
releasing.

**The widening must leave its reason behind in the docstring.** `card_api.py`'s
comment on `CARD_VIEWING_ROLES` predicted this edit; consuming the prophecy
without replacing it would leave the next reader with a bursar in the set and no
statement of what it does not imply:

> A bursar is here on purpose, and must never be added to
> `results.api.POSITION_VIEWING_ROLES`. The two constants answer different
> questions — who may see what went home, and who may see a rank — and they are
> deliberately not imported from one another so that a widening of one is not a
> widening of the other. This is that widening, and it stops here. Nothing in
> this module has a slot for a position for it to reach.

## 2.5 The write — `WITHHOLDING_ROLES`, and the one place `results` reads `fees`

```
WITHHOLDING_ROLES = frozenset({Role.PRINCIPAL.value, Role.BURSAR.value})

withhold(student_membership_id, term, actor, reason)
lift(student_membership_id, term, actor, reason="")
```

**Ruled: both roles.** Principal-only is the tempting answer because Phase 1
narrowed `RELEASING_ROLES` deliberately, and it is wrong-shaped here: the
principal is not the person who knows the ledger. A principal-only lever means
the bursar walks to the principal's office for every withheld child, which in
practice means the lever gets used from the principal's login by the bursar — and
then **the audit names the wrong person**, which is worse than granting it
honestly. Bursar-only is also wrong: withholding a report card carries academic
weight and a principal must be able to override. The append-only log is what
makes "both" safe — a principal lifting what a bursar withheld writes a second
row, and both acts stand with both names on them.

**Its own constant, never imported from `RELEASING_ROLES`**, and the comment
should say so in `card_api.py:90`'s shape. The two coincide on `principal` today
and answer different questions; tying them means widening one widens the other.

Authority goes through `services._require_authority(actor, WITHHOLDING_ROLES,
"withhold")`, which already resolves the school from the connection and refuses
an unauthenticated actor with a readable message.

**`fees` is imported inside the function, not at module scope.** There is no
import cycle to avoid — the reason is honesty about the dependency surface. The
serving path in 2.3 is in this same module, and a module-level `import fees`
would make "the serving path never touches the ledger" a claim about queries that
the imports contradict at a glance. `release()` already imports its freeze
modules inside the function, so the shape is precedented.

> The alternative is a `balance_kobo` parameter passed in by the bursar's screen,
> which removes the coupling entirely. Rejected: the number on an audit row would
> then be the caller's word rather than the books', which is the one thing that
> row exists to prevent.

---

## What is enforced where

| rule | database | code |
| --- | --- | --- |
| one bill per class per term | unique constraint | — |
| a bill names each line once | unique constraint | — |
| a schedule line charges something | check constraint | — |
| a line charges a child once | partial unique index | service skips first, for a readable result |
| a concession discounts a child once per term | partial unique index | service skips first |
| a source column matches its kind | check constraints | — |
| an entry has one source | check constraint | — |
| a charge or refund increases what is owed | check constraint | `_magnitude()` refuses a signed amount |
| a concession says why | check constraint | — |
| a withholding says why | check constraint | service refuses blank, with a message |
| a withholding school names who to call | check constraint | — |
| decisions are append-only | trigger | `save()` / `delete()` refuse |
| **the freeze stays unconditional** | **nothing can express it** | `cards.freeze_for_release()`, pinned by tests |
| **the switch gates the decisions** | — | `withholding.is_withheld()`, step 1 |
| **the gate spares staff claims** | — | `report_card()`, pinned by tests |
| **404 before 403** | — | the shared call order, pinned by tests |
| **both routes gate identically** | — | one `_require_servable()`, called from `report_card()` and `report_card_pdf()`, pinned by tests |

The bottom four rows are the ones to be nervous about, and the pattern is the one
`ReleasedCard`'s docstring already names: no constraint can express "a row exists
for every child on a roster this transaction has moved on from", so the
unconditional-ness is a property of the code and of the tests that pin it.

## The tests this design owes

1. **The fee door does not touch the freeze.** Release a school with
   `withhold_for_fees_enabled` on and every child in arrears; assert a
   `ReleasedCard` for every child on the roster. This is #31/#33/#34's guarantee
   re-tested through the new door, and it is the single most important test here.

   **A control run is part of the deliverable, not a nicety.** No constraint can
   express "a row exists for every child on a roster this transaction has moved
   on from" — the table at the end of this document has `nothing can express it`
   in that row — so this test is the only thing holding the guarantee, and a test
   that has never been seen red is a test whose subject has never been proven.
   The control: make `cards.freeze_for_release()` skip a child with a standing
   `withheld` decision, which is exactly the bug the fee door invites; run the
   test; show it RED; revert; show it GREEN. Both outputs go in the PR body.
2. A withheld card is served to staff and refused to a guardian, same term, same
   child.
3. A stranger gets 404 for a withheld card, not 403.
4. A guardian of a child with no released card gets 404, not 403.
4b. **The four-character bypass.** Every one of tests 2–4 run again against
   `/pdf/`. A guardian refused the JSON card and handed the file is the failure
   `report_card_pdf()`'s docstring predicted, and it is the one test in this list
   that would catch a gate fitted to one route.

   **Control run required, and it is the more informative of the two.** Fit
   `_require_servable()` to `report_card()` alone, leaving `report_card_pdf()`
   ungated; run tests 2–4 against `/pdf/`; show them RED while the JSON tests
   stay GREEN; revert; show both GREEN. A gate fitted to one route is not a
   hypothetical failure mode — it is what an unwary implementation of this design
   produces, because the JSON route is the one the feature is described in terms
   of and the file route is four characters nobody re-reads.
4c. A withheld card whose PDF is not yet built answers 403, not 202 — the family
   learns nothing about the render state.
4d. The `ReleasedCardPdf` marker is still written at release for a child whose
   school is withholding, and the render still runs.
4e. **A third serving surface cannot be added ungated — as far as a test can
   reach.** Enumerate `card_api.router.path_operations` for every operation whose
   path begins `/cards/{int:student_membership_id}/{int:term_id}`, drive each one
   as the guardian of a withheld child, and assert every one answers 403. The
   test **discovers** routes rather than naming them, so a third surface added
   under that prefix is covered the day it is written and goes red if it does not
   call the helper. An operation the enumeration cannot drive — a different
   signature, a non-GET method — **fails with an explicit message** rather than
   being skipped: an unrecognised serving surface is the finding, not an
   exemption from the finding.

   **Its limit, stated because a coverage claim is exactly the kind of prose that
   goes stale (rule 7).** It proves the property for *this router*. A future
   surface serving card content from somewhere else — a staff export in
   `results/api.py`, an emailed attachment, a management command — is outside its
   reach, because the only thing tying the helper to a route is that the route
   calls it, and no test can enumerate code in a module it does not know to look
   at. So the design's promise is the narrower one, and it belongs in
   `_require_servable()`'s own docstring rather than in a test name:
   **this helper is the only door, and a new way to put card content in a
   family's hands is a change to this design rather than an addition to it.**

5. `reason` and the balance appear in no family-facing payload — asserted against
   the serialised JSON, not the rendered page.
6. Switching the school policy off serves a card that has a standing `withheld`
   decision, and switching it back on withholds it again without a new decision.
7. A revision of a withheld child's card is still withheld — the `(child, term)`
   keying, tested directly.
8. Applying a schedule twice charges nobody twice; applying it after a child is
   admitted charges only that child.
9. A reversed schedule charge is not re-posted by re-running the application.
10. Concurrent applications of one schedule do not double-charge.

## Settled in review, after the first draft

Three questions this document originally left open, and the answers it now
carries in full:

- **The settings placement** (2.1) — two columns on `ReportCardSettings`, no
  third singleton, because withholding is a property of how a school handles
  report cards and a third singleton is a third place to look. With it,
  `withholding_contact` is ruled to be plain free text with a database
  constraint, and no contact model is invented inside a fees change.
- **`BURSAR` in `CARD_VIEWING_ROLES`** (2.4) — take the widening; the narrower
  staff screen is a second surface answering a question the first already
  answers. The docstring carries what the widening does not imply.
- **Revoking a concession** — filed rather than built, as below.

## What this design does not settle

1. **Revoking a concession leaves no log.** Setting `is_active` false records
   *when* through `updated_at` and never who or why. This follows the operating
   rule honestly — the concession produces DISCOUNT entries, so the grant is
   recorded — but the revocation produces an absence in future terms, and by the
   rule's own logic an absence wants a log. Filed as
   [issue #75](https://github.com/adedejimakinde/luffy-school-saas/issues/75)
   with rule 8 quoted in it, so that whoever picks it up can see it is a real
   gap and not a tidiness request. It is not built here because it is a
   different decision type from withholding, and this PR already carries the
   billing half and the card gate.
2. **The takings report** is deliberately out of this phase and is filed as
   [issue #74](https://github.com/adedejimakinde/luffy-school-saas/issues/74),
   so that nothing in the entry shape forecloses it. Three things it asks of
   this design and gets: `effective_on` separate from `recorded_at`, `kind`
   separating money received from money waived, and itemised schedule lines —
   without which "how much of the tuition came in, as against the levy" has no
   denominator.
