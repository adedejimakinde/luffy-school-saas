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
    invitation_page,
    roll_import_page,
    roll_page,
    sign_in_page,
    sign_out,
    staff_page,
    staff_sign_in_page,
)
from attendance.views import absences_page, register_page
from cbt import sit_views
from cbt.views import exam_slips_page, tests_page
from fees.views import bank_page, fees_page
from gradebook.views import marking_page, subject_teachers_page, subject_teachers_seen, teaching_page
from home.views import home_page
from onboarding.views import help_page, start_again_page, start_here, step_page
from notices.views import settings_page
from schools.paths import RESERVED
from schools.views import reserved
from schoolsite import editor as site_editor
from schoolsite import views as site
from files import views as files_views
from results.views import (
    broadsheet_page,
    master_broadsheet_page,
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
    # The school's public website (`schoolsite.views`, `docs/school-sites.md`):
    # today's page at the root until the school first publishes, then the
    # pages it switched on. Read by nobody's session (`schools.paths`).
    path("", site.home, name="school-site"),
    path("about/", site.about, name="school-site-about"),
    path("admissions/", site.admissions, name="school-site-admissions"),
    path("news/", site.news, name="school-site-news"),
    path("gallery/", site.gallery, name="school-site-gallery"),
    path("gallery/<slug:slug>/", site.album, name="school-site-album"),
    path("contact/", site.contact, name="school-site-contact"),
    path("pages/<slug:slug>/", site.custom_page, name="school-site-page"),
    path("sitemap.xml", site.sitemap, name="school-site-sitemap"),
    path("robots.txt", site.robots, name="school-site-robots"),
    # Files: public ones on the website's path, private ones on the portal's
    # (`files.views` says what each will send, to whom).
    path("media/<str:key>/<str:variant>", files_views.public_file, name="media-file"),
    path("files/<str:key>/<str:variant>", files_views.private_file, name="private-file"),
    path("api/", api.urls),
    # The offline worker: the marking and register pages kept for a phone with
    # no connection. At the root because a worker's scope is where it is served
    # from. Identical for every school and for a caller with no session.
    path("sw.js", service_worker, name="service-worker"),
    # The school's own two doors (`docs/sign-in-page.md`, "A school's own
    # door"): its crest, name and colour, for its own members only, and a
    # session good on this host alone. `urls_public.py` names the portal's,
    # listed before these, so the portal's own names win there.
    path("sign-in/", sign_in_page, name="school-sign-in"),
    path("staff-sign-in/", staff_sign_in_page, name="school-staff-sign-in"),
    # Where an invitation's link lands: the school it is for
    # (`settings.INVITATION_ACCEPT_URL`), and the portal too, for every link
    # sent before. Another school's invitation is a 404 here (`api._validated`).
    path("invitations/<str:token>/", invitation_page, name="invitation"),
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
    # Start here and the administrator's setup steps, and Help and next steps
    # for every member of staff (`onboarding`).
    path("start/", start_here, name="start-here"),
    # Start again: the principal clears the setup while there are no real
    # records yet. Before the step pattern, which "again" would also match.
    path("start/again/", start_again_page, name="start-again"),
    path("start/<slug:key>/", step_page, name="setup-step"),
    path("help/", help_page, name="help"),
    path("setup/", setup_page, name="school-setup"),
    # Subjects, this term's papers and the class teachers: the office's, beside setup.
    path("teaching/", teaching_page, name="teaching"),
    # Who teaches which subject to which class: the principal's, read by the office too.
    path("subject-teachers/", subject_teachers_page, name="subject-teachers"),
    # Home's Dismiss on "Assignments copied from last term".
    path("subject-teachers/seen/", subject_teachers_seen, name="subject-teachers-seen"),
    # Exam slips and exam officers (`docs/cbt.md`): the principal, the administrator and
    # an exam officer print; the principal names officers.
    path("exam-slips/", exam_slips_page, name="exam-slips"),
    # Question banks and tests (`docs/cbt.md`, step 3): teachers write and set, the
    # principal or the vice principal approves; the administrator sees the list with no question in it.
    path("tests/", tests_page, name="tests"),
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
    # One class's master broadsheet: the table, and its PDF and Excel files.
    path(
        "master-broadsheet/<int:class_group_id>/<int:term_id>/",
        master_broadsheet_page,
        name="master-broadsheet",
    ),
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
    # The exam door and the exam screen (`docs/cbt.md`, step 4): a student with no
    # account sits a test with the code, their admission number and their exam PIN. Its
    # own small API and service worker live under it, because the cookie it sets is
    # scoped to `/sit/` and the worker's scope is where it is served from.
    path("sit/", sit_views.sit_page, name="sit"),
    path("sit/sw.js", sit_views.sit_worker, name="sit-worker"),
    path("sit/api/door/", sit_views.door, name="sit-door"),
    path("sit/api/not-me/", sit_views.not_me, name="sit-not-me"),
    path("sit/api/start/", sit_views.start, name="sit-start"),
    path("sit/api/attempt/", sit_views.attempt, name="sit-attempt"),
    path("sit/api/sync/", sit_views.sync, name="sit-sync"),
    path("sit/api/submit/", sit_views.submit, name="sit-submit"),
    path("sit/pictures/<str:key>/<str:variant>", sit_views.picture, name="sit-picture"),
    # The school's website editor and its preview of the draft (`schoolsite.editor`,
    # `docs/school-sites.md` PR 4): a portal path, never indexed.
    path("website/", site_editor.editor_page, name="website-editor"),
    path("website/preview/", site_editor.preview, name="website-preview"),
    path("website/preview/pages/<slug:slug>/", site_editor.preview_custom_page, name="website-preview-page"),
    path("website/photos/", site_editor.photos_page, name="website-photos"),
    path("website/look/", site_editor.look_page, name="website-look"),
    path("website/preview/gallery/<slug:slug>/", site_editor.preview_album, name="website-preview-album"),
    path("website/pictures/<str:key>/<str:variant>", site_editor.picture, name="website-picture"),
    path("website/preview/<slug:key>/", site_editor.preview_page, name="website-preview-fixed"),
    # Names held for work not yet built (`schools.paths.RESERVED`): a 404 at the name
    # and everywhere under it until the work is routed here.
    *(
        pattern
        for name in RESERVED
        for pattern in (
            path(f"{name}/", reserved, name=f"reserved-{name}"),
            path(f"{name}/<path:rest>", reserved),
        )
    ),
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
