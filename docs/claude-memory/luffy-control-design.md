---
name: luffy-control-design
description: A control that breaks everything says as little as one that breaks nothing — aim it at the single branch the test routes through
metadata:
  node_type: memory
  type: feedback
---

Rule 5 controls must isolate **the one path the test under test actually
takes**. Two ways a control fails to be one, both hit on PR #88:

- **It breaks too much.** Neutering `0023`'s append-only trigger by repointing
  it `BEFORE INSERT` made every insert raise, so all 5 tests failed including
  `setUp`. That says nothing about the claim. Redone as "never create the
  trigger" (`RunSQL(sql=noop)`), it failed exactly the 2 new trigger tests and
  left the 2 model tests green — which was the finding.
- **It misses the branch.** `services._require_authority()` has *two* raises:
  an authentication branch (`actor=None`) and a roles branch. A control on the
  roles branch leaves `test_signing_out_is_refused_in_english` green, and that
  survival is not evidence of anything until a second control neuters the
  authentication branch and shows it red.

**Do not explain a surviving test — control it or rename it.** The user rejected
the explanation outright: "Prove that, don't explain it… I'm not closing this PR
on an explanation."

The strongest control shape for a named-constraint assertion: **rename the
constraint while leaving the rule identical**. If the test still passes, it was
pinning "something raised", not identity.

**Never run a control concurrently with another test run.** Both use
`test_luffy_db`; they collide with
`FATAL: database "test_luffy_db" does not exist … just been dropped` and both
results are void. Serialise. See [[control-runs-go-stale]],
[[luffy-test-suite-runtime]].
