"""The premise `assertRefusedBy` rests on, asserted instead of described.

`tests/refusals.py` pins the exception type at `IntegrityError`, and that only
works because every trigger in this repository raises with
`USING ERRCODE = 'restrict_violation'` — SQLSTATE 23001, in the
integrity-constraint-violation class Django maps to `IntegrityError`. A trigger
raised with plpgsql's default `P0001` arrives as `InternalError` instead, and
every `assertRefusedBy` written against it would fail with "IntegrityError not
raised" — a sentence that reads as *the trigger is missing* rather than *the
trigger stopped claiming to be a constraint*.

That premise was a paragraph in a docstring, which is rule 6's open question
rather than a fact. Found by the `/code-review` pass on PR #88: a claim
load-bearing enough to hold up a shared assertion helper, inside a PR whose
whole argument is that prose enforces nothing.
"""

import ast
import pathlib
import re

from django.test import SimpleTestCase

#: The SQLSTATE every refusal in this repo is raised with. `restrict_violation`
#: is 23001; the class is what matters, because `django.db.utils` maps the whole
#: of class 23 to `IntegrityError` and nothing else to it.
REQUIRED = "USING ERRCODE = 'restrict_violation'"

REPO = pathlib.Path(__file__).resolve().parent.parent


def _statement_at(sql, start):
    """The RAISE statement beginning at `start`, up to its real semicolon.

    Splitting on the first `;` is wrong and fails loudly: every append-only
    message in this repo reads `'<table> is append-only; % is not allowed'`,
    so the first semicolon is *inside* the message literal, several lines
    before the `USING` clause. Quote state has to be tracked. plpgsql escapes a
    quote by doubling it, which needs no special case here — the doubled pair
    flips the flag twice and lands back where it started.
    """
    quoted = False
    for i in range(start, len(sql)):
        char = sql[i]
        if char == "'":
            quoted = not quoted
        elif char == ";" and not quoted:
            return sql[start:i]
    return sql[start:]


def _sql_literals(path):
    """Every string constant in a module except its own docstring.

    Parsed rather than grepped because the migrations discuss `RAISE EXCEPTION`
    in prose as well as raising it — `0017` and `0023` both do — and a grep
    counts the sentence about the trigger as though it were the trigger.
    Comments are absent from the AST for the same reason, which is convenient.
    """
    tree = ast.parse(path.read_text())
    docstring = ast.get_docstring(tree, clean=False)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value != docstring:
                yield node.value


class EveryRaiseIsAConstraintViolation(SimpleTestCase):
    """`assertRefusedBy` matches `IntegrityError`; this is why it can."""

    def test_every_raise_exception_in_a_migration_carries_the_errcode(self):
        migrations = sorted(REPO.glob("*/migrations/0*.py"))
        self.assertGreater(len(migrations), 20, "migrations went missing")

        offenders = []
        checked = 0
        for path in migrations:
            for sql in _sql_literals(path):
                for match in re.finditer(r"RAISE\s+EXCEPTION", sql):
                    statement = _statement_at(sql, match.start())
                    checked += 1
                    if REQUIRED not in statement:
                        offenders.append(
                            f"{path.relative_to(REPO)}: "
                            f"{' '.join(statement.split())[:90]}"
                        )

        self.assertGreater(checked, 15, "found no RAISE EXCEPTION to check")
        self.assertEqual(
            offenders,
            [],
            "a refusal raised without "
            f"{REQUIRED} arrives as InternalError, not IntegrityError, and "
            "every assertRefusedBy written against it fails as though the "
            "trigger were missing:\n" + "\n".join(offenders),
        )
