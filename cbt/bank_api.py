"""HTTP for question banks and tests: the `/tests/` screen. `docs/cbt.md`, step 3.

Mounted under `/api/cbt/` beside the exam slips routes (`cbt.api`). Tenant-host only.
**Every route asks who is asking before it looks anything up** (the oracle rule), and
`cbt.banks` and `cbt.setting` ask again and hold every rule:

- **Banks and questions** answer the principal, the vice principal (to read) and a
  teacher for the subjects and levels they teach this term. **Never a login holding the
  administrator role**, nor a bursar, a parent or a student: 403, before any row is read.
- **Tests** answer the same people for the tests they reach, and the administrator with
  the list alone: title, subject, classes, window, size, state and whether a code is
  set. No route gives the administrator a question, an option or an answer; a test's
  own page refuses them.
- **A question's answer** (`correct_index`, `explanation`) is in a bank's or a test's
  page for staff who read it, and in nothing shaped for a student: the preview is
  `cbt.paper.for_device()`, which carries no key.

A picture in a question is sent only by `pictures/`, to a login that reads a bank or a
test naming it, with `Cache-Control: private, no-store` (`files.views.send`).
"""

from datetime import datetime
from typing import List, Optional

from django.http import Http404, HttpResponse
from django.utils import timezone
from ninja import Router, Schema

from academics.models import ClassGroup
from accounts.session import session_auth
from gradebook.models import Subject

from . import access, banks, paper, setting
from .models import (
    Question,
    QuestionBank,
    Test,
    TestAudience,
    TestAudienceChange,
    TestItem,
    TestSection,
    TestStateChange,
)

router = Router(auth=session_auth)

_NOT_BANKS = "Question banks are read by teachers of the subject, the vice principal and the principal."
_NOT_TESTS = "Tests are set by teachers and approved by the principal or the vice principal."
_SUMMARY_ONLY = (
    "The administrator sees each test's title, classes, window and size on the list, and never its questions."
)


class MessageOut(Schema):
    detail: str


# -- shapes --------------------------------------------------------------------------------


class BankRowOut(Schema):
    subject_id: int
    subject: str
    level: int
    level_name: str
    #: Questions in use, and retired ones.
    in_use: int
    retired: int
    may_write: bool


class BanksOut(Schema):
    term: Optional[str] = None
    may_write: bool
    banks: List[BankRowOut]
    #: Why the list is empty, for a teacher with no subject this term.
    empty_because: str = ""


class PictureOut(Schema):
    key: str
    state: str
    url: Optional[str] = None
    error: str = ""


class QuestionOut(Schema):
    id: int
    stem: str
    options: List[str]
    correct_index: int
    marks: int
    topic: str
    explanation: str
    picture: Optional[PictureOut] = None
    image_alt: str
    version: int
    retired: bool
    used_in: int
    updated_by: str
    updated_at: str


class BankOut(Schema):
    subject_id: int
    subject: str
    level: int
    level_name: str
    may_write: bool
    #: Who reads it, in a sentence.
    readers: str
    questions: List[QuestionOut]


class QuestionIn(Schema):
    stem: str
    options: List[str]
    correct_index: int
    marks: int = 1
    topic: str = ""
    explanation: str = ""
    image_key: str = ""
    image_alt: str = ""
    #: The version the writer was shown, on an edit.
    version: int = 0


class ClassOut(Schema):
    id: int
    name: str


class TestRowOut(Schema):
    """What anybody who opens the Tests page may see of a test. **No question in it.**"""

    id: int
    title: str
    subject: str
    level_name: str
    classes: List[ClassOut]
    state: str
    state_label: str
    opens_at: str
    closes_at: str
    opens: str
    closes: str
    duration: int
    #: How many questions it has.
    size: int
    code_set: bool
    set_by: str


class ChoiceOut(Schema):
    subject_id: int
    subject: str
    level: int
    level_name: str
    in_use: int
    classes: List[ClassOut]


class TestsOut(Schema):
    term: Optional[str] = None
    #: The administrator: the list alone, and no test's own page.
    summaries_only: bool
    may_set: bool
    approves: bool
    tests: List[TestRowOut]
    #: Where a new test can draw from, for a login that sets tests.
    choices: List[ChoiceOut]


class ItemOut(Schema):
    number: int
    stem: str
    options: List[str]
    correct_index: int
    marks: int
    explanation: str
    topic: str
    picture_url: Optional[str] = None
    image_alt: str
    origin_question_id: int
    origin_version: int


class ChangeOut(Schema):
    what: str
    by: str
    note: str
    at: str


class TestOut(TestRowOut):
    subject_id: int
    level: int
    class_group_ids: List[int]
    question_count: int
    late_window: int
    shuffle_questions: bool
    shuffle_options: bool
    can_go_back: bool
    grid: bool
    calculator: bool
    require_pin: bool
    may_send_to_ca: bool
    total_marks: int
    items: List[ItemOut]
    history: List[ChangeOut]
    may_edit: bool
    may_submit: bool
    may_withdraw: bool
    may_approve: bool
    may_change_classes: bool
    may_delete: bool
    #: Classes the login could add to it, at its level.
    class_choices: List[ClassOut]


class TestIn(Schema):
    title: str
    subject_id: int
    level: int
    class_group_ids: List[int]
    question_count: int
    opens_at: datetime
    closes_at: datetime
    duration: int
    late_window: int = 2
    shuffle_questions: bool = True
    shuffle_options: bool = True
    can_go_back: bool = True
    grid: bool = True
    calculator: bool = False
    require_pin: bool = True


class NoteIn(Schema):
    note: str = ""


class ClassesIn(Schema):
    class_group_ids: List[int]


class PaperOptionOut(Schema):
    index: int
    text: str


class PaperItemOut(Schema):
    id: int
    number: int
    stem: str
    image: Optional[str] = None
    image_alt: str
    marks: int
    options: List[PaperOptionOut]


class PaperOut(Schema):
    """The paper as a student's device would get it. No `correct_index`, no explanation."""

    title: str
    duration: int
    can_go_back: bool
    grid: bool
    calculator: bool
    items: List[PaperItemOut]


# -- helpers -------------------------------------------------------------------------------


def _school_of(request):
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("No tests on this host.")
    return school


def _worded(at) -> str:
    return timezone.localtime(at).strftime("%-d %b %Y, %H:%M")


def _term_label(term) -> Optional[str]:
    if term is None:
        return None
    from academics.models import TermName

    return f"{TermName(term.name).label}, {term.session}"


def _bank_reach(request, school):
    """The reach, or None if this login reads no bank by its roles: asked before any row."""
    if not access.can_read_banks(request.user, school):
        return None
    return banks.reach_now(request.user, school)


def picture_url(key: str) -> str:
    return f"/api/cbt/pictures/{key}/full.webp"


def _picture(key) -> Optional[PictureOut]:
    if not key:
        return None
    from files import service

    stored = service.find(key)
    if stored is None:
        return PictureOut(key=key, state="missing", error="This picture is no longer here. Add it again.")
    return PictureOut(
        key=key,
        state=stored.state,
        url=picture_url(key) if stored.state == "ready" else None,
        error=stored.error,
    )


def _question_out(q, used) -> QuestionOut:
    options = [o.text for o in sorted(q.options.all(), key=lambda o: o.position)]
    return QuestionOut(
        id=q.pk,
        stem=q.stem,
        options=options,
        correct_index=q.correct_index,
        marks=q.marks,
        topic=q.topic,
        explanation=q.explanation,
        picture=_picture(q.image_key),
        image_alt=q.image_alt,
        version=q.version,
        retired=q.is_retired,
        used_in=used.get(q.pk, 0),
        updated_by=q.updated_by_name,
        updated_at=_worded(q.updated_at),
    )


def _draft(payload: QuestionIn) -> banks.Draft:
    return banks.Draft(
        stem=payload.stem,
        options=payload.options,
        correct_index=payload.correct_index,
        marks=payload.marks,
        topic=payload.topic,
        explanation=payload.explanation,
        image_key=payload.image_key,
        image_alt=payload.image_alt,
    )


# -- banks ---------------------------------------------------------------------------------


def _reachable_pairs(reach) -> set:
    """(subject id, level) of every bank this reach reads: its own pairs, and for a reader
    of all, every bank that exists and every pair somebody teaches this term."""
    pairs = set(reach.bank_pairs)
    if reach.reads_all:
        from gradebook.models import SubjectTeacher

        pairs |= set(QuestionBank.objects.values_list("subject_id", "level"))
        term = banks.current_term()
        if term is not None:
            taught = SubjectTeacher.objects.filter(term=term, class_group__is_active=True)
            pairs |= set(taught.values_list("subject_id", "class_group__level"))
    return pairs


@router.get("/banks/", response={200: BanksOut, 403: MessageOut})
def bank_list(request):
    school = _school_of(request)
    reach = _bank_reach(request, school)
    if reach is None:
        return 403, MessageOut(detail=_NOT_BANKS)
    from django.db.models import Count, Q

    pairs = _reachable_pairs(reach)
    subjects = dict(Subject.objects.filter(pk__in={s for s, _ in pairs}).values_list("pk", "name"))
    counts = {
        (row["subject_id"], row["level"]): row
        for row in QuestionBank.objects.filter(subject_id__in=subjects)
        .values("subject_id", "level")
        .annotate(
            in_use=Count("questions", filter=Q(questions__retired_at__isnull=True)),
            retired=Count("questions", filter=Q(questions__retired_at__isnull=False)),
        )
    }
    names = banks.level_names({level for _, level in pairs})
    rows = sorted(
        (
            BankRowOut(
                subject_id=s,
                subject=subjects[s],
                level=level,
                level_name=names.get(level, f"Level {level}"),
                in_use=counts.get((s, level), {}).get("in_use", 0),
                retired=counts.get((s, level), {}).get("retired", 0),
                may_write=reach.writes_bank(s, level),
            )
            for s, level in pairs
            if s in subjects
        ),
        key=lambda r: (r.level, r.subject.casefold()),
    )
    empty = ""
    if not rows:
        empty = (
            "You have no subject to teach this term yet. The principal says who teaches what, "
            "and your banks are the subjects and classes you are given."
            if not reach.reads_all
            else "No subject is taught by anybody this term yet, and no bank has a question."
        )
    return 200, BanksOut(term=_term_label(banks.current_term()), may_write=reach.writes_any, banks=rows, empty_because=empty)


@router.get("/banks/{int:subject_id}/{int:level}/", response={200: BankOut, 403: MessageOut, 404: MessageOut})
def bank_detail(request, subject_id: int, level: int):
    school = _school_of(request)
    reach = _bank_reach(request, school)
    if reach is None:
        return 403, MessageOut(detail=_NOT_BANKS)
    try:
        banks.require_read(request.user, school, subject_id, level, reach=reach)
    except banks.NotAllowed:
        return 404, MessageOut(detail="There is no such bank of yours here.")
    subject = Subject.objects.filter(pk=subject_id).first()
    if subject is None:
        return 404, MessageOut(detail="There is no such bank of yours here.")
    bank = banks.bank_of(subject_id, level)
    questions = list(Question.objects.filter(bank=bank).prefetch_related("options").order_by("retired_at", "-updated_at", "-id")) if bank else []
    used = banks.used_in(q.pk for q in questions)
    level_name = banks.level_names({level}).get(level, f"Level {level}")
    return 200, BankOut(
        subject_id=subject.pk,
        subject=subject.name,
        level=level,
        level_name=level_name,
        may_write=reach.writes_bank(subject_id, level),
        readers=f"Only teachers of {subject.name} in {level_name}, the vice principal and the principal see this bank. "
        "Students never see a question until a test opens, and never see an answer.",
        questions=[_question_out(q, used) for q in questions],
    )


_WRITE = {200: QuestionOut, 403: MessageOut, 404: MessageOut, 422: MessageOut}


@router.post("/banks/{int:subject_id}/{int:level}/questions/", response=_WRITE)
def add_question(request, subject_id: int, level: int, payload: QuestionIn):
    school = _school_of(request)
    if _bank_reach(request, school) is None:
        return 403, MessageOut(detail=_NOT_BANKS)
    try:
        question = banks.add_as(request.user, school, subject_id, level, _draft(payload))
    except banks.NotAllowed as exc:
        return 403, MessageOut(detail=str(exc))
    except banks.Refused as exc:
        return 422, MessageOut(detail=str(exc))
    return 200, _question_out(question, {})


@router.post("/banks/{int:subject_id}/{int:level}/pictures/", response={200: PictureOut, 403: MessageOut, 422: MessageOut})
def add_picture(request, subject_id: int, level: int):
    """A picture for a question, as a multipart `picture`: PNG, JPG or WebP, at most 5 MB.

    Read from `request.FILES` by hand, after the authority check, for the reason
    `academics.api.set_card_crest` gives. Answers with the key the question then names.
    """
    school = _school_of(request)
    reach = _bank_reach(request, school)
    if reach is None:
        return 403, MessageOut(detail=_NOT_BANKS)
    try:
        banks.require_write(request.user, school, subject_id, level, reach=reach)
    except banks.NotAllowed as exc:
        return 403, MessageOut(detail=str(exc))
    from files import service
    from files.kinds import Kind

    upload = request.FILES.get("picture")
    try:
        stored = service.accept(Kind.QUESTION_IMAGE, upload, by=request.user)
    except service.UploadRefused as exc:
        return 422, MessageOut(detail=str(exc))
    if stored.state == "failed":
        return 422, MessageOut(detail=stored.error)
    return 200, _picture(stored.key)


def _reads_picture(request, school, key) -> bool:
    """Does this login read a bank, or a test's questions, that names this picture?"""
    if not access.can_read_banks(request.user, school):
        return False
    reach = banks.reach_now(request.user, school)
    for bank in QuestionBank.objects.filter(questions__image_key=key).distinct():
        if reach.reads_bank(bank.subject_id, bank.level):
            return True
    for test in Test.objects.filter(items__image_key=key).distinct():
        if setting.reads_questions(access.reach(request.user, school, test.term), test):
            return True
    # A picture just uploaded, not yet saved with a question: its uploader's.
    from files import service

    stored = service.find(key)
    named = Question.objects.filter(image_key=key).exists() or TestItem.objects.filter(image_key=key).exists()
    return stored is not None and not named and stored.uploaded_by_id == request.user.pk


@router.get("/pictures/{key}/{variant}", response={403: MessageOut, 404: MessageOut})
def picture(request, key: str, variant: str):
    school = _school_of(request)
    if not access.can_read_banks(request.user, school):
        return 403, MessageOut(detail=_NOT_BANKS)
    from files import service, views
    from files.kinds import Kind

    if variant not in ("full.webp", "small.webp") or len(key) != 32:
        return 404, MessageOut(detail="No such picture.")
    stored = service.find(key)
    if stored is None or stored.kind != Kind.QUESTION_IMAGE or not _reads_picture(request, school, key):
        return 404, MessageOut(detail="No such picture.")
    try:
        return views.send(stored, variant, cache_control=views.PRIVATE)
    except Http404:
        return 404, MessageOut(detail="No such picture.")


@router.get("/questions/{int:question_id}/", response={200: QuestionOut, 403: MessageOut, 404: MessageOut})
def question_detail(request, question_id: int):
    school = _school_of(request)
    if _bank_reach(request, school) is None:
        return 403, MessageOut(detail=_NOT_BANKS)
    try:
        question = banks.question_as(request.user, school, question_id)
    except banks.NotYours as exc:
        return 404, MessageOut(detail=str(exc))
    except banks.NotAllowed as exc:
        return 403, MessageOut(detail=str(exc))
    return 200, _question_out(question, banks.used_in([question.pk]))


@router.post("/questions/{int:question_id}/", response=_WRITE)
def edit_question(request, question_id: int, payload: QuestionIn):
    school = _school_of(request)
    if _bank_reach(request, school) is None:
        return 403, MessageOut(detail=_NOT_BANKS)
    try:
        question = banks.edit_as(request.user, school, question_id, _draft(payload), version=payload.version)
    except banks.NotYours as exc:
        return 404, MessageOut(detail=str(exc))
    except banks.NotAllowed as exc:
        return 403, MessageOut(detail=str(exc))
    except banks.Refused as exc:
        return 422, MessageOut(detail=str(exc))
    return 200, _question_out(question, banks.used_in([question.pk]))


@router.post("/questions/{int:question_id}/retire/", response=_WRITE)
def retire_question(request, question_id: int):
    school = _school_of(request)
    if _bank_reach(request, school) is None:
        return 403, MessageOut(detail=_NOT_BANKS)
    try:
        question = banks.retire_as(request.user, school, question_id)
    except banks.NotYours as exc:
        return 404, MessageOut(detail=str(exc))
    except banks.NotAllowed as exc:
        return 403, MessageOut(detail=str(exc))
    except banks.Refused as exc:
        return 422, MessageOut(detail=str(exc))
    return 200, _question_out(question, banks.used_in([question.pk]))


@router.post("/questions/{int:question_id}/delete/", response={200: MessageOut, 403: MessageOut, 404: MessageOut, 422: MessageOut})
def delete_question(request, question_id: int):
    school = _school_of(request)
    if _bank_reach(request, school) is None:
        return 403, MessageOut(detail=_NOT_BANKS)
    try:
        banks.delete_as(request.user, school, question_id)
    except banks.NotYours as exc:
        return 404, MessageOut(detail=str(exc))
    except banks.NotAllowed as exc:
        return 403, MessageOut(detail=str(exc))
    except banks.Refused as exc:
        return 422, MessageOut(detail=str(exc))
    return 200, MessageOut(detail="Deleted.")


# -- tests ---------------------------------------------------------------------------------


def _rows(tests):
    """Every test's row, in four queries whatever the number of tests."""
    tests = list(tests)
    ids = [t.pk for t in tests]
    sections = {
        s.test_id: s for s in TestSection.objects.filter(test_id__in=ids).select_related("bank", "bank__subject")
    }
    classes = {}
    for a in TestAudience.objects.filter(test_id__in=ids).select_related("class_group"):
        classes.setdefault(a.test_id, []).append(ClassOut(id=a.class_group_id, name=a.class_group.name))
    names = banks.level_names({s.bank.level for s in sections.values()})
    out = []
    for t in tests:
        section = sections.get(t.pk)
        out.append(
            dict(
                id=t.pk,
                title=t.title,
                subject=section.bank.subject.name if section else "",
                level_name=names.get(section.bank.level, "") if section else "",
                classes=classes.get(t.pk, []),
                state=t.state,
                state_label=Test.State(t.state).label,
                opens_at=t.opens_at.isoformat(),
                closes_at=t.closes_at.isoformat(),
                opens=_worded(t.opens_at),
                closes=_worded(t.closes_at),
                duration=t.duration,
                size=section.question_count if section else 0,
                code_set=bool(t.code_digest),
                set_by=t.created_by_name,
            )
        )
    return out, sections


def _visible(request, school, tests):
    """The tests this login reaches. The administrator's are all, as summaries.

    Each test's subject and classes are read for all of them at once, so a teacher's
    list costs what a principal's does, whatever the number of tests.
    """
    tests = list(tests)
    ids = [t.pk for t in tests]
    subjects = dict(TestSection.objects.filter(test_id__in=ids, position=0).values_list("test_id", "bank__subject_id"))
    classes = {}
    for test_id, class_id in TestAudience.objects.filter(test_id__in=ids).values_list("test_id", "class_group_id"):
        classes.setdefault(test_id, set()).add(class_id)
    out = []
    reaches = {}
    for t in tests:
        reach = reaches.get(t.term_id)
        if reach is None:
            reach = reaches[t.term_id] = access.reach(request.user, school, t.term)
        theirs = set(classes.get(t.pk, ()))
        if reach.sees_test_summaries or reach.reads_all:
            out.append(t)
        elif reach.class_pairs and (
            setting.teaches_it(reach, t, subjects.get(t.pk), theirs)
            or (t.created_by_id == request.user.pk and not theirs)
        ):
            out.append(t)
    return out


def _choices(reach) -> List[ChoiceOut]:
    if not reach.writes_any:
        return []
    from django.db.models import Count, Q

    groups = list(ClassGroup.objects.filter(is_active=True).order_by("level", "name"))
    if reach.writes_all:
        pairs = {(s, g.level) for s in Subject.objects.filter(is_active=True).values_list("pk", flat=True) for g in groups}
    else:
        pairs = set(reach.bank_pairs)
    in_use = {
        (row["subject_id"], row["level"]): row["n"]
        for row in QuestionBank.objects.values("subject_id", "level").annotate(
            n=Count("questions", filter=Q(questions__retired_at__isnull=True))
        )
    }
    subjects = dict(Subject.objects.filter(pk__in={s for s, _ in pairs}).values_list("pk", "name"))
    names = banks.level_names({level for _, level in pairs})
    out = []
    for s, level in pairs:
        if s not in subjects or not in_use.get((s, level)):
            continue
        classes = [ClassOut(id=g.pk, name=g.name) for g in groups if g.level == level and reach.teaches(s, g.pk)]
        if classes:
            out.append(
                ChoiceOut(
                    subject_id=s, subject=subjects[s], level=level, level_name=names.get(level, f"Level {level}"),
                    in_use=in_use[(s, level)], classes=classes,
                )
            )
    return sorted(out, key=lambda c: (c.level, c.subject.casefold()))


@router.get("/tests/", response={200: TestsOut, 403: MessageOut})
def test_list(request):
    school = _school_of(request)
    if not access.may_open_tests(request.user, school):
        return 403, MessageOut(detail=_NOT_TESTS)
    term = banks.current_term()
    reach = access.reach(request.user, school, term)
    tests = _visible(request, school, Test.objects.select_related("term").order_by("-opens_at", "-id")[:200])
    rows, _ = _rows(tests)
    return 200, TestsOut(
        term=_term_label(term),
        summaries_only=reach.sees_test_summaries,
        may_set=reach.writes_any,
        approves=reach.approves,
        tests=[TestRowOut(**r) for r in rows],
        choices=_choices(reach),
    )


def _test_out(request, school, test) -> TestOut:
    reach = access.reach(request.user, school, test.term)
    [row], sections = _rows([test])
    section = sections.get(test.pk)
    items = list(TestItem.objects.filter(test=test).order_by("position"))
    history = [
        ChangeOut(
            what=f"{Test.State(c.from_state).label} to {Test.State(c.to_state).label}",
            by=c.by_name, note=c.note, at=_worded(c.at),
        )
        for c in TestStateChange.objects.filter(test=test)
    ] + [
        ChangeOut(what=f"{c.class_group_name} {c.kind}", by=c.by_name, note="", at=_worded(c.at))
        for c in TestAudienceChange.objects.filter(test=test)
    ]
    writes = reach.writes_all or (bool(reach.class_pairs) and setting.teaches_it(reach, test)) or (
        test.created_by_id == request.user.pk and bool(reach.class_pairs) and not row["classes"]
    )
    draft = test.state == Test.State.DRAFT
    class_choices = []
    if writes and section:
        class_choices = [
            ClassOut(id=g.pk, name=g.name)
            for g in ClassGroup.objects.filter(is_active=True, level=section.bank.level).order_by("name")
            if reach.teaches(section.bank.subject_id, g.pk)
        ]
    return TestOut(
        **row,
        subject_id=section.bank.subject_id if section else 0,
        level=section.bank.level if section else 0,
        class_group_ids=[c.id for c in row["classes"]],
        question_count=section.question_count if section else 0,
        late_window=test.late_window,
        shuffle_questions=test.shuffle_questions,
        shuffle_options=test.shuffle_options,
        can_go_back=test.can_go_back,
        grid=test.grid,
        calculator=test.calculator,
        require_pin=test.require_pin,
        may_send_to_ca=test.may_send_to_ca,
        total_marks=sum(i.marks for i in items),
        items=[
            ItemOut(
                number=i.position + 1,
                stem=i.stem,
                options=list(i.options),
                correct_index=i.correct_index,
                marks=i.marks,
                explanation=i.explanation,
                topic=i.topic,
                picture_url=picture_url(i.image_key) if i.image_key else None,
                image_alt=i.image_alt,
                origin_question_id=i.origin_question_id,
                origin_version=i.origin_version,
            )
            for i in items
        ],
        history=history,
        may_edit=writes and draft,
        may_submit=writes and draft,
        may_withdraw=writes and test.state == Test.State.SUBMITTED,
        may_approve=reach.approves and test.state == Test.State.SUBMITTED,
        may_change_classes=writes and test.state in (Test.State.SUBMITTED, Test.State.PUBLISHED),
        may_delete=writes and draft and not TestStateChange.objects.filter(test=test).exists(),
        class_choices=class_choices,
    )


_TEST = {200: TestOut, 403: MessageOut, 404: MessageOut, 422: MessageOut}


def _test_reader(request, school):
    """None, or the refusal for a login that may not open a test's own page."""
    if not access.may_open_tests(request.user, school):
        return 403, MessageOut(detail=_NOT_TESTS)
    if not access.can_read_banks(request.user, school):
        return 403, MessageOut(detail=_SUMMARY_ONLY)
    return None


def _draft_of(payload: TestIn) -> setting.TestDraft:
    return setting.TestDraft(**payload.model_dump())


@router.post("/tests/", response=_TEST)
def create_test(request, payload: TestIn):
    school = _school_of(request)
    refused = _test_reader(request, school)
    if refused:
        return refused
    try:
        test = setting.create_as(request.user, school, _draft_of(payload))
    except banks.NotAllowed as exc:
        return 403, MessageOut(detail=str(exc))
    except banks.Refused as exc:
        return 422, MessageOut(detail=str(exc))
    return 200, _test_out(request, school, test)


@router.get("/tests/{int:test_id}/", response=_TEST)
def test_detail(request, test_id: int):
    school = _school_of(request)
    refused = _test_reader(request, school)
    if refused:
        return refused
    try:
        test, _ = setting.test_as(request.user, school, test_id)
    except banks.NotYours as exc:
        return 404, MessageOut(detail=str(exc))
    except banks.NotAllowed as exc:
        return 403, MessageOut(detail=str(exc))
    return 200, _test_out(request, school, test)


def _act(request, test_id, act):
    school = _school_of(request)
    refused = _test_reader(request, school)
    if refused:
        return refused
    try:
        act(school)
        test, _ = setting.test_as(request.user, school, test_id)
    except banks.NotYours as exc:
        return 404, MessageOut(detail=str(exc))
    except banks.NotAllowed as exc:
        return 403, MessageOut(detail=str(exc))
    except banks.Refused as exc:
        return 422, MessageOut(detail=str(exc))
    return 200, _test_out(request, school, test)


@router.post("/tests/{int:test_id}/", response=_TEST)
def update_test(request, test_id: int, payload: TestIn):
    return _act(request, test_id, lambda school: setting.update_as(request.user, school, test_id, _draft_of(payload)))


@router.post("/tests/{int:test_id}/submit/", response=_TEST)
def submit_test(request, test_id: int):
    return _act(request, test_id, lambda school: setting.submit_as(request.user, school, test_id))


@router.post("/tests/{int:test_id}/withdraw/", response=_TEST)
def withdraw_test(request, test_id: int):
    return _act(request, test_id, lambda school: setting.withdraw_as(request.user, school, test_id))


@router.post("/tests/{int:test_id}/send-back/", response=_TEST)
def send_back_test(request, test_id: int, payload: NoteIn):
    return _act(request, test_id, lambda school: setting.send_back_as(request.user, school, test_id, payload.note))


@router.post("/tests/{int:test_id}/approve/", response=_TEST)
def approve_test(request, test_id: int):
    return _act(request, test_id, lambda school: setting.approve_as(request.user, school, test_id))


@router.post("/tests/{int:test_id}/classes/", response=_TEST)
def change_classes(request, test_id: int, payload: ClassesIn):
    return _act(
        request, test_id, lambda school: setting.change_classes_as(request.user, school, test_id, payload.class_group_ids)
    )


@router.post("/tests/{int:test_id}/delete/", response={200: MessageOut, 403: MessageOut, 404: MessageOut, 422: MessageOut})
def delete_test(request, test_id: int):
    school = _school_of(request)
    refused = _test_reader(request, school)
    if refused:
        return refused
    try:
        setting.delete_as(request.user, school, test_id)
    except banks.NotYours as exc:
        return 404, MessageOut(detail=str(exc))
    except banks.NotAllowed as exc:
        return 403, MessageOut(detail=str(exc))
    except banks.Refused as exc:
        return 422, MessageOut(detail=str(exc))
    return 200, MessageOut(detail="Deleted.")


@router.get("/tests/{int:test_id}/preview/", response={200: PaperOut, 403: MessageOut, 404: MessageOut, 409: MessageOut})
def preview(request, test_id: int):
    """The paper as one student would get it ("Try it as a student"): a fresh order each
    time, and no answer. Built by `paper.for_device()`, the function step 4 sends."""
    school = _school_of(request)
    refused = _test_reader(request, school)
    if refused:
        return refused
    try:
        test, _ = setting.test_as(request.user, school, test_id)
    except banks.NotYours as exc:
        return 404, MessageOut(detail=str(exc))
    except banks.NotAllowed as exc:
        return 403, MessageOut(detail=str(exc))
    items = list(TestItem.objects.filter(test=test))
    if not items:
        return 409, MessageOut(detail="Its questions are drawn when it is sent for approval.")
    import secrets

    return 200, paper.for_device(test, items, secrets.token_hex(8), image_url=picture_url)


__all__ = ["router"]
