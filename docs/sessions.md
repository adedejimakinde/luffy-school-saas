# The three-term view, and the decision at the end of it

Everything else in `results` is reckoned per **term**. This is the page for the
two lines at the bottom of a Nigerian report card that are not: the average of
the whole year, and what the school decided to do about it.

`results/sessions.py` computes and records both. `results/models.py` holds
`SessionSettings`, `ReleasedSessionResult` and `PromotionDecision`.

## A session is three terms and a string

There is no session row to point at. `Term.session` is a `CharField` holding
`"2025/2026"`, for the reason its own docstring gives — the term after 2025/2026
Third is 2026/2027 First, so a session is not something a school's calendar can
be walked along. A session here is therefore `Term.objects.filter(session=...)`,
which returns one, two or three rows.

Fewer than three is the **ordinary** case, not an error. For most of the year a
school is part-way through: reading a session in October means reading a session
with one term in it, and a head of year does exactly that.

## The average is configurable, because the number decides promotions

Two conventions are both real:

    equal        (first + second + third) / 3
    weighted     20% / 20% / 60%

The second counts the third term heaviest because it is the one that examines
the whole year. Neither can be hardcoded, because the number that comes out
decides whether a child moves up.

`SessionSettings.averaging` holds the choice and `EQUAL` is the default — what a
school that has never thought about it means. A weighting must be three numbers
**summing to 100**, refused by `sessions.use_a_weighting()` with a sentence
naming the total the school actually typed, and again by the
`weights_sum_to_one_hundred` check constraint for the import and the `psql`
session that never reach the service.

### The weights are null in `EQUAL` mode

A straight mean of three terms is not expressible as three integers summing to
100, and 33.33/33.33/33.34 is not a straight mean — it is a weighting that
quietly favours third term by a hundredth. So the mode is stored and the weights
are *absent* when it is `EQUAL`, rather than left at whatever they were: a stale
20/20/60 under a mode that says `EQUAL` is a field that lies to the next reader.

## An absent term renormalises. It is never a zero

This is the whole point of the module.

    configured   20 / 20 / 60
    sat           — /  ✓ /  ✓
    applied       — / 25 / 75

A child who transferred in at second term did not score nothing in first term;
they were not there. Scoring the absence zero invents a failing grade the child
never earned, and it propagates — it drags the session average below the pass
mark and produces a `REPEATED` **suggestion** out of arithmetic rather than out
of anything that happened:

| | second 70, third 80 | suggestion at a 70 pass mark |
| --- | --- | --- |
| absent term as a zero | 62.00 | `REPEATED` |
| renormalised | 77.50 | `PROMOTED` |

`results/tests/test_sessions.py::TheTwoTermCaseTests` holds that under both
conventions, with the numbers.

### Three reasons a term is absent, and they are not collapsed

All three renormalise identically. They are recorded separately because they
need opposite responses from staff:

| `TermAbsence` | means | what staff do |
| --- | --- | --- |
| `NOT_ENROLLED` | the child was not here that term | nothing; a transfer |
| `UNMARKED` | the child was here and nobody entered marks | enter the marks |
| `NO_TERM` | the school has no such term this session | create the term, or wait |

A bare `None` would make a marking backlog look exactly like a mid-session
transfer on the one screen a head of year uses to find both.

### A weighting can leave nothing to renormalise

`0/0/100` is a legal configuration — a school counting only the third term. A
child who left before third term therefore has a total weight of zero, and no
proportion of nothing is a hundred. That child has **no session average**, which
is the truthful answer, and it leaves the promotion suggestion blank so that a
person decides rather than the arithmetic inventing a `REPEATED`.

The terms they *did* sit still carry the weight that was applied to them, and it
is **nought** — not an absent weight. The distinction is the whole content of
the two columns:

| the row says | it means |
| --- | --- |
| an average, and a weight of `0.00` | the child sat this term, and the school counts it for nothing |
| no average, no weight, an absence reason | there was no term here for this child |

So a frozen line under `0/0/100` reads `60.00 @ 0.00`, `70.00 @ 0.00`, `— (not
marked)`, and no session average. The weights on such a line sum to nought
rather than to a hundred, and a null average is how a reader tells that case
from a real weighting. Migration `0014` has the release this cost: recording
the zero and dropping it were each refused by one of the two check constraints,
so a third-term release under that configuration failed for the **whole class**.

## The exact mean, and the weights you can read

The stored weights are rounded to two places and adjusted so they add to exactly
a hundred — a stored weighting that adds to 99.99 is one every reader has to
explain away. The **average is not computed from them**: it is calculated from
the exact ratios and rounded once, so a straight mean of three terms is a true
third each.

The two disagree in the last penny, and that is deliberate:

    scores 0, 0, 100
    from the stored weights   100 × 33.34 / 100  =  33.34
    the exact mean            100 / 3            =  33.33   ← what is stored

When the rounding leaves a spare hundredth, it goes to the **later** term.
Under an equal weighting every remainder is identical, so a stable sort would
hand it to whichever term happened to be inserted first — a number on a school's
screen decided by dictionary order. Every weighting a Nigerian school actually
uses counts the third term heaviest, so the end of the year is the least
surprising place for it to land.

Rounding itself is `positions.round_percentage()` — the single rounding
authority for every percentage in this app, `ROUND_HALF_UP` in a pinned context.
`docs/positions.md` has the argument for why that is not left to ambient state.

## The freeze: third term only

`sessions.freeze_for_release()` is called by `results.services.release()` inside
the transaction that writes the release row, alongside the conduct section and
the remarks. It writes nothing except at **third term**, and decides that for
itself rather than being called conditionally — a caller that has to remember
which freezes apply to which term is one that will eventually forget.

A session average is not a thing until the year it averages is over. Freezing
one at first-term release would write the first term's average wearing a
session's name, unfixable except by revision, while the year was still being
taught.

Why a copy at all, when every term is still in the database:

| the school does this | the session average would |
| --- | --- |
| switches from 20/20/60 to a straight mean | move, on every past session |
| revises a first-term result (task 8) | move, after the card went home |
| corrects a placement for a term long closed | gain or lose a whole term |

None of those are misuse, and every one silently rewrites a number a parent is
holding.

### A child can collect two frozen lines

The tempting claim is that at most one exists: a child is on exactly one
third-term roster, because `ClassPlacement` allows one group per child per term.
That is true at any *instant* and false over time.

    JSS 1A releases its third term   -> the child is frozen here
    the child is moved to JSS 3B     -> the placement row is rewritten
    JSS 3B releases its third term   -> the child is on that roster too

Both rows are real records of releases that happened, and the table is
append-only, so neither is deleted. **The card is the first one.** A released
card keeps saying what it said, and a later release cannot reach backwards into
one already in a parent's hand — the same rule migrations `0010` and `0011` and
issue #27's mark guard all turn on.

## Promotion: a suggestion, and a decision that is nobody's but a person's

`suggested` is what the arithmetic proposes. `status` is what a person decided,
and it is the only one that prints.

The suggestion can only ever be `PROMOTED` or `REPEATED` — a pass mark cannot
reach `ON_TRIAL`, which is a judgement about a child who fell short and is worth
carrying anyway, or `WITHDRAWN`, which is not an academic outcome at all. Both
are things a school knows and a threshold cannot.

### Undecided is the absence of a row

There is no `UNDECIDED` status and no current-status column anywhere. A child
nobody has decided about has no `PromotionDecision` row, and every reader has to
handle that. The alternative — a status column defaulting to something — is a
school-wide promotion performed by a default value: a principal who reviews
nothing would promote four hundred children without an act, and the audit would
show it as decided.

### The suggestion is frozen at the moment of the decision

Stored, not recomputed on read, and this is load-bearing. The gap between
`suggested` and `status` is the record that a person went against the
arithmetic. Recompute it and the same row reads as agreement or override
depending on when it is asked:

    principal sees   REPEATED on 47.00 under 20/20/60, records ON_TRIAL
    school later switches to a straight mean
    the same child now reads 51.67, which suggests PROMOTED
    recomputed, the row would say "the system said promote, the principal
    said on trial" — a downgrade nobody performed

So the suggestion is frozen with the two things that produced it, the session
average and the pass mark in force. The *weighting* behind that average is not
copied here: it lives on `ReleasedSessionResult`, which is where the arithmetic
is auditable, and a second copy would be a second answer to "how was this year
averaged?" in a table that is not the authority on it.

The "but a mark was wrong and got fixed" case belongs to task 8. A revision
makes a new version, so it makes a new decision row.

### Append-only, and the latest row wins

A principal changing their mind writes a second row; both stand. The approval
chain's argument reused — a decision record that edits itself has silently
forgotten that it was ever different, who changed it and when, which is the one
thing an appeal from a parent turns on.

`promotion_of()` reads the latest, ordering on `-decided_at` and then `-id`.
The tie-break is not decoration: `decided_at` is `auto_now_add`, two decisions
recorded in one request can share it to the microsecond, and a promotion status
that resolves arbitrarily between two rows is one that changes when nothing
changed.

## Who may do what

| act | roles | why |
| --- | --- | --- |
| configure the averaging and pass mark | principal, administrator | an office act, matching `ratings.CONFIGURING_ROLES` |
| decide a promotion | **principal only** | matching `services.RELEASING_ROLES` |

The one place these deliberately disagree is the administrator. Setting a
school's weighting is clerical; telling a family their child repeats the year is
the act they will come in to argue about, and it belongs to the person who
released the results. Task 8 settles revisions the same way, on the same
sentence: release is the principal's act, so what follows it is too.

## What a parent must not see

Two things on this page are staff-only, and both leak the same way — by sitting
in the API response even when they are off the rendered card:

- **why a term is missing.** "No marks were entered" is a fact about the
  school's filing, not about the child's year.
- **the suggestion, and the gap between it and the decision.** A parent seeing
  "the system said promote, the school said repeat" is being handed the inside
  of a decision the school made and owns. What prints is the decision.

Position is already under this rule — see `docs/positions.md`. Enforcement is
the same: exclude at the **serializer**, not merely at the template, because a
card that omits a field whose value is sitting in the JSON has not omitted it.

## Still to come

- **The read API.** `results/api.py` exposes one broadsheet route today; the
  session view and the promotion sheet are not on it yet, and the serializer
  rules above are what that PR has to hold.
- **Task 3's snapshot.** The broadsheet has since been switched — a released
  term is served from the frozen cards, issue #55 — but the other two terms of a
  session are still read live by `_lines_for()`. That is safe for the one number
  it takes: `TermLine.average` is the child's own, and marks lock at release, so
  it cannot move the way a *rank* can. It would stop being safe the moment a
  session line carried a position, which is the reason to record it here rather
  than to leave it as an unstated assumption.
