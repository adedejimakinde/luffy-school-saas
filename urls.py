"""What a **school's own host** serves.

The API, and the report card page that calls it. In particular not the admin:
see `urls_public.py`, which is what the portal serves and where the admin now
lives.

The page is here rather than on the portal for the session cookie's sake: a
frame served from one host calling another is cross-site, and the cookie that
authenticates a parent would not be sent with the fetch. `results/views.py`
says the rest.

`django_tenants` picks between the two by schema. `ROOT_URLCONF` (this file) is
what a tenant host gets; `PUBLIC_SCHEMA_URLCONF` replaces it on the public
schema, which is the portal. So "the admin is on the portal only" is enforced by
routing rather than by a check inside a view somebody could forget to add.
"""

from django.urls import path

from api import api
from academics.views import promotion_page, setup_page
from accounts.views import (
    roll_import_page,
    roll_page,
    sign_in_page,
    sign_out,
    staff_page,
    staff_sign_in_page,
)
from attendance.views import absences_page, register_page
from fees.views import bank_page, fees_page
from gradebook.views import marking_page
from home.views import home_page
from notices.views import settings_page
from schools.demo import only_in_the_single_host_demo
from schools.views import school_site
from results.views import (
    broadsheet_page,
    card_index_page,
    card_page,
    chain_page,
    checker_page,
    comments_page,
    ogsera_page,
)
from sync.views import service_worker
from timetable.views import timetable_page

urlpatterns = [
    # A school's public page: its face to a family, on its own address.
    path("", school_site, name="school-site"),
    path("api/", api.urls),
    # The offline worker: the marking and register pages kept for a phone with
    # no connection. At the root because a worker's scope is where it is served
    # from. Identical for every school and for a caller with no session.
    path("sw.js", service_worker, name="service-worker"),
    # Development only (`settings.DEMO_SINGLE_HOST`): the two doors on a
    # school's own host too, so one forwarded port is the whole demo. A 404
    # unless `schools.demo.single_host()`. `urls_public.py` serves the real
    # ones on the portal, listed before these, so they win there.
    path(
        "sign-in/",
        only_in_the_single_host_demo(sign_in_page),
        name="demo-sign-in",
    ),
    path(
        "staff-sign-in/",
        only_in_the_single_host_demo(staff_sign_in_page),
        name="demo-staff-sign-in",
    ),
    # The first staff surface on a school's host, and the mirror image of the
    # two sign-in pages: they are portal-only because a door needs a host that
    # lets somebody with no membership through, and this needs the one host
    # that will not.
    #
    # `urls_public.py` splats these patterns in, so the **portal serves this
    # frame too** — exactly as it already serves `/cards/`. That is harmless
    # and deliberate rather than an oversight: the frame holds nothing, and
    # every `attendance` route it fetches begins with `_school_of()`, which
    # raises `Http404` on the portal because the register tables do not exist
    # in the public schema. The page has a state for that answer.
    # The office's own surface: the calendar and the class groups.
    # The menu's Sign out, on every staff page: a POST, CSRF-checked.
    path("sign-out/", sign_out, name="sign-out"),
    # The principal's and the vice principal's first screen.
    path("home/", home_page, name="home"),
    path("setup/", setup_page, name="school-setup"),
    path("promotion/", promotion_page, name="promotion"),
    path("roll/", roll_page, name="roll"),
    path("roll/import/", roll_import_page, name="roll-import"),
    path("staff/", staff_page, name="staff"),
    path("notices/settings/", settings_page, name="notices-settings"),
    path("register/", register_page, name="register"),
    # Who is absent too often: the principal's, on the broadsheet's terms.
    path("absences/", absences_page, name="absences"),
    # The second staff surface, on the same terms as the register above.
    path("marking/", marking_page, name="marking"),
    # The third staff surface, on the same terms as the two above.
    path("results/", chain_page, name="results-chain"),
    path("broadsheet/", broadsheet_page, name="broadsheet"),
    # The fourth staff surface, on the same terms as the three above.
    path("comments/", comments_page, name="comments"),
    path("ogsera/", ogsera_page, name="ogsera"),
    # The bursar's, on the broadsheet's terms.
    path("fees/", fees_page, name="fees"),
    path("bank/", bank_page, name="bank"),
    # Who teaches what, when: every teacher reads it, on the same terms.
    path("timetable/", timetable_page, name="timetable"),
    path("cards/", card_index_page, name="report-card-index"),
    path(
        "cards/<int:student_membership_id>/<int:term_id>/",
        card_page,
        name="report-card-page",
    ),
    # The result checker: a family with no account opens a card with the
    # admission number and the PIN from a slip (docs/messaging.md D11).
    path("check/", checker_page, name="result-checker"),
]

#: The 403 page, named here so **a school's host** has one — which is the host
#: `SchoolAccessMiddleware` refuses people on, and therefore the only host where
#: its two refusals are ever raised. Django resolves this off the urlconf in
#: force, and `django_tenants` swaps that per schema, so the portal needs its
#: own name for the same view; `urls_public.py` imports this one rather than
#: writing a second string that could drift.
#:
#: Issue #122: before this, both refusals fell to Django's default handler,
#: which rendered `ERROR_PAGE_TEMPLATE` with empty `details` and discarded the
#: sentence each one carried.
handler403 = "accounts.views.refused"
