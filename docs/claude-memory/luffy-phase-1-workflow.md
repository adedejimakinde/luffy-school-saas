---
name: luffy-phase-1-workflow
description: "How the user wants Phase 1 work delivered on luffy-school-saas — one PR per task, merged to main before the next"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: aef5da7e-0170-4c81-b5f2-338b9abb8f0e
  modified: 2026-08-22T07:46:36.657Z
---

For Phase 1 (results and report cards) on luffy-school-saas, the user set these rules:

- **One PR per task, targeting `main`. Merge each into main before starting the next.** Do **not** stack branches on branches.
- After each merge: confirm **CI** is green on main before moving on. Run only
  the app under test locally — the full suite belongs to CI, see
  [[luffy-test-suite-runtime]] (decided 2026-08-30).
- **Prove behaviour with a real runnable test, run it, show the output.** Do not reason about library behaviour instead of testing it. **Test with 2+ tenants, never one.**
- Self-review each task before opening the PR, looking for the bug classes this project keeps hitting: stale reads under concurrent access, exceptions masking unrelated failures, silent no-ops, guards that check the wrong object, and anything that only breaks with more than one school.
- Track anything found-but-not-fixed in a **GitHub issue**, not in prose.
- Stop and ask on decisions with real tradeoffs rather than picking silently.

**Why:** an earlier batch of PRs (#12–#15) was each merged into its own base branch instead of upward, so none reached `main` and the user lost the whole chain until they checked manually. The no-stacking rule exists to prevent exactly that.

**`gh` is installed and I open PRs and merge them myself** (since 2026-08-29 —
this replaces the old split where the user did it because the devcontainer had no
`gh`). It authenticates off the Codespaces `GITHUB_TOKEN` as **`only1paulo`**, and
write scope is confirmed: it has posted a PR comment and opened PR #37.

Installed from the official apt repo, and **an `apt` install does not survive a
devcontainer rebuild** — reinstall with:

```
sudo mkdir -p -m 755 /etc/apt/keyrings
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null
sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt-get update -qq && sudo apt-get install -y gh
```

**The ancestry check after a merge is not conditional on which tool merged.** Run
`git merge-base --is-ancestor <sha> origin/main` after every merge, including my
own `gh pr merge` — the point was never that the user's clicking was untrustworthy,
it is that a "merged" badge is not the same claim as reachability from `main`.
That is what PRs #12–#15 got wrong.

**Merging `main` still gets a word from the user first.** Opening a PR is
reversible; merging is the step that changes what everyone else builds on.

**And the word means "merge WHEN CI is green", never "merge now".** Set
2026-09-05 after PR #79 merged ungated. The user's "merge it" is permission to
merge, not permission to skip the check — if CI is still running when the word
comes, the merge **waits on the check, explicitly**, and I say that rather than
merging and reporting it afterwards.

**`gh pr merge --auto` does not gate on this repo.** Auto-merge is not enabled
here, so `--auto` **silently falls through to an immediate merge**: no error, no
warning, and `--auto --merge` merged #79 while its `test` job was still in
progress. Do not use it as the gate. Either:

- wait on a *single* background waiter for the check (see
  [[luffy-never-idle-on-ci]] — arm it, then build or stop, never poll), then run
  `gh pr merge` explicitly; or
- if `--auto` is used anyway, assert `gh pr view <n> --json autoMergeRequest`
  came back **non-null** afterwards. Null plus `state: MERGED` means it merged
  now, not on green.

The failure is quiet in both directions: the merge succeeds and the transcript
reads like a normal merge. Nothing tells you the gate was skipped except asking.

**And the gate is checked against the head being merged, not against the PR.**
Set 2026-09-12 on PR #86, same failure as `--auto` through a different door.
`gh pr checks <n>` and `statusCheckRollup` answer for whatever head GitHub has
most recently attached a run to, so in the minutes after a push they still
report the **previous** commit's green. A waiter built on either one fires
immediately, and the merge then sails through a gate that never ran on the code
being merged. Key it on the SHA instead:

```
gh api repos/<owner>/<repo>/commits/<sha>/check-runs
```

and require `total_count >= 1` **and** every run `status == "completed"` before
reading conclusions — a zero count is "no run has been created yet", which is
not the same as pending and looks identical to green if you only inspect
conclusions. The quietness is the point in both doors: the merge succeeds, the
transcript reads like any other merge, and nothing says the green belonged to
different code.

So the ancestry check afterwards covers **two** shas — the merge commit and the
head the gate was verified on — because "something merged" and "the thing I
tested merged" are different claims.

**How to apply:** after opening a PR, confirm it targets `main`; after merging, verify with `git merge-base --is-ancestor <sha> origin/main` rather than trusting the PR's "merged" badge. See [[phase-1-results-decisions]] for the settled domain calls.
