"""Local only, never committed: serve the demo behind Codespaces port forwarding.

The forwarding proxy delivers every request as Host: localhost:<port> and puts
the real hostname in X-Forwarded-Host, so django-tenants cannot tell the portal
from the school without USE_X_FORWARDED_HOST.
"""
from settings import *  # noqa: F401,F403

USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
CSRF_TRUSTED_ORIGINS = ["https://sturdy-guide-p7wwr6jv65wg29wvp-8002.app.github.dev", "https://sturdy-guide-p7wwr6jv65wg29wvp-8001.app.github.dev"]
# The proxy rewrites Origin as well: a POST from the forwarded page arrives with
# Origin: http://localhost:<port>. The CSRF token check still applies.
CSRF_TRUSTED_ORIGINS += ["http://localhost:8002", "http://localhost:8001"]
