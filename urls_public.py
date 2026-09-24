"""What the **portal host** serves: everything a school's host does, plus the admin.

The admin is here and only here, for the same reason `/api/login/` is: it is a
door, and a door on thirty hostnames is thirty doors to watch. It was previously
served from every school's host as well, which was worse than untidy — the admin
edits *shared* tables (users, memberships, schools, invitations), so serving it
from a tenant host meant privileged writes to platform-wide data issued from a
connection whose `search_path` had been set to one school's schema.

The API is reused from `urls.py` rather than repeated, so a route added there
cannot go missing here.
"""

from django.contrib import admin
from django.urls import path

from accounts.views import invitation_page, sign_in_page, staff_sign_in_page
from urls import handler403, urlpatterns as tenant_urlpatterns

urlpatterns = [
    path("admin/", admin.site.urls),
    # Sign-in is **here and only here**, which is why it is not in `urls.py`
    # among the routes both hosts share. The API routes behind it begin with
    # `api._portal_only()`, so a sign-in page on a school's host would be a
    # form that submits into a 404 — and a school's host refuses anyone without
    # an active membership there, which is the opposite of what a door needs.
    path("sign-in/", sign_in_page, name="sign-in"),
    # The staff door, on the same host and for the same reason: `api.sign_in()`
    # begins with `_portal_only()` too. Two routes and not one with a flag —
    # the flows share no step, and a query parameter deciding which form a
    # sign-in page shows is a page whose URL cannot be linked to.
    path("staff-sign-in/", staff_sign_in_page, name="staff-sign-in"),
    # Where an invitation's link lands (settings.INVITATION_ACCEPT_URL). Here
    # and only here, beside the two doors: the routes it calls answer on the
    # portal, and what it ends in is a pointer to the staff door above.
    path("invitations/<str:token>/", invitation_page, name="invitation"),
    *tenant_urlpatterns,
]

#: Re-exported, not re-declared. Django looks `handler403` up as an attribute of
#: whichever urlconf is in force, and `django_tenants` gives the public schema
#: this module instead of `urls.py` — so without this line the portal would fall
#: back to the default handler while every school's host used ours. Importing
#: the name keeps one definition; writing the dotted path again would be a
#: second copy to drift.
__all__ = ["urlpatterns", "handler403"]
