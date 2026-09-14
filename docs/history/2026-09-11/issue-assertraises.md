Found while reporting the `/code-review` pass on PR #83. Two of that review's six
findings — `set_policy()` letting a raw `IntegrityError` escape, and `withhold()`
raising a bare `ValueError` — **survived a fully green suite**, and the reason was
the assertion shape, not missing coverage. Tests existed for both. They said
`assertRaises(Exception)`, which cannot tell a refusal from a 500.

An assertion that cannot distinguish the sentence a user should read from the crash
they should never see is not pinning the behaviour it is named for.

## The sweep

`grep -rn "assertRaises(\s*Exception\s*)" --include=*.py` returns 14 hits. One
(`results/tests/test_withholding.py:931`) is prose in a docstring describing this
exact trap. **13 are real call sites**, all in `results`:

| file | count |
|---|---|
| `results/tests/test_withholding.py` | 6 |
| `results/tests/test_approval_chain.py` | 3 |
| `results/tests/test_ratings.py` | 2 |
| `results/tests/test_revision.py` | 1 |
| `results/tests/test_comments.py` | 1 |

No `assertRaisesRegex(Exception)` and no `assertRaises(BaseException)` anywhere.

They are not all equally bad, and the split is the actionable part.

## Priority: the three bare ones

No capture, no follow-up assertion of any kind. Any exception at all passes these —
`AttributeError`, `TypeError`, a driver error, a 500 from code that never reached
the guard.

- `results/tests/test_withholding.py:1036` —
  `OnlyAPrincipalOrABursarMayDecide::test_a_teacher_may_not_withhold`
- `results/tests/test_withholding.py:890` —
  `TheDecisionRowIsAppendOnly::test_updating_a_decision_is_refused`
- `results/tests/test_withholding.py:898` —
  `TheDecisionRowIsAppendOnly::test_deleting_a_decision_is_refused`

**`test_a_teacher_may_not_withhold` is the one to fix first.** It is an *authority*
refusal — the test standing between a class teacher and the power to withhold a
family's report card — and it is satisfied by a 500. It should assert
`WithholdingError`, which is the type PR #83 introduced precisely so this refusal
has a name. Until it does, the guarantee it is named for is untested, and this is
the same test that would have caught finding 5 had it been written this way.

The two append-only ones should assert *which* constraint refused, not that
something went wrong: a wrong-table or wrong-name violation currently passes them,
and on an append-only table a decision written against the wrong child can only be
masked by appending a `lifted` row, never corrected.

## Second tier: ten that pin the sentence but not the type

These capture and then assert on the message — `assertIn("append-only", ...)`,
`assertIn("released", ...)`, `assertNotIn("at results at", ...)`. Weaker than they
look: a 500 carrying the right substring passes, and so does a refusal arriving
from the wrong layer.

- `results/tests/test_withholding.py:1199,1214,1229` — `TheRefusalReadsAsASentence`
- `results/tests/test_approval_chain.py:827` — `ReleaseIsTerminalTests`
- `results/tests/test_approval_chain.py:877,889` — `TheLogIsAppendOnlyTests`
- `results/tests/test_ratings.py:369` — `TheScaleTests::test_the_database_refuses_it_too`
- `results/tests/test_ratings.py:1389` — `TheFreezeTests::test_the_model_refuses_before_the_database_has_to`
- `results/tests/test_comments.py:837` — `TheFreezeTests::test_the_model_refuses_before_the_database_has_to`
- `results/tests/test_revision.py:828` — `WhatARevisionCannotFixTests`

**Two of these have names their assertion cannot verify.**
`test_the_model_refuses_before_the_database_has_to`, in both `test_ratings.py` and
`test_comments.py`, claims the refusal comes from the *model layer* — and then
asserts `assertRaises(Exception)` plus a substring that a database-level trigger
error would carry just as happily. The test cannot tell which layer refused, which
is the single fact its name promises. That is rule 7's shape: a claim in prose with
nothing underneath it.

## The fix already exists in this repo

`fees/tests/test_schedules.py:129` defines `assertRefusedBy(name)` and uses it 12
times. It asserts *which* constraint refused rather than that something raised, and
it already caught one test passing while never reaching its constraint. That helper
should move somewhere shared and be used for the database-level cases; the
service-level cases should name their own exception type.

## Scope

Test-side only. No production code changes, and no new behaviour — every guarantee
named here is already implemented and believed correct. This is about making the
tests capable of noticing when it stops being.

`assertRaises(Exception)` should not appear in this codebase.
