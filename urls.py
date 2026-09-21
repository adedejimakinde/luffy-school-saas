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
from results.views import card_index_page, card_page

urlpatterns = [
    path("api/", api.urls),
    path("cards/", card_index_page, name="report-card-index"),
    path(
        "cards/<int:student_membership_id>/<int:term_id>/",
        card_page,
        name="report-card-page",
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
