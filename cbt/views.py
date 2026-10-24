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


__all__ = ["EXAM_SLIPS_MODULES", "exam_slips_page"]
