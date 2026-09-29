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

## The tab bar is one role's four screens

`design.css` draws it as four equal columns, for "the role's four main screens"
(`docs/design.md`). A login holding more than one role gets the four of the
role that leads (`_LEADING`), with the page being looked at swapped in for the
fourth when it is not among them: the tab bar never loses the page you are on.
A login whose roles have no four (a bursar) gets no tab bar, and the sidebar,
behind the menu button, still lists everything.
"""

from dataclasses import dataclass
from typing import Optional

from django import template

from accounts.models import MEMBERSHIP_GRANTING_ROLES, Role
from academics.services import PLACEMENT_ROLES, SETUP_ROLES
from attendance.absences import VIEWING_ROLES as ABSENCE_ROLES
from attendance.services import MARKING_ROLES as REGISTER_ROLES
from fees.authority import READING_ROLES as FEES_ROLES
from gradebook.services import MARK_ENTERING_ROLES
from home.summary import HOME_ROLES
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
    Link("bank", "/bank/", "i-fees", "Bank", FEES_ROLES, "Office"),
    Link("setup", "/setup/", "i-settings", "Setup", SETUP_ROLES, "Office"),
    Link("promotion", "/promotion/", "i-people", "Promotion", PLACEMENT_ROLES, "Office"),
    # The roll is read by whoever may admit a child or place one: the wider of
    # the two sets `enrolment_api._refuse_outsiders()` admits on.
    Link("roll", "/roll/", "i-people", "Roll", MEMBERSHIP_GRANTING_ROLES | PLACEMENT_ROLES, "Office"),
    Link("staff", "/staff/", "i-inbox", "Staff", MEMBERSHIP_GRANTING_ROLES, "Office"),
    Link("notices-settings", "/notices/settings/", "i-comments", "Notices", NOTICES_ROLES, "Office"),
)

BY_KEY = {link.key: link for link in LINKS}

#: Each role's four main screens, for the tab bar.
TABS = {
    Role.PRINCIPAL.value: ("home", "results", "broadsheet", "absences"),
    Role.VICE_PRINCIPAL_ACADEMIC.value: ("home", "results", "broadsheet", "absences"),
    Role.ADMIN.value: ("setup", "roll", "staff", "fees"),
    Role.TEACHER.value: ("register", "marking", "comments", "timetable"),
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

    @property
    def links(self):
        return tuple(link for group in self.groups for link in group.links)

    @property
    def home(self) -> Optional[str]:
        """Where the logo goes: the first tab, else the first link, else nowhere."""
        first = self.tabs or self.links
        return first[0].href if first else None


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


def _menu(context, current):
    request = context.get("request")
    return menu_for(getattr(request, "school_roles", frozenset()), current)


@register.inclusion_tag("design/shell_open.html", takes_context=True)
def shell_open(context, current):
    """`<body>` through the start of `.content`: the sidebar and the top bar.

    Sign out is offered to anybody signed in, whatever their roles here: a
    parent or a refused teacher still has a session to end.
    """
    request = context.get("request")
    user = getattr(request, "user", None)
    return {
        "menu": _menu(context, current),
        "signed_in": bool(user is not None and user.is_authenticated),
        "csrf_token": context.get("csrf_token"),
        "path": request.path if request is not None else "/",
    }


@register.inclusion_tag("design/shell_close.html", takes_context=True)
def shell_close(context, current):
    """The end of `.content`, the tab bar, and the end of the shell."""
    return {"menu": _menu(context, current)}


__all__ = ["LINKS", "Link", "Menu", "TABS", "menu_for", "register"]
