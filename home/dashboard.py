"""What one login sees on the dashboard, built from the school's cached facts.

`home.facts` reads the whole school once and caches it. This module is the
door between those facts and a reader: every tile, attention item, drawing and
activity line is added only when the login holds a role that may open the
page it links to (a tile, a drawing) or take the step it asks for (an
attention item). The role sets are imported from the modules that gate those
pages, never written out again here, for `menu.py`'s reason: a second opinion
on who may do what would drift from the first.

## A teacher sees their own classes

A teacher's attendance, scores, attention items and activity cover the
classes they are class teacher of this term (`ClassTeacher`), not the school.
Teachers are not assigned to subjects (`docs/teaching.md`), so "the classes a
teacher teaches" is the class they form-teach. A teacher who also holds a
school-wide role (a principal who teaches) sees the school.

A teacher never sees a fee figure, a payment or a payer's name: those are
`fees.authority.READING_ROLES`', and a teacher is not in it.

## Copy

No em dashes or en dashes in anything a reader sees (`docs/design.md`). A
minus sign is U+2212, the sign, not a dash.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from django.utils import timezone

from academics.services import PLACEMENT_ROLES, SETUP_ROLES
from accounts.models import MEMBERSHIP_GRANTING_ROLES, STAFF_ROLES, Role
from attendance.absences import VIEWING_ROLES as SCHOOL_ATTENDANCE_ROLES
from attendance.services import MARKING_ROLES as REGISTER_ROLES
from fees.authority import READING_ROLES as FEE_READING_ROLES
from fees.authority import WRITING_ROLES as FEE_KEEPING_ROLES
from gradebook.services import MARK_ENTERING_ROLES
from results import services as chain
from results.comments_api import VIEWING_ROLES as REMARK_ROLES
from typography import NBSP, keep_together

from . import charts
from .facts import monday_of

#: Who may open the dashboard: every member of staff. What each sees on it is
#: decided item by item below.
HOME_ROLES = STAFF_ROLES

#: Who reads the roll: whoever may admit a child or place one, the set the
#: roll's own link carries (`menu.py`).
ROLL_ROLES = MEMBERSHIP_GRANTING_ROLES | PLACEMENT_ROLES

#: Roles that see the whole school's classes. Anyone else (a teacher) sees
#: the classes they form-teach.
WHOLE_SCHOOL_ROLES = STAFF_ROLES - {Role.TEACHER.value}

#: The roll import needs both authorities (`enrolment_api._may_import()`).
IMPORT_ROLES = MEMBERSHIP_GRANTING_ROLES & PLACEMENT_ROLES

MINUS = "−"
MAX_ATTENTION = 5
MAX_ACTIVITY = 5


# -- money and numbers ---------------------------------------------------------


def naira(kobo: int) -> str:
    """"₦48,620,500": whole naira, as the fee book prints them."""
    return f"₦{round(kobo / 100):,}"


def figure(value) -> str:
    """Every number the dashboard prints: at most one decimal, and never a
    trailing ".0". "100", "94.2", "1,234". The one formatter, so no two
    tiles disagree about how a number looks."""
    rounded = round(float(value), 1)
    if rounded == int(rounded):
        return f"{int(rounded):,}"
    return f"{rounded:,.1f}"


def pct(part, whole) -> Optional[str]:
    """"94.2%", "100%"; None when there is nothing to divide by."""
    return f"{figure(part * 100 / whole)}%" if whole else None


def short_naira(kobo: int) -> str:
    """"₦48.6m": a tile's figure, short enough never to wrap. Whole numbers
    from 100 of a unit up, `figure()`'s one decimal below that."""
    value = abs(kobo) / 100
    for unit, suffix in ((1e9, "bn"), (1e6, "m"), (1e3, "k")):
        if value >= unit:
            scaled = value / unit
            return f"₦{figure(round(scaled) if scaled >= 100 else scaled)}{suffix}"
    return f"₦{figure(round(value))}"


def signed(n, unit: str = "") -> str:
    """"+14", "−2", "+1.3", with the true minus sign and `figure()`'s digits."""
    if not round(float(n), 1):
        return f"{unit}0"
    return f"{'+' if n > 0 else MINUS}{unit}{figure(abs(n))}"


def plural(n: int, one: str, many: str = "") -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def percent(part: int, whole: int) -> Optional[int]:
    return round(part * 100 / whole) if whole else None


def join_names(items: list, limit: int = 3) -> str:
    """"JSS 3A, SS 1C and SS 2B", or "... and 4 more"."""
    if len(items) > limit:
        return f"{', '.join(items[:limit])} and {len(items) - limit} more"
    if len(items) > 1:
        return f"{', '.join(items[:-1])} and {items[-1]}"
    return items[0] if items else ""


def _at(value: str) -> datetime:
    return timezone.localtime(datetime.fromisoformat(value))


def when(at: datetime, today: date) -> str:
    """"11:42" today, "Yesterday", else "Tue 6 Oct"."""
    day = at.date()
    if day == today:
        return at.strftime("%H:%M")
    if day == today - timedelta(days=1):
        return "Yesterday"
    return short_day(day)


def short_day(day: date) -> str:
    """"Thu 1 Oct", held on one line."""
    return f"{day.strftime('%a')}{NBSP}{day.day}{NBSP}{day.strftime('%b')}"


def days_ago(at: datetime, today: date) -> str:
    n = (today - at.date()).days
    return "today" if n <= 0 else ("yesterday" if n == 1 else f"{n} days ago")


# -- the reader's scope ----------------------------------------------------------


@dataclass(frozen=True)
class Scope:
    roles: frozenset
    user_id: int
    #: Class ids this login sees: every active class, or a teacher's own.
    classes: frozenset
    whole_school: bool
    names: dict = field(default_factory=dict)

    def may(self, allowed) -> bool:
        return bool(self.roles & allowed)

    def label(self) -> str:
        """"JSS 1C", or "your 2 classes"."""
        if self.whole_school:
            return "the school"
        if len(self.classes) == 1:
            return self.names[next(iter(self.classes))]
        return f"your {len(self.classes)} classes"


def scope_for(facts: dict, roles, user_id: int) -> Scope:
    people = facts["people"]
    names = {cid: name for cid, name, _ in people["classes"]}
    whole = bool(set(roles) & WHOLE_SCHOOL_ROLES)
    if whole:
        classes = frozenset(names)
    else:
        classes = frozenset(cid for cid, uid in people["form"] if uid == user_id and cid in names)
    return Scope(frozenset(roles), user_id, classes, whole, names)


# -- the page -----------------------------------------------------------------


#: Words that are a role or a title, not a name: a demo login called
#: "Administrator Sunrise" is greeted "Good morning", not "Good morning,
#: Administrator".
_NOT_A_NAME = {
    "admin", "administrator", "principal", "vice", "vp", "teacher", "bursar",
    "parent", "guardian", "student", "staff", "head", "headteacher", "proprietor",
    "school", "office", "user", "demo",
}
#: Honorifics a Nigerian staff room is addressed by. Kept with the surname
#: after them: "Mrs Adeyemi", never "Mrs".
_TITLES = {"mr", "mrs", "ms", "miss", "dr", "prof", "chief", "alhaji", "alhaja", "pastor", "rev", "engr"}


def first_name(user) -> str:
    """The name to greet: `short_name` if set, else the first word of the full
    name, else nothing. Never a username, a role or a bare title."""
    if user.short_name:
        words = user.short_name.split()
    elif user.full_name:
        words = user.full_name.split()
    else:
        return ""
    if not words or words[0].lower().strip(".") in _NOT_A_NAME:
        return ""
    if words[0].lower().strip(".") in _TITLES:
        return f"{words[0]} {words[-1]}" if len(words) > 1 and words[-1].lower() not in _NOT_A_NAME else ""
    return words[0]


def greeting(now: datetime) -> str:
    if now.hour < 12:
        return "Good morning"
    return "Good afternoon" if now.hour < 17 else "Good evening"


def term_block(term: Optional[dict], today: date) -> Optional[dict]:
    if term is None:
        return None
    from academics.models import TermName

    start = monday_of(date.fromisoformat(term["starts_on"]))
    end = date.fromisoformat(term["ends_on"])
    weeks = (end - start).days // 7 + 1
    week = (today - start).days // 7 + 1
    return {
        "id": term["id"],
        "session": term["session"],
        "name": TermName(term["name"]).label,
        "week": week if 1 <= week <= weeks else None,
        "weeks": weeks,
        "start": start,
    }


def build(facts: dict, *, school, user, roles, now: Optional[datetime] = None) -> dict:
    """The template's `dash`: everything this login may see, and nothing else."""
    from menu import initials

    now = timezone.localtime(now) if now else timezone.localtime()
    today = date.fromisoformat(facts["today"])
    scope = scope_for(facts, roles, user.pk)
    term = term_block(facts["people"]["term"], today)
    dash = {
        "school": {"name": school.name, "initials": initials(school.name), "crest_url": facts["crest"]},
        "greeting": greeting(now),
        "name": first_name(user),
        "term": term,
        "today": today,
        "setup": None,
        "waiting": None,
        "tiles": [],
        "attention": [],
        "fees": None,
        "week": None,
        "activity": [],
    }
    if facts["setting_up"]:
        dash["greeting"] = "Welcome"
        if scope.may(SETUP_ROLES | MEMBERSHIP_GRANTING_ROLES):
            dash["setup"] = setup_steps(facts, scope)
        else:
            dash["waiting"] = True
        return dash

    week = attendance(facts, scope, today, term)
    dash["tiles"] = tiles(facts, scope, today, term, week)
    dash["attention"] = attention(facts, scope, school, user, today, term, week)[:MAX_ATTENTION]
    if scope.may(FEE_READING_ROLES) and facts["money"] is not None:
        dash["fees"] = fee_card(facts, term, today)
    if week is not None:
        dash["week"] = week["card"]
    dash["activity"] = activity(facts, scope, today)[:MAX_ACTIVITY]
    return dash


# -- set up your school ----------------------------------------------------------


def setup_steps(facts: dict, scope: Scope) -> dict:
    people = facts["people"]
    steps = [
        {
            "title": "Add your classes",
            "detail": "JSS 1 to SS 3, with arms such as A, B and C",
            "href": "/setup/",
            "action": "Add classes",
            "done": bool(people["classes"]),
            "roles": SETUP_ROLES,
        },
        {
            "title": "Invite your teachers",
            "detail": "They get an email or SMS link to set a password",
            "href": "/staff/",
            "action": "Invite",
            "done": bool(people["people"].get(Role.TEACHER.value)),
            "roles": MEMBERSHIP_GRANTING_ROLES,
        },
        {
            "title": "Import your students",
            "detail": "Upload the roll as an Excel or CSV file",
            "href": "/roll/import/",
            "action": "Import",
            "done": bool(people["people"].get(Role.STUDENT.value)),
            "roles": IMPORT_ROLES,
        },
    ]
    for step in steps:
        if not scope.may(step.pop("roles")):
            # Shown, so the reader knows what is left, but not linked: the page
            # behind it would refuse them.
            step["href"] = None
            if not step["done"]:
                step["detail"] = "Your school administrator does this"
    done = sum(step["done"] for step in steps)
    return {"steps": steps, "done": done, "percent": round(done * 100 / len(steps))}


# -- attendance ------------------------------------------------------------------


def attendance(facts: dict, scope: Scope, today: date, term) -> Optional[dict]:
    """Attendance over the classes this login sees, as one story told three
    ways (the tile, the week's chart, the activity line), so they agree.

    - **The day shown** is today if any register was taken today, whatever
      day of the week it is. Otherwise it is the last day a register was
      taken, and the tile says so ("Last school day: Fri 9 Oct"); it never
      calls a day with no register "today".
    - **The chart** is Monday to Friday of this week, plus a Saturday or a
      Sunday only if a register was taken on it.
    - **The change** is the day shown against the seven days before it.

    Out of the children marked, never out of the roll (`summary.present()`'s
    reason): a class nobody has taken a register for has had nobody absent.
    """
    school_wide = scope.may(SCHOOL_ATTENDANCE_ROLES)
    if not school_wide and not (scope.may(REGISTER_ROLES) and scope.classes):
        return None
    monday = monday_of(today)
    by_day, taken_today = {}, set()
    for cid, on, marked, present, created, taken_by, taken_name in facts["people"]["registers"]:
        if cid not in scope.classes:
            continue
        on = date.fromisoformat(on)
        day = by_day.setdefault(on, [0, 0])
        day[0] += present
        day[1] += marked
        if on == today:
            taken_today.add(cid)
    placed = {cid for cid, _, n in facts["people"]["classes"] if n and cid in scope.classes}

    shown = today if today in by_day else max((d for d in by_day if d < today), default=None)
    before = [0, 0]
    if shown is not None:
        for day, (present, marked) in by_day.items():
            if shown - timedelta(days=7) <= day < shown:
                before[0] += present
                before[1] += marked

    days = [monday + timedelta(days=i) for i in range(5)]
    days += [d for d in (monday + timedelta(days=5), monday + timedelta(days=6)) if d in by_day and d <= today]
    bars = []
    for day in days:
        present, marked = by_day.get(day, (0, 0))
        exact = present * 100 / marked if marked else None
        pending = day >= today
        text = f"{figure(exact)}%" if exact is not None else ("Not yet" if pending else "None")
        bars.append((day.strftime("%a"), exact, day == today, pending, text))

    # A weekend is named as one only while nobody has taken a register on it.
    weekend = today.weekday() >= 5 and not taken_today
    if school_wide:
        foot = (
            "No registers on a weekend"
            if weekend
            else f"{len(taken_today & placed)} of {plural(len(placed), 'class', 'classes')} "
            "have taken today's register"
        )
        href, link = "/absences/", "Absences"
    else:
        label = scope.label()
        if weekend:
            foot = "No registers on a weekend"
        elif not placed - taken_today:
            foot = f"Today's register for {label} is taken"
        else:
            foot = f"Today's register for {label} is not taken yet"
        href, link = "/register/", "Register"
    return {
        "school_wide": school_wide,
        "shown": shown,
        "present": by_day[shown][0] if shown else 0,
        "marked": by_day[shown][1] if shown else 0,
        "before": before,
        "weekend": weekend,
        "placed": placed,
        "taken_today": taken_today,
        "card": {"bars": charts.bars(bars), "foot": foot, "href": href, "link": link},
    }


# -- the tiles ----------------------------------------------------------------------


def tiles(facts, scope: Scope, today, term, week) -> list:
    out = []
    people = facts["people"]
    if scope.may(ROLL_ROLES):
        placed = sum(n for _, _, n in people["classes"])
        classes = sum(1 for _, _, n in people["classes"] if n)
        before = people["placed_before"]
        out.append({
            "key": "students",
            "label": "Students enrolled",
            "icon": "i-people",
            "href": "/roll/",
            "value": f"{placed:,}",
            "meta": f"In {plural(classes, 'class', 'classes')}",
            "change": f"{signed(placed - before)} this term" if before is not None else None,
        })
    money = facts["money"]
    if scope.may(FEE_READING_ROLES) and money is not None:
        collected, billed = _collected(money), _billed(money)
        share = percent(collected, billed)
        this_week = _collected_in_week(money, term, today)
        out.append({
            "key": "fees",
            "label": "Fees collected",
            "icon": "i-fees",
            "href": "/fees/",
            "value": short_naira(collected),
            "exact": f"{naira(collected)} of {naira(billed)}",
            "meter": min(share, 100) if share is not None else None,
            "meta": f"{pct(collected, billed)} of {short_naira(billed)}" if billed else "Nothing billed this term yet",
            "change": f"{_signed_naira(this_week)} this week",
        })
    if week is not None and (week["school_wide"] or scope.classes):
        out.append(_attendance_tile(week, scope, today))
    if scope.may(chain.APPROVING_ROLES | chain.CHECKING_ROLES | {Role.ADMIN.value}) and facts["work"] is not None:
        out.append(_results_tile(facts, scope))
    if not scope.whole_school and scope.may(MARK_ENTERING_ROLES) and scope.classes and facts["work"] is not None:
        out.append(_scores_tile(facts, scope, today))
    return out


def _signed_naira(kobo: int) -> str:
    if not kobo:
        return "₦0"
    return f"{'+' if kobo > 0 else MINUS}{short_naira(kobo)}"


def _attendance_tile(week, scope: Scope, today: date) -> dict:
    where = "" if week["school_wide"] else f" in {scope.label()}"
    shown = week["shown"]
    tile = {
        "key": "attendance",
        "label": "Attendance today" if shown == today else "Attendance",
        "icon": "i-register",
        "href": "/absences/" if week["school_wide"] else "/register/",
    }
    if shown is None:
        meta = "No registers on a weekend" if week["weekend"] else f"No register taken yet{where}"
        return {**tile, "value": "-", "meta": meta, "change": None}
    present, marked = week["present"], week["marked"]
    exact = present * 100 / marked
    change = None
    if week["before"][1]:
        # The day shown against the seven days before it.
        points = exact - week["before"][0] * 100 / week["before"][1]
        change = f"{signed(points)} pts"
    meta = (
        f"{present:,} of {marked:,} present{where}"
        if shown == today
        else f"Last school day: {short_day(shown)}"
    )
    return {
        **tile,
        "value": f"{figure(exact)}%",
        "exact": f"{present:,} of {marked:,} present{where}",
        "meta": meta,
        "change": change,
    }


#: Which sheets wait on whom, and how the tile names them.
def _results_tile(facts, scope: Scope) -> dict:
    if scope.may(chain.APPROVING_ROLES):
        state, label, meta = "checked", "Approvals", "Results checked and waiting on you"
    elif scope.may(chain.CHECKING_ROLES):
        state, label, meta = "submitted", "Checks", "Results submitted and waiting on you"
    else:
        state, label, meta = "checked", "Approvals", "Results checked, with the principal"
    sheets = [s for s in facts["work"]["sheets"] if s[0] in scope.classes]
    now = sum(1 for s in sheets if s[1] == state)
    before = sum(1 for s in sheets if s[5] == state)
    return {
        "key": "results",
        "label": label,
        "icon": "i-results",
        "href": "/results/",
        "value": str(now),
        "unit": "class" if now == 1 else "classes",
        "meta": meta,
        "change": f"{signed(now - before)} this week",
    }


def _papers(facts, scope: Scope) -> list:
    return [p for p in facts["work"]["papers"] if p[0] in scope.classes]


def _scores_tile(facts, scope: Scope, today: date) -> dict:
    papers = _papers(facts, scope)
    complete = [p for p in papers if p[4] >= p[3]]
    monday = monday_of(today)
    this_week = sum(1 for p in complete if _at(p[5]).date() >= monday)
    tile = {"key": "scores", "label": "Scores entered", "icon": "i-marks", "href": "/marking/"}
    if not papers:
        return {**tile, "value": "-", "meta": f"No marks entered yet in {scope.label()}", "change": None}
    return {
        **tile,
        "value": pct(len(complete), len(papers)),
        "meta": f"{len(complete)} of {plural(len(papers), 'paper')} complete in {scope.label()}",
        "change": f"{signed(this_week)} this week",
    }


# -- money ---------------------------------------------------------------------------


def _collected(money) -> int:
    kinds = money["kinds"]
    return -(kinds.get("payment", 0) + kinds.get("refund", 0))


def _billed(money) -> int:
    kinds = money["kinds"]
    return kinds.get("charge", 0) + kinds.get("discount", 0)


def _collected_in_week(money, term, today) -> int:
    if term is None:
        return 0
    week = (monday_of(today) - term["start"]).days // 7
    return -sum(total for wk, total in money["weekly"] if wk == week)


def fee_card(facts, term, today) -> dict:
    money = facts["money"]
    collected, billed = _collected(money), _billed(money)
    share = percent(collected, billed)
    card = {
        "collected": naira(collected),
        "expected": naira(billed),
        "percent": min(share or 0, 100),
        "percent_text": pct(collected, billed) or "0%",
        "this_week": short_naira(_collected_in_week(money, term, today)),
        "outstanding": short_naira(money["owing"]["kobo"]),
        "owing": money["owing"]["n"],
        "spark": None,
        "weeks": term["weeks"] if term else None,
        "weeks_so_far": None,
    }
    if term is not None:
        so_far = max(1, min(term["week"] or term["weeks"], term["weeks"]))
        weekly = {wk: -total for wk, total in money["weekly"]}
        running, points = 0, []
        for wk in range(so_far):
            running += weekly.get(wk, 0)
            points.append(running)
        # Anything before the term's first week (paid early) counts from week 1.
        early = sum(v for wk, v in weekly.items() if wk < 0)
        points = [p + early for p in points]
        card["spark"] = charts.sparkline(points, term["weeks"], ceiling=max(billed, 1))
        card["weeks_so_far"] = so_far
    return card


# -- needs your attention ----------------------------------------------------------


def _chip(tone, icon, text):
    return {"tone": tone, "icon": icon, "text": text}


def attention(facts, scope: Scope, school, user, today, term, week) -> list:
    """What this login can act on, most pressing first, each linked to where
    it is done. Never more than five."""
    items = []
    names = scope.names
    work = facts["work"]

    # A teacher's own register, on a school day in term, not yet taken.
    if (
        week is not None
        and not week["school_wide"]
        and today.weekday() < 5
        and term is not None
        and term["week"] is not None
    ):
        missing = sorted(week["placed"] - week["taken_today"], key=lambda c: names[c])
        if missing:
            items.append({
                "key": "register",
                "icon": "i-register",
                "href": "/register/",
                "title": f"Take today's register for {join_names([names[c] for c in missing])}",
                "detail": "Not taken yet today",
                "chip": _chip("warn", "i-clock", "Due today"),
            })

    money = facts["money"]
    if scope.may(FEE_KEEPING_ROLES) and money is not None and money["owing"]["n"]:
        n = money["owing"]["n"]
        when_ = f" in week {term['week']} of {term['weeks']}" if term and term["week"] else ""
        items.append({
            "key": "fees",
            "icon": "i-fees",
            "href": "/fees/",
            "title": f"{plural(n, 'student')} {'owes' if n == 1 else 'owe'} fees for this term",
            "detail": f"{short_naira(money['owing']['kobo'])} outstanding{when_}",
            "chip": _chip("stop", "i-alert", "Unpaid"),
        })

    if work is not None:
        items.extend(_results_waiting(work, scope, user, today))
        if scope.may(MARK_ENTERING_ROLES):
            item = _missing_scores(facts, scope)
            if item:
                items.append(item)
        if scope.may(REMARK_ROLES):
            item = _missing_remarks(facts, scope)
            if item:
                items.append(item)

    invited = facts["people"]["invited"]
    if scope.may(MEMBERSHIP_GRANTING_ROLES) and invited["n"]:
        items.append({
            "key": "invites",
            "icon": "i-mail",
            "href": "/staff/",
            "title": f"{plural(invited['n'], 'staff invitation')} not accepted",
            "detail": f"Oldest sent {days_ago(_at(invited['oldest']), today)}",
            "chip": _chip("brand", "i-clock", "Pending"),
        })

    if not school.contact_email and scope.may(SETUP_ROLES):
        items.append({
            "key": "contact",
            "icon": "i-settings",
            "href": "/setup/#contact-email",
            "title": "Add your school's contact email",
            "detail": "So replies from parents reach your office",
            "chip": _chip("brand", "i-todo", "To do"),
        })
    for item in items:
        item["title"] = keep_together(item["title"])
        item["detail"] = keep_together(item["detail"])
    return items


def _results_waiting(work, scope: Scope, user, today) -> list:
    """The chain's steps that wait on this login, as `summary.waiting()` reads
    them: release and approve for the principal, check for the vice principal."""
    out = []
    sheets = [s for s in work["sheets"] if s[0] in scope.classes]
    for state, roles, what, tone, icon, chip, verb in (
        ("approved", chain.RELEASING_ROLES, "approved and ready to release", "ok", "i-check", "Ready", "approved"),
        ("checked", chain.APPROVING_ROLES, "waiting for your approval", "warn", "i-clock", "Waiting", "checked"),
        ("submitted", chain.CHECKING_ROLES, "waiting for your check", "warn", "i-clock", "Waiting", "submitted"),
    ):
        if not scope.may(roles):
            continue
        waiting = sorted((s for s in sheets if s[1] == state), key=lambda s: s[2])
        if not waiting:
            continue
        oldest = waiting[0]
        n = len(waiting)
        title = (
            f"{scope.names[oldest[0]]} results {what}"
            if n == 1
            else f"{n} classes' results {what}"
        )
        out.append({
            "key": f"results-{state}",
            "icon": "i-results",
            "href": "/results/" if n > 1 else f"/results/?class={oldest[0]}",
            "title": title,
            "detail": (
                f"Oldest is {scope.names[oldest[0]]}, {verb} {days_ago(_at(oldest[2]), today)}"
                if n > 1
                else f"{verb.capitalize()} {days_ago(_at(oldest[2]), today)}"
            ),
            "chip": _chip(tone, icon, chip),
        })
    return out


def _missing_scores(facts, scope: Scope) -> Optional[dict]:
    """Papers started in a class and not finished: some children have a mark
    and some do not. A paper nobody has started is not flagged, because
    nothing records which classes sit which subject (`docs/teaching.md`)."""
    partial = [p for p in _papers(facts, scope) if p[4] < p[3]]
    if not partial:
        return None
    names = scope.names
    classes = sorted({p[0] for p in partial}, key=lambda c: names[c])
    if len(partial) == 1:
        cid, subject, paper, placed, scored, _ = partial[0]
        title = f"{paper} scores missing for {names[cid]}"
        detail = f"{subject}: {placed - scored} of {placed} students without a score"
    elif len(classes) == 1:
        title = f"{len(partial)} papers have missing scores in {names[classes[0]]}"
        detail = join_names(sorted({f"{p[1]} {p[2]}" for p in partial}))
    else:
        title = f"{len(classes)} classes have missing scores"
        detail = f"{join_names([names[c] for c in classes])}: {plural(len(partial), 'paper')} unfinished"
    return {
        "key": "scores",
        "icon": "i-marks",
        "href": "/marking/",
        "title": title,
        "detail": detail,
        "chip": _chip("warn", "i-clock", "Incomplete"),
    }


def _missing_remarks(facts, scope: Scope) -> Optional[dict]:
    """Children still without this reader's remark, in classes whose results
    are still open (no sheet, or a draft): the only time a remark can be
    written (`home.summary.waiting()` gives the reason)."""
    from results.models import CommentAuthor

    if scope.may(chain.APPROVING_ROLES):
        author, whose = CommentAuthor.PRINCIPAL.value, "your remark"
        classes = scope.classes
    elif scope.may({Role.TEACHER.value}):
        author, whose = CommentAuthor.CLASS_TEACHER.value, "a remark"
        classes = {cid for cid, uid in facts["people"]["form"] if uid == scope.user_id}
    else:
        return None
    closed = {s[0] for s in facts["work"]["sheets"] if s[1] != "draft"}
    placed = {cid: n for cid, _, n in facts["people"]["classes"]}
    written = {cid: n for cid, who, n in facts["work"]["remarks"] if who == author}
    missing = {
        cid: placed.get(cid, 0) - written.get(cid, 0)
        for cid in classes
        if cid not in closed and placed.get(cid, 0) > written.get(cid, 0)
    }
    if not missing:
        return None
    names = scope.names
    total = sum(missing.values())
    if len(missing) == 1:
        (cid,) = missing
        title = f"Remarks missing for {plural(total, 'student')} in {names[cid]}"
        detail = "Write them before the results are submitted"
        href = f"/comments/?class={cid}"
    else:
        title = f"Remarks missing in {len(missing)} classes"
        detail = f"{plural(total, 'student')} without {whose}"
        href = "/comments/"
    return {
        "key": "remarks",
        "icon": "i-comments",
        "href": href,
        "title": title,
        "detail": detail,
        "chip": _chip("brand", "i-todo", "To do"),
    }


# -- recent activity ---------------------------------------------------------------

_DID = {
    "submitted": "submitted",
    "checked": "checked",
    "approved": "approved",
    "released": "released to families",
    "draft": "sent back",
}


def activity(facts, scope: Scope, today: date) -> list:
    """The latest things the school's own logs recorded, as this login may
    read them. No table of its own: results steps (`ResultSheetTransition`),
    payments (`FeeLedgerEntry`), registers (`Register`) and accepted staff
    invitations (`Invitation`), all append-only or stamped when written."""
    events = []

    def by(actor_id, name):
        return "you" if actor_id == scope.user_id else (name or "a member of staff")

    work = facts["work"]
    if work is not None and scope.may(chain.OPENING_ROLES):
        for cid, to_state, actor_id, actor, at in work["steps"]:
            if cid in scope.classes:
                events.append((_at(at), "results", "i-results", f"{scope.names[cid]} results {_DID[to_state]} by {by(actor_id, actor)}"))

    money = facts["money"]
    if money is not None and scope.may(FEE_READING_ROLES):
        for paid in money["paid"]:
            events.append((_at(paid["at"]), "payment", "i-fees", f"{naira(paid['kobo'])} payment recorded for {paid['name']}"))

    registers = [r for r in facts["people"]["registers"] if r[0] in scope.classes]
    if scope.whole_school and scope.may(SCHOOL_ATTENDANCE_ROLES):
        todays = [r for r in registers if r[1] == today.isoformat()]
        if todays:
            placed = sum(1 for _, _, n in facts["people"]["classes"] if n)
            latest = max(_at(r[4]) for r in todays)
            events.append((latest, "registers", "i-register", f"Registers taken for {len(todays)} of {plural(placed, 'class', 'classes')} today"))
    elif not scope.whole_school:
        for cid, on, _, _, created, taken_by, taken_name in registers:
            at, on = _at(created), date.fromisoformat(on)
            # A register entered on a later day says which day it was for.
            day = "" if on == at.date() else f" for {short_day(on)}"
            events.append((at, "register", "i-register", f"{scope.names[cid]} register{day} taken by {by(taken_by, taken_name)}"))

    if scope.may(MEMBERSHIP_GRANTING_ROLES):
        for joined in facts["people"]["joined"]:
            role = Role(joined["role"]).label
            events.append((_at(joined["at"]), "joined", "i-people", f"{joined['name']} joined as {role}"))

    events.sort(key=lambda e: e[0], reverse=True)
    return [
        {"kind": kind, "icon": icon, "text": keep_together(text), "at": at, "when": when(at, today)}
        for at, kind, icon, text in events[:MAX_ACTIVITY]
    ]


__all__ = ["HOME_ROLES", "build", "naira", "short_naira", "signed"]
