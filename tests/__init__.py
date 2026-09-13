"""Tests for repo infrastructure that is not any one app's.

`scripts/run-tests.sh` is the only occupant so far. It belongs here rather than
under an app because it is the thing that *runs* the apps' tests, and putting it
inside one would make that app's suite the judge of the harness judging it.

Discovered because `manage.py test` with no labels starts at the repository root
and matches `test*.py`, which is how CI invokes it.

`refusals.py` sits here too, and is not a test. It holds `assertRefusedBy`, the
one assertion every app's tests need and no app owns; the name does not match
`test*.py`, so discovery walks past it.
"""
