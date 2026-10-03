"""Classnode's public site: the homepage, on `settings.SITE_HOST` only.

All server-drawn, like a school's own page (`schools.views.school_site`): the
one module it loads moves the slides and the fade-ups and is not needed to read
anything or to send the form.
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.throttling import client_address
from schools.hosts import portal_host

from .forms import DemoRequestForm
from .models import DemoRequest
from .notify import demo_requested

#: The site's one module. It imports nothing, so it needs no import map: its
#: `{% static %}` URL is hashed and there is nothing behind it to go stale
#: (`tests/test_pages.py` holds it to that).
SITE_MODULES = ("website/site.js",)

#: Where the form sends a reader back to once it is saved: the thank-you, in
#: place of the form, and the browser's back and reload do not post it twice.
SENT = "/?sent=1#demo"


def too_many_from(address):
    """Whether this address has left its hour's worth of requests already."""
    since = timezone.now() - timedelta(hours=1)
    return (
        DemoRequest.objects.filter(address=address, created_at__gte=since).count()
        >= settings.DEMO_REQUESTS_PER_HOUR
    )


@require_http_methods(["GET", "HEAD", "POST"])
def homepage(request):
    form = DemoRequestForm()
    status = 200
    refused = ""
    if request.method == "POST":
        form = DemoRequestForm(request.POST)
        if form.is_bait_taken():
            # Answered as if it worked, so a script learns nothing from it.
            return redirect(SENT)
        if not form.is_valid():
            refused, status = "invalid", 400
        else:
            address = client_address(request)
            if too_many_from(address):
                refused, status = "limited", 429
            else:
                demo = form.save(commit=False)
                demo.address = address
                demo.save()
                transaction.on_commit(lambda: demo_requested(demo.pk))
                return redirect(SENT)
    return render(
        request,
        "website/home.html",
        {
            "form": form,
            "refused": refused,
            "sent": request.method == "GET" and request.GET.get("sent") == "1",
            "portal_host": portal_host(),
        },
        status=status,
    )
