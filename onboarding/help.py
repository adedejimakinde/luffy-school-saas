"""Help and next steps: a few tips for the page somebody came from.

The page is chosen from the `Referer` header, and only when it names a page
on this same host: a path from anywhere else is ignored, and so is anything
that is not a path we know. "Go back" follows the same rule and falls back to
Home, so the link never sends anybody off the school's own address.

Tips are written per page, for the people who can open that page. A page's
tips are only shown to a login whose roles may open it (`menu.BY_KEY`), so a
teacher who types a fees address into the header reads nothing about fees.
"""

from typing import Optional
from urllib.parse import urlsplit

import menu

#: Contact for Classnode support, on every help page.
SUPPORT_EMAIL = "hello@classnode.co"
SUPPORT_PROMISE = "We reply within two working days."

#: (page key, heading) and three tips, each a (title, line) pair.
TIPS = {
    "home": ("Home", (
        ("Start with what needs you", "The list under the figures is what is waiting on you today."),
        ("Tap a figure to see it all", "Each tile opens the page that holds the full list."),
        ("Figures refresh every few minutes", "A register taken now shows on Home a little later."),
    )),
    "register": ("Register", (
        ("One register a day per class", "Open your class, tap each name present or absent, then save."),
        ("No network? Keep going", "The register saves on your phone and sends itself when you are back online."),
        ("Made a mistake?", "Open the same day again and change the mark. The last save counts."),
    )),
    "marking": ("Marks", (
        ("Pick the class and the paper", "Each paper, such as First CA, is marked out of its own total."),
        ("Marks save as you type", "They stay on your phone until they reach the school, even offline."),
        ("A mark out of range is refused", "Check the paper's total if a mark will not save."),
    )),
    "comments": ("Remarks", (
        ("One remark per student per term", "The class teacher writes the class remark and the principal adds theirs."),
        ("Keep it short and kind", "Parents read it on the report card."),
        ("You can change it until release", "Once results are released the remark is fixed."),
    )),
    "timetable": ("Timetable", (
        ("Your week at a glance", "Each row is a period, each column a day."),
        ("A clash is shown, not hidden", "Tell the office if two classes land on you at once."),
        ("The office keeps it up to date", "Changes show here as soon as they are saved."),
    )),
    "results": ("Results", (
        ("Each class goes step by step", "The class teacher submits, the vice principal checks, the principal approves and releases."),
        ("Nothing reaches parents early", "A report card is only seen once results are released."),
        ("Something wrong?", "Send it back a step with a note, and it can be corrected."),
    )),
    "broadsheet": ("Broadsheets", (
        ("Every subject for one class", "Swipe sideways on a phone to see all the subjects."),
        ("Totals and averages are worked out for you", "They update as marks are entered."),
        ("Print it from here", "Use your browser's print button for a paper copy."),
    )),
    "absences": ("Absences", (
        ("Who is missing school too often", "Students are listed once they pass the school's limit this term."),
        ("Follow up early", "A call to the parent in week three saves a hard talk in week ten."),
        ("It comes from the registers", "A register not taken counts as nobody absent."),
    )),
    "fees": ("Fees", (
        ("Set fee items per class", "Open a class's bill for the term and add each item and amount."),
        ("Record a payment the day it comes in", "The parent gets a receipt and the balance updates."),
        ("A mistake is reversed, never deleted", "Reverse the wrong entry and record the right one."),
    )),
    "bank": ("Bank", (
        ("Where parents pay", "Each family can get its own account number to pay into."),
        ("Payments match themselves", "A transfer into a family's account is recorded for you."),
        ("Something did not match?", "It waits here until you place it against the right child."),
    )),
    "setup": ("Setup", (
        ("One term is current at a time", "Opening a new term makes it the current one."),
        ("One class per arm", "JSS 1A and JSS 1B are two classes. A school with no arms has one class per level."),
        ("Contact email and crest", "The crest heads every report card, and replies from parents go to the contact email."),
    )),
    "teaching": ("Subjects", (
        ("Add each subject once", "Mathematics is one subject, taught in many classes."),
        ("Papers belong to a term", "First CA, Second CA and Exam, each with its own total."),
        ("Set the form teachers", "The form teacher takes the register and writes the class remark."),
    )),
    "promotion": ("Promotion", (
        ("At the end of the session", "Move each class up, or keep a student back where needed."),
        ("Check before you confirm", "The list shows where every student will go."),
        ("Leavers are kept on record", "SS 3 students leave the roll but their report cards stay."),
    )),
    "roll": ("Roll", (
        ("Every student, by class", "Search by name or admission number."),
        ("Import the whole roll at once", "Use the Excel or CSV template on the import page."),
        ("Add parents for each student", "A parent with a phone number can sign in to see report cards."),
    )),
    "staff": ("Staff", (
        ("Invite by email", "Each person gets a link to set their own password."),
        ("Pick the right role", "Teacher, bursar, vice principal or principal. A person can hold more than one."),
        ("Invitation not arrived?", "Resend it from this page, or check the address."),
    )),
    "notices-settings": ("Notices", (
        ("Tell parents what matters", "Choose which messages go out by SMS or email."),
        ("Each message costs a little", "Keep the ones parents need."),
        ("Test with your own number first", "Then switch it on for everybody."),
    )),
}

GENERAL = ("Classnode", (
    ("Start from Home", "Home shows what is waiting on you today."),
    ("Everything is in the menu", "On a phone, tap the menu at the top left to see every page."),
    ("Signed in on a shared phone?", "Sign out from the menu when you finish."),
))


def came_from(request) -> Optional[str]:
    """The same-host path in the `Referer`, or None."""
    referer = request.META.get("HTTP_REFERER", "")
    if not referer:
        return None
    parts = urlsplit(referer)
    if parts.scheme not in ("http", "https") or parts.netloc.lower() != request.get_host().lower():
        return None
    path = parts.path or "/"
    if not path.startswith("/") or path.startswith("//"):
        return None
    return path


def page_key(path: Optional[str]) -> Optional[str]:
    """The menu key of a path we have tips for: "/fees/" is "fees"."""
    if not path:
        return None
    for link in menu.LINKS:
        if path == link.href or path.startswith(link.href):
            return link.key
    return None


def for_page(path: Optional[str], roles) -> dict:
    """What the help page shows: the heading, the tips and where Back goes."""
    key = page_key(path)
    roles = set(roles)
    allowed = key is not None and key in TIPS and bool(menu.BY_KEY[key].roles & roles)
    heading, tips = TIPS[key] if allowed else GENERAL
    return {
        "key": key if allowed else None,
        "heading": heading,
        "tips": tips,
        # Back to where you were if that was a path on this host, else Home.
        "back": path if path and not path.startswith("/help/") else "/home/",
    }


__all__ = ["GENERAL", "SUPPORT_EMAIL", "SUPPORT_PROMISE", "TIPS", "came_from", "for_page", "page_key"]
