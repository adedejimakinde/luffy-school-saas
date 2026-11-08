"""The exam slips screen: a frame, and not a PIN in it.

A shell like every staff page (`gradebook/views.py` says why): a frame, a stylesheet
and a few ES modules, with **no `login_required`**, because a redirect on a guessable
URL is an oracle. `cbt.api` asks who is asking before it reads anything.
"""

import pages
from django.shortcuts import render

from schools.hosts import portal_host

#: The exam slips page's modules, entry point last.
EXAM_SLIPS_MODULES = (
    "web/html.js",
    "web/http.js",
    "web/picker.js",
    "exam-slips/api.js",
    "exam-slips/states.js",
    "exam-slips/app.js",
)


#: The Tests page's modules, entry point last.
TESTS_MODULES = (
    "web/html.js",
    "web/http.js",
    "web/picker.js",
    "tests/api.js",
    "tests/states.js",
    "tests/app.js",
)


#: A test's results page's modules (CBT step 5), entry point last.
RESULTS_MODULES = (
    "web/html.js",
    "web/http.js",
    "web/picker.js",
    "test-results/api.js",
    "test-results/states.js",
    "test-results/app.js",
)


def results_page(request):
    """The frame for `/tests/results/`: a test's results, item analysis, release and Send to
    CA. Its own page beside the Tests page, so neither carries the other's modules.

    No score and no question is in the frame. `cbt.results_api` asks who is asking before
    it reads one, and serves the administrator the released scores alone.
    """
    return render(
        request,
        "cbt/test_results_page.html",
        {
            "import_map": pages.import_map(*RESULTS_MODULES),
            "portal_host": portal_host(),
        },
    )


def tests_page(request):
    """The frame for `/tests/`: question banks, setting a test, and approving one.

    No question is in the frame. `cbt.bank_api` asks who is asking before it reads one,
    and never answers the administrator, a bursar, a parent or a student with one.
    """
    return render(
        request,
        "cbt/tests_page.html",
        {
            "import_map": pages.import_map(*TESTS_MODULES),
            "portal_host": portal_host(),
        },
    )


def exam_slips_page(request):
    """The frame for `/exam-slips/`: print exam slips, and the principal names exam officers."""
    return render(
        request,
        "cbt/exam_slips_page.html",
        {
            "import_map": pages.import_map(*EXAM_SLIPS_MODULES),
            "portal_host": portal_host(),
        },
    )


__all__ = ["EXAM_SLIPS_MODULES", "RESULTS_MODULES", "TESTS_MODULES", "exam_slips_page", "results_page", "tests_page"]
