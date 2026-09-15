---
name: luffy-release-marker-requirement
description: The architectural rule behind three luffy guard fixes, and the task 3 requirement (issue #34) that finally closes it
metadata:
  type: project
---

**A guard on a released artefact keys off the artefact, not off the child's
current placement.** Placement is a live fact that changes; release is an event
that happened. This is the rule four fixes turned on — `0010` (remarks), `0011`
(ratings), and issue #27's mark guard at both the service and trigger layers —
and it is worth stating to anyone touching a release guard.

**The trap it sets, which caught issue #27's first draft:** "the marks are not
frozen" and "no artefact records the release" are different claims, and the
first does not imply the second. `results_releasedtraitrating` answers *did a
card go home for this child* for any ratings-enabled school, whatever else was
or was not frozen. Before concluding a release guard cannot be keyed properly,
check what release actually writes — not what this particular guard is about.

It cannot be reconstructed from placement: `academics.ClassPlacement` constrains
one group per child per term, so a mid-term move *rewrites* the row and the
record of where the child sat at release is destroyed, not superseded.

What is left after that is a **per-school** gap, not a per-child one: a school
with the conduct section off freezes nothing for anybody, so nothing records
its releases at all.

**Issue #34 is the requirement that closes it properly**: task 3's release path
must write a per-child "a card went home" marker — one row per (released sheet,
child), inside the release transaction, independent of enabled groups, visible
traits, or whether any content was frozen. It is recorded as a REQUIREMENT, not
a nice-to-have: it collapses ratings' two checks into one, closes the
zero-visible-traits case, and makes issue #31's options decidable.

Deliberately not built inside a bug-fix PR — it is the heart of task 3 and would
be designed with no review gate. See [[luffy-open-work-state]].
