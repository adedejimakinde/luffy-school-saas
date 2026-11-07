"""Question banks and their questions: writing, editing, retiring. `docs/cbt.md`, step 3.

Every function asks who is asking first (`cbt.access.reach()`), for the current term,
and refuses with `NotAllowed` before it reads anything else: a teacher writes into the
banks of the subjects and levels they teach this term, the principal into any, and
nobody else into one. The routes ask too (`cbt.api`); this is the second asking, so a
later caller that forgets the first still meets this one.

**A question is plain text.** Whitespace at either end is trimmed and control
characters other than a line break are taken out; nothing is parsed as markup, and every
page that shows a question escapes it. Powers are typed as characters (x², 10³), which
is what "plain text" can carry; the page's faces draw superscript digits and not, yet,
subscript ones (`tests/glyphs.py`), though either is kept as typed.

**Saving makes a new version** (`Question.version`). A test already sent for approval
holds its own copy (`TestItem`) and never sees the edit. A question a test has used is
retired, not deleted, and a retired one is never drawn into a new test.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional, Sequence

from django.db import transaction
from django.utils import timezone

from academics.models import ClassGroup
from gradebook.models import Subject

from . import access
from .models import (
    MAX_EXPLANATION,
    MAX_IMAGE_ALT,
    MAX_MARKS,
    MAX_OPTION,
    MAX_STEM,
    MAX_TOPIC,
    Question,
    QuestionBank,
    QuestionOption,
    TestItem,
)

LETTERS = "ABCDE"


class BankError(Exception):
    """A bank or a question could not be changed as asked."""


class NotAllowed(BankError):
    """This login does not write into (or read) this bank."""


class NotYours(NotAllowed):
    """No such question or test in this login's reach: "not here" and "not yours" alike."""


class Refused(BankError):
    """Well formed, and the rules say no. The message is the reason, for the person."""


def current_term():
    from academics.models import Term

    return Term.objects.filter(is_current=True).first()


def name_of(user) -> str:
    return getattr(user, "full_name", "") or getattr(user, "username", "") or "Somebody"


_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def plain(text, *, limit: int, what: str, required: bool = True, lines: bool = True) -> str:
    """Plain text as it is kept: trimmed, without control characters, at most `limit`."""
    text = unicodedata.normalize("NFC", str(text or "")).replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub("", text)
    if not lines:
        text = " ".join(text.split())
    text = text.strip()
    if required and not text:
        raise Refused(f"{what} cannot be empty.")
    if len(text) > limit:
        raise Refused(f"{what} can be at most {limit} characters; this is {len(text)}.")
    return text


# -- reaching a bank --------------------------------------------------------------------


def reach_now(actor, school):
    return access.reach(actor, school, current_term())


def level_names(levels=None) -> dict:
    """`{level: "JSS 2"}`: what the school calls a level, from its classes' names.

    The longest start the active classes at a level share, less a trailing arm letter
    ("JSS 2A" and "JSS 2B" make "JSS 2"); one class names its level itself. A level with
    no class is "Level 3".
    """
    groups = ClassGroup.objects.filter(is_active=True)
    if levels is not None:
        groups = groups.filter(level__in=set(levels))
    names = {}
    for level, name in groups.order_by("level", "name").values_list("level", "name"):
        names.setdefault(level, []).append(name)
    out = {}
    for level, these in names.items():
        if len(these) == 1:
            out[level] = these[0]
            continue
        start = these[0]
        for other in these[1:]:
            while not other.startswith(start):
                start = start[:-1]
        start = start.rstrip(" -/(")
        out[level] = start or f"Level {level}"
    for level in levels or ():
        out.setdefault(level, f"Level {level}")
    return out


def _subject(subject_id) -> Subject:
    subject = Subject.objects.filter(pk=subject_id).first()
    if subject is None:
        raise Refused("There is no such subject here.")
    return subject


def require_read(actor, school, subject_id, level, reach=None):
    reach = reach or reach_now(actor, school)
    if not reach.reads_bank(subject_id, level):
        raise NotAllowed("This bank is read by its subject's teachers at that level, the vice principal and the principal.")
    return reach


def require_write(actor, school, subject_id, level, reach=None):
    reach = reach or reach_now(actor, school)
    if not reach.writes_bank(subject_id, level):
        raise NotAllowed("Questions are written by the subject's teachers at that level, and the principal.")
    return reach


def bank_of(subject_id, level) -> Optional[QuestionBank]:
    return QuestionBank.objects.filter(subject_id=subject_id, level=level).select_related("subject").first()


def _bank_for_writing(actor, subject_id, level) -> QuestionBank:
    subject = _subject(subject_id)
    if not ClassGroup.objects.filter(level=level).exists():
        raise Refused("No class is at that level here.")
    bank, _ = QuestionBank.objects.get_or_create(subject=subject, level=level, defaults={"created_by_id": actor.pk})
    return bank


# -- a question as it is written ----------------------------------------------------------


@dataclass
class Draft:
    """What a teacher typed, before it is checked."""

    stem: str
    options: Sequence[str]
    correct_index: int
    marks: int = 1
    topic: str = ""
    explanation: str = ""
    image_key: str = ""
    image_alt: str = ""


def _checked(draft: Draft) -> dict:
    stem = plain(draft.stem, limit=MAX_STEM, what="The question")
    given = list(draft.options or [])
    if len(given) not in (4, 5):
        raise Refused("A question has four options (A to D) or five (A to E).")
    options = [plain(o, limit=MAX_OPTION, what=f"Option {LETTERS[i]}", lines=False) for i, o in enumerate(given)]
    seen = {}
    for i, text in enumerate(options):
        key = text.casefold()
        if key in seen:
            raise Refused(f"Options {LETTERS[seen[key]]} and {LETTERS[i]} say the same thing. Each option must be different.")
        seen[key] = i
    try:
        correct = int(draft.correct_index)
    except (TypeError, ValueError):
        correct = -1
    if not 0 <= correct < len(options):
        raise Refused("Choose which option is the correct answer.")
    try:
        marks = int(draft.marks)
    except (TypeError, ValueError):
        marks = 0
    if not 1 <= marks <= MAX_MARKS:
        raise Refused(f"A question carries 1 to {MAX_MARKS} marks.")
    image_key = (draft.image_key or "").strip()
    image_alt = plain(draft.image_alt, limit=MAX_IMAGE_ALT, what="The picture's description", required=False, lines=False)
    if image_key:
        _require_a_picture(image_key)
        if not image_alt:
            raise Refused("Describe the picture for a student who cannot see it.")
    else:
        image_alt = ""
    return {
        "stem": stem,
        "options": options,
        "option_count": len(options),
        "correct_index": correct,
        "marks": marks,
        "topic": plain(draft.topic, limit=MAX_TOPIC, what="The topic", required=False, lines=False),
        "explanation": plain(draft.explanation, limit=MAX_EXPLANATION, what="The explanation", required=False),
        "image_key": image_key,
        "image_alt": image_alt,
    }


def _require_a_picture(key):
    from files import service
    from files.kinds import Kind

    stored = service.find(key)
    if stored is None or stored.kind != Kind.QUESTION_IMAGE or stored.state == "failed":
        raise Refused("That picture is not here. Add it again.")


def _write_options(question, options):
    QuestionOption.objects.filter(question=question).delete()
    QuestionOption.objects.bulk_create(
        QuestionOption(question=question, position=i, text=text) for i, text in enumerate(options)
    )


def add_as(actor, school, subject_id, level, draft: Draft) -> Question:
    """A new question in the bank of `subject_id` at `level`, made if it is the first."""
    require_write(actor, school, subject_id, level)
    fields = _checked(draft)
    options = fields.pop("options")
    with transaction.atomic():
        bank = _bank_for_writing(actor, subject_id, level)
        question = Question.objects.create(
            bank=bank,
            created_by_id=actor.pk,
            created_by_name=name_of(actor),
            updated_by_id=actor.pk,
            updated_by_name=name_of(actor),
            **fields,
        )
        _write_options(question, options)
    return question


def _question_for(actor, school, question_id, *, write: bool, lock: bool = False) -> Question:
    """The question, once this login is shown to reach its bank. One refusal for both
    "no such question" and "not yours", so an id says nothing about another bank."""
    reach = reach_now(actor, school)
    if not reach.reads_any_bank:
        raise NotYours("There is no such question in a bank of yours.")
    rows = Question.objects.select_related("bank", "bank__subject")
    if lock:
        rows = rows.select_for_update(of=("self",))
    question = rows.filter(pk=question_id).first()
    allowed = question is not None and (
        reach.writes_bank(question.bank.subject_id, question.bank.level)
        if write
        else reach.reads_bank(question.bank.subject_id, question.bank.level)
    )
    if not allowed:
        raise NotYours("There is no such question in a bank of yours.")
    return question


def question_as(actor, school, question_id) -> Question:
    return _question_for(actor, school, question_id, write=False)


def edit_as(actor, school, question_id, draft: Draft, *, version: int) -> Question:
    """Save a new version of a question. `version` is the one the writer was shown.

    A tap on Save over a version somebody else saved since is refused with a sentence,
    rather than writing over what the writer never saw.
    """
    fields = _checked(draft)
    options = fields.pop("options")
    with transaction.atomic():
        question = _question_for(actor, school, question_id, write=True, lock=True)
        if question.source != Question.Source.SCHOOL:
            raise Refused("A provider's question cannot be edited. Copy it to your bank instead.")
        if question.is_retired:
            raise Refused("This question is retired. It is kept for the tests that used it.")
        if int(version) != question.version:
            raise Refused(
                f"{question.updated_by_name} saved this question since you opened it. Open it again to see their version."
            )
        for name, value in fields.items():
            setattr(question, name, value)
        question.version += 1
        question.updated_by_id = actor.pk
        question.updated_by_name = name_of(actor)
        question.save()
        _write_options(question, options)
    return question


def retire_as(actor, school, question_id) -> Question:
    """Take a question out of use. It stays, for the tests that copied it."""
    with transaction.atomic():
        question = _question_for(actor, school, question_id, write=True, lock=True)
        if question.is_retired:
            raise Refused("This question is retired already.")
        question.retired_at = timezone.now()
        question.updated_by_id = actor.pk
        question.updated_by_name = name_of(actor)
        question.save(update_fields=["retired_at", "updated_by_id", "updated_by_name", "updated_at"])
    return question


def delete_as(actor, school, question_id) -> None:
    """Delete a question no test has used. A used one is retired instead."""
    with transaction.atomic():
        question = _question_for(actor, school, question_id, write=True, lock=True)
        if TestItem.objects.filter(origin_question=question).exists():
            raise Refused("A test has used this question, so it is kept. Retire it instead.")
        question.delete()


def used_in(question_ids) -> dict:
    """`{question id: how many tests copied it}`. One query."""
    from django.db.models import Count

    return dict(
        TestItem.objects.filter(origin_question_id__in=list(question_ids))
        .values("origin_question_id")
        .annotate(n=Count("test_id", distinct=True))
        .values_list("origin_question_id", "n")
    )


def live_questions(bank):
    return Question.objects.filter(bank=bank, retired_at__isnull=True)


__all__ = [
    "BankError",
    "Draft",
    "LETTERS",
    "NotAllowed",
    "NotYours",
    "Refused",
    "add_as",
    "bank_of",
    "current_term",
    "delete_as",
    "edit_as",
    "level_names",
    "live_questions",
    "plain",
    "question_as",
    "require_read",
    "require_write",
    "retire_as",
    "used_in",
]
