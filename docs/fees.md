# The fee ledger

What a family owes a school and what they have paid, as an append-only book.

The book, and since B1 the bursar's routes and page — see "B1" below — and
since B2 the bills and concessions on that page ("B2"). There is no
reporting. `fees/services.py` is the layer `fees/api.py` calls, and the rules
live there rather than in a view so that an import and a management command get
the same ones.

## Three rules, and why each is where it is

### Money is whole kobo, stored as a signed integer

`amount_kobo` is a `BigIntegerField`. Never a float, never a `DecimalField`
column. Naira is a presentation concern that belongs at the very edge, and the
only representation safe in between is a count of the smallest unit — `1500.10`
does not exist in binary floating point, and half the classic accounting bugs
are that sentence.

The **sign carries the meaning**:

| | |
| --- | --- |
| positive | increases what the family owes — a charge |
| negative | reduces it — a payment, a discount, a reversal of a charge |

So a balance is `SUM(amount_kobo)` with no case analysis and no "except the
cancelled ones" clause to forget. `FeeLedgerQuerySet.balance()` is exactly that
sum, and it returns `0` rather than `None` for an empty ledger, because `None`
is not a balance and would print as "None owing".

A negative balance is a real state, not an error: fees paid ahead of the charge
being posted, or an overpayment carried forward.

Because the sign is grammar rather than data, **the caller never chooses it**.
`charge()`, `record_payment()` and `discount()` each take a positive magnitude
and apply the sign themselves; a negative or zero amount is refused, and so is a
`float`. Check constraints hold the same line at the database: a charge must be
positive, a payment or discount must be negative, and nothing may be zero.

### Corrections are new entries. Nothing is ever edited or deleted

A wrong entry is undone by a `REVERSAL` that names it, and the right entry is
then posted fresh. There is deliberately **no free-form adjustment**: an entry
reading "−₦30,000, first number was wrong" tells a reader the difference and
never what actually happened, whereas a reversal plus a re-post leaves both the
mistake and the fix legible a year later.

This is enforced twice, on purpose:

- `FeeLedgerEntry.save()` refuses to write over an existing row and `.delete()`
  refuses outright, raising `LedgerIsAppendOnly`. That is the error a developer
  sees, in the caller's own language.
- A **Postgres trigger**, installed per schema by `fees/migrations/0002`, refuses
  `UPDATE` and `DELETE` on the table. That is the one a `psql` session, a data
  import or a `QuerySet.update()` runs into — none of which go anywhere near the
  model's methods. It arrives as an `IntegrityError`.

The trigger is row-level and deliberately does **not** cover `TRUNCATE`: a
statement-level guard would also block Django's test teardown, and a schema being
emptied wholesale is a different act from a row being quietly rewritten.

Two further rules about reversals, because the interesting ones span rows:

- An entry may be reversed **at most once**, as a partial unique index. Two
  reversals of one charge would take the balance below where it started and read
  as a refund that never happened. `reverse_entry()` also checks under
  `select_for_update()`, because two bursars clicking undo at the same instant
  both pass an unlocked check before either commits — the service call is what
  gives a good error, the index is what makes it true.
- A reversal cannot itself be reversed. Undoing an undo is how a book stops
  being readable; reverse the original, or post a fresh entry.
- A reversal must be exactly equal and opposite to its target. No check
  constraint can express that (it compares two rows), so it lives in
  `Model.clean()` and every service path calls `full_clean()`.

### An entry freezes who it was for

`student_name` and `student_reference` are stored as they stood when the entry
was posted. This is not denormalisation for speed. A financial record has to keep
saying what it said: if a school corrects a child's name or reissues admission
numbers, last term's receipt must still read the way it was issued, and a join to
the live membership would silently rewrite every historical entry.

It is also what keeps the books legible after a student leaves, when the
membership the entry names has ended.

## What it points at, and what it does not

`student_membership_id` is a **bare id**, not a `ForeignKey` — it names the
student's `STUDENT` membership, which pins both the child and their school in one
value, exactly as `Guardianship.student` does. `recorded_by_id` is the same, for
`accounts.User`.

That is the [tenancy.md](tenancy.md) blocker being answered rather than dodged,
and the full reasoning is recorded there. The short version: `PROTECT` does not
protect across schemas, so on the one table where "this history cannot be
destroyed by deleting somebody" is the whole point, a foreign key buys a
guarantee that is false exactly when it matters. **That decision is proposed, not
ratified** — it is platform-wide policy settled by the first model that needed an
answer.

**The bare id is checked, not trusted.** `fees/services.py` refuses a membership that is
not a `STUDENT` membership, and one whose school is not the school whose books are being
written — read from the connection's own schema, since that is what already chose the
table being written to. Without it, one school's ledger could name a child at another
school and nothing would look wrong: the entry would sit in St Mary's books, count towards
a St Mary's balance, and name a student St Mary's has never taught.

Worth being precise about what the missing foreign key actually costs here, because the
obvious reading is wrong. `Membership` is **shared**, so a foreign key into it would
constrain only that the row *exists* — every school's students live in that one table, so
the school half of the question needs asking in code either way. What is genuinely given up
is the existence half.

Tenant → **tenant** foreign keys are unaffected and this model uses two:
`term` onto `academics.Term`, and `reverses` onto itself. Both live in the same
schema, so `PROTECT` there really does protect — a term with money against it
cannot be deleted, and a test pins it.

## The shape

```
FeeLedgerEntry
    term                    FK  -> academics.Term      (same schema, PROTECT)
    student_membership_id   int -> accounts.Membership (bare id, indexed)
    student_name            frozen at posting time
    student_reference       frozen at posting time
    kind                    charge | payment | discount | reversal | refund
    amount_kobo             signed whole kobo
    narration               what this line is for
    reference               teller / receipt number, free text
    reverses                FK  -> self                (reversals only)
    source_line             FK  -> FeeScheduleLine     (what billed it, nullable)
    source_concession       FK  -> FeeConcession       (what discounted it, nullable)
    effective_on            the date it counts for, not the date it was typed
    recorded_at             when it was typed
    recorded_by_id          int -> accounts.User       (bare id, nullable)
```

`effective_on` and `recorded_at` are separate because they disagree: a payment
made on Friday and entered on Monday belongs to Friday.

`reference` is free text because every bank and every school reconciles
differently, and a format guessed now is a format wrong later. It is also
**deliberately non-unique**: payment is against a child, so a parent paying for
three children in one transfer produces three PAYMENT rows sharing one teller
number. A unique index there would refuse the ordinary case.

`refund` is the one kind whose sign surprises people. It is **positive**,
alongside `charge`: a family sitting at −₦50,000 who are handed ₦50,000 in cash
are square, not −₦100,000. It exists because money handed back and a mistake
undone are different facts — the same argument that makes `discount` its own
kind rather than a negative charge. The default answer to a mid-term withdrawal
is still that money is *carried*, not returned: the credit simply stands against
the child, which needs no machinery at all.

Ordering is `-effective_on, -id`. The tiebreak is not decorative — two entries
posted in the same millisecond need a stable order, and a ledger that reorders
itself between two reads is one nobody can reconcile.

## Billing a class: the schedule, the concession, and one application

Charges no longer have to be posted one at a time. `FeeSchedule` is a class's
bill for a term, `FeeScheduleLine` is one item on it, and
`fees.schedules.apply_to_class()` posts the lot.

```
FeeSchedule                          term + class_group, unique together
    FeeScheduleLine                  description, amount_kobo, position

FeeConcession                        a standing discount for one child
    student_membership_id, amount_kobo, reason      never edited (B2, #75)
    FeeConcessionRevocation          who revoked it, when and why
```

**The template is not the record**, which is the question this document used to
leave open — *does editing a schedule change past charges?* It does not.
Applying a schedule posts CHARGE entries that freeze the amount and the
narration; editing the bill afterwards changes only what a **future**
application would post. A school that edits after applying and wants the
difference reflected reverses and re-posts, which the ledger already does.

That is why `FeeSchedule` and `FeeScheduleLine` are plain editable rows with no
append-only `save()` and no trigger — `operating-rules.md` rule 8 in the
direction that saves work. `FeeConcession` was one too until B2; revoking one
produces an absence, which is rule 8 in the other direction (see "B2"). The entries they produce are the
financial record and are already append-only twice over; making the template
append-only too would be a second, weaker copy of that guarantee, and it would
stop a bursar fixing next term's bill.

**Lines rather than one lumped amount**, because the ledger's only correction is
reverse-and-repost. With one ₦140,000 charge, a school that gets the PTA levy
wrong reverses the whole term for every child in the class; with lines they
reverse the levy.

**A concession is a DISCOUNT, not an override.** A staff child is charged the
full fee and given a full concession, not billed nothing — "we waived it" and
"they paid it" are different facts, and an override amount would erase the
concession from the record. Fixed amounts only: a percentage needs a rounding
rule *and* an answer to "a percentage of which lines".

**Applying is idempotent by skipping, not by refusing.** Re-running is the
normal case — a school charges in week one and three children are admitted in
week three — so a child who already has a line's charge is skipped and the
bursar is told "42 skipped, 3 charged". Two mechanisms hold that and they are
not the same one: the service's skip is what produces a readable summary, and
the partial unique index `a_schedule_line_charges_a_child_once` is what holds
when two bursars click at the same instant. `fees/tests/test_schedule_concurrency.py`
carries the measurement that separates them — unlocked, the index still refuses
every double charge and the losing bursar gets an `IntegrityError` instead of a
summary.

**A child whose membership has ended is skipped, and the summary says so.**
Nothing deletes a `ClassPlacement` when a membership ends — the placement is last
term's record and is meant to survive it — so a child released in December is
still on JSS 1A's roster in January. Applying that term's bill again, which
happens whenever a bursar adds a line, would charge somebody who has left.

Skipped rather than refused, for the reason the concession collision is a skip:
one child having left must not stop the class being billed. Counted, though —
`AppliedSummary.students_skipped`, and `__str__` renders it — because a skip
nobody is told about is the silent no-op this module refuses everywhere else.
Note that `students` therefore means "billed", not "on the roster".

`academics` made the same call first: `carry_forward_placements()` filters ended
memberships and calls it "a correctness rule and not a tidiness one", while
`place_student()` deliberately allows an ended child to be placed by hand,
because entering last term's roster after the fact is real work. The automated
path is the one that must not repeat such a mistake across a whole school.

**A reversed schedule charge cannot be re-posted against that line, by any
route.** The reversed original still exists — the ledger is append-only, so it
always will — and `a_schedule_line_charges_a_child_once` still sees it. The
index is on the row rather than on the caller, so an explicit `charge()` naming
the same line is refused exactly as a re-run is; only a charge that does **not**
name the line will post, and that one is no longer attributable to the line.
Both halves are pinned by a test, because the first version of this paragraph
claimed an explicit `charge()` was the escape hatch and nothing contradicted it.

The practical rule that follows: reverse a schedule charge when it should not
have been raised, not when its *amount* was wrong. A wrong amount is fixed by
correcting the line and reversing plus re-posting by hand, accepting that the
new row stands on its own.

**A child who moves class mid-term is billed once and waived once.** Decided
2026-09-24 (B2), replacing the old rule that both bills charged them. A child
with a standing charge from another class's bill this term is skipped by this
bill and named in the summary (`AppliedSummary.billed_elsewhere`). The waiver
was already once per term: the concession key is `(child, term, concession)`,
because a waiver is a fact about the term, not about the classroom. A bursar
who wants the new class's bill to be theirs undoes the old bill's charges
first; with every one reversed, the new bill charges them. See "B2" for
exactly what counts.

**The schedule keys on `ClassGroup`, and `ClassPlacement` rewrites on a
mid-term move.** A child charged as JSS 1A in week one who moves to JSS 3 in
week four keeps the JSS 1A charge unless a person acts. That is correct — a
posted charge is a fact — and it is stated here because the obvious repair is to
recompute charges from live placement, which is the same class of bug as keying
a released report card on placement (`operating-rules.md` rule 1).

**No run table.** Who applied a bill and when is already on every entry it
produced: `recorded_by_id`, `effective_on`, `recorded_at`, `source_line`. A run
row would be a second answer to a question the entries already answer.

## B1: the bursar's routes and page

Built 2026-09-24. `fees/api.py` under `/api/fees/`, and the page at `/fees/`.
Billing — fee schedules and concessions on a screen — is B2.

### What was decided, and where each decision holds

| | decision | where it holds |
| --- | --- | --- |
| 1(a) | The **bursar and the administrator** write. The **principal and the vice principal (academic)** read. Everybody else gets a flat 404 | `fees/authority.py`; every route asks before it reads anything |
| 2(a) | **Discounts and reversals** are the same people's, and each **says why** | `services.discount_once()` and `services.undo()`, both refusing with `NoReason` |
| 3(a) | A payment's **method** is cash, bank transfer, POS or cheque, and a **bank transfer names its teller or transfer reference** | two check constraints (`a_method_on_money_that_moved_and_nowhere_else`, `a_bank_transfer_names_its_reference`), and `NoMethod` so the route can answer in a sentence |
| 4 | A **form posts once** | the unique index `a_form_posts_once` on `form_key`, and `services._once()` |
| 5 | A **receipt is numbered** by the school's code and the ledger entry | `authority.receipt_number()`: `ST-MARYS-000041` |

### The routes

| route | who | what |
| --- | --- | --- |
| `GET classes/?term_id=` | readers | the terms, and the classes with children placed in one |
| `GET classes/<id>/?term_id=` | readers | every child in the class, with their whole account's balance |
| `GET students/<id>/` | readers | one child's account: every entry, newest first |
| `GET entries/<id>/receipt/` | readers | a payment's receipt; any other kind of entry is the flat 404 |
| `POST students/<id>/payments/` | writers | a payment, with its form key |
| `POST students/<id>/discounts/` | writers | a discount given by hand, with its reason and form key |
| `POST entries/<id>/reversal/` | writers | undo any entry, with the reason |

A write answers **201** when it posted and **200 when the same form had already
posted**, with the entry that form posted. That way a retried request tells the
page the truth: the payment is in the books once. A reader who may not write
gets a **403** with a sentence. They read the books, so the account's existence
is not news to them. Anybody else gets the flat 404 before any lookup, the
answer the broadsheet and the absence list give. Without it, the routes would
be a directory of the school's children and their debts.

**The child is looked up with `school=` in the query.** `student_membership_id`
is a bare id into the shared table, so a lookup without the school would find
another school's child and print her name on this school's host. The services
refuse to *post* against her anyway, but by then the read would have told the
caller who she is.

### Money in, money out

**What a bursar types is naira, as text.** `fees.money.kobo_from_naira()` is
the only thing that turns it into kobo, and it refuses rather than guesses:
`12.345` is refused, not rounded, and a comma counts only as a thousands
separator. **What leaves is integer kobo**, and `static/fees/money.js` formats
it by cutting the digit string, so a float touches it nowhere.

**A balance is said in words**: "Owes ₦…", "In credit ₦…", "Nothing owed". A
minus sign is the character a phone screen most easily loses, and a family in
credit being chased for money is the mistake this page must not make.

### The form key

Each payment form and each discount form the page draws carries a fresh UUID.
The unique index is the whole mechanism. Two racing submissions both pass any
read, and only the index sees them both. The same key with the same details is
a double click, and the answer is the first click's entry. The same key with
different details is refused (409), because answering with the first entry
would tell the bursar something was recorded that was not. When the answer is
lost, the page keeps the key and what was typed, so sending again is safe.

### The receipt

The student's name and admission number come from the entry's frozen snapshot,
not the live row. A receipt reprinted next year says what it said when it was
issued. An undone payment's receipt says so across its face. **"Received by"
is the exception**: it is read live from the recorder's login. Issue #143.

## B2: bills and concessions

Built 2026-09-24. `fees/billing.py` is the service layer, and the routes and the
page are B1's, extended: "Bills for this term" on the class list, and a
Concessions section on a child's account.

### What was decided, and where each decision holds

| decision | where it holds |
| --- | --- |
| **The same people as B1**: the bursar and the administrator set bills and concessions; the principal and the vice principal (academic) read them; everybody else gets the flat 404 | `fees/authority.py`, asked by every route before it reads anything; the 403 sentence is "Bills and concessions are set by the bursar or an administrator." |
| **Applying a bill must not charge a child already charged for that term** | the same bill: the per-line skip and `a_schedule_line_charges_a_child_once`, as before. Another class's bill: the billed-elsewhere skip in `apply_to_class()`, serialised by a lock on the term's row |
| **Issue #75: revoking a concession needs a required reason and an append-only row saying who, when and why; the concession row is never edited or deleted** | `FeeConcessionRevocation`; `billing.revoke_concession()` refusing with `NoReason`; `a_revocation_says_why` at the database; `fees/migrations/0006`'s triggers on both tables |

### "Already charged for that term"

A child is already charged for the term when they have a CHARGE entry in the
term that names a schedule line of **another** bill, and nobody has reversed
it. Each part is there for a reason, and each has a test:

- **This bill's own charges are not "elsewhere"**, or adding a line after the
  first run would charge nobody the new line.
- **A charge posted by hand names no line**, and is not a bill: a broken
  window does not stop the term's fees being charged.
- **Reversed charges do not count**, so undoing a bill is how a bursar moves
  a child from one bill to another. **One standing charge is enough**: the
  levy undone and the tuition left standing leaves the child on the old bill.
- **Last term's bill is last term's.**

The check reads other bills' charges, which the schedule lock does not cover:
two bursars billing JSS 1A and JSS 3A at once, with a child moved between the
two roster reads, would each read the child as unbilled. So an application
also takes the term's row, `FOR NO KEY UPDATE`: every bill in the term waits
for the one before it, and nothing else does, because no foreign key's
`FOR KEY SHARE` conflicts with it. `TwoBillsOneTermTests` stages that
interleaving and fails without the lock.

### Issue #75: a concession is granted once and revoked once

A concession used to be switched off with `is_active`, which recorded when (as
`updated_at`) and never who or why. A revoked concession produces nothing from
then on, and by `operating-rules.md` rule 8 that absence needs a log. So:

- **Revoking writes a `FeeConcessionRevocation`**: the reason (required, and
  held by `a_revocation_says_why` wherever the write comes from), the person
  (as an id **and** their name frozen at that moment, rule 2, so it cannot
  repeat #143), and when. One per concession, as a one-to-one.
- **The concession row is never edited or deleted**, and neither is a
  revocation. `save()` and `delete()` refuse with `ConcessionIsFixed`; a trigger
  on each table refuses UPDATE and DELETE from anywhere else.
- **#75's other two questions have the same answer.** A *reduction* is a
  revocation and a new, smaller grant. *Re-granting* is a new concession. Both
  leave the old one legible.
- **What revoking does not do** is touch discounts already posted. This term's
  discount stands, because the ledger is append-only; the next application of
  a bill gives no more.
- **A grant form posts once**, `a_concession_form_grants_once`, for the same
  reason a payment form does: a double click would otherwise discount the
  child twice every term.

Migration 0005 turned each concession already switched off into a revocation
with no person and a reason that says who and why were not kept. No school had
any at the time, so the backfill has run on nothing; there is no test that
drives it.

### The bill

A bill is still a template. Adding a line, renaming one or correcting its
amount changes what the next application posts, and the page says so beside
every line that has charged anybody: "The 2 already charged keep what they
were charged." A line that has charged anybody cannot be removed. The same
line twice is a double click (200, the existing line); the same name at
another amount is refused (409).

### The routes

| route | who | what |
| --- | --- | --- |
| `GET bills/?term_id=` | readers | every class in use, with its bill's lines and total, billed or not |
| `GET classes/<id>/bill/?term_id=` | readers | one bill, each line with how many it has charged |
| `POST classes/<id>/bill/lines/` | writers | add a line, starting the bill; 201, or 200 for the same line again |
| `PUT bill-lines/<id>/`, `DELETE bill-lines/<id>/` | writers | change a line; remove one nobody was charged by (409 otherwise) |
| `POST classes/<id>/bill/charges/` | writers | charge the class; always 200 with what it did, including who was billed elsewhere |
| `GET students/<id>/concessions/` | readers | every concession, revoked ones with who, when and why |
| `POST students/<id>/concessions/` | writers | grant one, with its reason and form key |
| `POST concessions/<id>/revocation/` | writers | revoke one, with the reason; 422 without, 409 if already revoked |

Every bill write answers with the bill as it now stands, and the page draws
that answer rather than patching what it had.

## Not built

- **No refund route.** `services.refund()` exists and nothing on the page calls
  it.
- **"Received by" on a receipt is not frozen.** [Issue #143](https://github.com/adedejimakinde/luffy-school-saas/issues/143).
- **No takings report.** What a school actually collected in a term has no home
  yet; [issue #74](https://github.com/adedejimakinde/luffy-school-saas/issues/74)
  holds the requirements this shape was built not to foreclose.
- **No allocation.** A payment reduces the balance; it is not matched against
  particular charges. Schools that need "which term is this ₦50,000 against?"
  need payment allocation, which is a real feature and a bigger one.
- **No double entry.** There is one ledger per student, not a chart of accounts.
  Correct for a school's fee book, and it does not generalise to the school's own
  accounting.
