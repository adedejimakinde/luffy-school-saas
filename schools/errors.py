"""What an error report may carry off the server, and what it may not.

Decided 2026-09-23: Sentry (EU region) with personal data off. The options that
say so are in `settings.py` (`send_default_pii=False`, no local variables, no
request bodies); these two hooks are the part options cannot express.

**An invitation's address is a credential.** `/invitations/<token>/` and
`/api/invitations/<token>/…` make whoever holds them a school's new member, so
a URL carrying one is scrubbed wherever it appears in a report — the request,
the transaction name, a breadcrumb.

**SQL breadcrumbs are dropped.** A query's parameters are children's names,
marks and phone numbers; the traceback says where it failed without them.

**Every report says which school**, from the same `current_school()` the logs
use (`schools/logging.py`), so the first question about an incident has an
answer in the report itself.
"""

import re

from schools.logging import current_school

_TOKEN_IN_PATH = re.compile(r"(/(?:api/)?invitations/)[^/?#\s]+")

#: Request headers worth keeping; everything else (cookies, authorization,
#: forwarded addresses) stays on the server.
_HEADERS_KEPT = {"user-agent", "content-type", "accept", "host"}


def scrub_url(value):
    """`value` with any invitation token replaced by `[token]`."""
    if not value:
        return value
    return _TOKEN_IN_PATH.sub(r"\1[token]", value)


def before_send(event, hint):
    request = event.get("request")
    if request:
        for key in ("data", "cookies", "query_string", "env"):
            request.pop(key, None)
        headers = request.get("headers") or {}
        request["headers"] = {k: v for k, v in headers.items() if k.lower() in _HEADERS_KEPT}
        if "url" in request:
            request["url"] = scrub_url(request["url"])
    if "transaction" in event:
        event["transaction"] = scrub_url(event["transaction"])
    event["tags"] = {**(event.get("tags") or {}), "school": current_school() or "none"}
    return event


def before_breadcrumb(crumb, hint):
    if crumb.get("category") == "query":
        return None
    data = crumb.get("data")
    if isinstance(data, dict) and "url" in data:
        data["url"] = scrub_url(data["url"])
    if "message" in crumb:
        crumb["message"] = scrub_url(crumb["message"])
    return crumb


__all__ = ["before_breadcrumb", "before_send", "scrub_url"]
