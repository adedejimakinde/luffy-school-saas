"""`/dev/outbox/`: what the fake provider was given, for a developer. D2.

On the portal only, beside the sign-in page it exists to serve, and only under
`DEBUG`: routed only then (`urls_public.py`), and a 404 here as well if it is
ever reached otherwise. It shows codes in the clear, which is the point of it
and the reason for both.
"""

from django.conf import settings
from django.http import Http404
from django.shortcuts import render

from .models import FakeMessage


def outbox(request):
    if not settings.DEBUG:
        raise Http404("No such page.")
    messages = FakeMessage.objects.all()[:100]
    return render(request, "messaging/outbox.html", {"messages": messages})
