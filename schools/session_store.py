"""Django's database sessions, which know whose host a session was made on.

`settings.SESSION_ENGINE`. Everything is Django's except `load()`, which refuses
a session on a host it does not belong to, whatever cookie carried it there
(`docs/sign-in-page.md`, "A school's own door").

Two kinds of session, told apart by the cookie that carries them
(`schools.sessions`):

- **The portal's** (`sessionid`, scoped to the platform domain): made by
  signing in on `app.<domain>`. Valid on the portal and on every school's
  host, where `SchoolAccessMiddleware` still asks for a membership there. This
  is the session the platform has always had.
- **A school's** (`school_session`, host-only): made by signing in on that
  school's own host, and **bound** to that school: `SIGNED_IN_AT` holds its id.
  Valid on that school's host and nowhere else, the portal included.

The browser already keeps a school's cookie to its own host, because it has no
`Domain` attribute. This is the second lock, for everything a browser is not:
a cookie copied by hand, one set for the parent domain by a sibling host, or a
test client, which keeps one jar for every host.

A store made outside a request (the test client's `login()`, `clearsessions`)
has no host, so nothing is checked: there is nothing to check against.
"""

from django.contrib.auth import SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore as DatabaseSessionStore

#: The session key holding the school a session was signed in at, on its own host.
SIGNED_IN_AT = "_signed_in_at_school"

#: Which cookie carries a session (`schools.sessions` chooses).
PORTAL = "portal"
SCHOOL = "school"


def belongs_here(data, *, kind, school_id) -> bool:
    """May this session's `data` be used on a host whose school is `school_id` (None: not a school)?

    - A session bound to a school is good on that school's host alone.
    - A signed-in session arriving in a school's cookie must be bound to that
      school: the school's cookie only ever carries a session signed in there.
    - Anything else (a portal session, or a school's session nobody has signed
      in on yet, holding only a shared handset's pick) is as it always was.
    """
    bound = data.get(SIGNED_IN_AT)
    if bound is not None and bound != school_id:
        return False
    if kind == SCHOOL and SESSION_KEY in data and bound != school_id:
        return False
    return True


class SessionStore(DatabaseSessionStore):
    #: Set by `schools.sessions.SessionMiddleware` on the store it makes for a
    #: request. None on a store made anywhere else, which checks nothing.
    kind = None
    #: The id of the school whose host this request is on, or None.
    school_id = None

    def load(self):
        data = super().load()
        if self.kind is None or belongs_here(data, kind=self.kind, school_id=self.school_id):
            return data
        # Not this host's: the request goes on as if no cookie had been sent,
        # and the session itself is left alone for the host it belongs to. A
        # write after this makes a new session with a new key, never this one.
        self._session_key = None
        return {}


__all__ = ["PORTAL", "SCHOOL", "SIGNED_IN_AT", "SessionStore", "belongs_here"]
