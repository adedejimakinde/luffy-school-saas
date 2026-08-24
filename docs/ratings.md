# The conduct section: affective and psychomotor ratings

The half of a Nigerian report card that is not marks. Two blocks of lines —
"Affective Domain" and "Psychomotor Domain" on most cards, punctuality and
neatness in one, handwriting and games in the other — each rated 1 to 5 by the
person who taught the child all term.

`results/ratings.py` holds all of it: what a school prints, who may say so, who
may rate, and what a released card keeps saying afterwards. `results/models.py`
holds the five tables. There is deliberately no HTTP here — see
[Nothing to call yet](#nothing-to-call-yet).

## Off by default, and off means *absent*

Both sections start turned off, for every school, and that default is
load-bearing rather than cautious. Plenty of Nigerian schools print both, plenty
print one, and plenty print neither. A school that has never heard of this
feature must see **no trace of it**: no heading, no rule across the page, and no
row of empty boxes for a parent to wonder about.

So `card_sections()` returns *no section* for a group that is off, rather than a
section with no lines:

```python
    if lines:
        sections.append(CardSection(group=..., heading=..., lines=lines))
```

An empty section is a heading with nothing under it, because the caller loops
over whatever it is handed. The distinction only shows up in the rendered card,
which is exactly where it matters. A group that is *on* but has no visible
traits produces nothing either, for the same reason.

`ReportCardSettings` is one row per schema, pinned to `id=1` by a check
constraint so that "the settings" cannot become a table somebody appends a
second opinion to. `settings()` falls back to an **unsaved** default where the
row is missing rather than creating it: reading a report card should not write
to the database, and an unsaved default has both sections off, which is the
answer a school with no settings row should get anyway.

## The trait list is the school's, so it is rows

`Trait` is a table, not a `TextChoices`. The requirement is that adding, hiding
or reordering a line must not need a migration — a school that wants "Respect
for school property" adds one, a school that never grades handwriting hides one,
and both are Tuesday-afternoon administration.

Migration `0006` seeds the list most schools start from, per schema, so a school
that says yes has something to edit rather than a blank page. **A seed is a
starting point and not a promise**: nothing in the code names a seeded row.
There is no `Trait.PUNCTUALITY`, no lookup by name, and no test that asserts a
particular seeded trait exists — the moment a code path depends on one, hiding
it breaks something, and hiding it is the very thing the feature promises.

### Hidden, never deleted

`Trait.is_hidden` takes a line off next term's sheet. Deleting is not on offer:
`TraitRating.trait` and `ReleasedTraitRating.trait` are both `PROTECT`, because a
trait that has been rated is named by those ratings and by every released card
that printed it. Hiding leaves all of that alone.

### Position is explicit, and duplicates are legal

Order on a report card is the school's own and carries meaning;
"Attentiveness in class" does not lead the section merely because A sorts first.
So `position` is a number the school sets, and `Meta.ordering` is
`["group", "position", "name", "id"]` — `id` last so the order is *total* and
two traits sharing a position still print in the same order every time.

`(group, position)` is deliberately **not** unique. It reads tidier and it makes
the ordinary edit — swap two traits round — impossible without a temporary value
or a deferred constraint, which is how reordering code ends up with a hole in
the middle of it.

That has one consequence worth stating, because getting it wrong is invisible
until a school looks at a card. **`reorder()` renumbers the whole group**, the
named traits first and then everything else in the order it was already
printing. Renumbering only the traits the caller named is the version that looks
right and is not:

```
seeded:        Punctuality 0   Attendance 1   Neatness 2   Politeness 3   Honesty 4
reorder to:    Honesty, Neatness, Punctuality

renumber only those three:
               Honesty 0   Neatness 1   Punctuality 2   Attendance 1   Politeness 3
prints as:     Honesty, Attendance, Neatness, Punctuality, Politeness
                        ^^^^^^^^^^ tie at 1, broken by name
```

Attendance was never moved and still lands *between* the two traits the school
had just put next to each other. A screen that sends only the page it is showing
still gets what it meant, because the unnamed traits keep their relative order
and follow.

Ids belonging to another group are ignored rather than moved into this one:
reordering is not a way to change what section a trait is in.

## The numbers are fixed; the words are not

`RatingScalePoint` is `value → label`, five rows, seeded 5 = Excellent down to
1 = Poor. A school may rename any of them — some say "Very Good" where others
say "Good", a few use "Exemplary" — and the card's key prints the school's word.

The **value** is not configurable, and that difference is the point.
`TraitRating.score` stores the integer, so moving to a 1–10 scale would
reinterpret every rating already recorded, including the ones on cards that have
gone home. A school wanting ten points is asking for a different scale, not a
relabelled one, and that is a change to make deliberately.

The range is checked twice — `a_rating_is_within_the_scale` on the rating, and
`a_scale_point_is_within_the_scale` on the scale — and the two are not the same
check. A school can delete or relabel a scale point; a rating whose label had
gone missing would still have to be a number between one and five.

## Where the class group comes from: nowhere

The spec says a rating is per (student, class group, term). `TraitRating` is
keyed on **(term, student, trait)** and stores no class group at all.

It does not need to. A child sits in exactly one group per term, by
`academics.ClassPlacement`'s `one_class_placement_per_student_per_term`. Storing
the group as well would be a second answer to a question the placement already
answers, and the two disagree the moment a child moves arms in January: the
rating stays pinned to JSS 1A while the child, the sheet and the card all move
to JSS 1B, so the new class teacher can neither see the old rating nor replace
it, and the card prints nothing.

So the group is derived, on the same reasoning `positions.roster_ids()` derives
a roster rather than caching one. A child with **no** placement cannot be rated
at all — `NotPlacedThisTerm` — because with no group there is no class teacher
with standing to make the judgement and no sheet to submit it on.

## No row means not rated

Exactly as `gradebook.Score` means it. There is no null score on `TraitRating`
and clearing a rating deletes the row, because a nullable score would make a
blank on the card ambiguous between "the teacher has not got to this yet" and
"the teacher looked and left it empty" — the conflation that has a teacher
certain they entered something the card prints blank.

`unrated()` reports what is still to do, for a screen that wants to say "eleven
left before you submit". It is a report and **not a rule**: a card with a blank
conduct line is a school's business, and blocking release on a missing rating
would be this module inventing a policy nobody asked for.

## Only the class teacher rates

Narrower than `results.services.SUBMITTING_ROLES`, which admits an
administrator, and the difference is deliberate. Submitting a paper sheet is
office work in most schools — transcription, where the judgement was made on
paper by somebody else. **A conduct rating has no paper behind it.** It is a
judgement about a child made by the person who taught them all term, and there
is no clerical version of it.

So there is no administrator exemption and no principal one either. A group with
nobody assigned refuses everybody, and says so: that is a school configuration
problem, not a pretence that the sheet is in the wrong state.

Configuring is the opposite act and has the opposite set. `CONFIGURING_ROLES` is
the principal and the administrator — the same set `academics.services` uses for
assigning class teachers — because changing the trait list changes every card
the school issues from then on. A teacher who could add a trait could also hide
the one they had been rated poorly against.

|                        | class teacher | administrator | principal |
| ---------------------- | ------------- | ------------- | --------- |
| rate a child           | ✔ own group   | ✘             | ✘         |
| turn a section on      | ✘             | ✔             | ✔         |
| add / hide / reorder   | ✘             | ✔             | ✔         |
| rename a scale point   | ✘             | ✔             | ✔         |

### Decided on the row, not on the argument

`_require_a_ratable_trait()` re-reads the trait by `pk` from the schema on the
connection before checking anything. The checks read `is_hidden` and `group`;
the write uses `pk` alone. Trust the instance for the first and the row for the
second, and they are two different traits — the shape `a2a9656` corrected in
`_require_class_teacher_scope()` one module along.

Nothing exotic is required to hit it. A `Trait` read on another school's
connection is enough: every schema is seeded by the same migration in the same
order, so the ids coincide, and a row that says "visible" over there names a
hidden trait over here.

## Ratings follow the chain

They are part of what gets submitted, checked and approved, so they stop moving
when the sheet does. `draft` is the test — not "has never been submitted",
because a send-back returns the sheet to `draft` precisely so that a teacher
told to fix a rating can fix it.

```
draft        rate, clear, correct freely
submitted    locked — the vice principal is looking at it
checked      locked
approved     locked
released     locked for good; correcting one is a revision (task 8)
```

If a rating could change after submission, then what the vice principal checked
and what the principal approved are not the same document, and the chain's
signatures are attached to a thing that moved underneath them.

### The check holds the sheet's row lock

A state read followed by a write that depends on it is two statements, and
between two statements is where this codebase keeps finding its bugs —
`schools.Invitation.accept()` decided on rows it had not locked, and
`_require_class_teacher_scope()` authorised against an instance while `_move()`
wrote to a row.

So `_require_the_sheet_is_open()` re-reads the sheet `FOR UPDATE`, and the
rating is written in the same transaction. A teacher pressing save while the
vice principal presses submit now waits, and is refused by what it finds; before
the lock it read `draft`, wrote, and committed a rating into a document that had
been submitted a millisecond later.

`.get()`, not `.filter().first()`, and that is not a style choice.
`ResultSheet.Meta.ordering` is two relations, so a `select_for_update()` that
inherits it locks a row in `academics_term` and `academics_classgroup` too —
neither of which a rating writes. `QuerySet.get()` clears ordering itself, the
property `results.services._locked()` documents and
`test_ratings_concurrency.TheRatingLockTests` pins on the captured SQL.

### And the database holds the terminal case

Migration `0007` adds a trigger refusing INSERT, UPDATE **and** DELETE on
`results_traitrating` for a term whose sheet is released. Narrow on purpose:
`released` is terminal and has no legitimate exception, while `submitted` and
`checked` are a rule about a review in progress that an import fixing a mistyped
batch may legitimately need to work around. A guard broader than its rule is one
somebody eventually turns off wholesale.

Because `TraitRating` stores no class group, the trigger joins through
`academics_classplacement` to find the sheet. The alternative was a denormalised
`class_group_id` on every rating, kept correct by nothing.

It fires on INSERT as well, unlike the append-only trigger below: a *new* rating
for a released term is as wrong as an edited one, and likelier — a teacher
rating a child in a term that closed while their screen was open.

## The freeze: a released card does not change

The part to get right. At the moment of release, `freeze_for_release()` copies
the conduct section of **every child in the class** into
`ReleasedTraitRating` — the trait names, the order they are in, the scores, and
the school's word for each score. A released card is rendered from that table
and nothing else.

Every one of those four is a join away, and every one of those joins goes
through a row the school may edit next term:

| the school does this                      | the released card would otherwise have |
| ----------------------------------------- | -------------------------------------- |
| renames "Neatness" to "Tidiness"          | a line it never printed                |
| hides "Honesty"                           | one line fewer                         |
| reorders the section                      | the same lines in a different order    |
| relabels 4 from "Very Good" to "Good"     | a worse judgement than the teacher gave |
| turns the whole section off               | no section at all                      |

None of those are misuse. They are a school tidying its own configuration, and
each one silently reaches backwards into a term that is closed.

`trait` stays a real foreign key even though the name is copied: it is in the
same schema, `PROTECT` is right, and it answers "which trait is this line,
today" for a school comparing two terms. The copy is what the card renders; the
key is provenance.

### One row per (child, trait), including the traits nobody rated

The frozen thing is the **section**, not merely the marks in it. "Which traits
existed, and in what order" is precisely what a later edit would rewrite, so it
has to be recorded even where the answer is a blank line — a row with a null
score.

That is the one place a null score is right, and it is right for the opposite
reason to `TraitRating`'s: there, no row means unrated; here, the row *is* the
record that the line existed.

It repeats the trait list once per child — about five hundred short rows for a
class of forty-five with eleven traits. The alternative, a per-sheet list joined
to per-child scores, saves those rows and buys a second table that can disagree
with the first. One table means a released card is exactly "these rows, in this
order", which is a property that can be looked at.

`a_frozen_rating_carries_its_label` refuses a row with a score and no label, or
a label and no score: a bare "4" in a column of words is a card nobody can read,
and a word attached to nothing is worse.

### Written inside the release transaction

`results.services.release()` passes `freeze_for_release` to `_move()` as a
callback, which calls it after the state is written and inside the same
transaction. A sheet that says `released` therefore always has the card that was
released sitting behind it; there is no window in which one exists without the
other.

It is a callback rather than a branch on `to_state` so that `_move()` stays a
description of the chain, and so that task 3 adds the scores, the averages and
the attendance by extending one release-time step rather than by editing the
mover.

### Append-only, twice

`ReleasedTraitRating.save()` and `.delete()` refuse — the error a developer
sees — and migration `0007`'s trigger refuses, which is the error a `psql`
session, a data import or a bulk `.update()` runs into. The bulk update is the
one that matters, because it never goes near the model:

```python
ReleasedTraitRating.objects.filter(sheet=sheet).update(score=5)
```

would rewrite every child's conduct section on a card already issued, with
nothing recording that it had happened. The pattern is `results/0002`'s and
`fees/0002`'s, copied rather than factored out for the reason `0002` gives.

`bulk_create()` is what writes the rows, and it does not call `save()` — which
is fine, and deliberate: the model's `save()` refuses *edits*, and inserting is
the one thing a frozen row is allowed to do.

### A school with the section off freezes nothing

No enabled group means no rows, which is what makes such a school's released
card render with no section rather than an empty one — for ever, however the
school later configures itself. Turning the section on in April does not
retrofit a heading onto a card that went home in March.

## Refusals say what actually happened

`rate()` used to wrap its write in `except IntegrityError` and read every
refusal as "the other tab inserted first", retrying as an `UPDATE`. It was
wrong twice over.

Django's `update_or_create()` already takes the row lock and `get_or_create()`
re-reads after a unique violation, so the branch never saw the race it was
written for. What it *did* see was every other way this table refuses a row: the
`CHECK` behind a bare id, the foreign key onto a trait deleted meanwhile, and
migration `0007`'s trigger — which raises `restrict_violation` and therefore
also arrives as `IntegrityError`. Each was retried as an `UPDATE` matching
nothing and then re-read, so the caller got

    TraitRating matching query does not exist.

where the database had just said, in a sentence written for a teacher, that the
card had gone home. The catch is gone; `gradebook.services` narrows its
equivalent instead of dropping it, because there the collision genuinely reaches
the caller.

The write still takes its own `atomic()` block. An `IntegrityError` marks the
enclosing transaction unusable, and a caller rating a whole class inside one
transaction has to be able to go on to the next child after one refused row.

### Two columns that always agreed would be one column

`rated_by_id` is written at the insert and never again; `updated_by_id` moves on
every correction. That needs `create_defaults` alongside `defaults` — a single
dict is used for both paths, so every correction would overwrite the teacher who
made the judgement with whoever last touched the row. `gradebook.services`
already keeps the pair apart the same way.

Both are bare ids, nullable, on `docs/tenancy.md`'s policy and
`Score.recorded_by_id`'s reasoning: a rating can arrive from an import of last
year's cards with nobody behind it, and naming a fictional rater is worse than
naming none.

They hold **`User` ids** — `rate_as()` stamps the actor, and an actor is a user.
`student_membership_id`, in the next column of the same table, is a `Membership`
id. Three `PositiveBigIntegerField`s on one row, two id spaces, and both are
small dense integers: a "who rated this child?" panel that resolves the wrong
one does not fail, it names somebody else.

## Nothing to call yet

No endpoint, no serializer, no template. `results/api.py` still publishes only
the broadsheet, and `card_sections()` is what the report card will render from
when task 3 builds it — the section list is already in the right shape for it,
frozen or live, and the caller does not have to know which.

That is also why `academics.services` has no `api.py` and this module has none:
the rules have to hold for an import too, and a rule that lives in a view only
holds for the view.

## Every refusal is this module's own

The constraints are what actually hold — that is why they are there — but a
service that lets one fire hands the caller a raw `IntegrityError`: outside
`RatingsError`, so every `except ResultsError` misses it, and fatal to an
enclosing transaction with no savepoint under it. So the service refuses what
the table would refuse, first and in a sentence:

| the caller does this | what used to happen | what happens now |
| --- | --- | --- |
| adds a trait named `"   "` | `a_trait_has_a_name` fires as a 500 | "A trait needs a name" |
| re-adds a trait it had hidden | `uniq_trait_name_per_group` fires | "…already a trait of the affective section, hidden rather than deleted" |
| renames a scale point that is not on the scale | `update_or_create` *inserts*, then the CHECK fires | "7 is not on the scale" |
| passes `"conduct"` as a group | `ValueError` from the enum cast | "…is not a section of the report card" |

Re-adding a hidden trait is refused rather than quietly unhidden. A hidden trait
carries every rating ever made against it, so bringing it back is a decision
about that history, not a side effect of typing a name into an "add" box.

## Open

- **`gradebook.Score` has no equivalent of the chain lock**, so a mark can still
  be changed after release while a rating cannot. That gap is
  [issue #27](https://github.com/adedejimakinde/luffy-school-saas/issues/27),
  filed rather than fixed here because it is a change to the gradebook's write
  path with its own design question about which way the dependency runs.
- **A correction keeps no record of what it corrected.** `rated_by_id` names who
  first judged and `updated_by_id` who last changed it, so a third person's touch
  is unrecoverable and every previous score is gone. Released cards are safe —
  the frozen copy is append-only — but the review window, which is where
  corrections happen, is not covered. `gradebook.Score` has the same hole, and
  the two tables disagree about concurrent writes: `Score` carries a `version`
  and refuses a stale write, `TraitRating` last-write-wins on the single-writer
  argument. Both go together in
  [issue #28](https://github.com/adedejimakinde/luffy-school-saas/issues/28),
  to be decided with task 8's revisions rather than twice in two shapes.
- **A rating begun before the sheet exists takes no lock**, because there is no
  row to lock, so it can still land under a submission that opens and submits
  the sheet in the same window. Closing it needs a lock on something other than
  the row —
  [issue #30](https://github.com/adedejimakinde/luffy-school-saas/issues/30).
- **A child placed into a released term gets no section at all**: the frozen
  table has no rows for them and the live path is never reached, so their card
  prints nothing where every classmate's carries a section.
  [Issue #31](https://github.com/adedejimakinde/luffy-school-saas/issues/31),
  which task 3 will meet in a larger form.
- **Every `ForeignKey` carries an automatic index** that a unique constraint
  already leads with, here and across the repository.
  [Issue #32](https://github.com/adedejimakinde/luffy-school-saas/issues/32);
  `NoIndexIsBuiltTwiceTests` holds the declared-index rule and excludes those by
  an explicit list, so adding a relation fails until somebody looks.
- A third trait group, if one is ever wanted, is a `TraitGroup` member plus a
  column on `ReportCardSettings`. `FIELD_FOR` is a written-down map rather than
  `getattr(self, f"{group}_enabled")` so that the pair cannot drift into an
  `AttributeError` on somebody's report card; `enabled()` refuses a group it does
  not know.
