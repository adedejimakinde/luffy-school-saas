"""`/healthz/`: is this process up, and can it reach its database?

Asked by three things, none of which come through the TLS proxy or care which
school a host belongs to: the web container's own healthcheck, the deploy
script after it swaps containers, and an external uptime monitor. So it is
answered by a middleware at the very top of the stack, before the HTTPS
redirect and before `TenantMainMiddleware` resolves a host to a school — a
health check that needed a `Domain` row would report a missing school as a
dead server.

**It touches the database, because that is the question.** A process that is
up and cannot reach Postgres serves nothing but errors, and a health check that
answered 200 without asking would wave a deploy through onto exactly that. One
`SELECT 1`, touching no table, so it says nothing about any school and reads
nothing that belongs to one.

It answers the same on every host, including ones that are nobody's: it has
nothing to say about which hosts exist, so it is not an oracle for them.
"""

from django.db import DatabaseError, connection
from django.http import HttpResponse

PATH = "/healthz/"


def _answer(body, status):
    response = HttpResponse(body, status=status, content_type="text/plain; charset=utf-8")
    response["Cache-Control"] = "no-store"
    return response


class HealthCheckMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path != PATH:
            return self.get_response(request)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except DatabaseError:
            return _answer("database unavailable\n", 503)
        return _answer("ok\n", 200)
