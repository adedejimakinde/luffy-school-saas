"""The grading scale: what letter a percentage prints as.

School configuration, the same class of thing as `ratings`' trait list — a
school edits its scale without a deploy, and the letter is printed on a card a
parent keeps. `GradeBand` carries the argument for the shape; this module is
the two things done to it: reading a grade, and replacing the scale.

## Two functions, and only one of them writes

`grade_for()` is on the read path of every subject line of every card, and it
**never writes**. `scale()` likewise. The one writer, `set_scale()`, replaces
the whole scale in a transaction — see below for why it is wholesale rather
than per band.

## Why the scale is replaced whole

A band records where it *starts*, so the bands are only meaningful as a set:
deleting one silently widens the one below it, and adding one silently narrows
it. Neither is wrong — it is what the school asked for — but both mean "edit one
band" is really "change the scale", and an API that pretends otherwise invites a
school to remove a band and not notice that a different band now covers the
marks it used to.

Replacing the lot also puts the one invariant that is a fact about the *table*
rather than about a row in exactly one place: **a scale starts at nought.**
Without that, a mark below the lowest band has no grade, and the card prints a
blank where a letter belongs — which looks identical to a subject nobody marked.

## `None` is a real answer

`grade_for(None)` is `None`: an unmarked subject has no percentage, so there is
no grade, and the card prints the line blank. That is the same rule
`positions._percentage()` and `TermLine.average` already keep — not marked is
not zero, and it is not an F either.
"""

from decimal import Decimal, InvalidOperation

from accounts.models import Role
from django.db import transaction

from .models import GradeBand
from .services import ResultsError, school_on_this_connection


class GradesError(ResultsError):
    """A grading scale could not be read or set as asked.

    Subclasses `results.services.ResultsError` for `SessionsError`'s reason:
    one app publishes one thing, and a caller wrapping "get this class's
    results out" in `except ResultsError` should not have to know the grading
    scale keeps its refusals somewhere else.
    """


class NotAllowedToConfigureGrades(GradesError):
    """The actor may not change what letter a mark earns. See `CONFIGURING_ROLES`."""


class InvalidGradeScale(GradesError):
    """The scale offered is not a set of bands that covers every mark."""


#: Who may change the scale. The pair that already decides what the card prints
#: — matching `ratings.CONFIGURING_ROLES` and `sessions.CONFIGURING_ROLES` on
#: purpose: a school's grading scale, its trait list and its averaging
#: convention are the same kind of act by the same people.
CONFIGURING_ROLES = frozenset({Role.PRINCIPAL.value, Role.ADMIN.value})

#: Where a scale has to start. Not a style choice: a mark below the lowest band
#: has no grade, and a blank where a letter belongs is indistinguishable on the
#: page from a subject nobody marked.
BOTTOM = Decimal(0)

FULL_MARKS = Decimal(100)


def scale() -> list[GradeBand]:
    """This school's bands, highest first. **Never writes.**

    A list rather than a queryset, because every caller iterates it more than
    once — `grade_for()` walks it, and a card renders the key beside the marks —
    and a queryset re-queried per subject line is the shape this codebase keeps
    having to unwind.
    """
    return list(GradeBand.objects.all())


def grade_for(percentage, *, bands=None) -> GradeBand | None:
    """The band a percentage earns, or `None` if it earns none.

    `None` for `None`: an unmarked subject has no grade, and the card prints the
    line blank. Not an F — that would be the same lie as ranking an unmarked
    child last.

    `None` also for a mark below the lowest band, which `set_scale()` prevents
    and this does not assume: a scale seeded before that guard existed, or one
    edited row by row in `psql`, can leave a hole, and a card printing a blank
    grade is a better answer than an exception thrown while a parent waits.

    `bands` is accepted so a caller rendering forty-five cards reads the scale
    once rather than once per subject line.
    """
    if percentage is None:
        return None
    for band in bands if bands is not None else scale():
        if percentage >= band.minimum:
            return band
    return None


def _require_a_scale(bands):
    """A list of `(minimum, letter, remark)`, covering every mark, or a refusal.

    Every check here is also a database constraint except the last, and that is
    the point of the division: the constraints catch the import and the `psql`
    session one row at a time, and this turns the refusal into a sentence about
    the *scale*, which is the thing the school actually typed.

    The coverage check is the one with nowhere else to live. "Is there a band at
    nought?" is a fact about the table, and a row-level `CHECK` cannot see
    another row.
    """
    if not bands:
        raise InvalidGradeScale(
            "A grading scale needs at least one band. An empty scale prints no "
            "letter on any card."
        )

    cleaned, seen_minima, seen_letters = [], set(), set()
    for band in bands:
        try:
            minimum, letter, remark = band
        except (TypeError, ValueError):
            raise InvalidGradeScale(
                f"A band is (minimum, letter, remark). Got {band!r}."
            ) from None

        try:
            minimum = Decimal(str(minimum))
        except (TypeError, ValueError, ArithmeticError, InvalidOperation):
            raise InvalidGradeScale(
                f"A band starts at a percentage. Got {minimum!r} for {letter!r}."
            ) from None

        if not (BOTTOM <= minimum <= FULL_MARKS):
            raise InvalidGradeScale(
                f"A band starts between 0 and 100. {letter!r} starts at {minimum}."
            )

        letter = str(letter).strip()
        if not letter:
            raise InvalidGradeScale(
                f"A band needs a letter. The one starting at {minimum} has none."
            )

        if minimum in seen_minima:
            raise InvalidGradeScale(
                f"Two bands start at {minimum}. A mark can only earn one grade."
            )
        if letter in seen_letters:
            raise InvalidGradeScale(
                f"The letter {letter!r} is used twice. A scale that prints one "
                f"letter for two bands is one a parent cannot read."
            )
        seen_minima.add(minimum)
        seen_letters.add(letter)
        cleaned.append((minimum, letter, str(remark or "").strip()))

    if BOTTOM not in seen_minima:
        lowest = min(seen_minima)
        raise InvalidGradeScale(
            f"A grading scale has to start at 0. This one starts at {lowest}, so "
            f"a mark below {lowest} would earn no grade at all and print blank — "
            f"which on a card is indistinguishable from a subject nobody marked."
        )

    cleaned.sort(key=lambda band: band[0], reverse=True)
    return cleaned


def set_scale(bands) -> list[GradeBand]:
    """Replace this school's scale with these bands. Returns them, highest first.

    Wholesale and in one transaction, for the reason in the module docstring: a
    band records where it starts, so the bands mean something only as a set, and
    "delete one band" silently rewrites the meaning of another.

    **The rows are new rows.** Nothing tries to match an offered band to an
    existing one and update it in place: there is no stable identity to match on
    — a school moving "B2" from 70 to 72 has edited a band, and a school
    replacing "B2 at 70" with "B at 70" has replaced one — and guessing which
    produces a scale nobody asked for. `GradeBand` is not referenced by a
    foreign key anywhere, deliberately: what a card prints is the letter and the
    remark **copied** at release, exactly as `ReleasedTraitRating` copies a
    trait's name, so replacing the scale cannot reach a card that has gone home.
    """
    cleaned = _require_a_scale(bands)
    with transaction.atomic():
        GradeBand.objects.all().delete()
        GradeBand.objects.bulk_create(
            [
                GradeBand(minimum=minimum, letter=letter, remark=remark)
                for minimum, letter, remark in cleaned
            ]
        )
    return scale()


# ---------------------------------------------------------------------------
# Actor-checked entry points.
# ---------------------------------------------------------------------------


def can_configure_grades(actor, school) -> bool:
    if not getattr(actor, "is_authenticated", False):
        return False
    return bool(set(actor.roles_at(school)) & CONFIGURING_ROLES)


def _require_configuring_authority(actor):
    school = school_on_this_connection()
    if not getattr(actor, "is_authenticated", False):
        raise NotAllowedToConfigureGrades(
            "Signing in is required to change a grading scale."
        )
    if not can_configure_grades(actor, school):
        raise NotAllowedToConfigureGrades(
            f"{actor} may not change how {school} grades a mark. The scale is "
            f"set by a principal or an administrator of the school."
        )
    return school


def set_scale_as(actor, bands) -> list[GradeBand]:
    """`set_scale()` for a caller with a request behind it."""
    _require_configuring_authority(actor)
    return set_scale(bands)


__all__ = [
    "BOTTOM",
    "CONFIGURING_ROLES",
    "GradesError",
    "InvalidGradeScale",
    "NotAllowedToConfigureGrades",
    "can_configure_grades",
    "grade_for",
    "scale",
    "set_scale",
    "set_scale_as",
]
