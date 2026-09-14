## The policy question, with options and no recommendation

Asked for by the repo owner before any of this is built. **May a released term be reopened, and by whom?**

### What any answer has to survive

Four things stand in the way, and they are not the same kind of obstacle:

1. **`results.services.is_open_for_writing(sheet)`** returns true only for `draft` or a sheet nobody opened. `gradebook.services`, `results.ratings` and `results.comments` all gate on it. It takes a **sheet** — not a child — which matters for option A.
2. **`_move()` refuses every transition out of `released`** by name: a released result "is corrected by issuing a revision, which keeps this one standing, not by moving it back."
3. **`ReleasedCard` and its five content tables are append-only by database trigger.** Nothing edits a card that went home; a correction can only ever be a *new version*.
4. **The signature chain.** `is_open_for_writing`'s docstring states the real constraint: "ratings and remarks are part of what the vice principal checked and the principal approved. If they could change afterwards, the signatures would be attached to a document that moved." Every option below is really an answer to *what happens to three signatures when a value they signed changes*.

### A — a per-child, per-term write window

A row (`sheet`, `student_membership_id`, `opened_by`, `reason`, `expires_at`, `consumed_by_revision`) opened by the same authority that may revise, closed by the revision that consumes it. `is_open_for_writing()` gains a second clause: draft, **or** a live window for this child.

- **For.** Smallest blast radius on the platform — one child, one term; the other forty-four cards cannot move. The audit is complete by construction: the window says who opened it and why, the revision says who consumed it, and neither is optional. The signature question gets a clean answer — the window is a *named exception* to what was approved, recorded as one, rather than an approval quietly reinterpreted.
- **Against.** `is_open_for_writing()` takes a sheet and would have to take a child as well, which is a signature change through three modules and their six refusals. A window opened and never consumed leaves that child's term writable until it expires, so expiry needs either a sweep or a check-on-read. And two windows open on one sheet at once compound #55 badly: two revisions, each re-ranked against a class that moved between them.

### B — send the sheet back through the chain for a second cycle

Lift `_move()`'s refusal. `released → draft` becomes a real transition with its own authority and reason; the class walks submit → check → approve → release again and every card becomes version 2.

- **For.** The only option where the signatures are genuinely **re-obtained** rather than reasoned about: three fresh ones on the corrected document. No new concept, no new table — `ResultSheetTransition` already records every step with actor and reason, so the audit costs nothing. It is also the only option that leaves the gradebook, the card and the broadsheet all agreeing afterwards, because the correction goes in through the ordinary mark-entry surface.
- **Against.** It reissues **forty-five cards to fix one child's mark** — forty-four families get a card stamped "Revised" over a change to somebody else's child, which is precisely what `results/revision.py` argues against. While the term is open, any teacher with access can change anything: the correction is not scoped to the thing being corrected. And every card's version advances together, so the version number stops answering "was *my* child's card corrected".

### C — corrections supplied to `revise()` directly

`revise(..., corrections={...})`. The values are passed in and written into the frozen rows; the gradebook stays shut.

- **For.** The two guards stay absolute, so no other caller is ever surprised by a term that is writable. The correction exists only for the duration of one call — the smallest possible window in time.
- **Against.** Two serious ones. It **duplicates the mark-entry surface**: a second way to write a mark, with its own validation, its own scope rules, and no `Assessment.max_score` check unless it is reimplemented — and whoever types the correction is typing it into a form that is not the form the original typo came from. Worse, **the gradebook and the card would disagree for ever**: `Score` still holds 41 while `ReleasedAssessmentScore` holds 61, so next term's broadsheet, the session average and anything analytical keep the wrong number. The card is corrected and the record is not.

### D — reopen nothing; the refusal is the answer

A released term is final. A wrong mark is corrected on paper by the school, or noted on the next term's card.

- **For.** No new mechanism and no new failure modes, and the guarantee "a released card is exactly what it said" stays absolute. It is also what the refusals now say after the task 8 PR: the write is refused, reissuing cannot reach it, raise it with the principal.
- **Against.** It is not an answer a pilot survives. Schools correct marks after release; the only question is whether the platform records the correction or the school does it on paper — and in the second case the platform's record becomes wrong, silently, with nothing able to detect it.

### The coupling that decides more than the mechanism does

**A mark correction is the case where #55 stops being cosmetic.** Fixing a spelling changes nobody's rank. Fixing a mark changes the whole class's — so under A or C, the corrected child's card would say "3rd of 45" while three other children go on holding cards saying they finished ahead of her, and both are frozen. #54 and #55 have to be answered together, or the fix for one manufactures the other. Option B is the only one where the ranking stays coherent for free, because it re-ranks everybody.

### The questions the choice actually turns on

1. Does a correction need **fresh signatures** (B), a **recorded exception** (A), or neither (C, D)?
2. Must the gradebook and the card **agree** afterwards? If yes, C is out.
3. Is it acceptable for one child's correction to **restamp the whole class**? If no, B is out.
4. Who is the authority — principal only, or principal plus the audited platform-staff door task 8 already built? Orthogonal; applies to A, B and C alike.
5. What is a parent **told**? A revision that changes a mark is a different communication from one that fixes a spelling, and `is_revised` is one boolean today.

Whichever is chosen, `revision.revise()` is a call site that has to honour it, and the six refusal messages corrected in the task 8 PR are the places that have to change back — each carries a comment saying so.
