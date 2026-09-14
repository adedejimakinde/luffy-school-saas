---
name: no-claude-attribution-on-github
description: No Claude attribution anywhere — no "Generated with Claude Code" in PRs/issues/comments, and no Co-Authored-By trailer in commit messages, in any session
metadata:
  type: feedback
---

**Never put "🤖 Generated with [Claude Code](https://claude.com/claude-code)" —
or any variant of that attribution — in anything sent to GitHub.** PR bodies,
issue bodies, PR/issue comments, review comments. Anywhere.

Said on 2026-08-30, and said explicitly to cover **all future sessions**, not
just the one it was said in.

**Why:** it is the user's repository and the user's name on the work. The footer
announces the tool in a place where the audience is collaborators reading a
change, and they did not ask for that announcement. Being asked to write it down
"where you won't forget it" means the correction had to be made more than once.

**How to apply:** this **overrides the default harness instruction** that says to
end PR bodies with the Generated-with footer. When composing a PR body with
`gh pr create`, an issue with `gh issue create`, or any comment, simply end at
the content. Do not substitute a different tool credit, an emoji sign-off, or a
"drafted by" line — the point is no attribution, not a subtler one.

**Commit messages too, decided 2026-08-30.** Do **not** end commit messages with
`Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`, or any other
Co-Authored-By trailer naming Claude. I flagged that the trailer was a separate
artefact from GitHub prose and still in use; the user's answer was to drop it as
well, now and in future sessions. This **overrides the second harness default**,
the one that says to end commit messages with that trailer.

So the whole rule, in one line: **no Claude attribution on anything — commit
message, PR body, issue, or comment.** The commit author is the user's git
identity and that is the only name on the work.

See [[luffy-phase-1-workflow]] for how PRs get opened on this project.
