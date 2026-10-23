"""The school dashboard, drawn whole on the server.

Every figure, both drawings and every link arrive in this one response, so
the page has nothing to fetch after it and no script to run. What a login may
see is `home.dashboard`'s question, answered item by item; who may open the
page at all is answered here, **before** a single fact is read.

**No `login_required`**, for the oracle reason `results/views.py` gives: a
redirect on a guessable URL says the URL is real. Signed out, the page says
where to sign in; signed in as somebody who is not staff here, it says the page
is not theirs, in one sentence whatever the school holds; on the portal, it
says the dashboard lives on the school's own address.
"""

from django.shortcuts import render

from gradebook import assignments
from onboarding import first as first_days
from onboarding import progress as onboarding
from schools.hosts import portal_host

from . import dashboard, facts

TEMPLATE = "home/dashboard.html"


def home_page(request):
    school = getattr(request, "school", None)
    if school is None:
        return render(request, TEMPLATE, {"state": "elsewhere"}, status=404)
    user = request.user
    if not user.is_authenticated:
        return render(request, TEMPLATE, {"state": "signed-out", "portal_host": portal_host()})
    roles = request.school_roles
    if not roles & dashboard.HOME_ROLES:
        return render(request, TEMPLATE, {"state": "not-yours"}, status=403)
    dash = dashboard.build(facts.load(school), school=school, user=user, roles=roles)
    # Setup, from `onboarding.progress`: the administrator's next step as a
    # card at the top, until setup is first finished; the principal, while
    # there are no students yet, how far the administrator has got. Never a
    # redirect: only signing in sends an administrator to Start here.
    setup = onboarding.for_request(request)
    if setup is not None and setup.next is not None:
        # The next-step card says it already; the list below need not repeat it.
        dash["attention"] = [item for item in dash["attention"] if item["key"] != "contact"]
    if setup is None and dash["setup"] and not onboarding.is_onboarding(roles):
        setup = onboarding.progress_for(school)
    return render(request, TEMPLATE, {
        "state": "home",
        "dash": dash,
        "setup": setup,
        "leads_setup": onboarding.is_onboarding(roles),
        "first": first_days.card_for(request, school, user, roles),
        # The principal's prompt to say who teaches what, read live rather than from
        # the cached facts so it goes the moment the first assignment is made.
        "assign": not (dash["setup"] or dash["waiting"]) and assignments.prompt_for(roles),
    })


__all__ = ["home_page"]
