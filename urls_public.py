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

from django.conf import settings
from django.contrib import admin
from django.urls import path, re_path
from django.views.generic import RedirectView

from accounts.views import sign_in_page, staff_sign_in_page
from blog import write_views as write
from fees.webhook_view import paystack_webhook
from onboarding.views import handover_page
from schools.views import platform_page
from urls import handler403, urlpatterns as tenant_urlpatterns

urlpatterns = [
    path("admin/", admin.site.urls),
    # The portal's two doors: Classnode's look, for anybody with an account,
    # naming every school the login reaches. Each school's host has its own
    # pair as well (`urls.py`), in the school's look and for its members alone;
    # named here so `reverse("sign-in")` is the portal's. Two routes and not one
    # with a flag — the flows share no step, and a query parameter deciding
    # which form a sign-in page shows is a page whose URL cannot be linked to.
    path("sign-in/", sign_in_page, name="sign-in"),
    path("staff-sign-in/", staff_sign_in_page, name="staff-sign-in"),
    # The invitation page is in `urls.py`, served here as well by the splat
    # below: every link sent before invitations went to a school's own host
    # points here, and still opens.
    # The platform operator's screen: every school, and a way to add one. Here
    # and only here; its API answers 404 on a school's host and 403 to anyone
    # who is not platform staff.
    path("platform/", platform_page, name="platform"),
    # New school handover: each school's checklist and its welcome message.
    # Here and only here, and platform staff only (`onboarding.handover`).
    path("platform/handover/", handover_page, name="platform-handover"),
    # Paystack's webhook: here and only here, and signed instead of logged in.
    path("api/paystack/webhook/", paystack_webhook, name="paystack-webhook"),
    # Classnode's blog, the writing side (`blog.write_views`): here and only
    # here, for the blog's writers and editors. The published posts are on the
    # public site (`urls_site.py`); nothing unpublished is ever served there.
    path("write/sign-in/", write.sign_in, name="write-sign-in"),
    path("write/sign-out/", write.sign_out, name="write-sign-out"),
    path("write/", write.posts, name="write-posts"),
    path("write/new/", write.new, name="write-new"),
    path("write/review/", write.review, name="write-review"),
    path("write/posts/<int:pk>/", write.editor, name="write-post"),
    path("write/posts/<int:pk>/preview/", write.preview, name="write-preview"),
    path("write/posts/<int:pk>/images/", write.upload, name="write-upload"),
    path("write/posts/<int:pk>/view/", write.view, name="write-view"),
    re_path(r"^write/images/(?P<key>[0-9a-f]{32})\.webp$", write.portal_image, name="write-image"),
    re_path(r"^write/images/(?P<key>[0-9a-f]{32})-small\.webp$", write.portal_image_small, name="write-image-small"),
    # The portal has no front page of its own: `app.<domain>/` used to fall
    # through to the school's page below, which is not a school here, and answered
    # "Not Found". Everybody who types the portal's name wants a door, and the
    # staff door has the link to the parent one. Temporary, so it can become a
    # page of its own later.
    path("", RedirectView.as_view(pattern_name="staff-sign-in", permanent=False), name="portal-root"),
    *tenant_urlpatterns,
]

# The fake provider's outbox, which shows codes in the clear: routed only under
# DEBUG, and refused by the view as well (docs/messaging.md D2).
if settings.DEBUG:
    from messaging.views import outbox

    urlpatterns.insert(0, path("dev/outbox/", outbox, name="dev-outbox"))

#: Re-exported, not re-declared. Django looks `handler403` up as an attribute of
#: whichever urlconf is in force, and `django_tenants` gives the public schema
#: this module instead of `urls.py` — so without this line the portal would fall
#: back to the default handler while every school's host used ours. Importing
#: the name keeps one definition; writing the dotted path again would be a
#: second copy to drift.
__all__ = ["urlpatterns", "handler403"]
