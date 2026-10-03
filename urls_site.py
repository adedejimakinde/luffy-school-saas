"""What the **public site host** serves (`settings.SITE_HOST`, the bare domain).

Classnode's own pages for a school that is not a customer yet, and nothing
else: no API, no admin, no sign-in. The doors are linked from here and stay on
the portal, for the reason `urls_public.py` gives. Chosen by
`schools.middleware.PlatformTenantMiddleware`, which is the only thing that
routes a request here.
"""

from django.urls import path

from website.views import homepage

urlpatterns = [
    path("", homepage, name="site-home"),
]
