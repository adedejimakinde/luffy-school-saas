"""`/test-scores/` on a school's own host: a student's and a parent's released test scores.

`docs/cbt.md`, "Release and CA", screens 09a and 09b. One page, two readers:

- **A parent**, signed in, is shown their own children's released scores by
  `GET /api/cbt/scores/` (`cbt.results_api`): no question, no answer, no class average.
- **A student** has no account, so the page is a door, like `/sit/` and the result
  checker: the test code (the teacher reads it out, as the "review code"), their admission
  number and their exam PIN, sent to `POST /test-scores/api/open/` (`open_scores`),
  behind the exam door's throttle and its one refusal. It answers with their own released
  score and corrections for that test, and their other released scores. **The exam PIN is
  always asked**: a practice test without one is never released (audit F-08), so there
  is nothing here a number alone opens. Wrong tries are counted against this browser and
  its address, never against the number typed (audit F-09): the one cookie it sets is the
  door's random device id (`sit_views.DEVICE_COOKIE`, scoped to `/test-scores/`), which
  names nobody. It keeps nothing else: closing the page ends it.

Not under `/sit/`, so the exam page's service worker (scoped to `/sit/`) never sees it.
A guardian's account session is never offered the student's door (`docs/parent-access.md`
D2): their page is their children's scores.
"""

import pages
from django.http import Http404
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from accounts.throttling import client_address

from . import release, sitting
from .sit_views import _a_guardian, _api, _ok, device_of, keep_device

PATH = "/test-scores/"

#: The page's modules, entry point last.
SCORES_MODULES = (
    "web/html.js",
    "web/http.js",
    "test-scores/api.js",
    "test-scores/states.js",
    "test-scores/app.js",
)


@never_cache
def scores_page(request):
    """The frame. Holds no student, no score and no question; the module asks."""
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("Test scores are on each school's own address.")
    from schools import brand

    response = render(
        request,
        "cbt/test_scores_page.html",
        {
            "import_map": pages.import_map(*SCORES_MODULES),
            "school_brand": brand.for_request(request, door=True),
            "guardian": _a_guardian(request, school),
        },
    )
    response["Cache-Control"] = "no-store, private"
    device, made = device_of(request)
    return keep_device(response, request, device, made, path=PATH)


@require_POST
@_api
def open_scores(request, school, body):
    """The code, the admission number and the PIN: one refusal for every failure of them,
    counted against this browser and its address."""
    device, made = device_of(request)
    try:
        found = release.student_scores(
            school,
            code=str(body.get("code") or ""),
            admission_number=str(body.get("admission_number") or ""),
            pin=str(body.get("pin") or ""),
            address=client_address(request),
            device=device,
        )
    except sitting.SitError as exc:
        exc.device, exc.device_path = (device, made), PATH
        raise
    response = _ok({"name": found.name, "class_name": found.class_name, "this": found.this, "earlier": found.earlier})
    return keep_device(response, request, device, made, path=PATH)


__all__ = ["SCORES_MODULES", "open_scores", "scores_page"]
