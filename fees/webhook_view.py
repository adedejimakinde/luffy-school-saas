"""The webhook's one URL, on the **portal host only** (`urls_public.py`).

A plain view, not part of the session-authenticated API: Paystack has no session,
so it is exempt from CSRF, and what stands in for a login is the signature
`fees.webhook.handle()` checks before it reads a byte of the body. POST only.
"""

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import webhook


@csrf_exempt
@require_POST
def paystack_webhook(request):
    status, body = webhook.handle(request.body, request.headers.get("x-paystack-signature", ""))
    return JsonResponse(body, status=status)
