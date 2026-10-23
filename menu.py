"""The sidebar and the tab bar, built from the roles of whoever is signed in.

Project-level, beside `pages.py`, for its reason: it is every staff page's and
no one app's.

## A link is shown only where its page will answer

Every link names the role set **its own page's API gates on**, imported from the
module that gates, never written out again here. A menu that listed roles of
its own would be a second opinion on who may open a page, and the day the two
disagreed somebody would tap a link and read "This page is not yours".
`tests/test_menu.py` holds the other half: for a login of each role, at two
schools, every link shown opens and every page not shown refuses.

The roles are `request.school_roles`, which `SchoolAccessMiddleware` already
read with `User.roles_at()` for this request: the same answer every gate reads,
and no extra query. On the portal, or signed out, it is empty, and so is the
menu.

## The tab bar is one role's main screens

`design.css` draws one equal column per tab, for "the role's main screens"
(`docs/design.md`): four for most roles. A login holding more than one role
gets the tabs of the role that leads (`_LEADING`), with the page being looked
at swapped in for the last when it is not among them: the tab bar never loses
the page you are on.
A bursar has three main screens and gets three tabs. The sidebar, behind the
menu button, still lists everything.
"""

from dataclasses import dataclass
from typing import Optional

from django import template

from accounts.models import MEMBERSHIP_GRANTING_ROLES, Role
from academics.services import PLACEMENT_ROLES, SETUP_ROLES
from attendance.absences import VIEWING_ROLES as ABSENCE_ROLES
from attendance.services import MARKING_ROLES as REGISTER_ROLES
from fees.authority import READING_ROLES as FEES_ROLES
from gradebook.assignments import VIEWING_ROLES as SUBJECT_TEACHER_ROLES
from gradebook.services import MARK_ENTERING_ROLES
from home.dashboard import HOME_ROLES
from notices.services import SETTINGS_ROLES as NOTICES_ROLES
from results.api import POSITION_VIEWING_ROLES
from results.comments_api import VIEWING_ROLES as REMARK_ROLES
from results.services import OPENING_ROLES as CHAIN_ROLES
from timetable.services import READING_ROLES as TIMETABLE_ROLES


@dataclass(frozen=True)
class Link:
    key: str
    href: str
    icon: str
    label: str
    #: The roles this page's API admits, from the module that gates it.
    roles: frozenset
    #: The sidebar heading it sits under; None for Home, which sits above them.
    group: Optional[str] = None


#: Every staff page, in the order the sidebar lists them.
LINKS = (
    Link("home", "/home/", "i-home", "Home", HOME_ROLES),
    Link("register", "/register/", "i-register", "Register", REGISTER_ROLES, "Teaching"),
    Link("marking", "/marking/", "i-marks", "Marks", MARK_ENTERING_ROLES, "Teaching"),
    Link("comments", "/comments/", "i-comments", "Remarks", REMARK_ROLES, "Teaching"),
    Link("timetable", "/timetable/", "i-calendar", "Timetable", TIMETABLE_ROLES, "Teaching"),
    Link("results", "/results/", "i-results", "Results", CHAIN_ROLES, "Results"),
    Link("broadsheet", "/broadsheet/", "i-sheet", "Broadsheets", POSITION_VIEWING_ROLES, "Results"),
    Link("absences", "/absences/", "i-absent", "Absences", ABSENCE_ROLES, "Results"),
    Link("fees", "/fees/", "i-fees", "Fees", FEES_ROLES, "Office"),
    Link("bank", "/bank/", "i-bank", "Bank", FEES_ROLES, "Office"),
    Link("setup", "/setup/", "i-settings", "Setup", SETUP_ROLES, "Office"),
    Link("teaching", "/teaching/", "i-book", "Subjects", SETUP_ROLES, "Office"),
    Link("subject-teachers", "/subject-teachers/", "i-staff", "Who teaches what", SUBJECT_TEACHER_ROLES, "Office"),
    Link("promotion", "/promotion/", "i-promote", "Promotion", PLACEMENT_ROLES, "Office"),
    # The roll is read by whoever may admit a child or place one: the wider of
    # the two sets `enrolment_api._refuse_outsiders()` admits on.
    Link("roll", "/roll/", "i-people", "Roll", MEMBERSHIP_GRANTING_ROLES | PLACEMENT_ROLES, "Office"),
    Link("staff", "/staff/", "i-staff", "Staff", MEMBERSHIP_GRANTING_ROLES, "Office"),
    Link("notices-settings", "/notices/settings/", "i-megaphone", "Notices", NOTICES_ROLES, "Office"),
)

BY_KEY = {link.key: link for link in LINKS}

#: Each role's main screens, for the tab bar: four, or as many as the role
#: has. The principal and the bursar keep Fees on it; the vice principal, who
#: may read the fee book but does not keep it, keeps Broadsheets.
TABS = {
    Role.PRINCIPAL.value: ("home", "results", "fees", "absences"),
    Role.VICE_PRINCIPAL_ACADEMIC.value: ("home", "results", "broadsheet", "absences"),
    Role.ADMIN.value: ("home", "roll", "staff", "fees"),
    Role.TEACHER.value: ("home", "register", "marking", "timetable"),
    Role.BURSAR.value: ("home", "fees", "bank"),
}

#: Whose four a login with several roles gets. The one that sees the most of
#: the school first, so a teacher who is also the principal lands on the
#: principal's screens and still has her register one tap into the sidebar,
#: and on the tab bar whenever she is on it.
_LEADING = (
    Role.PRINCIPAL.value,
    Role.VICE_PRINCIPAL_ACADEMIC.value,
    Role.ADMIN.value,
    Role.TEACHER.value,
    Role.BURSAR.value,
)


@dataclass(frozen=True)
class Group:
    heading: Optional[str]
    links: tuple


@dataclass(frozen=True)
class Menu:
    groups: tuple
    tabs: tuple
    current: str
    #: Classnode's own staff on the portal, whose pages are not a school's: no
    #: Help and next steps (that is a school's page), no tab bar.
    platform: bool = False

    @property
    def links(self):
        return tuple(link for group in self.groups for link in group.links)

    @property
    def home(self) -> Optional[str]:
        """Where the logo goes: the first tab, else the first link, else nowhere."""
        first = self.tabs or self.links
        return first[0].href if first else None


#: The platform operator's pages, on the portal. A platform login has no roles
#: at any school for `menu_for()` to read, and these pages answer to
#: `user.is_platform_staff` instead (`schools.platform_api`, `onboarding.handover`),
#: so the menu is not built from roles at all.
PLATFORM_LINKS = (
    Link("platform", "/platform/", "i-people", "Schools", frozenset(), "Platform"),
    Link("handover", "/platform/handover/", "i-flag", "New school handover", frozenset(), "Platform"),
    Link("admin", "/admin/", "i-settings", "Admin", frozenset(), "Platform"),
)


def platform_menu(current: str) -> Menu:
    return Menu(groups=(Group("Platform", PLATFORM_LINKS),), tabs=(), current=current, platform=True)


def menu_for(roles, current: str) -> Menu:
    roles = set(roles)
    shown = [link for link in LINKS if link.roles & roles]

    groups, seen = [], {}
    for link in shown:
        if link.group not in seen:
            seen[link.group] = []
            groups.append(link.group)
        seen[link.group].append(link)

    tabs = ()
    leading = next((role for role in _LEADING if role in roles), None)
    if leading is not None:
        keys = list(TABS[leading])
        if current in BY_KEY and BY_KEY[current] in shown and current not in keys:
            keys[-1] = current
        tabs = tuple(BY_KEY[key] for key in keys)

    return Menu(
        groups=tuple(Group(heading, tuple(seen[heading])) for heading in groups),
        tabs=tabs,
        current=current,
    )


# -- the template side -------------------------------------------------------

register = template.Library()


def _is_platform_page(request) -> bool:
    """Classnode's own staff, on the portal: no school here, so no roles to read."""
    user = getattr(request, "user", None)
    return bool(
        user is not None
        and user.is_authenticated
        and user.is_platform_staff
        and getattr(request, "school", None) is None
    )


def _menu(context, current):
    request = context.get("request")
    if _is_platform_page(request):
        return platform_menu(current)
    return menu_for(getattr(request, "school_roles", frozenset()), current)


def initials(name: str) -> str:
    """Two letters for an avatar or a crest: "Sunrise Demo Academy" is "SD"."""
    words = [w for w in (name or "").split() if w[:1].isalnum()]
    return "".join(w[0] for w in words[:2]).upper() or "?"


def _role_names(roles) -> str:
    """"Principal, Teacher": the login's roles here, leading role first."""
    order = {role: i for i, role in enumerate(_LEADING)}
    return ", ".join(Role(r).label for r in sorted(roles, key=lambda r: order.get(r, 99)))


@register.inclusion_tag("design/shell_open.html", takes_context=True)
def shell_open(context, current):
    """`<body>` through the start of `.content`: the sidebar and the top bar.

    Sign out is offered to anybody signed in, whatever their roles here: a
    parent or a refused teacher still has a session to end. The top bar names
    the school and carries the account menu; both are read off the request
    the middleware already built, so the bar costs no query.
    """
    from sync.views import PAGES as OFFLINE_PAGES

    request = context.get("request")
    user = getattr(request, "user", None)
    signed_in = bool(user is not None and user.is_authenticated)
    school = getattr(request, "school", None)
    path = request.path if request is not None else "/"
    # The pages the offline worker keeps (`sync.views.PAGES`) are served from
    # the phone's cache to whoever opens them next, and a staff-room phone is
    # shared (`docs/offline.md`, S7). Their frame names nobody: the account
    # menu there is a person icon and Sign out.
    personal = signed_in and path not in OFFLINE_PAGES
    name = (user.get_full_name() or user.get_username()) if personal else ""
    # The setup chip: an administrator's, until the school's setup is first
    # finished, and never on the offline pages, which carry nothing personal.
    # `onboarding.progress.for_request()` reads nothing for anybody else.
    setup_chip = None
    if personal and request is not None:
        from onboarding.progress import for_request

        setup_chip = for_request(request)
    return {
        "menu": _menu(context, current),
        "signed_in": signed_in,
        "csrf_token": context.get("csrf_token"),
        "path": path,
        # Named only to a member here: a frame is served to whoever opens the
        # URL, and names no school to a stranger (`results/views.py`).
        "school_name": school.name if school is not None and getattr(request, "school_roles", None) else "",
        "user_name": name,
        "user_initials": initials(name) if name else "",
        "role_names": (
            "Platform staff"
            if personal and _is_platform_page(request)
            else _role_names(getattr(request, "school_roles", ())) if personal else ""
        ),
        "setup_chip": setup_chip,
    }


@register.inclusion_tag("design/shell_close.html", takes_context=True)
def shell_close(context, current):
    """The end of `.content`, the tab bar, and the end of the shell."""
    return {"menu": _menu(context, current)}


__all__ = ["LINKS", "Link", "Menu", "PLATFORM_LINKS", "TABS", "initials", "menu_for", "platform_menu", "register"]
