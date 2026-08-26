"""The three-term view: a child's year, and what the school decided about it.

Everything else in this app is reckoned per **term**. This module is the one
place that is not: a Nigerian report card's last lines are the average of the
whole session and the school's decision about the child's year, and neither is
derivable from a single term.

Three kinds of function, answering to three different people:

1. **Configuration** — how this school combines its three terms, and the mark at
   which promotion is suggested. An office act, so `CONFIGURING_ROLES` is the
   principal and the administrator, matching `ratings`.
2. **Reading** — the three term lines and the session average. Staff read the
   whole thing; a parent reads a strict subset, and the difference is not
   cosmetic. See "What a parent must not see" below.
3. **Deciding** — the promotion itself, and **the principal alone**. Release is
   the principal's act, so the decision that follows it is too; the same
   reasoning task 8 settled for revisions.

## The session average, and why it is configurable

Two conventions are both real in Nigerian schools: a straight mean of the three
terms, and a weighting — most often 20/20/60, which counts the third term
heaviest because it is the one that examines the whole year. The number decides
promotions, so it cannot be hardcoded to either. `SessionSettings` holds the
choice; `EQUAL` is the default, because it is what a school that has never
thought about it means.

## A missing term renormalises. It is never a zero

A child who transferred in at second term did not score nothing in first term —
they were not there. Scoring the absence zero would invent a failing grade the
child never earned, drag the session average below the pass mark and produce a
`REPEATED` suggestion out of arithmetic rather than out of anything the child
did. So the weights of the terms actually sat are **renormalised to sum to a
hundred**, and the average is the average of the year the child had.

    configured   20 / 20 / 60
    sat          —  /  ✓ /  ✓
    applied      —  / 25 / 75

The same is true of a term the child *was* enrolled for and nobody marked, and
of a term the school never created. All three renormalise identically — but
they are recorded as three different causes, because they need three different
responses from staff. `TermAbsence` has that argument.

## What a parent must not see

Two things on this page are staff-only, and both leak the same way — by being
in the JSON even when they are off the rendered card:

- **why a term is missing.** "No marks were entered" is a fact about the
  school's filing, not about the child's year, and a parent reading it learns
  only that somebody did not do their job.
- **the promotion *suggestion*, and the gap between it and the decision.** A
  parent seeing "the system said promote, the school said repeat" is being
  handed the inside of a decision that the school made and owns. What prints is
  the decision.

Position is already under this rule for the same reason — see `positions`. The
enforcement is the same as there: exclude at the **serializer**, not merely at
the template, because a card that omits a field whose value is sitting in the
API response has not omitted it.

## Undecided is the absence of a row

There is no `UNDECIDED` status. A child nobody has decided about has no
`PromotionDecision` row, and every caller has to handle that — which is the
point: a default value would promote a whole school without anybody acting.
"""

from dataclasses import dataclass
from decimal import Decimal, localcontext

from academics.models import ClassPlacement, Term, TermName
from accounts.models import Role
from accounts.students import why_not_a_student_here

from . import positions
from .models import (
    DEFAULT_PASS_MARK,
    PromotionDecision,
    PromotionStatus,
    ReleasedSessionResult,
    SessionAveraging,
    SessionSettings,
    SheetState,
    TermAbsence,
)
from .positions import CONTEXT, round_percentage
from .services import ResultsError, school_on_this_connection


class SessionsError(ResultsError):
    """A session could not be configured, read or decided as asked.

    Subclasses `results.services.ResultsError` for `RatingsError`'s reason: this
    is one app publishing one thing, and a caller wrapping "get this class's
    results out" in `except ResultsError` should not have to know the session
    line keeps its refusals somewhere else.
    """


class NotAllowedToDecidePromotion(SessionsError):
    """The actor may not decide whether a child moves up. See `DECIDING_ROLES`."""


class NotAllowedToConfigureSessions(SessionsError):
    """The actor may not change how this school reckons a year."""


class InvalidWeighting(SessionsError):
    """The weights offered are not three numbers summing to a hundred."""


class InvalidPassMark(SessionsError):
    """The pass mark offered is not a percentage."""


class NotThisSchoolsStudent(SessionsError):
    """The membership named is not a student of the school being written to.

    Its own type here for the reason `fees`, `gradebook` and `ratings` each keep
    one: `accounts.students.why_not_a_student_here()` defines the rule and
    returns a sentence, and each app raises it in its own words and hierarchy.
    """


#: Who may change how this school reckons a year. The pair that already decides
#: what the card prints — see `ratings.CONFIGURING_ROLES`, which this matches on
#: purpose: a school's averaging convention and its trait list are the same kind
#: of act by the same people.
CONFIGURING_ROLES = frozenset({Role.PRINCIPAL.value, Role.ADMIN.value})

#: Who may decide a promotion. **The principal, and nobody else.**
#:
#: Narrower than `CONFIGURING_ROLES` above, and deliberately: configuring the
#: averaging is an office act, while deciding that a child repeats a year is the
#: act the parent will come in to argue about. It matches
#: `services.RELEASING_ROLES` rather than `SUBMITTING_ROLES` — release is the
#: principal's, and the decision that follows a release is of the same weight.
#: An administrator is excluded here even though they may configure, which is
#: the one place these two sets are meant to disagree.
DECIDING_ROLES = frozenset({Role.PRINCIPAL.value})

#: The three terms, in the order they are sat and printed. `TermName`'s
#: declaration order, not the alphabetical order of the stored values — which
#: disagrees with it ("first", "second", "third" sorts to first/second/third by
#: luck, and would stop the day a school names one differently).
TERM_ORDER = (TermName.FIRST, TermName.SECOND, TermName.THIRD)

#: Which `SessionSettings` column weights which term. A map rather than a name
#: built at runtime, for `ReportCardSettings.FIELD_FOR`'s reason: an f-string
#: column name is one nothing checks, and a term renamed in `TermName` would go
#: on reading a field that no longer exists.
#: Where each term sits in the year, for breaking ties deliberately. See
#: `_as_percentages()`.
TERM_INDEX = {name.value: index for index, name in enumerate(TERM_ORDER)}

WEIGHT_FIELD_FOR = {
    TermName.FIRST.value: "first_weight",
    TermName.SECOND.value: "second_weight",
    TermName.THIRD.value: "third_weight",
}

FULL_WEIGHT = Decimal(100)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def settings() -> SessionSettings:
    """This school's session settings. **Never writes.**

    Falls back to an **unsaved default** where the row is missing, rather than
    creating it — `ratings.settings()`'s reasoning exactly: reading a report
    card should not write to the database, and the unsaved default is a straight
    mean with a pass mark of fifty, which is the answer a school with no row
    should get anyway. Migration `0013` seeds the row for every schema; this is
    what holds if a schema is ever created around it.
    """
    return SessionSettings.objects.filter(pk=1).first() or SessionSettings()


def _require_a_weighting(first, second, third):
    """Three numbers summing to a hundred, or this module's own refusal.

    The database refuses it too — `weights_sum_to_one_hundred` — and both are
    needed for the reason every paired guard in this app is: the constraint
    catches the import and the `psql` session, and this turns the refusal into
    a sentence naming the total the school actually typed. A school that enters
    20/20/50 has made one typo, and every session average it produces is wrong
    in a way nobody notices, because the numbers all still look like
    percentages.
    """
    try:
        weights = [Decimal(str(value)) for value in (first, second, third)]
    except (TypeError, ValueError, ArithmeticError):
        raise InvalidWeighting(
            f"A weighting is three numbers. Got {first!r}, {second!r}, {third!r}."
        ) from None

    if any(weight < 0 for weight in weights):
        raise InvalidWeighting(
            f"A weight cannot be negative. Got {weights[0]}/{weights[1]}/{weights[2]}."
        )

    total = sum(weights)
    if total != FULL_WEIGHT:
        raise InvalidWeighting(
            f"A weighting has to add up to 100. "
            f"{weights[0]}/{weights[1]}/{weights[2]} adds up to {total}."
        )
    return weights


def _the_settings_row() -> SessionSettings:
    """The row itself, created if this is the first time anybody set anything."""
    row, _ = SessionSettings.objects.get_or_create(pk=1)
    return row


def use_a_straight_mean() -> SessionSettings:
    """Average the terms the child sat, equally. Returns the settings row.

    Clears the weights rather than leaving them where they were. A 20/20/60
    sitting in a row whose mode says `EQUAL` is a field that lies to the next
    reader — it looks like configuration and nothing reads it — and the database
    refuses that combination anyway.
    """
    row = _the_settings_row()
    row.averaging = SessionAveraging.EQUAL
    row.first_weight = row.second_weight = row.third_weight = None
    row.save(
        update_fields=[
            "averaging",
            "first_weight",
            "second_weight",
            "third_weight",
            "updated_at",
        ]
    )
    return row


def use_a_weighting(first, second, third) -> SessionSettings:
    """Weight the three terms, for example 20/20/60. Returns the settings row."""
    first, second, third = _require_a_weighting(first, second, third)
    row = _the_settings_row()
    row.averaging = SessionAveraging.WEIGHTED
    row.first_weight, row.second_weight, row.third_weight = first, second, third
    row.save(
        update_fields=[
            "averaging",
            "first_weight",
            "second_weight",
            "third_weight",
            "updated_at",
        ]
    )
    return row


def set_pass_mark(mark) -> SessionSettings:
    """The average at which promotion is *suggested*. Returns the settings row."""
    try:
        mark = Decimal(str(mark))
    except (TypeError, ValueError, ArithmeticError):
        raise InvalidPassMark(f"A pass mark is a percentage. Got {mark!r}.") from None
    if not (0 <= mark <= FULL_WEIGHT):
        raise InvalidPassMark(f"A pass mark is between 0 and 100. Got {mark}.")

    row = _the_settings_row()
    row.pass_mark = mark
    row.save(update_fields=["pass_mark", "updated_at"])
    return row


# ---------------------------------------------------------------------------
# Reading: the three terms, and the year they add up to
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TermLine:
    """One term of a child's session, present or accounted for.

    `average` and `absence` are the two halves of one answer and are never both
    set: a term either contributed a number or says why it did not. The frozen
    table keeps the same pair under a check constraint.
    """

    term_name: str
    term_id: int | None
    average: Decimal | None
    #: A `TermAbsence` value, or `""` when the term contributed.
    absence: str = ""

    @property
    def was_sat(self) -> bool:
        return self.average is not None


@dataclass(frozen=True)
class SessionLine:
    """A child's whole year: three terms, the weighting applied, the average.

    `average` is `None` when no term contributed — a child with no marks at all
    that session, or one whose only terms carry zero weight under the school's
    configuration. A card prints a blank there, which is the honest rendering
    and the reason nothing defaults it to zero.

    `weights` holds only the terms that contributed, keyed by term name, and
    sums to a hundred. It is the weighting **as applied** — renormalised over
    the terms actually sat — and not the school's configured pair.
    """

    session: str
    terms: tuple[TermLine, ...]
    average: Decimal | None
    averaging: str
    weights: dict[str, Decimal]

    def weight_for(self, term_name) -> Decimal | None:
        return self.weights.get(str(term_name))


def _terms_of(session) -> dict[str, Term]:
    """This school's rows for that session, keyed by term name.

    A session is three terms and there is no session row to point at, which is
    why `Term.session` is a string — see the model. A school part-way through
    the year has one or two of these, and a missing one is `NO_TERM` rather than
    an error: reading a session in progress is the ordinary case.
    """
    return {term.name: term for term in Term.objects.filter(session=session)}


def _lines_for(student_ids, session) -> dict[int, tuple[TermLine, ...]]:
    """Every named child's three term lines. Batched, because release calls it.

    **The query count is per (term, class group), not per child.** The obvious
    implementation asks `positions.overall_percentages()` once per child per
    term, and `overall_percentages()` builds a whole class's broadsheet — so
    freezing a class of forty-five would compute a hundred and thirty-five
    broadsheets to read forty-five numbers off them. Here each term does one
    placement query and then one broadsheet per distinct class group those
    children sat in, which for an ordinary class is one.

    That the children of *one* sheet may sit in several class groups across the
    session is not an edge case — it is the mid-session transfer this whole
    module renormalises for.
    """
    lines = {student_id: {} for student_id in student_ids}
    terms = _terms_of(session)

    for term_name in TERM_ORDER:
        name = term_name.value
        term = terms.get(name)

        if term is None:
            for student_id in student_ids:
                lines[student_id][name] = TermLine(name, None, None, TermAbsence.NO_TERM)
            continue

        placements = {
            placement.student_membership_id: placement
            for placement in ClassPlacement.objects.filter(
                term=term, student_membership_id__in=student_ids
            ).select_related("class_group")
        }

        # One broadsheet per class group any of these children sat in that term.
        percentages = {}
        for placement in placements.values():
            if placement.class_group_id not in percentages:
                percentages[placement.class_group_id] = positions.overall_percentages(
                    placement.class_group, term
                )

        for student_id in student_ids:
            placement = placements.get(student_id)
            if placement is None:
                lines[student_id][name] = TermLine(
                    name, term.pk, None, TermAbsence.NOT_ENROLLED
                )
                continue

            average = percentages[placement.class_group_id].get(student_id)
            if average is None:
                # Placed, and nobody entered a mark. Same arithmetic as a
                # transfer and a different thing to tell staff about.
                lines[student_id][name] = TermLine(
                    name, term.pk, None, TermAbsence.UNMARKED
                )
                continue

            lines[student_id][name] = TermLine(name, term.pk, average)

    return {
        student_id: tuple(by_name[term.value] for term in TERM_ORDER)
        for student_id, by_name in lines.items()
    }


def _applied_weights(sat, config) -> dict[str, Decimal]:
    """Renormalise the school's weighting over the terms actually sat.

    Returns the raw (unnormalised) weights, keyed by term name, for the terms
    that contributed. Empty when nothing can be weighed — which is either "no
    term contributed" or the reachable oddity below.

    **A weighting may legitimately give a term zero.** `0/0/100` is a school
    that counts the third term alone, and `_require_a_weighting()` allows it
    because it sums to a hundred. A child who sat only the first two terms of
    such a session therefore has a total weight of zero, and there is nothing to
    renormalise: no proportion of nothing is a hundred. That child has no
    session average, which is the truthful answer — the school has said those
    terms count for nothing — and it leaves the promotion suggestion blank so a
    person has to decide rather than the arithmetic inventing a `REPEATED`.
    """
    if config.averaging == SessionAveraging.EQUAL:
        raw = {line.term_name: Decimal(1) for line in sat}
    else:
        raw = {
            line.term_name: getattr(config, WEIGHT_FIELD_FOR[line.term_name])
            or Decimal(0)
            for line in sat
        }
    return {} if sum(raw.values()) <= 0 else raw


def _as_percentages(raw) -> dict[str, Decimal]:
    """The applied weighting, rounded to two places and summing to exactly 100.

    Rounding each share independently does not sum to a hundred — a straight
    mean of three terms is 33.33 three times, which is 99.99 — and a stored
    weighting that does not add up is one every reader has to explain away. So
    the rounding drift is handed to the largest remainders, which is the
    standard apportionment rule and the one that moves each share by at most a
    hundredth.

    **The session average is not computed from these.** It is computed from the
    exact ratios and rounded once, so a straight mean stays a true third each
    rather than becoming the mean of 33.33/33.33/33.34. These exist to record
    *the weighting*, which is what the school must not be able to change after
    the fact; `ReleasedSessionResult` says the same thing from the other side.
    """
    total = sum(raw.values())
    with localcontext(CONTEXT):
        exact = {name: weight * FULL_WEIGHT / total for name, weight in raw.items()}
    shares = {name: round_percentage(value) for name, value in exact.items()}

    step = Decimal("0.01")
    drift = FULL_WEIGHT - sum(shares.values())
    steps = int((drift / step).to_integral_value())
    if steps:
        # Biggest leftover first when handing hundredths out, smallest first
        # when taking them back, so the share moved is always the one with the
        # weakest claim to its current value.
        #
        # **The tie is broken on the term, and it had to be broken on
        # something.** A straight mean gives all three terms an identical
        # remainder, so the sort is entirely ties and a stable sort would hand
        # the odd hundredth to whichever term happened to be inserted first —
        # a number on a school's screen decided by dictionary order. Later
        # terms win it instead: every weighting a Nigerian school actually uses
        # counts the third term heaviest, so the end of the year is the least
        # surprising place for a spare hundredth to land.
        order = sorted(
            shares,
            key=lambda name: (exact[name] - shares[name], TERM_INDEX[name]),
            reverse=steps > 0,
        )
        for index in range(abs(steps)):
            name = order[index % len(order)]
            shares[name] += step if steps > 0 else -step
    return shares


def _weigh(terms, config, session) -> SessionLine:
    """Combine the term lines into a session line under this configuration."""
    sat = [line for line in terms if line.was_sat]
    raw = _applied_weights(sat, config)

    if not raw:
        return SessionLine(session, tuple(terms), None, config.averaging, {})

    total = sum(raw.values())
    with localcontext(CONTEXT):
        weighted = sum(line.average * raw[line.term_name] for line in sat)
        average = round_percentage(weighted / total)

    return SessionLine(
        session, tuple(terms), average, config.averaging, _as_percentages(raw)
    )


def session_line(membership, session, *, config=None) -> SessionLine:
    """One child's year as it stands **right now**, computed from live rows.

    The read every staff screen wants, and the one a card must *not* use once
    the third term has been released — `released_session_line()` is that, and
    `card_session_line()` picks between them the way `ratings.card_sections()`
    does.

    `config` is accepted so a caller freezing a whole class reads the settings
    row once rather than once per child.
    """
    student_id = getattr(membership, "pk", membership)
    terms = _lines_for([student_id], session)[student_id]
    return _weigh(terms, config or settings(), session)


# ---------------------------------------------------------------------------
# The freeze
# ---------------------------------------------------------------------------


def freeze_for_release(sheet) -> int:
    """Copy this class's session lines as they read now. Returns rows written.

    Called by `results.services.release()` **inside the transaction that writes
    the release row**, alongside `ratings.freeze_for_release()` and
    `comments.freeze_for_release()`, so a sheet that says `released` has the
    whole card behind it rather than part of one.

    **Third term only, and silent otherwise.** A session average is not a thing
    until the year it averages is over: freezing one at first-term release would
    write a number that is the first term's average wearing a session's name,
    and it would then be frozen — unfixable except by revision — while the year
    was still being taught. So first and second term releases write nothing here
    and the card prints no session line, which is what a real first-term card
    looks like.

    Writes a row for **every child on the roster**, including those with nothing
    to average: the child who transferred in for third term alone still has a
    session line, and it says so. `TermAbsence` is what it says it with. That is
    the same rule `ratings.freeze_for_release()` follows in writing a row for
    every visible trait including the ones nobody rated — what is being frozen
    is the *line*, and "there was nothing here" is a thing the line has to be
    able to go on saying.
    """
    if sheet.term.name != TermName.THIRD:
        return 0

    roster = positions.roster_ids(sheet.class_group, sheet.term)
    if not roster:
        return 0

    config = settings()
    session = sheet.term.session
    lines = _lines_for(roster, session)

    rows = []
    for student_id in roster:
        line = _weigh(lines[student_id], config, session)
        columns = {}
        for term in TERM_ORDER:
            name = term.value
            term_line = next(t for t in line.terms if t.term_name == name)
            columns[f"{name}_average"] = term_line.average
            columns[f"{name}_absence"] = term_line.absence
            columns[f"{name}_weight_used"] = line.weights.get(name)
        rows.append(
            ReleasedSessionResult(
                sheet=sheet,
                student_membership_id=student_id,
                session=session,
                averaging=line.averaging,
                session_average=line.average,
                **columns,
            )
        )

    ReleasedSessionResult.objects.bulk_create(rows)
    return len(rows)


def released_session_line(membership, session) -> ReleasedSessionResult | None:
    """The frozen row for this child's session, or `None` if none was written.

    **The earliest one, and there can be more than one.** The tempting claim is
    that at most one exists — `freeze_for_release()` writes a row per child on
    the third term's roster, and `ClassPlacement` allows a child one group per
    term, so a child is on exactly one roster. That is true at any *instant* and
    not true over time:

        JSS 1A releases its third term   -> the child is frozen here
        the child is moved to JSS 3B     -> the placement row is rewritten
        JSS 3B releases its third term   -> the child is on that roster too

    Both rows are real records of two releases that happened, and the table is
    append-only, so neither is deleted. What has to be decided is which one is
    *the card*, and it is the first: a released card keeps saying what it said,
    and the second release cannot reach backwards into a card already in a
    parent's hand. The same rule `0010`, `0011` and issue #27's mark guard turn
    on — a guard on a released artefact keys off the artefact, and the artefact
    here is the release that happened first.

    Ordered explicitly on `created_at` and then `id`, never left to
    `Meta.ordering`: the tie-break matters for the same reason it does on
    `PromotionDecision`, and a "which card is this" that resolves arbitrarily
    between two rows is one that changes when nothing changed.
    """
    return (
        ReleasedSessionResult.objects.filter(
            session=session, student_membership_id=getattr(membership, "pk", membership)
        )
        .order_by("created_at", "id")
        .first()
    )


def _as_session_line(frozen) -> SessionLine:
    """A frozen row, read back in the shape the live computation returns.

    So that a caller rendering a session line does not have to know which side
    of a release it is on — the same service `ratings.card_sections()` performs
    for the conduct section.
    """
    terms, weights = [], {}
    for term in TERM_ORDER:
        name = term.value
        average = getattr(frozen, f"{name}_average")
        terms.append(
            TermLine(name, None, average, getattr(frozen, f"{name}_absence"))
        )
        weight = getattr(frozen, f"{name}_weight_used")
        if weight is not None:
            weights[name] = weight
    return SessionLine(
        frozen.session, tuple(terms), frozen.session_average, frozen.averaging, weights
    )


def card_session_line(membership, session) -> SessionLine:
    """The session line as the card shows it: frozen if released, live if not.

    The one function a renderer should call. Reading the freeze when it exists
    is not an optimisation — it is the whole guarantee. A released card's last
    line has to go on saying what it said, and everything the live computation
    reads through (the school's weighting, a first term's marks, a placement)
    is a row somebody may legitimately change afterwards.
    """
    frozen = released_session_line(membership, session)
    return _as_session_line(frozen) if frozen else session_line(membership, session)


# ---------------------------------------------------------------------------
# Promotion: a suggestion, and a decision that is nobody's but a person's
# ---------------------------------------------------------------------------


def suggested_status(average, *, config=None) -> str | None:
    """What the arithmetic proposes for this average. `None` when it proposes nothing.

    **Two outcomes only, and never the interesting ones.** A pass mark can
    separate `PROMOTED` from `REPEATED` and cannot reach `ON_TRIAL` or
    `WITHDRAWN`: the first is a judgement about a child who fell short and is
    worth carrying anyway, and the second is not an academic outcome at all.
    Both are things a school knows and a threshold cannot, which is the whole
    reason this returns a *suggestion* and something else records the decision.

    `None` for a child with no session average — a child who sat no term of this
    session with a mark in it. There is nothing to compare to a pass mark, and
    guessing `REPEATED` from an absence of data is exactly the arithmetic-driven
    failure this module refuses everywhere else.
    """
    if average is None:
        return None
    config = config or settings()
    return (
        PromotionStatus.PROMOTED
        if average >= config.pass_mark
        else PromotionStatus.REPEATED
    ).value


def _require_student_of_this_school(membership):
    """The school is read off the connection, not passed in. See that function.

    A school handed in as an argument is a second opinion that can disagree
    with the `search_path` the row is about to land in — and when it disagrees,
    the decision is checked against one school and written into another's
    tables.
    """
    refusal = why_not_a_student_here(
        membership, subject="a promotion decision", holder="results"
    )
    if refusal:
        raise NotThisSchoolsStudent(refusal)
    return membership


def _require_a_status(status) -> str:
    """One of the four, and never a defaulted one.

    `PromotionStatus` has no `UNDECIDED` member and this refuses anything
    outside the four for the same reason: undecided is the absence of a row, and
    a caller passing something falsy is asking to record a decision that is not
    one.
    """
    try:
        return PromotionStatus(status).value
    except ValueError:
        raise SessionsError(
            f"{status!r} is not a promotion outcome. It is one of: "
            f"{', '.join(choice.value for choice in PromotionStatus)}."
        ) from None


def promotion_of(membership, session) -> PromotionDecision | None:
    """This child's promotion decision for that session, or `None` if undecided.

    The **latest** row, because a principal who changes their mind writes a
    second one and both stand. `Meta.ordering` puts newest first and breaks the
    timestamp tie on `-id`, which is not decoration: `decided_at` is
    `auto_now_add`, two decisions recorded in one request can share it to the
    microsecond, and a promotion status that resolves arbitrarily between two
    rows is one that changes when nothing changed.

    `None` is a real answer and not a missing one. Nothing here defaults it,
    and no caller should: a child nobody has decided about has not been
    promoted.
    """
    return PromotionDecision.objects.filter(
        student_membership_id=getattr(membership, "pk", membership), session=session
    ).first()


def decide(membership, session, status, *, note="", by=None) -> PromotionDecision:
    """Record what the school decided about a child's year. Returns the row.

    Always an insert. A principal changing their mind writes a second row and
    both stand — `PromotionDecision` refuses an update in `save()` and again in
    the database, and `promotion_of()` reads the latest.

    **The suggestion is computed here and frozen into the row**, together with
    the session average and the pass mark that produced it. Not recomputed on
    read, and the reason is the whole point of keeping it: the gap between
    `suggested` and `status` is the record that a person went against the
    arithmetic, and a suggestion recomputed under a weighting the school changed
    afterwards would make the same row read as agreement or override depending
    on when it was asked — inventing overrides no principal ever performed, on
    precisely the rows kept to prove who decided what.

    **The average comes from the freeze when there is one.** A released card's
    session line is what the parent is holding, so a decision recorded after
    release has to be a decision about that number rather than about a live
    recomputation of it that may already have moved.
    """
    _require_student_of_this_school(membership)
    status = _require_a_status(status)
    config = settings()

    line = card_session_line(membership, session)
    suggested = suggested_status(line.average, config=config)

    # No `atomic()` here, and deliberately: this is a single INSERT, which is
    # already atomic, and there is no read-then-write to hold together. The
    # suggestion was computed above from a frozen row or a live one, and two
    # principals deciding at once is not a race to be locked out — it is two
    # rows, both real, the later of which holds.
    return PromotionDecision.objects.create(
        student_membership_id=membership.pk,
        session=session,
        status=status,
        # Blank, not null: the column is a `CharField` with choices, and
        # `a_suggestion_carries_what_produced_it` ties the three together.
        suggested=suggested or "",
        session_average=line.average if suggested else None,
        pass_mark_used=config.pass_mark if suggested else None,
        note=note,
        decided_by_id=getattr(by, "pk", by),
    )


# ---------------------------------------------------------------------------
# Actor-checked entry points.
# ---------------------------------------------------------------------------


def can_decide_promotions(actor, school) -> bool:
    if not getattr(actor, "is_authenticated", False):
        return False
    return bool(set(actor.roles_at(school)) & DECIDING_ROLES)


def can_configure_sessions(actor, school) -> bool:
    if not getattr(actor, "is_authenticated", False):
        return False
    return bool(set(actor.roles_at(school)) & CONFIGURING_ROLES)


def _require_configuring_authority(actor):
    school = school_on_this_connection()
    if not can_configure_sessions(actor, school):
        raise NotAllowedToConfigureSessions(
            f"{actor} may not change how {school} reckons a session. The "
            f"averaging and the pass mark are set by a principal or an "
            f"administrator of the school."
        )
    return school


def _require_deciding_authority(actor):
    """The principal, and not the administrator who may configure the averaging.

    The one place `CONFIGURING_ROLES` and `DECIDING_ROLES` are meant to
    disagree. Setting a school's weighting is an office act; telling a family
    their child repeats the year is the act they will come in to argue about,
    and it belongs to the person who released the results.
    """
    school = school_on_this_connection()
    if not getattr(actor, "is_authenticated", False):
        raise NotAllowedToDecidePromotion(
            "Signing in is required to decide a promotion."
        )
    if not can_decide_promotions(actor, school):
        raise NotAllowedToDecidePromotion(
            f"{actor} may not decide promotions at {school}. Whether a child "
            f"moves up is the principal's decision."
        )
    return school


def decide_as(actor, membership, session, status, *, note="") -> PromotionDecision:
    """`decide()` for a caller with a request behind it."""
    _require_deciding_authority(actor)
    return decide(membership, session, status, note=note, by=actor)


def use_a_straight_mean_as(actor) -> SessionSettings:
    _require_configuring_authority(actor)
    return use_a_straight_mean()


def use_a_weighting_as(actor, first, second, third) -> SessionSettings:
    _require_configuring_authority(actor)
    return use_a_weighting(first, second, third)


def set_pass_mark_as(actor, mark) -> SessionSettings:
    _require_configuring_authority(actor)
    return set_pass_mark(mark)


__all__ = [
    "CONFIGURING_ROLES",
    "DECIDING_ROLES",
    "TERM_ORDER",
    "InvalidPassMark",
    "InvalidWeighting",
    "NotAllowedToConfigureSessions",
    "NotAllowedToDecidePromotion",
    "NotThisSchoolsStudent",
    "SessionLine",
    "SessionsError",
    "TermLine",
    "can_configure_sessions",
    "can_decide_promotions",
    "card_session_line",
    "decide",
    "decide_as",
    "freeze_for_release",
    "promotion_of",
    "released_session_line",
    "session_line",
    "set_pass_mark",
    "set_pass_mark_as",
    "settings",
    "suggested_status",
    "use_a_straight_mean",
    "use_a_straight_mean_as",
    "use_a_weighting",
    "use_a_weighting_as",
]
