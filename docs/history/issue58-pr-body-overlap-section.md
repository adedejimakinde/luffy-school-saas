## Overlap with #66 — resolved, and it was not clean

Both branches were cut from `main` at `ff36dda` and both touch
`results/tests/test_pdf.py` in different regions. `git merge-tree` reported a
clean merge either way round, and that turned out not to settle it.

#66 has since merged (`main` is now `54ec826`), and `origin/main` is merged into
this branch here. The textual merge was indeed clean. But #66 added
`results/tests/test_renders.py`, and that new file carries the *same*
`connected_to` workaround this PR exists to remove — neither branch could see
the other. After the merge, `TheDebounceTests.ask()` claimed in its docstring
that `connected_to()` "does not nest — it always lands back on `public`, which
is issue #58", which the merged code makes false, and it repeated `marker()`'s
query by hand to dodge a bug that is no longer there.

Left alone that is a stale comment of the worst kind: the file's own
justification for duplication that no longer has a reason to exist. So `ask()`
now calls `self.marker()` — which nests, and so exercises this fix in a second
module — and the docstring describes the code as merged.

`results/tests/test_revision.py:972` also cites #58 and is deliberately left
alone: it says to assert inside the context because the outermost block still
lands on `public`, which this PR does not change.

**CI on this branch before the merge was green against the pre-#66 base**, so
the run that matters is the one on the merge commit.
