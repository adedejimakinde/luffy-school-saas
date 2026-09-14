## After the rebase onto task 8: `cards_on()` is the enqueuer's shape, and its docstring already names a caller that does not exist

Noted while rebasing #62 onto `main` now that task 8 has landed. Nothing here changes the issue; it narrows what the fix looks like and flags a premise that will mislead whoever writes it.

**`results.cards.cards_on()` has no caller anywhere in the repository.** Only its definition and its `__all__` entry. Its docstring — written in task 8, which re-keyed it — opens with:

> `Prefetch` rather than a join per card: task 7's PDF job walks a whole class and a per-card query there is forty-five round trips inside a Celery task.

Task 7 does not walk a whole class. It renders **one card per job**, deliberately, for the two reasons in `results/tasks.py`: `acks_late` with `task_reject_on_worker_lost` means a worker killed on the forty-fourth card hands the message back, and a per-class job would re-render the forty-three that already finished to reach it; and `visibility_timeout` is 300 seconds, so a per-class job risks redelivery *alongside itself*. `docs/cards.md` was corrected in #62 to match; the `cards_on()` docstring on `main` was not, because task 8 was written in parallel and merged first.

So the sentence is not wrong about why `cards_on()` prefetches — it is wrong about who does the walking, and that matters for this issue specifically, because **the walk is exactly the thing that is missing.** Something has to iterate a released class to enqueue forty-five per-card jobs, and `cards_on()` is that something's natural query. The premise to avoid inheriting is that a batch reader implies a batch *job* — it does not, and the queue settings are the reason.

Two consequences for the fix:

1. **The enqueuer wants ids, not cards.** `cards_on()` prefetches `subject_results` and `assessment_scores` so a renderer can read a card without forty-five round trips. An enqueuer needs `(schema_name, card_id)` and nothing else — the worker re-reads the card in its own transaction anyway, which is what makes the job idempotent and redelivery-safe. Handing it fully-prefetched cards loads about 1,350 score cells per class to throw them away. The `DISTINCT ON (student_membership_id) … ORDER BY version DESC` rule task 8 gave `cards_on()` is the part that must be kept, whatever the projection: without it a forty-five child class enqueues forty-six jobs and a superseded version 1 gets rendered and sent home beside version 2.

2. **`cards_on()`'s docstring should be corrected when the enqueuer lands**, to name its real caller rather than a job shape that was reversed before it was written. Filing it here rather than as its own issue because it is one line and the fix is this issue's.

The rebuild path described above is unaffected — it is still the half that produces silent missing files, and it needs the same walk plus "and has no `ReleasedCardPdf` row", which is a left join rather than a second query.
