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

**A released card is not yet protected from a scale change.** The protection is
the copy task 3's snapshot will take at release, and it does not exist here —
`set_scale()` has that written out rather than implied.

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

#: What the columns hold. Read off the fields so the refusals below and the
#: table agree about one number — `ratings.MAX_TRAIT_NAME`'s reason exactly: a
#: service that leaves a width to the column hands the caller a raw `DataError`
#: from inside its own `atomic()`, which is outside `ResultsError`, missed by
#: every `except ResultsError`, and fatal to the enclosing transaction.
MAX_LETTER = GradeBand._meta.get_field("letter").max_length
MAX_REMARK = GradeBand._meta.get_field("remark").max_length

#: The precision `GradeBand.minimum` actually stores. Two bands offered as
#: 49.996 and 50.001 are one band once the column has rounded them, so the
#: duplicate check has to compare what will be *stored* rather than what was
#: typed — otherwise the refusal arrives as an `IntegrityError` from the insert.
PLACES = Decimal(10) ** -GradeBand._meta.get_field("minimum").decimal_places


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
    once rather than once per subject line. **It may be in any order.** The
    obvious implementation walks the list and returns the first band at or below
    the mark, which is correct only for a highest-first list — and `bands` is a
    public parameter, so a caller passing `order_by("minimum")` or a hand-built
    list would get the *lowest* band for every mark. Every child on the page
    graded F, no exception, nothing to notice. Taking the greatest qualifying
    minimum instead is the same cost and cannot be held wrong.
    """
    if percentage is None:
        return None
    qualifying = [
        band
        for band in (bands if bands is not None else scale())
        if percentage >= band.minimum
    ]
    return max(qualifying, key=lambda band: band.minimum, default=None)


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
            minimum = Decimal(str(minimum)).quantize(PLACES)
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
        if len(letter) > MAX_LETTER:
            raise InvalidGradeScale(
                f"A grade letter fits {MAX_LETTER} characters and {letter!r} is "
                f"{len(letter)}. A band is labelled, not described — the words go "
                f"in the remark."
            )

        remark = str(remark or "").strip()
        if len(remark) > MAX_REMARK:
            raise InvalidGradeScale(
                f"A remark fits {MAX_REMARK} characters and {letter!r}'s is "
                f"{len(remark)}."
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
        cleaned.append((minimum, letter, remark))

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
    produces a scale nobody asked for.

    ## Nothing points at a band yet, and released cards are **not** protected yet

    `GradeBand` is deliberately not the target of any foreign key, so that task
    3's snapshot can **copy** the letter and remark at release the way
    `ReleasedTraitRating` copies a trait's name.

    Until that snapshot exists, this is a plan and not a guarantee, and it is
    written as one on purpose: there is no released-grade table, nothing in the
    repo calls `grade_for()`, and `set_scale()` deletes every band with no check
    for released usage. **The moment a renderer grades a frozen percentage
    live, replacing the scale silently rewrites the letters on cards already in
    parents' hands** — precisely the failure `ReleasedTraitRating`'s docstring
    table enumerates for trait names. Task 3 closes it by copying; anything
    reaching for `grade_for()` before then is reaching past a hole.
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
