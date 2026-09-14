---
name: luffy-no-pilot-data
description: "luffy-school-saas has NO pilot school data anywhere — any request to measure a real-world distribution cannot be satisfied and must be reported, not estimated"
metadata:
  node_type: memory
  type: project
---

Established 2026-09-12 while scoping #85, which asked for "the real distribution
of concessions per child across the pilot schools".

**There is no such data, and there are no pilot schools.** Checked directly, not
inferred:

- `schools_school`: **0 rows**. `accounts_membership`: **0 rows**.
- Tenant schemas across every database on the cluster (`luffy_db`,
  `luffy_comments`, `luffy_ratings`, `luffy_runa`, `luffy_scores`): **none**.
  Only `public`.
- `fees_feeconcession` exists **only inside a tenant schema**, so with no tenant
  schemas there is no such table anywhere to count.
- No fixtures, no seed data, no dumps.
- The repo label says it outright: `must-fix-before-pilot` — *"Must be fixed
  before the **first** pilot school uses this in anger."*

## How to apply

When an instruction asks for a measurement "across the pilot schools", or any
number that would have to come from real school usage, **the answer is that it
cannot be taken** — say so and show the checks above. Do **not** substitute
roster arithmetic, a hypothetical distribution, or a modelled one. Presenting
derived numbers as measured is the exact failure [[a-bound-needs-a-constraint]]
records, and it is worse for a distribution than for a bound because the
distribution is the input that picks the option.

The user confirmed this reading on 2026-09-12 and withdrew their own "median
class past 64" as *"arithmetic on a hypothetical roster"*. What remains available
is **what the schema permits**, and that is the correct basis for a fix: a loop
with no constraint bounding it has to be safe at any count.

What a missing distribution *does* change is **urgency, not the fix** — it cannot
tell you whether the bad case is common, only that it is reachable.

See [[luffy-85-discount-subtransactions]], [[luffy-open-work-state]],
[[a-bound-needs-a-constraint]], [[luffy-subtransaction-measurement]].
