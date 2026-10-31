"""The administrator's setup steps, and which are done, read from the school's own tables.

## Done means the data is there

No step is ticked by hand. Each is a question asked of the tables that hold
the thing the step makes: a step is done when a class exists, not when
somebody said they added one. Deleting the last class makes "Add your classes"
undone again, and that is correct.

## One statement, uncached

`read()` is one `SELECT json_build_object(...)`, like `home.facts`. It is not
cached, for the reason `home.facts.load()` already gives for a school still
being set up: the numbers change with every step the office takes, and a step
should show done the moment it is. The existing per-school cache keeps its
five minutes for the dashboard's figures; reading the steps through it would
make a step look undone for up to five minutes after it was done.

So the cost is **one statement per page for an administrator whose school is
not yet set up, and none for anybody else**. `for_request()` keeps the answer
on the request, so the setup chip in the top bar and the page under it share
one read.

## The first time every required step holds is written down

`School.setup_completed_at` records when the required steps were first all
found done. After that the chip is gone and sign-in stops sending the
administrator to Start here, without reading anything: "a finished setup
never redirects again" holds even if a class is later deleted. Start here
itself still reads the steps, so what it shows is always the truth.

## Tenant safety

The statement names tenant tables bare, so it reads whichever schema the
connection is on, and `read()` refuses to run on any schema but the school's
own. Shared tables (`accounts_membership`) are read with `school_id = %s`.
"""

from dataclasses import dataclass, field
from typing import Optional

from django.db import connection
from django.utils import timezone
from django_tenants.utils import schema_context

from accounts.models import Role

#: Who may open Start here and the step pages: the school administrator and
#: the principal. The steps are mostly the administrator's to do, and several
#: of them (inviting staff, importing the roll) are the administrator's alone,
#: but a principal must be able to see where setup stands and open any step;
#: a step the viewer cannot do says who does it (`Step.doers`).
ONBOARDING_ROLES = frozenset({Role.ADMIN.value, Role.PRINCIPAL.value})

#: Who setup is brought to while it is unfinished: signing in lands them on
#: Start here, the top bar carries the setup chip, and the dashboard opens
#: with the next-step card. The administrator only. The principal's dashboard
#: says how far setup has got and links Start here, without the push.
LEAD_ROLES = frozenset({Role.ADMIN.value})


#: Who can do each kind of step, by the authority each page already asks.
_SETUP = frozenset({Role.ADMIN.value, Role.PRINCIPAL.value})  # academics.services.SETUP_ROLES
_GRANTING = frozenset({Role.ADMIN.value})  # accounts.models.MEMBERSHIP_GRANTING_ROLES
_FEES = frozenset({Role.ADMIN.value, Role.BURSAR.value})  # fees.authority.WRITING_ROLES


@dataclass(frozen=True)
class Step:
    key: str
    title: str
    #: One line under the title in the list.
    detail: str
    icon: str
    what: str
    why: str
    todo: tuple
    action: str
    href: str
    minutes: int
    optional: bool = False
    #: Another place on the platform this step also uses: (label, href).
    also: Optional[tuple] = None
    #: The facts this step goes better after, and the one line said about it
    #: while they are missing. Advice only: no step is ever locked, and the
    #: step's own button is always there.
    needs: tuple = ()
    hint: str = ""
    get_ready: tuple = ()
    #: The roles that can do this step's work, and who to name to anybody else.
    doers: frozenset = _SETUP
    done_by: str = "your principal or school administrator"

STEPS = (
    Step(
        key="school-details",
        title="Add your school details",
        detail="Contact email and crest. You can add either later",
        icon="i-school",
        what="Saves your school's contact email and its crest.",
        why="The crest heads every report card, and replies from parents go to the contact email, not to Classnode.",
        todo=(
            "Type the email address your office reads.",
            "Upload your crest as a PNG or JPG picture.",
            "Save each one, or choose Add later. You can change them any time.",
        ),
        action="Add the contact email",
        href="/setup/#contact-email",
        also=("Upload the crest", "/setup/#report-card"),
        minutes=2,
    ),
    Step(
        key="session-and-term",
        title="Set the session and term",
        detail="For example 2026/2027, First term, with its dates",
        icon="i-calendar",
        what="Opens the term your school is in now, inside its session.",
        why="Registers, marks, fees and report cards all belong to a term. Nothing else can start without one.",
        todo=(
            "Type the session, such as 2026/2027, pick the term and its first and last days, and save.",
            "Tap Make current beside it, so Classnode knows this is the term you are teaching now.",
            "Open next term the same way when its dates are known. It waits until you make it current.",
        ),
        action="Open the term setup",
        href="/setup/#terms",
        minutes=2,
    ),
    Step(
        key="classes",
        title="Add your classes",
        detail="JSS 1 to SS 3, with arms such as A, B and C",
        icon="i-sheet",
        what="Creates the classes your school runs, such as JSS 1A or SS 2 Science.",
        why="Every register, mark sheet and report card belongs to a class. Students can only be imported once their class exists.",
        todo=(
            "Type a class name, such as JSS 1A.",
            "Add one class for each arm you run.",
            "Save. You can rename, archive or add a class later.",
        ),
        action="Open class setup",
        href="/setup/#classes",
        minutes=5,
    ),
    Step(
        key="subjects",
        title="Add your subjects",
        detail="What your school teaches, such as Mathematics",
        icon="i-book",
        what="Lists the subjects your school teaches, each with a short code.",
        why="Marks are entered per subject, and the report card prints one line for each.",
        todo=(
            "Type the subject name, such as Mathematics.",
            "Give it a short code, such as MTH.",
            "Add the rest the same way.",
        ),
        action="Open subjects",
        href="/teaching/#subjects",
        minutes=5,
    ),
    Step(
        key="teachers",
        title="Invite your teachers",
        detail="They get a link to set their own password",
        icon="i-staff",
        what="Sends each teacher an invitation to Classnode by email.",
        why="Teachers take the register and enter marks themselves, so the office does not have to type them.",
        todo=(
            "Type the teacher's name and email address.",
            "Choose Teacher as the role and send.",
            "They set their own password from the email.",
        ),
        action="Invite teachers",
        href="/staff/",
        minutes=5,
        doers=_GRANTING,
        done_by="your school administrator",
    ),
    Step(
        key="students",
        title="Import your students",
        detail="Upload the roll from Excel or a CSV file",
        icon="i-people",
        what="Adds every student to the school and places each one in a class.",
        why="Registers list the students in a class, and each report card is one student's.",
        todo=(
            "Download the template and fill it in, one student a row.",
            "Upload the file and check what Classnode found.",
            "Confirm. Each student goes into their class.",
        ),
        action="Import students",
        href="/roll/import/",
        minutes=10,
        needs=("classes",),
        hint=(
            "Each student is placed in a class as they are imported, so add your classes "
            "too. The import will tell you about any class it cannot find."
        ),
        doers=_GRANTING,
        done_by="your school administrator",
        get_ready=(
            "Your roll as an Excel or CSV file",
            "Each student's surname, first name and class",
            "A parent's phone number, if you have it",
        ),
    ),
    Step(
        key="fees",
        title="Set up fee items",
        detail="Optional. School fees, PTA levy, uniform",
        icon="i-fees",
        what="Lists what parents pay this term, class by class.",
        why="With fee items in place the bursar can record payments and parents get receipts.",
        todo=(
            "Open a class's bill for this term.",
            "Add each item and its amount, such as School fees.",
            "Save. The bursar can change them later.",
        ),
        action="Open fees",
        href="/fees/",
        minutes=10,
        optional=True,
        needs=("term", "classes"),
        hint="Fees are set per class, for the current term, so you need a current term and a class to set them on.",
        doers=_FEES,
        done_by="your bursar or school administrator",
    ),
    Step(
        key="report-card",
        title="Set up the report card",
        detail="The Ogun State template or your own papers",
        icon="i-card",
        what="Chooses the report card your school prints and the papers each subject is marked on.",
        why="The papers, such as First CA and Exam, are what teachers enter marks against.",
        todo=(
            "Choose the standard card or the Ogun State template.",
            "With the Ogun State template the papers are set for you.",
            "With the standard card, add this term's papers yourself.",
        ),
        action="Choose the report card",
        href="/setup/#report-card",
        also=("Add this term's papers", "/teaching/#papers"),
        minutes=5,
        needs=("term", "subjects"),
        hint="Papers belong to a subject, in the current term, so you need both to add them. You can choose the card itself now.",
    ),
)

BY_KEY = {step.key: step for step in STEPS}
REQUIRED = tuple(step for step in STEPS if not step.optional)


@dataclass
class StepState:
    step: Step
    number: int
    state: str  # "done", "next" or "todo"
    status: str = ""
    #: What this step's done-ness let the office put off ("contact email",
    #: "crest"), for the list to say. Only the first step has any.
    later: tuple = ()

    @property
    def done(self):
        return self.state == "done"


@dataclass
class Progress:
    steps: list
    facts: dict
    complete: bool
    next: Optional[StepState] = None
    total: int = len(STEPS)
    done: int = 0
    minutes_left: int = 0
    by_key: dict = field(default_factory=dict)

    @property
    def percent(self):
        return round(self.done * 100 / self.total)

    @property
    def register_taken(self):
        return bool(self.facts.get("registers"))


# -- the statement -------------------------------------------------------------

_STEPS_SQL = """
WITH t AS (SELECT id FROM academics_term WHERE is_current ORDER BY starts_on DESC LIMIT 1)
SELECT json_build_object(
    'term', EXISTS (SELECT 1 FROM t),
    'terms', (SELECT count(*) FROM academics_term),
    'classes', (SELECT count(*) FROM academics_classgroup WHERE is_active),
    'subjects', (SELECT count(*) FROM gradebook_subject WHERE is_active),
    'teachers', (
        SELECT count(*) FROM accounts_membership
        WHERE school_id = %(school)s AND role = 'teacher' AND status IN ('active', 'invited')
    ),
    'students', (
        SELECT count(*) FROM accounts_membership
        WHERE school_id = %(school)s AND role = 'student' AND status IN ('active', 'invited')
    ),
    'fees', EXISTS (
        SELECT 1 FROM fees_feescheduleline l
        JOIN fees_feeschedule s ON s.id = l.schedule_id
        WHERE s.term_id = (SELECT id FROM t)
    ),
    'papers', EXISTS (SELECT 1 FROM gradebook_assessment WHERE term_id = (SELECT id FROM t)),
    'crest', (EXISTS (SELECT 1 FROM results_reportcardsettings WHERE crest IS NOT NULL)
              OR EXISTS (SELECT 1 FROM files_storedfile
                         WHERE slot = 'crest' AND state = 'ready' AND schema_name = current_schema())),
    'registers', EXISTS (SELECT 1 FROM attendance_register)
)
"""


class WrongSchema(RuntimeError):
    """`read()` was asked about one school on another school's connection."""


def read(school) -> dict:
    """The facts the steps are judged on: one statement, in the school's schema.

    On the school's own host the connection is already there. Anywhere else
    (the portal's sign-in, the platform's handover page) the statement runs
    inside `schema_context` and the connection goes back where it was."""
    if connection.schema_name == school.schema_name:
        return _read_here(school)
    with schema_context(school.schema_name):
        return _read_here(school)


def _read_here(school) -> dict:
    if connection.schema_name != school.schema_name:
        raise WrongSchema(f"Asked about {school.schema_name} on {connection.schema_name}.")
    with connection.cursor() as cursor:
        cursor.execute(_STEPS_SQL, {"school": school.pk})
        (facts,) = cursor.fetchone()
    facts["contact_email"] = bool(school.contact_email)
    facts["contact_email_later"] = school.contact_email_later_at is not None
    facts["crest_later"] = school.crest_later_at is not None
    return facts


# -- judging the steps ---------------------------------------------------------


def _is_done(key: str, f: dict) -> bool:
    return {
        # Each is given or put off: neither is needed to sign in or to recover
        # an account, so the office can choose "Add later" for either.
        "school-details": (f["contact_email"] or f.get("contact_email_later", False))
        and (f["crest"] or f.get("crest_later", False)),
        "session-and-term": f["term"],
        "classes": f["classes"] > 0,
        "subjects": f["subjects"] > 0,
        "teachers": f["teachers"] > 0,
        "students": f["students"] > 0,
        "fees": f["fees"],
        "report-card": f["papers"],
    }[key]


def _holds(fact: str, f: dict) -> bool:
    value = f[fact]
    return value > 0 if isinstance(value, int) and not isinstance(value, bool) else bool(value)


def _plural(n, one, many=None):
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _status(key: str, f: dict) -> str:
    """What is there now, in a few words, for the step page's action box."""
    if key == "school-details":
        def one(given, later, name):
            if given:
                return f"{name} saved"
            return f"{name} to add later" if later else f"no {name.lower()} yet"
        email = one(f["contact_email"], f.get("contact_email_later"), "Contact email")
        crest = one(f["crest"], f.get("crest_later"), "Crest")
        return f"{email[0].upper()}{email[1:]}, {crest[0].lower()}{crest[1:]}"
    if key == "session-and-term":
        if f["term"]:
            return "A term is current"
        if f.get("terms"):
            return "A term is saved but not current yet. Tap Make current beside it."
        return "No term yet"
    if key == "classes":
        return _plural(f["classes"], "class", "classes") if f["classes"] else "No classes yet"
    if key == "subjects":
        return _plural(f["subjects"], "subject") if f["subjects"] else "No subjects yet"
    if key == "teachers":
        return f"{_plural(f['teachers'], 'teacher')} invited or signed in" if f["teachers"] else "No teachers yet"
    if key == "students":
        return _plural(f["students"], "student") if f["students"] else "No students yet"
    if key == "fees":
        if f["fees"]:
            return "Fee items set for this term"
        return "No fee items this term" if f["term"] else "Fee items count once a term is current"
    if f["papers"]:
        return "Papers set for this term"
    return "No papers this term yet" if f["term"] else "Papers count once a term is current"


def _later(key: str, f: dict) -> tuple:
    if key != "school-details":
        return ()
    put_off = []
    if not f["contact_email"] and f.get("contact_email_later"):
        put_off.append("contact email")
    if not f["crest"] and f.get("crest_later"):
        put_off.append("crest")
    return tuple(put_off)


def judge(facts: dict) -> Progress:
    """The steps' states from the facts. Pure, so every rule is testable alone.

    **Any order, nothing locked.** Each step is done when its data is there,
    whichever order it got there in, and a step that is not done is "todo",
    open to anybody who may see the steps. A step that goes better after
    another carries a hint (`Step.needs`, `hint_for()`), never a lock.
    """
    states = []
    for number, step in enumerate(STEPS, 1):
        state = "done" if _is_done(step.key, facts) else "todo"
        states.append(StepState(step, number, state, _status(step.key, facts), _later(step.key, facts)))

    # The next step is the first required one not yet done, in the list's
    # order. An optional step is never the next one: it waits in the list,
    # marked Optional, and the step pages' Next buttons still pass through it.
    nxt = next((s for s in states if s.state == "todo" and not s.step.optional), None)
    if nxt is not None:
        nxt.state = "next"
    complete = all(s.done for s in states if not s.step.optional)
    return Progress(
        steps=states,
        facts=facts,
        complete=complete,
        next=nxt,
        done=sum(s.done for s in states),
        minutes_left=sum(s.step.minutes for s in states if not s.done and not s.step.optional),
        by_key={s.step.key: s for s in states},
    )


#: Which step makes each fact a step's hint is about.
FACT_STEP = {"term": "session-and-term", "classes": "classes", "subjects": "subjects"}


def hint_for(state: StepState, facts: dict) -> Optional[Step]:
    """For a step not yet done, the first step its hint points to, or None
    when everything it goes better after is already there."""
    if state.done:
        return None
    for fact in state.step.needs:
        if not _holds(fact, facts):
            return BY_KEY[FACT_STEP[fact]]
    return None


def may_do(step: Step, roles) -> bool:
    """Whether somebody holding `roles` can do this step's work themselves."""
    return bool(set(roles) & step.doers)


def progress_for(school) -> Progress:
    """Read, judge, and write down the first time it was all done."""
    progress = judge(read(school))
    if progress.complete and school.setup_completed_at is None:
        now = timezone.now()
        type(school).objects.filter(pk=school.pk, setup_completed_at__isnull=True).update(
            setup_completed_at=now
        )
        school.setup_completed_at = now
    return progress


def is_onboarding(roles) -> bool:
    """Whether setup is brought to this person (`LEAD_ROLES`)."""
    return bool(set(roles) & LEAD_ROLES)


def for_request(request) -> Optional[Progress]:
    """The steps for the administrator on this request while setup is not
    finished, else None. Read once per request and kept on it."""
    if hasattr(request, "_onboarding_progress"):
        return request._onboarding_progress
    school = getattr(request, "school", None)
    progress = None
    if (
        school is not None
        and school.setup_completed_at is None
        and is_onboarding(getattr(request, "school_roles", ()))
    ):
        progress = progress_for(school)
        if progress.complete:
            # Finished on this very read: from here on it is a finished school.
            progress = None
    request._onboarding_progress = progress
    return progress


__all__ = [
    "BY_KEY",
    "LEAD_ROLES",
    "ONBOARDING_ROLES",
    "Progress",
    "REQUIRED",
    "STEPS",
    "Step",
    "StepState",
    "WrongSchema",
    "for_request",
    "hint_for",
    "is_onboarding",
    "judge",
    "progress_for",
    "may_do",
    "read",
]
