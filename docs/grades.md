# The grading scale

What letter a percentage prints as. School configuration, the same class of
thing as the trait list in [conduct](ratings.md) — a school edits its scale
without a deploy, and the letter goes on a card a parent keeps.

Code: `results/grades.py`, `results.models.GradeBand`, migration `0015`.

## A band stores where it starts

There is no `maximum` column. A band runs from its `minimum` up to the next
band's `minimum`; the highest runs to 100.

    A1   75.00  ─┐ 75.00 … 100
    B2   70.00  ─┘ 70.00 … 74.99
    B3   65.00     65.00 … 69.99
    ...
    F9    0.00      0.00 … 39.99

The requirement was "bands neither overlap nor leave gaps across 0–100", and
this shape meets it by **construction** rather than by inspection:

| the hazard | why it cannot happen |
| --- | --- |
| two bands overlapping | a mark resolves to exactly one band — the greatest `minimum` at or below it |
| a gap between bands | every mark at or above the lowest `minimum` is covered by that same rule |

Written the obvious way — `minimum` and `maximum` on each row — neither is a
row-level `CHECK`, because a gap is a fact about a *pair* of rows and Postgres
will not look at another row from inside a check. The honest version needs an
`EXCLUDE` constraint (and `btree_gist`) for the overlap half plus a trigger for
the gap half, and a checked invariant is one that can be false between checks.

### What is left over: coverage

"Is there a band at nought?" is a fact about the table, not about a row, so it
lives in `grades.set_scale()`. Without it a mark below the lowest band prints a
**blank grade**, which on a card is indistinguishable from a subject nobody
marked.

### The cost, stated

Deleting a band silently widens the one below it: drop "B2 at 70" and "B3 at 65"
now runs to 74. With explicit maxima that deletion would leave a gap instead. A
widened band is the better failure — it is what removing the row asked for, and
every mark still prints something — but it is not what a reader of an
explicit-range table expects, which is why the scale is replaced whole rather
than one band at a time.

## Reading a grade

    grades.grade_for(Decimal("75.00"))   -> A1
    grades.grade_for(Decimal("74.99"))   -> B2
    grades.grade_for(None)               -> None

`None` for `None` is the rule the rest of this app already keeps: **not marked
is not zero**, and it is not an F either. An unmarked subject prints a blank
line, and grading it F would be the card asserting the school assessed the child
and they scored nothing. Same argument as `positions`' "not marked is not zero"
and `TermAbsence`'s renormalisation.

Rendering a class passes `bands=` so the scale is read once rather than once per
subject line.

## Setting a scale

    grades.set_scale_as(principal, [
        (70, "A", "Excellent"),
        (60, "B", "Very Good"),
        (50, "C", "Credit"),
        (40, "D", "Pass"),
        (0,  "F", "Fail"),
    ])

Wholesale, in one transaction, and the rows are **new rows** — nothing tries to
match an offered band to an existing one. There is no stable identity to match
on: a school moving "B2" from 70 to 72 has edited a band, and one replacing "B2
at 70" with "B at 70" has replaced one, and guessing produces a scale nobody
asked for.

`GradeBand` is deliberately **not** a foreign key from anywhere. What a released
card shows is the letter and the remark **copied** at release, exactly as
`ReleasedTraitRating` copies a trait's name — so replacing the scale next term
cannot reach a card that has already gone home.

Who may: **principal or administrator**, matching `ratings.CONFIGURING_ROLES`
and `sessions.CONFIGURING_ROLES`. A school's grading scale, its trait list and
its averaging convention are the same kind of act by the same people. Note this
is wider than `sessions.DECIDING_ROLES`, which is the principal alone: setting a
scale is an office act, deciding that a child repeats a year is not.

## The seed

Migration `0015` seeds the WAEC nine-point scale per schema:

| | | | | |
| --- | --- | --- | --- | --- |
| A1 | 75–100 | Excellent | C6 | 50–54 Credit |
| B2 | 70–74 | Very Good | D7 | 45–49 Pass |
| B3 | 65–69 | Good | E8 | 40–44 Pass |
| C4 | 60–64 | Credit | F9 | 0–39 Fail |
| C5 | 55–59 | Credit | | |

**A seed is a starting point and not a promise.** Every row is editable, nothing
in the code names a band, and a school that grades differently replaces the lot.
A schema created around the migration still reads correctly: `scale()` returns
an empty list and `grade_for()` returns `None`, so a card prints no letter
rather than failing.
