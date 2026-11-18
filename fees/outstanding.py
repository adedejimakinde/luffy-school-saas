"""What "outstanding" means, once, for every screen that says it. Audit finding G-12.

Four places answered "who owes, and how much" from two different sums: the
dashboard summed **this term's** entries, while the fee book, the reminders and
withholding read **the whole account**. A child with ₦20,000 unpaid from last
term who had paid this term in full owed nothing on the dashboard, ₦20,000 in
the fee book, and was reminded.

## The one meaning (decided)

**Outstanding is the whole-account balance of the children placed this term**,
summed over those whose account is owing. It is labelled "Outstanding (all
terms)" wherever it is shown, with **"of which this term"** as a smaller line.

- *Whole account*: every entry of every term, the plain sum of the signed
  column (`FeeLedgerQuerySet.balance()`'s fold); a reversal needs no clause.
- *Placed this term*: the children with a `ClassPlacement` in the term, the
  rule reminders already chose them by. A child who has left (G-16) has no
  placement in a term they did not finish, so is not counted; their account is
  still read on its own page.
- *Owing*: a balance above zero. A family in credit is not netted against one
  that owes.
- *Of which this term*: for each owing child, the part of their balance that
  this term's entries make: this term's sum, but never below nothing and never
  more than the whole balance. ₦20,000 owed from last term and this term paid
  in full is ₦20,000 outstanding, of which this term ₦0. ₦5,000 in credit from
  last term against ₦20,000 billed this term is ₦15,000 outstanding, of which
  this term ₦15,000.

## Who reads it

- the dashboard's fee card and its "needs your attention" item
  (`home.facts._MONEY` embeds `OWING_SQL` as it is, so the dashboard stays three
  statements);
- the fees list, per class and for the school (`fees.api.books()`);
- the fee book's class page (`fees.api.class_balances()`);
- fee reminders, which remind exactly the children this counts, for exactly
  this amount (`notices.reminders._batch()`).

So the four agree by construction, and `fees/tests/test_outstanding.py` holds
them to it for one school with arrears, credit and an unplaced child, and holds
the second school's figures apart.
"""

from dataclasses import dataclass

from django.db import connection

#: One row per owing child placed in the term: `(student id, class id, whole
#: balance, of which this term)`. `%(term)s` is the term; `%(class_group)s`
#: narrows to one class, or is NULL for every class.
OWING_SQL = """
SELECT o.sid, o.gid, o.total, LEAST(GREATEST(o.this_term, 0), o.total) AS of_this_term
FROM (
    SELECT p.student_membership_id AS sid, p.class_group_id AS gid,
           coalesce(sum(e.amount_kobo), 0) AS total,
           coalesce(sum(e.amount_kobo) FILTER (WHERE e.term_id = p.term_id), 0) AS this_term
    FROM academics_classplacement p
    LEFT JOIN fees_feeledgerentry e ON e.student_membership_id = p.student_membership_id
    WHERE p.term_id = %(term)s
      AND (%(class_group)s::bigint IS NULL OR p.class_group_id = %(class_group)s::bigint)
    GROUP BY p.student_membership_id, p.class_group_id, p.term_id
) o
WHERE o.total > 0
"""


@dataclass(frozen=True)
class Owing:
    student_membership_id: int
    class_group_id: int
    #: The whole account, every term. Above zero.
    kobo: int
    #: Of which this term: between nought and `kobo`.
    this_term_kobo: int


@dataclass(frozen=True)
class Outstanding:
    """The figure as every screen shows it."""

    #: Children placed this term whose account is owing.
    children: int
    #: "Outstanding (all terms)".
    kobo: int
    #: "Of which this term".
    this_term_kobo: int


def owing(term, class_group=None) -> dict:
    """`{student membership id: Owing}` for the term (and class), one query."""
    term_id = getattr(term, "pk", term)
    group_id = getattr(class_group, "pk", class_group)
    with connection.cursor() as cursor:
        cursor.execute(OWING_SQL, {"term": term_id, "class_group": group_id})
        return {
            sid: Owing(sid, gid, int(total), int(this_term))
            for sid, gid, total, this_term in cursor.fetchall()
        }


def total(rows) -> Outstanding:
    """The sum of `owing()`'s rows, or of any subset of them."""
    rows = list(rows.values() if isinstance(rows, dict) else rows)
    return Outstanding(
        children=len(rows),
        kobo=sum(r.kobo for r in rows),
        this_term_kobo=sum(r.this_term_kobo for r in rows),
    )


def by_class(rows) -> dict:
    """`{class id: Outstanding}` over `owing()`'s rows."""
    grouped = {}
    for row in (rows.values() if isinstance(rows, dict) else rows):
        grouped.setdefault(row.class_group_id, []).append(row)
    return {gid: total(group) for gid, group in grouped.items()}


__all__ = ["OWING_SQL", "Outstanding", "Owing", "by_class", "owing", "total"]
