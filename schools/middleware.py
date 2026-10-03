"""Which school a request is for, and the one host that is no school's.

django-tenants' `TenantMainMiddleware` resolves every request's host against
`schools.Domain` and answers 404 for a host it does not know. That is the
allowlist this platform relies on (`settings.ALLOWED_HOSTS` says so), and it
stays exactly as it was for every host but one.

The one is `SITE_HOST`, Classnode's public site on the bare domain. It is
deliberately **not** a `Domain` row. A row would make it the portal (the public
schema's urlconf, with the admin and both sign-in doors on it), and
`urls_public.py` is written on the rule that a door is served from one host
only. So the site host gets its own urlconf, `urls_site`, which routes the
site's pages and nothing else, and the connection is left on the public schema
where django-tenants put it before looking the host up.

`request.tenant` is not set, as for any host that is not a school; nothing on
the site's pages reads it, and `accounts.middleware.SchoolAccessMiddleware`
reads the connection's tenant, which is the public one.
"""

from django.conf import settings
from django.urls import set_urlconf
from django_tenants.middleware.main import TenantMainMiddleware


class PlatformTenantMiddleware(TenantMainMiddleware):
    def no_tenant_found(self, request, hostname):
        site_host = getattr(settings, "SITE_HOST", None)
        if site_host and hostname == site_host:
            request.urlconf = settings.SITE_URLCONF
            set_urlconf(request.urlconf)
            return None
        return super().no_tenant_found(request, hostname)


__all__ = ["PlatformTenantMiddleware"]
