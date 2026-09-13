"""One assertion, shared: *which* refusal arrived, not that one did.

`assertRaises(Exception)` cannot tell the sentence a user should read from the
crash they should never see, and rule 5's third way a green test lies — "it
passes for a reason unrelated to its subject" — is exactly what it invites. Two
findings on PR #83 survived a fully green suite for that reason: tests existed
for both, and neither could distinguish a refusal from a 500.

This module holds the database half of the answer. `assertRefusedBy(name)` fixes
the exception *type* at `IntegrityError` and the *identity* of the constraint at
`name`, so a refusal arriving from a different constraint, a different table, or
a different layer fails the test rather than passing it. It began life on
`fees.tests.test_schedules.BillingSetUp`, where it caught a test that passed
while never reaching the constraint it was named after; it lives here now
because the same trap is not one app's.

It works against this repo's triggers as well as its constraints because every
`RAISE EXCEPTION` in the migrations carries `USING ERRCODE = 'restrict_violation'`
— SQLSTATE 23001, integrity-constraint-violation class — which Django surfaces
as `IntegrityError`. A trigger raised with the default `P0001` would arrive as
`InternalError` instead and this helper would not match it, which is the
intended behaviour rather than a gap: it would mean the trigger had stopped
claiming to be a constraint.

There is deliberately no service-level counterpart. A service refusal already
has a name — `WithholdingError`, `RatingsLocked`, `TransitionsAreAppendOnly` —
and `assertRaises(ThatName)` says which layer refused without any helper. A
helper that took the type as an argument would only be `assertRaises` spelled
longer, and one that accepted any of them would re-introduce the thing this
module exists to remove.
"""

from django.db import IntegrityError


class RefusalAssertions:
    """Mix in alongside `TestCase` for tests that assert a database refusal."""

    def assertRefusedBy(self, name):
        """A context manager asserting *which* constraint refused the write.

        `assertRaises(IntegrityError)` alone is the green test rule 5 warns
        about: any constraint firing for any reason passes it, including one
        that has nothing to do with what the test claims to be about. Naming it
        means the test goes red if the refusal starts coming from somewhere
        else — which is what happens when a constraint is renamed, dropped, or
        quietly replaced by a different one.

        `name` is a regex, matched with `assertRaisesRegex` against the whole
        message. A constraint name is the strongest thing to pass; a distinctive
        phrase from a trigger's own sentence is the next best, because a trigger
        has no constraint name to report.
        """
        return self.assertRaisesRegex(IntegrityError, name)
