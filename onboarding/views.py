"""Start here, one page per setup step, and Help and next steps.

Drawn whole on the server, like the dashboard: no script, nothing fetched
after the page. Who may open each is answered here **before** a single step is
read, in the dashboard's words (`home/views.py`): signed out, the page says
where to sign in; signed in as somebody it is not for, it says so in one
sentence whatever the school holds; on the portal, it says the page lives on
the school's own address.

**No `login_required`**, for the oracle reason `results/views.py` gives.
"""

from datetime import date

from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone

from home.dashboard import HOME_ROLES, first_name
from schools.hosts import portal_host

from audit import log as audit_log

from . import again, handover, later
from . import help as tips
from . import progress as steps

START = "onboarding/start.html"
STEP = "onboarding/step.html"
HELP = "onboarding/help.html"
AGAIN = "onboarding/again.html"


def _refusal(request, template, roles, current):
    """The state to draw instead, or None when this login may see the page."""
    if getattr(request, "school", None) is None:
        return render(request, template, {"state": "elsewhere", "current": current}, status=404)
    if not request.user.is_authenticated:
        return render(request, template, {
            "state": "signed-out", "current": current, "portal_host": portal_host(),
        })
    if not request.school_roles & roles:
        return render(request, template, {"state": "not-yours", "current": current}, status=403)
    return None


def _share_with_the_chip(request, progress):
    """Hand this read to the setup chip, so the page and the chip share it.
    Only for whoever setup is brought to (`progress.LEAD_ROLES`): a principal
    opening the steps gets no chip."""
    lead = steps.is_onboarding(request.school_roles)
    request._onboarding_progress = progress if lead and not progress.complete else None


def _details(school, facts):
    """The first step's two parts, each given, put off, or still to do."""
    rows = []
    for what, given, label, href in (
        ("contact-email", facts["contact_email"], "Contact email", "/setup/#contact-email"),
        ("crest", facts["crest"], "Crest", "/setup/#report-card"),
    ):
        column, name = later.LATER[what]
        rows.append({
            "what": what,
            "label": label,
            "given": bool(given),
            "later": getattr(school, column) is not None,
            "href": href,
            "name": name,
        })
    return rows


def start_here(request):
    refused = _refusal(request, START, steps.ONBOARDING_ROLES, "start")
    if refused is not None:
        return refused
    school = request.school
    progress = steps.progress_for(school)
    _share_with_the_chip(request, progress)
    put_off = [d for d in _details(school, progress.facts) if d["later"] and not d["given"]]
    return render(request, START, {
        "state": "start",
        "current": "start",
        "progress": progress,
        "name": first_name(request.user),
        "school_name": school.name,
        "put_off": put_off,
        "changes": audit_log.recent(5),
        "may_start_again": again.may_start_again(request.user, school),
        "started_again": request.GET.get("started-again") == "1",
    })


def step_page(request, key):
    refused = _refusal(request, STEP, steps.ONBOARDING_ROLES, "start")
    if refused is not None:
        return refused
    if key not in steps.BY_KEY:
        raise Http404("No such step.")
    school = request.school
    note = ""
    if request.method == "POST":
        # "Add later", on the first step: a form post, so the page needs no script.
        try:
            later.put_off_as(request.user, school, request.POST.get("what", ""))
        except later.NotAllowedToPutOff:
            return render(request, STEP, {"state": "not-yours", "current": "start"}, status=403)
        except later.NothingToPutOff:
            note = "Choose the contact email or the crest to add later."
        else:
            return redirect(f"/start/{key}/")
    progress = steps.progress_for(school)
    _share_with_the_chip(request, progress)
    here = progress.by_key[key]
    index = progress.steps.index(here)
    after = progress.steps[index + 1] if index + 1 < len(progress.steps) else None
    return render(request, STEP, {
        "state": "step",
        "current": "start",
        "progress": progress,
        "here": here,
        "after": after,
        "hint": steps.hint_for(here, progress.facts),
        "may_do": steps.may_do(here.step, request.school_roles),
        "details": _details(school, progress.facts) if key == "school-details" else None,
        "note": note,
    }, status=422 if note else 200)


def start_again_page(request):
    """Start again: what it clears, what stays, and the typed confirmation.

    The principal's alone (`again.AGAIN_ROLES`), asked before anything of the
    school is read. A POST clears, then shows Start here; a refusal draws the
    page again with the reason and changes nothing."""
    refused = _refusal(request, AGAIN, again.AGAIN_ROLES, "again")
    if refused is not None:
        return refused
    school = request.school
    note = ""
    if request.method == "POST":
        try:
            again.start_again_as(
                request.user, school,
                typed_name=request.POST.get("school_name", ""),
                fingerprint=request.POST.get("plan", ""),
            )
        except again.NotAllowedToStartAgain:
            return render(request, AGAIN, {"state": "not-yours", "current": "again"}, status=403)
        except again.StartAgainRefused as exc:
            note = str(exc)
        else:
            return redirect("/start/?started-again=1")
    return render(request, AGAIN, {
        "state": "again",
        "current": "again",
        "plan": again.plan(school),
        "school_name": school.name,
        "note": note,
    }, status=422 if note else 200)


def help_page(request):
    refused = _refusal(request, HELP, HOME_ROLES, "help")
    if refused is not None:
        return refused
    page = tips.for_page(tips.came_from(request), request.school_roles)
    return render(request, HELP, {
        "state": "help",
        "current": "help",
        "page": page,
        "progress": steps.for_request(request),
        "support_email": tips.SUPPORT_EMAIL,
        "support_promise": tips.SUPPORT_PROMISE,
    })




# -- New school handover: the platform's, on the portal ---------------------------


def handover_page(request):
    """Every new school's handover checklist, and its welcome message.

    The portal only, and platform staff only, both asked before any table is
    read: a school's host has no such page (404), and anybody else is told
    in one sentence that the page is not theirs (403). A school never sees it.
    """
    template = "onboarding/handover.html"
    if getattr(request, "school", None) is not None:
        raise Http404("This page is on the portal host.")
    if not handover.is_platform_staff(request.user):
        state = "signed-out" if not request.user.is_authenticated else "not-yours"
        return render(request, template, {"state": state, "portal_host": portal_host()}, status=403)

    schools = handover.customers()
    hosts = handover.hosts_of(schools)
    slug = request.POST.get("school") if request.method == "POST" else request.GET.get("school")
    chosen = next((s for s in schools if s.slug == slug), schools[0] if schools else None)

    note = ""
    if request.method == "POST" and chosen is not None:
        try:
            signed_on = date.fromisoformat(request.POST.get("signed_on", ""))
        except ValueError:
            note = "Give the date the agreement was signed."
        else:
            try:
                handover.record_pilot_agreement(request.user, chosen, signed_on)
            except handover.HandoverRefused as exc:
                note = str(exc)
            else:
                return redirect(f"/platform/handover/?school={chosen.slug}")

    portal = portal_host()
    rows = [handover.handover_for(s, host=hosts.get(s.pk), portal=portal) for s in schools]
    current = next((r for r in rows if chosen is not None and r.school.pk == chosen.pk), None)
    return render(request, template, {
        "state": "handover",
        "rows": rows,
        "current": current,
        "note": note,
        "today": timezone.localdate(),
    }, status=422 if note else 200)


__all__ = ["handover_page", "help_page", "start_again_page", "start_here", "step_page"]
