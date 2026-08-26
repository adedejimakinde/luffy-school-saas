# The two remarks: the class teacher's and the principal's

A Nigerian report card ends with two signed sentences. The class teacher writes
about the term they taught the child; the principal writes about the card as a
whole. They print one under the other, each labelled, and a parent reads them as
two different judgements.

That is why they are two rows and not one paragraph, and it is the whole design.
`results/comments.py` holds the rules — what a school offers, who may sign what,
what a card keeps — and `results/models.py` holds the three tables. There is
deliberately no HTTP here; see [Nothing to call yet](#nothing-to-call-yet).

## A phrase is a starting point for typing, not a value

The requirement is a bank of canned remarks a school can offer, clickable to
insert. So: the screen offers the school's phrases, the teacher clicks one, it
lands in the box, and **they edit it**. What gets stored is the sentence the
teacher left.

`ReportCardComment` therefore keeps **no foreign key back to `CommentPhrase`**.
The denormalisation happens at write time rather than at release, and it is what
makes the rest of this document short:

- editing a phrase cannot reach a remark already written, released or not;
- deleting a phrase cannot either;
- there is no join for a later edit to travel along, so there is nothing to
  defend.

`TheFreezeTests` pins this as a *structural* test rather than a behavioural one.
It has a control — the same edits, against a **live, unreleased** comment, which
must also not move. If the control ever fails, the freeze is hiding a bug rather
than preventing one, and the tidy-looking change that would cause it is exactly
"replace the copied text with a foreign key".

### Deleted, not hidden

`Trait` is hidden rather than deleted, because ratings and released cards name
the trait row and removing it would take evidence with it. **Nothing names a
phrase.** So a school that no longer wants to offer a sentence simply stops
offering it, and every comment that sentence ever seeded is untouched.

### Two lists, never one pool filtered

`author` is mandatory on `CommentPhrase`, every read goes through
`for_author()`, and there is deliberately **no** accessor that returns both
lists. A teacher choosing a remark must never be shown "Has performed creditably
this term and should maintain the standard" written for a principal to sign, and
the way to guarantee that is for the question "which phrases exist" to be
unanswerable without saying whose.

The uniqueness rule is **per author, not per school**: the same sentence can
reasonably be offered to both signatories, and what is actually wrong is the
same line twice in *one* list, which gives a teacher two identical things to
click.

## Empty means absent

There is no blank remark. `a_comment_says_something` refuses whitespace,
`clear()` deletes the row rather than blanking the body, and `card_comments()`
returns **no line** for a remark nobody wrote.

Not a line with an empty body. The caller loops over what it is handed, so an
empty line is a heading and a rule across the page with nothing under it — a
labelled empty box, which is a question a parent rings the school about.
`ratings.card_sections()` refuses the same thing for the same reason.

So "the principal has not written one" is spelled as the absence of a row, all
the way through: absent in the live table, absent from the freeze, absent on the
card.

## No remark ever blocks the chain

A sheet submits, checks, approves and releases with both remarks missing.
Schools do release cards with a blank principal's remark, and a module that
refused would strand a term's results over a sentence.

`missing()` exists for the screen that wants to say "eleven still to write". It
reports; the school decides. It is deliberately not a rule.

## Who signs what

The point of the task, and the two halves are argued differently.

**The class teacher's remark is the class teacher's.** Not the office's.
`results.services.SUBMITTING_ROLES` admits an administrator, because submitting
a paper sheet is transcription — but a remark about a child is the judgement of
the person who taught them all term, and there is no paper behind it to
transcribe. `ratings._require_the_class_teacher()` makes the same argument about
a conduct rating.

**The principal's remark is the principal's**, and it is deliberately *not*
scoped to a class: a principal signs every card in the school. A vice principal
may not write it either, though they check the sheet — checking is a step in the
chain, and signing the card is not.

**Neither may write the other's.** A principal who could write the teacher's
remark could put words under a teacher's name on a card that goes home.

| | teacher's remark | principal's remark |
| --- | --- | --- |
| class teacher of that group | ✅ | ❌ |
| another class's teacher | ❌ | ❌ |
| vice principal | ❌ | ❌ |
| administrator | ❌ | ❌ |
| principal | ❌ | ✅ (any class) |
| the other school's anybody | ❌ | ❌ |

A group with no class teacher assigned says so, rather than falling through to
"you are not the class teacher": nobody may write its remarks yet, and what the
school has to do about it is assign one.

## Where the class group comes from: nowhere

`ReportCardComment` is keyed on **(term, student, author)** and stores no class
group, for `TraitRating`'s reason. `academics.ClassPlacement` already holds
exactly one answer per child per term, and a second copy strands the remark on
the arm the child left in January, where the new class teacher can neither see
it nor replace it.

The consequence is that "may you write this" is a question about the group the
child sits in, so the placement is read *before* authority is asked — and then
**handed down to the write**. `write_as()` resolves the placement, authorises
against it, and passes that same row into `write()`. Reading it twice is the
shape `_require_class_teacher_scope()` was corrected on and `ratings.rate()`
after it: an `academics.move_student()` committing between the two reads would
authorise against JSS 1A's class teacher and check JSS 1B's sheet — including
its state, so a remark could land in a term the guard would have refused.

`placement` stays optional rather than required, because the primitive is
reachable without an actor: an import has nobody to authorise and no earlier
read to reuse, so it reads its own.

## Remarks follow the chain

They are part of what gets submitted, checked and approved, so they stop moving
when the sheet does.

```
draft        write, clear, correct freely
submitted    locked — the vice principal is reading it
checked      locked
approved     locked
released     locked for good; correcting one is a revision (task 8)
```

If a remark could change after submission, then what the vice principal checked
and what the principal approved are not the same document. A send-back returns
the sheet to `draft`, so a teacher told to rewrite a remark can rewrite it —
which is why `draft` is the test rather than "has never been submitted".

A sheet nobody has opened yet is open: writing remarks before the chain starts
is the ordinary order of events.

### One lock, shared with the ratings

`_require_the_sheet_is_open()` re-reads the sheet `FOR UPDATE` and the caller
writes in the same transaction, so a teacher saving while the vice principal
submits waits and is refused by what it finds.

The lock and the predicate live in `results.services` —
`locked_sheet_for()` and `is_open_for_writing()` — rather than in the two
modules that call them. `ratings` and `comments` ask the identical question, and
the two must not be able to drift apart about what "open" means. What is *not*
shared is the refusal: the two phrase theirs differently ("its ratings are part
of what is being reviewed", "its remarks are"), and those sentences are read by
a teacher, so they stay where the vocabulary is.

`.get()` rather than `.filter().first()`, because `ResultSheet.Meta.ordering` is
two relations and a `select_for_update()` that inherits it would lock a row in
`academics_term` and `academics_classgroup` too.

The read path has the same trap without the lock, and `sheet_for()` — which
decides whether a card renders from the freeze or the live rows, once per child
— **is shared too**, for the same reason and one more. It must call
`.order_by()` before `.first()`, or it compiles to a three-table join sorted by
the term's session and the class's level to find a row
`one_result_sheet_per_class_term` guarantees is unique.
`TheCardReadTakesNoJoinItDoesNotNeedTests` asserts that on the captured SQL, so
an ordering added later fails there first.

It began as a copy in each module and a review found the two had already started
to drift — same query, same trap, two docstrings maintained separately. Unlike
the refusals above, there was nothing module-specific holding them apart: no
wording a teacher reads, no refusal at all, just one query and one note about
`Meta.ordering`. So it now lives in `results.services` beside `locked_sheet_for()`
and both modules import it. `comments.sheet_for` and `ratings.sheet_for` still
resolve, because an imported name is an attribute of the importing module.

### And the database holds the terminal case

Migration `0009` adds a trigger refusing INSERT, UPDATE **and** DELETE on
`results_reportcardcomment` for a term whose sheet is released.

Worth being clear about what it is *not* for. The frozen rows are what a
released card renders from, so editing a live comment after release cannot
change what a parent is holding — the freeze handles that, with or without the
trigger. What this stops is the two **disagreeing**: a school's own screens
showing one remark while the card in the parent's hand carries another, with
nothing to say which is real. Somebody would then "fix" the card to match the
screen.

Narrow on purpose — `released` only, not "anything past draft". `released` is
terminal and has no legitimate exception, while `submitted` and `checked` are a
rule about a review in progress that an import fixing a mistyped batch may
legitimately need to work around. It fires on INSERT too: a *new* remark for a
released term is as wrong as an edited one, and likelier — a principal writing
on a term that closed while their screen was open.

Because `ReportCardComment` stores no class group, the trigger joins through
`academics_classplacement` to find the sheet, and decides existence with
`IF FOUND` rather than by testing the selected column for NULL. The NULL test is
only correct while `academics_classgroup.name` happens to be `NOT NULL` — a
property this file does not own — and when it stops being true the refusal
silently becomes a permit. Migration `0007` shipped with that and was corrected
on it.

## The freeze: a released card does not change

`comments.freeze_for_release()` is called by `results.services.release()`,
inside the transaction that writes the release row, alongside
`ratings.freeze_for_release()` and in the order the two print. A sheet that says
`released` therefore always has the card that was released sitting behind it,
rather than part of one.

### Keyed on the child and the term, not on where the child sits

**A guard on a released artefact keys off the artefact, not off the child's
current placement.** Placement answers "whose class is this child in today",
which is a live fact that changes; release is an event that happened, and what
records it is the frozen row.

`0009` shipped without that distinction. It asked "has this term been released
for this child's *class*?" and reached the sheet by joining through
`academics_classplacement`, so the answer moved when the child did. Release JSS
1A with a remark frozen, move the child to JSS 3B — legitimate, mid-term, and
what `academics.move_student()` is for — and the guard looks at JSS 3B's
untouched draft and permits a rewrite of a remark already in a parent's hand.
The frozen card then says one thing and the school's screen another, which is
exactly what `0009`'s own docstring says it exists to prevent. It prevented it
for a child who stayed put.

Migration `0010` asks the frozen rows directly instead: a `ReleasedComment` for
this `(term, student)` means released, wherever the child is now.
`_require_this_card_has_not_gone_home()` is the service half of the same
question.

**Keyed on the child and the term, and not on the author** — which the first
draft of `0010` got wrong in the same shape one level down. Keying on
`(term, student, author)` meant a card released carrying only the class
teacher's remark froze no principal's row, so the principal's write found
nothing and, after a move, found the new class's draft below. It landed a remark
on a card already in a parent's hand, while the child who stayed put was
refused. Both were measured before either was changed.

Both checks stay, because they answer different things — but not the difference
the first draft claimed. The frozen rows now cover every signatory of a card
that went home; what they cannot cover is a card released carrying no remark of
*either* kind, which freezes nothing at all for that child. The sheet-state
check is what refuses a write onto that released sheet.

The case neither sees is that same empty card, for a child who is then moved.
Closing it needs a per-child record that a card was released, independent of
what was on it — a requirement on task 3, tracked in
[issue #34](https://github.com/adedejimakinde/luffy-school-saas/issues/34).

> The same join was in `results/0007` for `TraitRating`, and
> `ratings._require_the_sheet_is_open()` asked through `placement.class_group`
> too. Fixed in
> [issue #33](https://github.com/adedejimakinde/luffy-school-saas/issues/33) by
> migration `0011`, on the rule above.
>
> That issue expected the frozen-row check to suffice *alone* there, since
> ratings freeze a row even for an unrated trait, so the per-child gap this
> module has does not exist. That much held. It still keeps two checks, for a
> per-*school* gap instead: `ratings.freeze_for_release()` writes nothing when
> no group is enabled or no trait is visible, and a school that turns the
> section on after a term was released makes rating reachable again.
>
> [Issue #27](https://github.com/adedejimakinde/luffy-school-saas/issues/27)'s
> write guard on live marks should be built on the same rule, rather than a
> third copy of the placement join.

### Only the remarks that exist

**A child with no remark gets no row**, which is the one difference from the
frozen ratings.

There, a row is written even for a trait nobody rated, because what is frozen is
the *section* — which lines existed, in what order, under what heading — and
that survives only if it is recorded. Here there is no list to preserve: two
signatories, fixed in code, and an absent remark prints as absent whether the
card is live or frozen. A row carrying an empty body would be the labelled empty
box this design refuses everywhere else.

### Append-only, twice

`ReleasedComment.save()` and `.delete()` refuse, which is the error a developer
sees. Migration `0009`'s trigger refuses, which is the error a `psql` session, a
data import or a bulk `.update()` runs into — and the bulk update is the one
that matters, because it never goes near the model at all:

```python
ReleasedComment.objects.filter(sheet=sheet).update(body="See me.")
```

would rewrite what every parent in the class was told, on cards already issued,
with nothing anywhere recording that it had happened.

`freeze_for_release()` uses `bulk_create`, which does not call `save()` — and
does not need to. The model's `save()` refuses *edits*; inserting is the one
thing a frozen row is allowed to do, and it happens exactly once.

## Every refusal is this module's own

The constraints are what actually hold — that is why they are there — but a
service that lets one fire hands the caller a raw `IntegrityError`: outside
`ResultsError`, so every `except ResultsError` misses it, and fatal to an
enclosing transaction with no savepoint under it. So the service refuses what
the table would refuse, first and in a sentence:

| the caller does this | what would happen | what happens |
| --- | --- | --- |
| offers a phrase the list already has | `uniq_comment_phrase_per_author` fires as a 500 | "…is already on the list of class teacher's remarks this school offers" |
| writes a remark of `"   "` | `a_comment_says_something` fires | "A remark cannot be blank. Clear it instead" |
| writes 251 characters | `DataError` naming a column | "A remark fits 250 characters and this one is 251" |
| passes `"form_master"` as an author | `ValueError` from the enum cast | "…does not sign a report card. Two people do" |

The length is checked in the service *and* by the column, and the two are not
the same check. `varchar(250)` refuses 251 characters with a `DataError` naming
a column; the service refuses it with the number in it, which is what a teacher
who has just written four lines needs to read. The column stays, because a rule
that lives in the service only holds for the service.

### Decided on the row, not on the argument

`edit_phrase()` and `remove_phrase()` re-read the phrase from this school's
schema before touching it. Both compile to `... WHERE id = <pk>` against the
schema on the connection, while every check they make reads the *argument* — so
an instance read on another school's connection, deserialised from a cache or
built by hand decides the checks with whatever its fields say and lands the
write on whichever of our rows holds that id.

It matters most for `author`: the duplicate check looks for a clash in the list
the argument names, so an instance claiming to be the principal's while the row
here is the class teacher's searches the wrong list, passes, and lets the
constraint fire instead. `ratings._the_trait_row()` was added for this on the
same two verbs.

### Ids arrive from a screen as text

`reorder_phrases()` coerces through `services.as_ids()` first. A drag-and-drop
posts JSON, and JSON ids arrive as `["12", "9"]`; matched raw against a dict
keyed by `pk` every one of them misses, the list is renumbered into the order it
was already in, and the caller is told nothing moved — a silent no-op the screen
reports as success. `ratings.reorder()` shipped with exactly that.

And the **whole list is renumbered**, 0 upwards: the named phrases first, in the
order given, then the rest in the order they were already listed. Renumbering
only the named ones leaves an unmoved phrase holding a position a named one has
just been given, and `Meta.ordering` then breaks the tie by text, printing it in
the middle of the group the school had just arranged.

Ids belonging to the other author are ignored rather than moved across:
reordering is not a way to turn a teacher's phrase into a principal's.

But a **bare string is refused, not iterated**, and that is the case worth
naming. `"12,9"` is a sequence — of characters — so coercion succeeds on "1",
"2" and "9", skips the comma, and renumbers the list against three ids the
school never named, reporting success. It is the same silent no-op `as_ids()`
exists to prevent, wearing different clothes, and nothing downstream objects to
it. A non-sequence is refused for the plainer reason: `None` would iterate into
a bare `TypeError`, outside `ResultsError`, and reach a screen as a 500.

### Which error a refusal arrives as

There is one rule, and it follows from where the check lives rather than from
which feature the caller was using:

| Where the check lives | What it raises |
| --- | --- |
| Shared plumbing in `results.services` — `as_ids()`, `locked_sheet_for()`, `sheet_for()`, `school_on_this_connection()` | `ResultsError` |
| A feature module's own rule — `comments`, `ratings` | `CommentsError`, `RatingsError` |

Shared plumbing cannot raise a feature's error without knowing its callers, and
it has two. So `as_ids()` raises the parent that `CommentsError` and
`RatingsError` both subclass, and a caller catching only `CommentsError` misses
it. **Catch `ResultsError` to catch everything a results call can refuse with;
catch `CommentsError` only when you specifically mean this module's own rules.**

That is why this module's contract is stated as *inside the `ResultsError`
hierarchy* rather than as `CommentsError` — the guarantee worth relying on is
that no refusal escapes the hierarchy into an `IntegrityError`, `ValueError` or
`TypeError`, not that every one carries the narrower class.

The rule generalises: anything else built on the same plumbing inherits it, so
the write guard on live marks ([issue #27](https://github.com/adedejimakinde/luffy-school-saas/issues/27))
will refuse with `ResultsError` from the shared half and its own error from its
own, without that being a special case to rediscover.

### A position is checked before it reaches the column

`add_phrase()` takes `position` as an exposed keyword, so a screen reaches a
`PositiveSmallIntegerField` with it directly. Left out it means "the end", which
is what a school adding a phrase intends; given, it has to be a place in the
list. Each way of not being one escapes this module's hierarchy differently —
`-1` as an `IntegrityError`, `"first"` as a `DataError`, `70000` as a `smallint`
overflow — and each of those marks the caller's transaction unusable, which is
the failure the rest of this module goes to lengths to close.

`True` is the quiet one. It is an `int` as far as Python is concerned, so
nothing downstream objects and the phrase lands at position 1 — no error, wrong
answer. It is refused explicitly for that reason.

## A correction keeps its author

`written_by_id` is stamped once, at the insert, and names whose remark this is.
`updated_by_id` moves on every correction. Two columns because they answer two
questions, and `update_or_create()`'s `create_defaults` is what keeps them
apart — one `defaults` dict serving both paths would have every correction
overwrite the author with whoever last touched the row.

The case that makes it visible is real: the office reassigns a class mid-term,
and the new class teacher rewrites the remark. One row, two people.

**Both hold `User` ids, not `Membership` ids.** The column beside them holds a
membership id, and both are small dense integers, so a screen resolving the
wrong one would confidently name an unrelated person rather than fail.

## Nothing to call yet

No endpoint, no serializer, no template. `results/api.py` still publishes only
the broadsheet, and `card_comments()` is what the report card will render from
when task 3 builds it — two sources behind one call, and the caller does not
have to know which one it got.

The rules have to hold for an import too, and a rule that lives in a view only
holds for the view.

## Open

- **A remark begun before the sheet exists takes no lock**, because there is no
  row to lock, so it can still land under a submission that opens and submits
  the sheet in the same window. The same hole `ratings` has;
  [issue #30](https://github.com/adedejimakinde/luffy-school-saas/issues/30) is
  scoped to cover both.
- **A correction keeps no record of what it replaced.** `written_by_id` names
  who first wrote and `updated_by_id` who last changed it, so a third person's
  touch is unrecoverable and the previous sentence is gone. Released cards are
  safe — the frozen copy is append-only — but the review window, which is where
  corrections happen, is not covered. Same shape as the ratings and
  `gradebook.Score`;
  [issue #28](https://github.com/adedejimakinde/luffy-school-saas/issues/28),
  to be decided with task 8's revisions.
- **A child placed into a released term gets no remarks at all**: the frozen
  table has no rows for them and the live path is never reached.
  [Issue #31](https://github.com/adedejimakinde/luffy-school-saas/issues/31),
  which task 3 will meet in a larger form.
- **A third signatory** — some schools print a head of department's line — is a
  `CommentAuthor` member and nothing else. Print order is the enum's declaration
  order rather than the alphabetical order of the stored value, precisely so
  that adding one whose value sorts wrong does not silently reorder the card.
