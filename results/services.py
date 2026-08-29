"""Moving a result sheet along the chain. The only supported way to write one.

Five acts: submit, check, approve, release, and send back. Each is its own
function because each is a different decision by a different person, and a
single `transition(to=...)` would have made the authority table a lookup that
every caller could get wrong.

Every one of them does the same four things in the same order, and the order is
the security-relevant part:

1. **Check who is asking**, at the school on the connection — *before* anything
   is read or locked. `gradebook.api`'s `ExistenceOracleTests` settled this for
   the codebase: a caller who may not act should not be able to tell a sheet
   that exists from one that does not by which refusal comes back. It also
   keeps somebody with no authority from holding a row lock at all.
2. **Take the row lock.** `select_for_update()` on the sheet. Two people
   pressing approve at the same instant would otherwise both read `checked`,
   both find the move legal, and both write.

   What the lock buys was measured rather than assumed, and it is narrower than
   it sounds: `one_transition_to_each_state_per_cycle` already refuses the
   second row, so an unlocked race does **not** corrupt the audit. The lock is
   what makes the loser receive a `WrongState` naming where the sheet got to,
   instead of an unhandled `IntegrityError` — a 500 on a principal's screen
   saying nothing. See `tests/test_approval_concurrency.py` for the control run.
3. **Check the state under that lock**, never the state on the instance the
   caller passed in — that one was read at some earlier moment and can have
   moved since.
4. **Check they have not already signed this pass** — the same-signatory rule,
   also under the lock.

Then the row is written and the sheet is updated inside one transaction, so a
sheet whose state says `approved` always has a row saying who approved it.

`open_sheet()` is the sixth function and the only one that is not a signature.
It still takes an actor and still checks authority first, and the reason is the
paragraph below rather than anything about opening a sheet: a claim that a
module has no actor-less primitives is falsified by one, and it was exported.

The `_as()` split the other service modules use is deliberately *absent* here.
There are no primitives: every act in this module is somebody's signature, so
there is no version of it that makes sense without an actor. A data migration
that wants to move a sheet has to name the person it is moving it on behalf of,
which is the right amount of friction for rewriting an approval chain.

Authority is always asked at the school **on the connection**, and the portal is
refused rather than treated as a school — see `school_on_this_connection()`,
which is where that used to raise `School.DoesNotExist` out of the module's own
exception hierarchy.
"""

from collections.abc import Iterable

from django.db import connection, transaction
from django_tenants.utils import get_public_schema_name

from academics import services as academics
from accounts.models import ACCESS_STATUSES, Membership, Role

from .models import (
    ADVANCING_STATES,
    SENDABLE_BACK_FROM,
    ResultSheet,
    ResultSheetTransition,
    SheetState,
)


class ResultsError(Exception):
    """A sheet could not be moved as asked.

    One base class for the module, as `fees.services.FeeLedgerError` and
    `gradebook.services.GradebookError` are for theirs.
    """


class NotAllowedToActOnResults(ResultsError):
    """The actor holds no role at this school that may take this step."""


class WrongState(ResultsError):
    """The sheet is not where it would have to be for this step.

    Carries `state` — where it actually is — so a caller can say what happened
    rather than only that something did. That matters most when the answer is
    "somebody else already approved it while you were reading".
    """

    def __init__(self, message, state=None):
        super().__init__(message)
        self.state = state


class AlreadySignedThisCycle(ResultsError):
    """This person has already taken a step on this pass through the chain.

    The separation-of-duties refusal. Carries the transition they already made,
    so the refusal can name it: "you submitted this sheet" is a far more useful
    sentence than "you may not check it".
    """

    def __init__(self, message, existing=None):
        super().__init__(message)
        self.existing = existing


class ReleaseIsFinal(ResultsError):
    """A released result cannot be moved. It can only be revised."""


# ---------------------------------------------------------------------------
# Who may take which step.
#
# Sets rather than single roles because a school is a building with people off
# sick in it. The separation that matters is not "only the principal may
# approve" — it is that no one person can walk a sheet from draft to a parent
# alone, and that is held by the same-signatory rule below rather than by making
# these sets as narrow as possible.
# ---------------------------------------------------------------------------

#: A class teacher submits. An administrator is here because entering and
#: submitting a paper sheet is office work in most schools — the same reasoning
#: `gradebook.MARK_ENTERING_ROLES` gives for admitting one.
SUBMITTING_ROLES = frozenset({Role.TEACHER.value, Role.ADMIN.value})

#: The academic check. Deliberately one role: this is the step the chain exists
#: for, and widening it to admins would let the office both submit and check.
CHECKING_ROLES = frozenset({Role.VICE_PRINCIPAL_ACADEMIC.value})

#: Approval is the principal's, and only the principal's.
APPROVING_ROLES = frozenset({Role.PRINCIPAL.value})

#: Publishing to parents. The principal's, and only the principal's.
#:
#: This was `{principal, admin}`, on the argument that release is commonly gated
#: on something clerical — fees settled, cards printed — rather than being a
#: second academic judgement. That argument is not wrong about schools, but it
#: contradicted a decision already taken for this phase, and the contradiction
#: was load-bearing rather than cosmetic: **task 8 makes revision principal-only
#: on the stated grounds that "release is the principal's act, so revision is
#: too."** Widening release here would leave task 8's authority rule resting on
#: a premise this module had quietly stopped honouring.
#:
#: Narrowed rather than left, because the two ways of resolving it are not
#: symmetrical. Narrowing costs a school an inconvenience a later PR can undo;
#: widening publishes forty-five children's results on an authority the person
#: who owns the decision did not grant. If an administrator should be able to
#: release, that is a change to make deliberately, in a PR that says so.
RELEASING_ROLES = frozenset({Role.PRINCIPAL.value})

#: Sending back is refusing at whatever stage you sit, so it is the union of the
#: people who could have said yes instead.
SENDING_BACK_ROLES = CHECKING_ROLES | APPROVING_ROLES

#: Opening a class's sheet, which decides nothing — everyone who can take any
#: step on the chain, and nobody else. Derived from the sets above rather than
#: written out, so a step whose roles change cannot leave this one behind.
OPENING_ROLES = (
    SUBMITTING_ROLES | CHECKING_ROLES | APPROVING_ROLES | RELEASING_ROLES
)


def school_on_this_connection():
    """The school whose schema is being written.

    Public, and named without the underscore, because `results.ratings` asks the
    same question and the answer has to be the same one. Copying six lines into
    the second module would have been six lines that could disagree about
    whether the portal is a school — which is the one thing this function exists
    to be right about.

    Read from the connection rather than passed in, for the reason
    `accounts.students.why_not_a_student_here()` reads it there: the sheet being
    written is already chosen by the `search_path`, so a school in an argument
    is a second opinion that can disagree with it.

    The public schema is refused explicitly, on the reasoning
    `schools.logging.current_school()` gives: **the public schema is the portal,
    not a customer.** Two things go wrong without this. A caller that never
    entered a tenant — a management command, a data migration, an `on_commit`
    callback — gets `School.DoesNotExist`, which is outside `ResultsError`, so
    every `except ResultsError` handler misses it and a refusal arrives as a
    500. And where a `School(name="Portal", schema_name="public")` row exists,
    which this codebase creates in its own tests, the lookup *succeeds* and
    authority is then checked against the portal's memberships rather than any
    school's — a silent wrong answer, which is the worse of the two.
    """
    from schools.models import School

    if connection.schema_name == get_public_schema_name():
        raise NotAllowedToActOnResults(
            "Results are a school's own records and this connection is on the "
            "portal, which is not a school. Enter the school's schema first."
        )
    return School.objects.get(schema_name=connection.schema_name)


def _named(roles) -> str:
    """Role labels, for a sentence a person reads.

    Not `', '.join(sorted(roles))`, which is what this did and which renders the
    refusal as "that step is taken by vp_academic". The stored value is an
    internal key — `accounts.Role` says so, and `vp_academic` was truncated to
    fit `Membership.role`'s sixteen characters precisely because nobody was
    meant to read it. Sorted on the label, since that is the order somebody
    scanning the sentence sees.
    """
    return ", ".join(sorted(Role(role).label for role in roles))


def as_ids(values):
    """Whatever the screen sent, as integers. Anything else is dropped.

    Here rather than in `ratings` — where it was written — for
    `locked_sheet_for()`'s reason one paragraph down: `comments.reorder_phrases()`
    asks the identical question of the identical kind of input, and a second
    copy is a second thing to forget when the next reorder path is added.

    A drag-and-drop posts JSON, and JSON has no integers in a URL or a form:
    `["12", "9", "7"]` is what arrives. Matched against a dict keyed by `pk`,
    every one of those misses, the list is renumbered into the order it was
    already in, and the caller is told 0 rows changed — a silent no-op the
    screen reports as success, and one the "ids of rows that no longer exist"
    rule makes indistinguishable from a legitimate one.

    Non-numeric junk *inside* the sequence is dropped rather than raising: every
    caller's contract is already "ids it does not recognise are ignored".

    A **string** is refused rather than iterated, and that is the case worth
    naming. `as_ids("12,9")` iterates characters, so `int()` succeeds on "1",
    "2" and "9" and skips the comma — yielding `[1, 2, 9]`, three ids the school
    never named, against which the list is cheerfully renumbered and the call
    reports success. It is the same silent no-op this function was extracted to
    prevent, wearing different clothes. So is a non-sequence: `None` would raise
    a bare `TypeError`, outside `ResultsError`, arriving at a screen as a 500.
    """
    if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
        raise ResultsError(
            f"A list of ids is a sequence of numbers, not {values!r}. A single "
            f"id still arrives as a list of one."
        )
    ids = []
    for value in values:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return ids


def locked_sheet_for(class_group, term):
    """The sheet for this group and term, re-read under a row lock. `None` if none.

    **Public, and here rather than in the two modules that call it**, because it
    is the same lock twice and the tricky part is not the locking. `ratings` and
    `comments` both have to answer "may I write against this sheet right now",
    and both have to hold the answer across their write; what neither should
    have to know is *how* to lock a sheet without taking rows it never writes.

    That is what `.get()` buys, and it is not a style choice.
    `ResultSheet.Meta.ordering` is `["term", "class_group"]` — two relations — so
    a `select_for_update()` that inherits it compiles to a three-table join and
    Postgres locks a row in `academics_term` and `academics_classgroup` too.
    `QuerySet.get()` clears ordering itself, which is the property `_locked()`
    documents at length and `test_approval_concurrency.LockScopeTests` pins on
    the captured SQL.

    Deliberately **not** paired with a shared refusal. The two callers phrase
    theirs differently — "its ratings are part of what is being reviewed" and
    "its remarks are" — and those sentences are read by a teacher, so they stay
    where the vocabulary is. What is shared is the lock and the predicate below,
    which are the parts that must not differ.

    Must be called inside `transaction.atomic()`; Django refuses `FOR UPDATE`
    outside one.
    """
    try:
        return ResultSheet.objects.select_for_update().get(
            class_group=class_group, term=term
        )
    except ResultSheet.DoesNotExist:
        return None


def sheet_for(class_group, term):
    """The chain's sheet for this group and term, or `None` if never opened.

    The read path's counterpart to `locked_sheet_for()`, **taking no lock**:
    `comments.card_comments()` and `ratings.card_sections()` each ask it whether
    to render the freeze or the live rows, and rendering a card must not lock the
    row a principal is trying to release.

    `.order_by()` before `.first()`, and it is not decoration.
    `ResultSheet.Meta.ordering` is `["term", "class_group"]` — two relations —
    and `.filter().first()` keeps it, so this compiled to a three-table join
    sorted by the term's session and the class's level, once per child, for a
    row `one_result_sheet_per_class_term` guarantees is unique.
    `locked_sheet_for()` above documents the same hazard and uses `.get()`,
    which clears ordering itself; this is the spelling that does not.
    `ratings.sheet_for()` shipped without the call and was corrected on it.

    **Here rather than copied into both modules**, unlike the refusals
    `locked_sheet_for()` deliberately leaves local. Those stay local because
    their wording is read by a teacher and the two callers phrase them
    differently. This has no wording and no refusal — it is one query and one
    trap — so two copies bought nothing and meant maintaining the `.order_by()`
    note in two places, which is the state a review found it in.
    """
    return (
        ResultSheet.objects.filter(class_group=class_group, term=term)
        .order_by()
        .first()
    )


def is_open_for_writing(sheet) -> bool:
    """Can what this sheet is reckoned from still be changed?

    Two states say yes and they are the same state: `draft`, and a sheet nobody
    has opened yet. A send-back returns a sheet to `draft`, which is the whole
    reason the test is the state rather than "has never been submitted" — a
    teacher told to fix a rating or rewrite a remark has to be able to.

    Anything past `draft` says no, because ratings and remarks are part of what
    the vice principal checked and the principal approved. If they could change
    afterwards, the signatures would be attached to a document that moved.
    """
    return sheet is None or sheet.state == SheetState.DRAFT


def _require_authority(actor, allowed, step):
    """The school this act belongs to, and the roles the actor holds there.

    Returns both because the caller needs both and asking twice means asking
    the database twice: `_require_class_teacher_scope()` wants to know whether
    this is an administrator, which is a fact this function has just read.
    """
    if not getattr(actor, "is_authenticated", False):
        raise NotAllowedToActOnResults(f"Signing in is required to {step} results.")

    school = school_on_this_connection()
    roles = set(actor.roles_at(school))
    if not roles & allowed:
        raise NotAllowedToActOnResults(
            f"{actor} may not {step} results at {school}. That step is taken by "
            f"{_named(allowed)}."
        )
    return school, roles


def _require_not_already_signed(sheet, actor, to_state):
    """The same-signatory rule, asked before the row is written.

    The unique index is what actually holds it — this is what turns the refusal
    into a sentence naming what they already did. Both are needed: the index
    catches the concurrent pair where each request reads "not signed yet", and
    this catches the ordinary case with an error somebody can act on.

    Only asked of an *advancing* step, and only counts advancing steps. A
    send-back and a release are not signatures; `models.ADVANCING_STATES` sets
    out why, and the same scoping is on the index so the two cannot drift.
    """
    if to_state not in ADVANCING_STATES:
        return

    existing = (
        ResultSheetTransition.objects.filter(
            sheet=sheet, cycle=sheet.cycle, actor_id=actor.pk
        )
        .filter(to_state__in=ADVANCING_STATES)
        .first()
    )
    if existing is None:
        return
    raise AlreadySignedThisCycle(
        f"{actor} already moved this sheet from {existing.from_state} to "
        f"{existing.to_state} on this pass. Two steps in one chain have to be "
        f"two people; ask somebody else to take this one.",
        existing=existing,
    )


def _locked(sheet):
    """Re-read the sheet under a row lock. Everything decides on this copy.

    The instance the caller is holding was read at some earlier moment and its
    `state` is a fact about that moment. Deciding on it is the stale-read bug
    this codebase has hit before — see `schools.Invitation.accept()`, which was
    validating guards against rows it had not locked.

    `.order_by()` is **belt and braces, and the braces are Django's.** The
    concern is real and this codebase has been bitten by it three times — in
    `accounts.services`, `accounts.models` and `schools.invitations` — because
    `ResultSheet` sorts by `term` then `class_group`, both relations, and a
    joined `SELECT ... FOR UPDATE` locks a row in *every* joined table. A
    transition would then hold an exclusive lock on the term and the class,
    serialising two principals approving two different classes in one term on a
    row neither of them writes.

    It is not what happens here, and the reason is worth writing down rather
    than rediscovering: **`QuerySet.get()` already clears ordering itself.**
    Django 5.2's `get()` runs `clone = clone.order_by()` before compiling, so
    the lock this function takes is

        SELECT ... FROM results_resultsheet WHERE id = %s LIMIT 21 FOR UPDATE

    with no join, with or without the call below. That was checked by reading
    the SQL the tests actually captured, not by reasoning from `.filter()` —
    which does *not* clear ordering and which is where the intuition comes from.

    The call stays because it costs nothing and the property is one line away
    from being lost: `.filter(pk=...).first()` keeps the ordering, and so does
    anything that stops going through `get()`. `tests/LockScopeTests` pins the
    property rather than the spelling — both of its tests fail on that rewrite,
    one on the SQL and one on real contention for `academics_term`.
    """
    return ResultSheet.objects.select_for_update().order_by().get(pk=sheet.pk)


def _require_class_teacher_scope(sheet, actor, school, roles, step):
    """A teacher may only act on **their own** class group's sheet.

    The hole this closes, and it was live in the chain as merged (issue #25):
    `_require_authority()` asks `roles_at(school)`, which is school-wide, and
    nothing bound the actor to the `class_group` on the sheet. Any teacher could
    submit any class group's results, for any term, and the transition row would
    record them as the submitting signatory of a class they do not teach — an
    audit trail accurate about who acted and silent about their having had no
    standing to act.

    **`sheet` must be the row read under the lock**, never the instance the
    caller passed in. That is the module docstring's rule and this check was the
    one place that broke it: it read `class_group` and `term` off the caller's
    object while `_move()` wrote to the row `_locked()` fetched by `pk` alone. A
    mismatched instance — deserialised, cached, or holding a `class_group` a
    bulk `.update()` has since corrected, none of which any guard prevents — was
    therefore authorised against one group and applied to another. See
    `tests/test_class_teacher_scope.TheScopeIsCheckedOnTheLockedRowTests`, which
    submits JSS 3B on JSS 1A's authority with the check taking its old argument.

    **An administrator is unaffected**, and that is deliberate rather than an
    oversight. `SUBMITTING_ROLES` admits ADMIN on the stated reasoning that
    entering and submitting a paper sheet is office work in most schools; an
    administrator is not a teacher of anything, so "which class are they the
    class teacher of" is not a question about them. Narrowing the office path is
    a separate decision from scoping the teaching one, and would be a change to
    make deliberately.

    A group with **nobody assigned** refuses every teacher, which is the honest
    reading: an unassigned class has no class teacher, so nobody is it. That is a
    school configuration problem, and the message says so rather than pretending
    the sheet is in the wrong state.
    """
    if Role.ADMIN.value in roles:
        return

    assignment = academics.class_teacher_of(sheet.class_group, sheet.term)
    if assignment is None:
        raise NotAllowedToActOnResults(
            f"{sheet.class_group} has no class teacher for {sheet.term}, so "
            f"nobody may {step} its results yet. A principal or an administrator "
            f"assigns one."
        )

    membership_id = actor.membership_id_at(school, Role.TEACHER)
    if membership_id is not None and membership_id == assignment.teacher_membership_id:
        return

    _refuse_for_somebody_elses_class(assignment, actor, school, sheet, step)


def _refuse_for_somebody_elses_class(assignment, actor, school, sheet, step):
    """Say which of the two refusals this is. Only ever on the way to raising.

    The two are worth telling apart. "You are not the class teacher" is true of
    an ordinary teacher looking at the wrong group and tells them everything
    they need. Said about a group whose assigned teacher has been **suspended or
    has left**, it is still true and completely unhelpful: the group cannot be
    submitted by anybody, and the person reading the refusal has no way to learn
    that from it. They go looking for a colleague who cannot act.

    That state is reachable on purpose. `assign_class_teacher()` does not refuse
    a membership without access, for the reason `place_student()` gives about
    ended memberships — backfilling a past term's register is real work and the
    people in it have often left — so the assignment outlives the access, and
    the *reading* side is where the difference has to be explained.

    One extra query, on the refusal path only.
    """
    holder = (
        Membership.objects.select_related("user")
        .filter(
            pk=assignment.teacher_membership_id,
            school=school,
            role=Role.TEACHER,
        )
        .first()
    )
    if holder is None or holder.status not in ACCESS_STATUSES:
        who = "somebody who is no longer here" if holder is None else holder.name
        raise NotAllowedToActOnResults(
            f"{sheet.class_group}'s class teacher for {sheet.term} is {who}, "
            f"who cannot currently act at {school} — so nobody may {step} its "
            f"results. A principal or an administrator assigns another."
        )

    raise NotAllowedToActOnResults(
        f"{actor} is not the class teacher of {sheet.class_group} for "
        f"{sheet.term}, so may not {step} its results. That step is taken by the "
        f"class teacher of the group."
    )


def _move(
    sheet,
    actor,
    *,
    expected,
    to_state,
    reason="",
    roles,
    step,
    class_teacher_only=False,
    freeze=None,
):
    """One step. Locked, checked, recorded and applied in a single transaction.

    `freeze` is called with the locked sheet **after** the transition row and
    the new state are written, and inside the same transaction. Only `release()`
    passes one. It is a callback rather than a branch on `to_state` so that this
    function stays a description of the chain, and so that task 3 adds what it
    freezes by extending one release-time step rather than by editing the mover.
    """
    school, held = _require_authority(actor, roles, step)

    with transaction.atomic():
        locked = _locked(sheet)

        # Inside the lock, and on `locked` rather than `sheet`. The role check
        # above is deliberately still outside it — a caller with no standing at
        # all should not be able to take a row lock — but *which group this
        # sheet belongs to* is a fact about the row, and reading it off the
        # caller's instance is how JSS 1A's teacher submitted JSS 3B.
        if class_teacher_only:
            _require_class_teacher_scope(locked, actor, school, held, step)

        if locked.state == SheetState.RELEASED:
            raise ReleaseIsFinal(
                f"{locked.class_group} — {locked.term} has been released to "
                f"parents. A released result is corrected by issuing a revision, "
                f"which keeps this one standing, not by moving it back."
            )
        if locked.state not in expected:
            raise WrongState(
                f"This sheet is {locked.get_state_display().lower()}, and {step} "
                f"applies to a sheet that is "
                f"{' or '.join(sorted(SheetState(s).label.lower() for s in expected))}.",
                state=locked.state,
            )

        _require_not_already_signed(locked, actor, to_state)

        recorded = ResultSheetTransition.objects.create(
            sheet=locked,
            from_state=locked.state,
            to_state=to_state,
            cycle=locked.cycle,
            actor_id=actor.pk,
            reason=reason,
        )

        locked.state = to_state
        fields = ["state", "updated_at"]
        if to_state == SheetState.DRAFT:
            # A send-back closes this pass. The row above belongs to the pass
            # that is ending — it is that pass's last act — so the bump happens
            # after it is written, not before.
            locked.cycle += 1
            fields.append("cycle")
        locked.save(update_fields=fields)

        if freeze is not None:
            # After the state is written, so anything frozen here can rely on
            # the sheet already reading `released` — and inside the transaction,
            # so a sheet that says `released` always has the card that was
            # released sitting behind it. There is no window in which one exists
            # without the other.
            freeze(locked)

    return recorded


def open_sheet(class_group, term, actor):
    """The sheet for this class and term, created in `draft` if it is new.

    `get_or_create` rather than a plain create: opening a class's results is
    something a screen does on being looked at, and the second person to look
    must not be an error. The unique constraint settles the race between two
    first-lookers.

    `actor` is required, and was missing. This module's docstring says every
    function checks who is asking before anything is read or written, and argues
    that the `_as()` split the other service modules use is absent here because
    there are no actor-less primitives. `open_sheet()` was exactly the primitive
    that argument said did not exist: exported, writing a tenant table, and
    never once asking `school_on_this_connection()`. Anything reachable from a
    future screen — a parent, a student, a suspended teacher — could mint
    `ResultSheet` rows for arbitrary (class, term) pairs, each of which
    `ResultSheetTransition.sheet`'s `PROTECT` then makes awkward to remove.

    Admitted roles are the union of everyone who can take a step on the chain.
    Opening a sheet decides nothing and signs nothing — it is the act of
    *looking at* a class's results — so it would be wrong to make it narrower
    than the narrowest step, and wrong to admit anybody who cannot act on the
    thing they have just created.
    """
    _require_authority(actor, OPENING_ROLES, "open a sheet for")
    sheet, _ = ResultSheet.objects.get_or_create(class_group=class_group, term=term)
    return sheet


def submit(sheet, actor):
    """Teacher: these results are ready to be checked.

    **Scoped to the class teacher of this group**, not to teachers in general —
    see `_require_class_teacher_scope()` for the hole that closes and why an
    administrator is still admitted.
    """
    return _move(
        sheet,
        actor,
        expected={SheetState.DRAFT},
        to_state=SheetState.SUBMITTED,
        roles=SUBMITTING_ROLES,
        step="submit",
        class_teacher_only=True,
    )


def check(sheet, actor):
    """Vice principal: I have looked at these and they are right."""
    return _move(
        sheet,
        actor,
        expected={SheetState.SUBMITTED},
        to_state=SheetState.CHECKED,
        roles=CHECKING_ROLES,
        step="check",
    )


def approve(sheet, actor):
    """Principal: these may go out."""
    return _move(
        sheet,
        actor,
        expected={SheetState.CHECKED},
        to_state=SheetState.APPROVED,
        roles=APPROVING_ROLES,
        step="approve",
    )


def release(sheet, actor):
    """Publish to parents. The last thing that happens to this version.

    **The moment the card is frozen.** `ratings.freeze_for_release()` copies the
    conduct section of every child in the class as it reads right now — the
    trait names, the order they are in, the scores and the school's word for
    each score — because every one of those is a row the school may edit next
    term and none of them may reach backwards into a card that has gone home.

    That is task 4's half of the snapshot. Task 3 adds the scores, the averages
    and the attendance the same way: another function called from here, inside
    this transaction, not another branch in `_move()`.

    Task 5 adds the second half: `comments.freeze_for_release()` copies the
    class teacher's and the principal's remarks the same way. Both run inside
    this one transaction, in the order they print, so a sheet that says
    `released` has the whole card behind it rather than part of one.

    Task 9 adds the last line: `sessions.freeze_for_release()` copies the three
    terms' averages and the year they add up to. **It writes nothing except at
    third term**, and decides that for itself rather than being called
    conditionally from here — a caller that has to remember which freezes apply
    to which term is one that will eventually forget, and the fact "a session
    average is only a thing once the year is over" belongs to the module that
    owns session averages.

    Task 3 adds `cards.freeze_for_release()`, which goes **first** — see below.

    Imported inside the function rather than at the top of the module, because
    all four modules import this one — they need `school_on_this_connection()`,
    `locked_sheet_for()` and `ResultsError`, which are the chain's own — and a
    module-level import here would close the circle.
    """
    from . import cards, comments, ratings, sessions

    def freeze_the_card(locked):
        """Everything the card is made of, copied at the moment of release.

        A named function rather than four `freeze=` parameters or a list: what
        gets frozen is a growing list and `_move()` should go on knowing nothing
        about any of it.

        **`cards` runs first, and that is now structural rather than tidy.** It
        writes the `ReleasedCard` each of the other three hangs its section off,
        so the order is a dependency: the sections cannot be written before
        their parent row exists.

        The rest follow in the order they print, so that a reader sees the page.
        That used to be the whole rule here, and the note it replaced said a
        partial failure would leave a card truncated at the bottom rather than
        hollowed out in the middle. That was never load-bearing — the block is
        one transaction and either all of it lands or none does — and it is less
        so now, because the first call is required rather than merely first.

        `cards.freeze_for_release()` is **unconditional**: it writes a row for
        every child on the roster whatever else is true, including a school with
        the conduct section off, no marks and nothing decided. That is the
        guarantee issues #31, #33 and #34 all asked for, and no constraint can
        hold it — see `results.cards`.
        """
        cards.freeze_for_release(locked)
        ratings.freeze_for_release(locked)
        comments.freeze_for_release(locked)
        sessions.freeze_for_release(locked)

    return _move(
        sheet,
        actor,
        expected={SheetState.APPROVED},
        to_state=SheetState.RELEASED,
        roles=RELEASING_ROLES,
        step="release",
        freeze=freeze_the_card,
    )


def send_back(sheet, actor, reason: str):
    """Refuse at whatever stage you sit, and say what is wrong.

    The transition the task list did not have. A chain that only goes forward
    does not mean mistakes are not made — it means the fix is somebody editing
    the database, which leaves no record that anything was ever wrong.

    `reason` is required and is not allowed to be blank. A refusal that does not
    say what is wrong sends a teacher back to forty-five scores with no idea
    which one to look at, and the check constraint refuses the row anyway.
    """
    if not (reason or "").strip():
        raise ResultsError(
            "A send-back has to say what is wrong. The teacher is looking at "
            "forty-five scores and needs to know which one."
        )
    return _move(
        sheet,
        actor,
        expected=SENDABLE_BACK_FROM,
        to_state=SheetState.DRAFT,
        reason=reason.strip(),
        roles=SENDING_BACK_ROLES,
        step="send back",
    )


def history(sheet):
    """Every step this sheet has taken, oldest first. The audit."""
    return ResultSheetTransition.objects.filter(sheet=sheet)


# Includes the shared plumbing `ratings` and `comments` import — the lock, the
# predicate, the id coercion and the school lookup. Each says "public" in its own
# docstring and both docs name them as the shared surface; leaving them out let
# the module's stated API and its declared one disagree, which is worse than
# either answer on its own.
#
# `sheet_for` earns its place by being defined here, which it was not when this
# list first named it: a name listed in `__all__` that the module does not define
# is not inert — it raises `AttributeError` on `from results.services import *`,
# at import time. The entry was removed for that reason and is back because the
# function moved, not because the rule softened.
__all__ = [
    "APPROVING_ROLES",
    "CHECKING_ROLES",
    "OPENING_ROLES",
    "RELEASING_ROLES",
    "SENDING_BACK_ROLES",
    "SUBMITTING_ROLES",
    "AlreadySignedThisCycle",
    "NotAllowedToActOnResults",
    "ReleaseIsFinal",
    "ResultsError",
    "WrongState",
    "approve",
    "as_ids",
    "check",
    "history",
    "is_open_for_writing",
    "locked_sheet_for",
    "open_sheet",
    "release",
    "school_on_this_connection",
    "send_back",
    "sheet_for",
    "submit",
]
