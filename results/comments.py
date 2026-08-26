"""The two remarks on a report card: the class teacher's and the principal's.

A Nigerian card ends with two signed sentences. The class teacher writes about
the term they taught the child; the principal writes about the card as a whole.
They print one under the other, each labelled, and a parent reads them as two
different judgements — which is why they are two rows and not one paragraph.

Four kinds of function, answering to four different people:

1. **The phrase bank** — the canned remarks a school offers, per signatory. An
   office act, so `CONFIGURING_ROLES` is the principal and the administrator.
2. **Writing a remark** — the class teacher of that child's group writes the
   teacher's remark and nobody else; the principal writes the principal's and
   nobody else. `_require_authority_for()` sets both out.
3. **Reading** — the remarks as they print. From the freeze if the sheet has
   been released, from the live rows if it has not.
4. **The freeze** — `freeze_for_release()`, called by
   `results.services.release()` inside the transaction that writes the release.

## A phrase is a starting point for typing, not a value

The screen offers the school's phrases, the teacher clicks one, it lands in the
box, and they edit it. So what is stored is **the sentence the teacher left**,
and `ReportCardComment` keeps no key back to the phrase it may have started
from. Editing a phrase, or deleting it, therefore cannot reach a comment that
has been written — released or not. That is the denormalisation the task asks
for, done at write time rather than at release, and it is why the freeze below
has a different job: it guards edits to the *comment*, not to the bank.

## Empty means absent

There is no blank remark. `a_comment_says_something` refuses whitespace and
`clear()` deletes the row, so "the principal has not written one" is the absence
of a row and prints as nothing at all — no heading, no labelled empty box. The
same rule `ratings.card_sections()` follows for a section a school does not
print, and for the same reason: a box with a label and nothing in it is a
question a parent asks the school about.

**No comment ever blocks the chain.** A sheet submits, checks, approves and
releases with both remarks missing. Schools do release cards with a blank
principal's remark, and a module that refused would strand a term's results
over a sentence.
"""

from dataclasses import dataclass

from django.db import transaction

from academics import services as academics
from accounts.models import Role
from accounts.students import why_not_a_student_here

from . import positions
from .models import (
    MAX_COMMENT_LENGTH,
    CommentAuthor,
    CommentPhrase,
    ReleasedComment,
    ReportCardComment,
    SheetState,
)
from .services import (
    ResultsError,
    as_ids,
    is_open_for_writing,
    locked_sheet_for,
    school_on_this_connection,
    sheet_for,
)


class CommentsError(ResultsError):
    """A remark could not be written, configured or read as asked.

    Subclasses `results.services.ResultsError` rather than starting a hierarchy
    of its own: this is one app publishing one thing, and a caller wrapping "get
    this class's results out" in `except ResultsError` should not have to know
    that the remarks keep their refusals somewhere else.
    """


class NotAllowedToComment(CommentsError):
    """The actor may not write this remark — it is somebody else's to sign."""


class NotAllowedToConfigurePhrases(CommentsError):
    """The actor may not change the remarks this school offers."""


class NotThisSchoolsStudent(CommentsError):
    """The membership named is not a student of the school being written to."""


class NotPlacedThisTerm(CommentsError):
    """The child sits in no class group this term.

    Not an edge case to paper over. The teacher's remark is the class teacher's,
    and with no placement there is no group, so there is no class teacher with
    standing to write it and no sheet for it to be submitted on.
    """


class CommentsLocked(CommentsError):
    """The sheet has left `draft`, so its remarks are part of what is being checked.

    Carries `state` — where the sheet actually is — so a caller can say whether
    this is "the vice principal has it" or "this went home in March".

    **Over HTTP this is a 423.** Not a 409, which in this codebase means "the
    row moved while you were typing" and is answered by reloading and sending
    again — a released term never reopens, so that client retries for ever. Not
    a 403, which is a refusal of the caller's authority, and the caller's
    authority has not changed; the resource's state has.
    `gradebook.api` implements it and states the case in full.
    """

    def __init__(self, message, state=None):
        super().__init__(message)
        self.state = state


#: Who may change the phrases this school offers. The same set
#: `ratings.CONFIGURING_ROLES` uses, and the same argument: the bank is what
#: every card's remark starts from, which is not one teacher's decision.
CONFIGURING_ROLES = frozenset({Role.PRINCIPAL.value, Role.ADMIN.value})


def _author(author) -> str:
    """A `CommentAuthor` value, or this module's own refusal.

    `CommentAuthor("form_master")` raises a bare `ValueError`, which is outside
    `ResultsError` — so a caller wrapping "get this class's results out" in
    `except ResultsError` misses it, and a mistyped query parameter arrives as a
    500 rather than as a sentence. `ratings._group()` was corrected on precisely
    this cast, and every entry point below goes through this one.
    """
    try:
        return CommentAuthor(author).value
    except ValueError:
        known = ", ".join(member.value for member in CommentAuthor)
        raise CommentsError(
            f"{author!r} does not sign a report card. Two people do: {known}."
        ) from None


# ---------------------------------------------------------------------------
# The phrase bank.
# ---------------------------------------------------------------------------


def phrases(author):
    """The remarks this school offers that signatory, in the order they list.

    `author` is required and there is deliberately **no** function returning
    both sets. The two are separate lists, not one pool filtered: a teacher
    picking a remark must never be shown one written for a principal to sign,
    and the way to guarantee that is for "which phrases exist" to be
    unanswerable without saying whose.
    """
    return CommentPhrase.objects.for_author(_author(author))


#: What `PositiveSmallIntegerField` actually holds. Named rather than inlined so
#: the refusal and the column cannot drift.
HIGHEST_POSITION = 32_767


def _require_a_position(position):
    """A place in the list, or `None` for "the end". This module's own refusal.

    `position` is an exposed keyword argument, so a screen reaches the column
    with it directly: `-1` arrives as an `IntegrityError`, `"first"` as a
    `DataError`, and `70000` overflows `smallint`. Each is outside
    `CommentsError`, and each marks the caller's transaction unusable — the
    failure the rest of this module goes to lengths to close.
    """
    if position is None:
        return None
    if isinstance(position, bool) or not isinstance(position, int):
        raise CommentsError(
            f"A position in the list is a whole number, not {position!r}."
        )
    if not 0 <= position <= HIGHEST_POSITION:
        raise CommentsError(
            f"{position} is not a place in the list. A position is 0 to "
            f"{HIGHEST_POSITION}, and leaving it out puts the phrase at the end."
        )
    return position


def _refuse_a_phrase_already_offered(author, text, *, except_pk=None):
    """`uniq_comment_phrase_per_author`, asked before the insert rather than after.

    Unasked, a school offering a sentence it already offers gets a raw
    `IntegrityError` naming a constraint. That is wrong twice: it is outside
    `CommentsError`, so every `except ResultsError` misses it, and an
    `IntegrityError` marks the enclosing transaction unusable, so a screen
    saving a batch of phrases cannot go on to the next one after a duplicate.
    `ratings._refuse_a_name_already_in_the_group()` is this function one module
    along, added to that branch for the same reason.

    No hidden-row case to explain, unlike the traits: a phrase nobody offers any
    more is deleted, because nothing names it.
    """
    clash = CommentPhrase.objects.for_author(author).filter(text=text)
    if except_pk is not None:
        clash = clash.exclude(pk=except_pk)
    if clash.exists():
        raise CommentsError(
            f"“{text}” is already on the list of "
            f"{CommentAuthor(author).label.lower()}s this school offers. The same "
            f"sentence twice in one list is two identical things to click."
        )


def add_phrase(author, text, *, position=None) -> CommentPhrase:
    """Offer another remark. No migration, which is the requirement.

    `position` defaults to the end of that author's list rather than to zero: a
    school adding a phrase means it to appear after what is already there.

    **The computed end is checked too, not only the given one.** Guarding the
    argument and then letting `last + 1` run past the column is the same escape
    with the guard's back turned: a list whose last phrase sits at
    `HIGHEST_POSITION` overflows `smallint` on the next append, as a `DataError`
    outside `CommentsError` that takes the enclosing transaction with it.
    """
    author = _author(author)
    text = _require_text_that_fits(text, noun="phrase")
    _refuse_a_phrase_already_offered(author, text)
    position = _require_a_position(position)
    if position is None:
        last = (
            CommentPhrase.objects.for_author(author)
            .order_by("-position")
            .values_list("position", flat=True)
            .first()
        )
        if last is not None and last >= HIGHEST_POSITION:
            raise CommentsError(
                f"This list already reaches position {HIGHEST_POSITION}, which "
                f"is as far as the column goes, so there is no end to add to. "
                f"Reordering the list renumbers it from 0 and makes room."
            )
        position = 0 if last is None else last + 1
    return CommentPhrase.objects.create(author=author, text=text, position=position)


def _the_phrase_row(phrase) -> CommentPhrase:
    """This school's phrase with that `pk`, whatever instance was handed in.

    Both writes below compile to `... WHERE id = <pk>` against the schema on the
    connection, while every check they make reads the *argument*. So an instance
    read on another school's connection, deserialised from a cache, or built by
    hand decides the checks with whatever its fields say and lands the write on
    whichever of our rows holds that id.

    It matters most for `author`. The duplicate check below looks for a clash in
    the list the argument names, so an instance claiming to be the principal's
    while the row here is the class teacher's searches the wrong list, passes,
    and lets `uniq_comment_phrase_per_author` fire instead. That is exactly what
    `ratings._the_trait_row()` was added for, on the same two verbs.
    """
    # An id or an instance, because a screen posting a phrase id has one and not
    # the other. `phrase.pk` on an `int` is an `AttributeError`, and junk from a
    # form reaches `get()` as a `ValueError` — both outside the hierarchy this
    # module promises, and both arriving at a screen as a 500 naming nothing.
    phrase_id = getattr(phrase, "pk", phrase)
    try:
        return CommentPhrase.objects.get(pk=phrase_id)
    except (CommentPhrase.DoesNotExist, TypeError, ValueError):
        raise CommentsError(
            f"There is no phrase {phrase_id!r} in this school's bank. A phrase "
            f"belongs to the school whose schema it was read in."
        ) from None


def edit_phrase(phrase, text) -> CommentPhrase:
    """Change what a phrase says from now on.

    Does **not** reach backwards, and needs no machinery to avoid it: a comment
    stores the sentence the teacher left, not a reference to this row.
    """
    phrase = _the_phrase_row(phrase)
    text = _require_text_that_fits(text, noun="phrase")
    _refuse_a_phrase_already_offered(phrase.author, text, except_pk=phrase.pk)
    phrase.text = text
    phrase.save(update_fields=["text", "updated_at"])
    return phrase


def remove_phrase(phrase) -> bool:
    """Stop offering a remark. Deletes the row, and that is safe here.

    `Trait` is hidden rather than deleted because ratings and released cards
    name the trait row, so removing it would take evidence with it. **Nothing
    names a phrase.** The text is copied into the comment at write time, so a
    deleted phrase leaves every comment it ever seeded exactly as it was.
    """
    deleted, _ = CommentPhrase.objects.filter(pk=_the_phrase_row(phrase).pk).delete()
    return bool(deleted)


def reorder_phrases(author, phrase_ids) -> int:
    """Put one author's phrases in this order. Returns how many rows moved.

    **The whole list is renumbered, 0 upwards** — the named phrases first, in
    the order given, then the rest in the order they were already listed.
    Renumbering only the named ones leaves an unmoved phrase holding a position
    a named one has just been given, and `Meta.ordering` then breaks the tie by
    text, printing it in the middle of the group the school had just arranged.
    That is `ratings.reorder()`'s bug, written down here so it is not made
    twice.

    Ids belonging to the other author are ignored rather than moved across:
    reordering is not a way to turn a teacher's phrase into a principal's.

    `services.as_ids()` coerces first, because a drag-and-drop posts JSON and
    JSON ids arrive as `["12", "9"]`. Matched raw against a dict keyed by `pk`
    every one of them misses, the list is renumbered into the order it was
    already in, and the caller is told nothing moved — the silent no-op
    `ratings.reorder()` shipped with and was corrected on.
    """
    author = _author(author)
    # Iterated in `Meta.ordering`, so `known` — and `rest` below — is in the
    # order the list shows today.
    known = {row.pk: row for row in CommentPhrase.objects.for_author(author)}

    named, seen = [], set()
    for phrase_id in as_ids(phrase_ids):
        phrase = known.get(phrase_id)
        if phrase is None or phrase.pk in seen:
            continue
        seen.add(phrase.pk)
        named.append(phrase)
    rest = [row for row in known.values() if row.pk not in seen]

    moved = []
    for position, phrase in enumerate(named + rest):
        if phrase.position == position:
            continue
        phrase.position = position
        moved.append(phrase)
    if moved:
        CommentPhrase.objects.bulk_update(moved, ["position"])
    return len(moved)


# ---------------------------------------------------------------------------
# Writing a remark.
# ---------------------------------------------------------------------------


def _require_text_that_fits(text, *, noun="remark", blank_message=None) -> str:
    """A sentence, stripped, that says something and fits the box.

    Checked here as well as by the column, and the two are not the same check.
    `varchar(250)` refuses 251 characters with a `DataError` naming a column;
    this refuses it with a sentence naming the limit, which is what a teacher
    who has just written four lines needs to read. The column stays because a
    rule that lives in the service only holds for the service.

    `noun` and `blank_message` because this serves **two audiences**. A teacher
    writing a remark and an administrator curating the phrase bank hit the same
    three rules, but telling the administrator "a remark cannot be blank — clear
    it instead" names an object they are not editing and an act that does not
    apply: there is no card in front of them and nothing to clear.
    `locked_sheet_for()`'s docstring makes the same call one level up — the
    shared part is the rule, and the wording belongs to whoever reads it.
    """
    if not isinstance(text, str):
        raise CommentsError(f"A {noun} is text, not {text!r}.")
    text = text.strip()
    if not text:
        raise CommentsError(
            blank_message
            or f"A {noun} cannot be blank. An empty {noun} and no {noun} are "
            f"the same thing, and the card prints neither."
        )
    if len(text) > MAX_COMMENT_LENGTH:
        raise CommentsError(
            f"A {noun} fits {MAX_COMMENT_LENGTH} characters and this one is "
            f"{len(text)}. The box on the card is a fixed size."
        )
    return text


def _require_student_of_this_school(membership):
    reason = why_not_a_student_here(
        membership, subject="a report card remark", holder="report card"
    )
    if reason:
        raise NotThisSchoolsStudent(reason)
    return membership


def _require_placed(membership, term):
    placement = academics.placement_of(membership.pk, term)
    if placement is None:
        raise NotPlacedThisTerm(
            f"{membership.name or membership.user} is in no class group for "
            f"{term}, so there is no class teacher to write about them and no "
            f"sheet to submit the remark on. Place them first."
        )
    return placement


def _require_this_card_has_not_gone_home(term, membership):
    """Has a card for this child, this term, already been frozen and sent home?

    A different question from the one below, and it has to be asked separately
    because the one below answers it wrong after a class move.
    `_require_the_sheet_is_open()` reaches the sheet through
    `placement.class_group` — the class the child is in **today** — so releasing
    JSS 1A and then moving the child to JSS 3B leaves the guard looking at JSS
    3B's untouched draft and permitting a write onto a card already in a
    parent's hand. Migration `0010` states the case in full.

    So this asks the frozen rows directly, and placement never enters into it.
    The rule generalises past this module — **a guard on a released artefact
    keys off the artefact, not off the child's current placement**, because
    placement is a live fact that changes while release is an event that
    happened.

    **Keyed on the child and the term, not on the author.** It asked
    `author=author` first, which was the same mistake one level down: a card
    released carrying only the class teacher's remark freezes no principal's
    row, so the principal's write found nothing here, and after a move found
    JSS 3B's draft below — and landed a remark on a card that had gone home.
    Measured before it was changed. The child who stayed in JSS 1A was refused
    that write by the check below, so the two answers disagreed on where the
    child was sitting rather than on what had happened, and this is what makes
    them agree.

    It does not replace the sheet-state check, which still answers what the
    frozen rows cannot: a class released while a child's card carries no remark
    at all freezes nothing for that child, and a remark must still not be
    written onto that released sheet.

    **The one case neither sees**, written down because the docstring here used
    to claim there was none: a child whose card went home with *no* remark of
    either kind, who is then moved. Nothing was frozen for them, so this finds
    nothing, and the check below is looking at the new class. Closing it needs a
    per-child record that a card was released — which is what the frozen rows
    are for every other child, and which task 3's card work would add. Until
    then the divergence is bounded to a card that published no remarks: the
    parent's copy still prints none, because `card_comments()` reads the frozen
    rows for a child that has them and an empty freeze for one that does not.
    """
    # Through `sheet__term`, because `ReleasedComment` stores the sheet and not
    # the term — the sheet is what was released, and it carries the term with it.
    if ReleasedComment.objects.filter(
        sheet__term=term,
        student_membership_id=membership.pk,
    ).exists():
        raise CommentsLocked(
            f"{membership.name or membership.user}'s report card for {term} has "
            f"been released to a parent. It has to keep saying what it said, and "
            f"correcting it is a revision rather than an edit.",
            state=SheetState.RELEASED,
        )


def _require_the_sheet_is_open(class_group, term):
    """Remarks are editable while the sheet is in `draft`, and not after.

    They are part of what gets submitted, checked and approved. If a remark
    could change after submission then what the vice principal checked and what
    the principal approved are not the same document, and the chain's signatures
    are attached to a thing that moved underneath them. A send-back returns the
    sheet to `draft`, so a teacher told to rewrite a remark can rewrite it.

    A sheet that does not exist yet is open: the chain has not started, and
    writing remarks before anybody opens the class's sheet is ordinary.
    **No lock is taken in that case, and cannot be** — Postgres has no row to
    lock — so the ordering below is a guarantee about sheets that exist. A
    remark begun before the sheet is opened can still land after somebody else
    opens *and* submits it in the same window. Closing that needs a lock on
    something other than the row, which is
    [issue #30](https://github.com/adedejimakinde/luffy-school-saas/issues/30),
    scoped to cover this module as well as `ratings`.

    **The sheet is locked, not merely read**, by `services.locked_sheet_for()`,
    which `ratings` calls too so the two cannot drift apart about what "open"
    means — and the caller writes in the same transaction. Unlocked, this is a
    check followed by an act on what it checked, the stale-read shape this
    codebase keeps finding: in `schools.Invitation.accept()`, and again in
    `_require_class_teacher_scope()`. A teacher saving while the vice principal
    submits would read `draft` and commit a remark into a document that was
    submitted a millisecond later.
    """
    sheet = locked_sheet_for(class_group, term)
    if is_open_for_writing(sheet):
        return sheet

    if sheet.state == SheetState.RELEASED:
        raise CommentsLocked(
            f"{class_group} — {term} has been released to parents. Its remarks "
            f"are part of a card somebody is holding, and correcting one is a "
            f"revision rather than an edit.",
            state=sheet.state,
        )
    raise CommentsLocked(
        f"{class_group} — {term} is {sheet.get_state_display().lower()}, so its "
        f"remarks are part of what is being reviewed and cannot be changed. Ask "
        f"for the sheet to be sent back if one is wrong.",
        state=sheet.state,
    )


def _stamp(by):
    return getattr(by, "pk", by)


def write(
    term, membership, author, body, *, by=None, placement=None
) -> ReportCardComment:
    """Record one signatory's remark about one child. Returns the row.

    An upsert: rewriting a remark is a correction, not a second remark, and
    `one_comment_per_author_per_student_per_term` would refuse the second row.

    No `except IntegrityError` here, deliberately. Django's `update_or_create()`
    takes the row lock and `get_or_create()` re-reads after a unique violation,
    so the insert race is already handled; a catch would only swallow the other
    refusals — the `CHECK` behind a bare id, the blank-body constraint, the
    trigger on a released term — and hand the caller a confused error in place
    of the one the database wrote for them. `ratings.rate()` records what that
    cost when it had one.

    `placement` is the row the caller has **already authorised against**, and
    passing it is what makes the guard and the write agree about which class
    group the child is in. `write_as()` reads the placement, asks whether this
    actor may sign that group's remark, and hands the same row down; without it
    this function read the placement a second time, and an
    `academics.move_student()` committing between the two would have a remark
    authorised against JSS 1A's class teacher and its sheet state checked on JSS
    1B's — so a remark could land in a term the guard would have refused. That
    is `_require_class_teacher_scope()`'s bug two modules along, and
    `ratings.rate()` was corrected on it one module along.

    Left optional rather than required because the primitive is reachable
    without an actor: an import has nobody to authorise and no earlier read to
    reuse, so it reads its own.
    """
    _require_student_of_this_school(membership)
    if placement is None:
        placement = _require_placed(membership, term)
    author = _author(author)
    body = _require_text_that_fits(
        body,
        noun="remark",
        # "Clear it instead" is advice about `clear()`, which exists for a
        # remark and has no counterpart in the phrase bank.
        blank_message=(
            "A remark cannot be blank. Clear it instead — an empty remark and "
            "no remark are the same thing, and the card prints neither."
        ),
    )

    stamp = _stamp(by)
    # Its own atomic block, for the reason `place_student()` gives: an
    # IntegrityError marks the enclosing transaction unusable, so without a
    # savepoint a caller writing a whole class's remarks in one transaction
    # could not go on to the next child after one refused row.
    #
    # The state check is inside it, holding the sheet's row lock across the
    # write. Checking outside and writing inside is two transactions with a
    # submission free to land between them.
    with transaction.atomic():
        _require_this_card_has_not_gone_home(term, membership)
        _require_the_sheet_is_open(placement.class_group, term)
        comment, _ = ReportCardComment.objects.update_or_create(
            term=term,
            student_membership_id=membership.pk,
            author=author,
            # Two sets, and the difference is the point of the second column.
            # `written_by_id` names whose remark this is and is written once;
            # putting it in `defaults` too would have every correction overwrite
            # the author with whoever last touched the row.
            defaults={"body": body, "updated_by_id": stamp},
            create_defaults={
                "body": body,
                "updated_by_id": stamp,
                "written_by_id": stamp,
            },
        )
        return comment


def clear(term, membership, author, *, placement=None) -> bool:
    """Take a remark back. True if there was one.

    Deletes the row rather than blanking the body: no row is how "no remark" is
    spelled, and a blank body would print as a labelled empty box.

    `placement` carries the row the caller authorised against, for `write()`'s
    reason.
    """
    _require_student_of_this_school(membership)
    if placement is None:
        placement = _require_placed(membership, term)
    author = _author(author)

    with transaction.atomic():
        _require_this_card_has_not_gone_home(term, membership)
        _require_the_sheet_is_open(placement.class_group, term)
        deleted, _ = ReportCardComment.objects.filter(
            term=term, student_membership_id=membership.pk, author=author
        ).delete()
    return bool(deleted)


def comments_for(membership_id, term) -> dict[str, str]:
    """`author -> body` for one child this term. One query."""
    return dict(
        ReportCardComment.objects.for_student(membership_id, term).values_list(
            "author", "body"
        )
    )


def missing(class_group, term) -> dict[int, list[str]]:
    """`student membership id -> the remarks nobody has written yet`.

    For a screen that wants to say "eleven still to write". Deliberately **not**
    a rule — nothing here blocks the chain, and a card released with a blank
    principal's remark is a school's business. It reports; the school decides.
    """
    students = positions.roster_ids(class_group, term)
    if not students:
        return {}

    written = {
        (row.student_membership_id, row.author)
        for row in ReportCardComment.objects.for_students(students, term).only(
            "student_membership_id", "author"
        )
    }
    outstanding = {}
    for student_id in students:
        # **Values, not labels.** The screen this exists for links "eleven still
        # to write" to the box that writes them, and that box calls `write_as()`,
        # which takes `"principal"` — not "Principal's remark". Returning the
        # label makes every caller map it back by scanning `CommentAuthor`, and
        # that reverse lookup breaks the first time a label is reworded or
        # translated. `card_comments()` below returns both for the same reason,
        # keeping `author` for the caller and `heading` for the page.
        absent = [
            author.value
            for author in CommentAuthor
            if (student_id, author.value) not in written
        ]
        if absent:
            outstanding[student_id] = absent
    return outstanding


# ---------------------------------------------------------------------------
# What prints.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CommentLine:
    """One remark as it prints: whose it is, what it is labelled, what it says."""

    author: str
    heading: str
    body: str


def card_comments(membership_id, class_group, term) -> list[CommentLine]:
    """The remarks on one child's card, as they should print.

    **Two sources, and which one is used is not a preference.** If a card for
    this child has been released this reads the frozen rows and nothing else,
    because the card is what was published. If none has, it reads the live rows,
    because a draft card follows what the school has written today.

    **Which source is decided by the child's frozen rows, not by the class
    passed in** — the same rule the write guard keys on, and for the same
    reason. Asking `sheet_for(class_group, term)` asks about the class the
    caller resolved from the child's placement, which is where the child sits
    *today*: release JSS 1A, move the child to JSS 3B, and re-printing the
    released card renders it from JSS 3B's draft, so the parent's copy and the
    reprint disagree. Measured before it was changed, and it is the read-side
    half of the write hole migration `0010` describes.

    `class_group` is still taken, and still consulted for a child with no frozen
    rows: it is what distinguishes a draft card from one released carrying no
    remark for this child, and the frozen rows cannot tell those apart.

    A remark nobody wrote produces **no line**. Not a line with an empty body —
    the caller loops over what it is given, so an empty line is a heading and a
    rule across the page with nothing under it, which is the labelled empty box
    this design refuses everywhere.
    """
    frozen = ReleasedComment.objects.filter(
        sheet__term=term, student_membership_id=membership_id
    ).values_list("author", "body")
    if frozen:
        bodies = dict(frozen)
    else:
        sheet = sheet_for(class_group, term)
        released = sheet is not None and sheet.is_released
        bodies = {} if released else comments_for(membership_id, term)

    # `CommentAuthor`'s declaration order, not the alphabetical order of the
    # stored value — which agrees today and would stop agreeing the first time a
    # signatory is added whose value sorts wrong.
    return [
        CommentLine(author=author.value, heading=author.label, body=body)
        for author in CommentAuthor
        if (body := bodies.get(author.value))
    ]


# ---------------------------------------------------------------------------
# The freeze.
# ---------------------------------------------------------------------------


def freeze_for_release(sheet) -> int:
    """Copy this class's remarks as they read now. Returns rows written.

    Called by `results.services.release()` **inside the transaction that writes
    the release row**, so a sheet that says `released` always has the card that
    was released sitting behind it.

    A row per remark that exists, and **no row where a remark does not** — the
    difference from the frozen ratings, which record even the traits nobody
    rated because what is frozen there is the section itself. Here there is no
    list to preserve: two signatories, fixed in code, and an absent remark
    prints as absent whether the card is live or frozen.
    """
    students = positions.roster_ids(sheet.class_group, sheet.term)
    if not students:
        return 0

    rows = [
        ReleasedComment(
            sheet=sheet,
            student_membership_id=row.student_membership_id,
            author=row.author,
            body=row.body,
        )
        for row in ReportCardComment.objects.for_students(students, sheet.term)
    ]
    if not rows:
        return 0

    # `bulk_create`, which does not call `save()` — and does not need to. The
    # model's `save()` refuses *edits*; inserting is the one thing a frozen row
    # is allowed to do, and it happens exactly once, here.
    ReleasedComment.objects.bulk_create(rows)
    return len(rows)


# ---------------------------------------------------------------------------
# Actor-checked entry points.
# ---------------------------------------------------------------------------


def _require_configuring_authority(actor):
    school = school_on_this_connection()
    if not getattr(actor, "is_authenticated", False):
        raise NotAllowedToConfigurePhrases(
            "Signing in is required to change the remarks a school offers."
        )
    if not set(actor.roles_at(school)) & CONFIGURING_ROLES:
        raise NotAllowedToConfigurePhrases(
            f"{actor} may not change the remarks {school} offers. The phrase "
            f"bank is set by a principal or an administrator of the school."
        )
    return school


def _require_authority_for(actor, author, placement, term):
    """Each remark is signed by exactly one person, and only they may write it.

    **The class teacher's remark is the class teacher's.** Not the office's:
    `results.services.SUBMITTING_ROLES` admits an administrator because
    submitting a paper sheet is transcription, and a remark about a child is not
    — it is the judgement of the person who taught them all term. The same
    argument `ratings._require_the_class_teacher()` makes.

    **The principal's remark is the principal's**, and it is deliberately not
    scoped to a class: a principal signs every card in the school. A vice
    principal cannot write it either, though they check the sheet — checking is
    a step in the chain, and signing the card is not.

    Neither may write the other's. A principal who could write the teacher's
    remark could put words under a teacher's name on a card that goes home.
    """
    school = school_on_this_connection()
    if not getattr(actor, "is_authenticated", False):
        raise NotAllowedToComment("Signing in is required to write a remark.")

    if author == CommentAuthor.PRINCIPAL.value:
        if Role.PRINCIPAL.value in set(actor.roles_at(school)):
            return school
        raise NotAllowedToComment(
            f"The principal's remark is signed by the principal of {school}, "
            f"and {actor} is not. A remark under somebody else's name on a card "
            f"that goes home is not a thing this can allow."
        )

    membership_id = actor.membership_id_at(school, Role.TEACHER)
    if academics.is_class_teacher(membership_id, placement.class_group, term):
        return school

    if academics.class_teacher_of(placement.class_group, term) is None:
        raise NotAllowedToComment(
            f"{placement.class_group} has no class teacher for {term}, so nobody "
            f"may write its remarks yet. A principal or an administrator assigns "
            f"one."
        )
    raise NotAllowedToComment(
        f"{actor} is not the class teacher of {placement.class_group} for "
        f"{term}, so may not write its remarks. The teacher's remark is the "
        f"class teacher's own judgement."
    )


def write_as(actor, term, membership, author, body, *, by=None) -> ReportCardComment:
    """`write()` for a caller with a request behind it.

    Authority is asked at the school on the connection, like every other write
    in this app, and the placement is read before it — because "may you write
    this" is a question about the group the child sits in, and there is no
    answer to it until we know which group that is.
    """
    _require_student_of_this_school(membership)
    placement = _require_placed(membership, term)
    author = _author(author)
    _require_authority_for(actor, author, placement, term)
    return write(
        term,
        membership,
        author,
        body,
        by=actor if by is None else by,
        # The row the authority question was just answered about. See `write()`.
        placement=placement,
    )


def clear_as(actor, term, membership, author) -> bool:
    """`clear()` for a caller with a request behind it."""
    _require_student_of_this_school(membership)
    placement = _require_placed(membership, term)
    author = _author(author)
    _require_authority_for(actor, author, placement, term)
    return clear(term, membership, author, placement=placement)


def add_phrase_as(actor, author, text, *, position=None) -> CommentPhrase:
    _require_configuring_authority(actor)
    return add_phrase(author, text, position=position)


def edit_phrase_as(actor, phrase, text) -> CommentPhrase:
    _require_configuring_authority(actor)
    return edit_phrase(phrase, text)


def remove_phrase_as(actor, phrase) -> bool:
    _require_configuring_authority(actor)
    return remove_phrase(phrase)


def reorder_phrases_as(actor, author, phrase_ids) -> int:
    _require_configuring_authority(actor)
    return reorder_phrases(author, phrase_ids)


__all__ = [
    "CONFIGURING_ROLES",
    "CommentLine",
    "CommentsError",
    "CommentsLocked",
    "NotAllowedToComment",
    "NotAllowedToConfigurePhrases",
    "NotPlacedThisTerm",
    "NotThisSchoolsStudent",
    "add_phrase",
    "add_phrase_as",
    "card_comments",
    "clear",
    "clear_as",
    "comments_for",
    "edit_phrase",
    "edit_phrase_as",
    "freeze_for_release",
    "missing",
    "phrases",
    "remove_phrase",
    "remove_phrase_as",
    "reorder_phrases",
    "reorder_phrases_as",
    "sheet_for",
    "write",
    "write_as",
]
