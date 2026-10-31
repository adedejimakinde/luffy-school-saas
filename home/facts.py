"""Every number the dashboard shows, read in three statements and cached.

## Three statements, whatever the size of the school

Each statement is one `SELECT json_build_object(...)` whose parts are
aggregates over the table that owns them, so the database does the counting
and hands back one row of JSON:

1. **people**: the current term, the classes and who is placed in them, the
   previous term's roll, staff and student counts, class teachers, this week's
   and the two weeks before's registers, staff invitations and the crest.
2. **money**: this term's ledger, by kind, by week, and by family.
3. **work**: the results sheets and their steps, papers with marks started,
   and remarks written.

A school still being set up (no students yet) needs only the first, and is
not cached: its numbers change with every step the office takes, and the
checklist should tick the moment a step is done.

## Cached per school, for five minutes

The facts are **the school's**, not any one reader's: every class, every
paper, every class teacher. `home.dashboard` narrows them to what a login may
see after they come out of the cache, so one cached copy serves every role at
one school and nothing one person may see is ever cached under a key another
school can reach.

The key names the tenant schema the statements ran in
(`connection.schema_name`), the school's id, and the day. A key without the schema would hand
one school's figures to the next school that asked on the same day;
`home/tests/test_dashboard.py` holds that, with its control.

## Days are Lagos days

`timezone.localdate()`, as everywhere else on the platform: a register taken
at 00:30 on Monday is a Monday register.
"""

import base64
import io
from datetime import date, timedelta
from typing import Optional

from django.core.cache import cache
from django.db import connection
from django.utils import timezone

from accounts.models import STAFF_ROLES

#: How long one school's facts are served from the cache.
CACHE_SECONDS = 5 * 60

#: Bumped when the shape of the facts changes, so a deploy never reads a
#: cached copy written by the code before it.
VERSION = 1

#: The crest is stored as a 256px square (`results.look.CREST_SIDE`). The
#: header draws it at 56px; this is twice that, for a sharp phone screen, and a
#: few kilobytes rather than tens.
CREST_SIDE = 112


def cache_key(schema: str, school_id: int, today: date) -> str:
    """The schema the facts were read in, the school row, and the day.

    The schema is what makes the facts this school's. The row's id is there
    too because a schema name can be reused (a school removed and another
    created under the same slug, or every test in the suite) and an id never
    is: a reused name must not inherit a cached copy."""
    return f"home:facts:v{VERSION}:{schema}:{school_id}:{today.isoformat()}"


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def lagos_today() -> date:
    """The school's calendar date. One function, so a test can pin it."""
    return timezone.localdate()


def load(school, today: Optional[date] = None) -> dict:
    """This school's facts for `today`, from the cache when they are there."""
    today = today or lagos_today()
    key = cache_key(connection.schema_name, school.pk, today)
    facts = cache.get(key)
    if facts is not None:
        return facts
    facts = read(school, today)
    if not facts["setting_up"]:
        cache.set(key, facts, CACHE_SECONDS)
    return facts


def read(school, today: date) -> dict:
    """The three statements, uncached. At most three queries; one while the
    school is being set up or has no current term."""
    # One cursor for all three: django-tenants sets the search path once per
    # cursor, so three cursors would be three more round trips.
    with connection.cursor() as cursor:
        people = _one(cursor, _PEOPLE, {
            "school": school.pk,
            "staff": sorted(STAFF_ROLES),
            # Two weeks back: the day shown can be last Friday, and its
            # change is against the seven days before that.
            "from": monday_of(today) - timedelta(days=14),
            "today": today,
        })
        term = people["term"]
        facts = {
            "today": today.isoformat(),
            "setting_up": not people["people"].get("student"),
            "people": people,
            "money": None,
            "work": None,
            "crest": _crest(people.pop("crest_key", None), people.pop("crest")),
        }
        if term is None or facts["setting_up"]:
            return facts
        start = monday_of(date.fromisoformat(term["starts_on"]))
        facts["money"] = _one(cursor, _MONEY, {"term": term["id"], "start": start})
        facts["work"] = _one(cursor, _WORK, {"term": term["id"], "week_ago": timezone.now() - timedelta(days=7)})
    return facts


def _one(cursor, sql, params) -> dict:
    cursor.execute(sql, params)
    (value,) = cursor.fetchone()
    return value


def _crest(key: Optional[str], encoded: Optional[str]) -> Optional[str]:
    """The crest's address on this host: the upload service's public file when
    there is one (`files`), sent by Caddy with a year's cache; otherwise the
    bytes still in the old column, shrunk and inlined."""
    if key:
        return f"/media/{key}/site.png"
    return _small_crest(encoded)


def _small_crest(encoded: Optional[str]) -> Optional[str]:
    """The crest as a small PNG data URI, or None. Re-drawn once per cache fill."""
    if not encoded:
        return None
    from PIL import Image

    try:
        image = Image.open(io.BytesIO(base64.b64decode(encoded)))
        image.thumbnail((CREST_SIDE, CREST_SIDE))
        out = io.BytesIO()
        image.save(out, format="PNG", optimize=True)
    except (OSError, ValueError):
        return None
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()


# -- the statements -----------------------------------------------------------
#
# Tenant tables are named bare and resolve in the school's schema; the
# shared ones (`accounts_*`, `schools_*`) resolve in `public` behind it, and
# every read of them names this school (`school_id = %(school)s`).

_PEOPLE = """
WITH t AS (
    SELECT id, session, name, starts_on, ends_on
    FROM academics_term WHERE is_current ORDER BY starts_on DESC LIMIT 1
),
prev AS (
    SELECT p.id FROM academics_term p, t
    WHERE p.starts_on < t.starts_on ORDER BY p.starts_on DESC LIMIT 1
),
placed AS (
    SELECT class_group_id, count(*) AS n FROM academics_classplacement
    WHERE term_id = (SELECT id FROM t) GROUP BY class_group_id
)
SELECT json_build_object(
    'term', (SELECT row_to_json(t) FROM t),
    'classes', (
        SELECT coalesce(json_agg(json_build_array(g.id, g.name, coalesce(pl.n, 0))
                                 ORDER BY g.level, g.name), '[]'::json)
        FROM academics_classgroup g LEFT JOIN placed pl ON pl.class_group_id = g.id
        WHERE g.is_active
    ),
    'placed_before', (
        SELECT CASE WHEN EXISTS (SELECT 1 FROM prev)
               THEN (SELECT count(*) FROM academics_classplacement WHERE term_id = (SELECT id FROM prev))
               END
    ),
    'people', (
        SELECT coalesce(json_object_agg(role, n), '{}'::json) FROM (
            SELECT role, count(*) AS n FROM accounts_membership
            WHERE school_id = %(school)s AND status IN ('active', 'invited')
            GROUP BY role
        ) r
    ),
    'form', (
        SELECT coalesce(json_agg(json_build_array(ct.class_group_id, m.user_id)), '[]'::json)
        FROM academics_classteacher ct
        JOIN accounts_membership m ON m.id = ct.teacher_membership_id AND m.school_id = %(school)s
        WHERE ct.term_id = (SELECT id FROM t)
    ),
    'registers', (
        SELECT coalesce(json_agg(json_build_array(
            r.class_group_id, r.taken_on, x.marked, x.present, r.created_at, r.taken_by_id, u.full_name
        ) ORDER BY r.created_at), '[]'::json)
        FROM attendance_register r
        JOIN LATERAL (
            SELECT count(*) AS marked, count(*) FILTER (WHERE a.status = 'present') AS present
            FROM attendance_attendancemark a WHERE a.register_id = r.id
        ) x ON true
        LEFT JOIN accounts_user u ON u.id = r.taken_by_id
        WHERE r.taken_on BETWEEN %(from)s AND %(today)s
    ),
    'invited', (
        SELECT json_build_object('n', count(*), 'oldest', min(i.created_at))
        FROM schools_invitation i
        JOIN accounts_membership m ON m.id = i.membership_id
        WHERE m.school_id = %(school)s AND i.status = 'pending'
          AND i.expires_at > now() AND m.role = ANY(%(staff)s)
    ),
    'joined', (
        SELECT coalesce(json_agg(j ORDER BY j.at DESC), '[]'::json) FROM (
            SELECT u.full_name AS name, m.role, i.accepted_at AS at
            FROM schools_invitation i
            JOIN accounts_membership m ON m.id = i.membership_id
            JOIN accounts_user u ON u.id = m.user_id
            WHERE m.school_id = %(school)s AND i.status = 'accepted'
              AND m.role = ANY(%(staff)s) AND i.accepted_at IS NOT NULL
            ORDER BY i.accepted_at DESC LIMIT 5
        ) j
    ),
    'crest_key', (
        SELECT key FROM files_storedfile
        WHERE slot = 'crest' AND state = 'ready' AND schema_name = current_schema()
        LIMIT 1
    ),
    'crest', (
        SELECT encode(crest, 'base64') FROM results_reportcardsettings
        WHERE crest IS NOT NULL ORDER BY id LIMIT 1
    )
)
"""

#: A reversal counts as the kind it undoes (`home.summary.fees()`'s rule, one
#: hop), so a reversed payment is not money collected. A family's balance is
#: the plain sum of its rows (`FeeLedgerQuerySet.balance()`).
_MONEY = """
WITH e AS (
    SELECT e.student_membership_id AS sid, e.amount_kobo AS amt, e.effective_on AS d,
           coalesce(r.kind, e.kind) AS k
    FROM fees_feeledgerentry e LEFT JOIN fees_feeledgerentry r ON r.id = e.reverses_id
    WHERE e.term_id = %(term)s
)
SELECT json_build_object(
    'kinds', (
        SELECT coalesce(json_object_agg(k, s), '{}'::json)
        FROM (SELECT k, sum(amt) AS s FROM e GROUP BY k) x
    ),
    'weekly', (
        SELECT coalesce(json_agg(json_build_array(wk, s) ORDER BY wk), '[]'::json) FROM (
            SELECT floor((d - %(start)s::date) / 7.0)::int AS wk, sum(amt) AS s
            FROM e WHERE k IN ('payment', 'refund') GROUP BY 1
        ) w
    ),
    'owing', (
        SELECT json_build_object('n', count(*), 'kobo', coalesce(sum(b), 0)) FROM (
            SELECT sum(amt) AS b FROM e GROUP BY sid HAVING sum(amt) > 0
        ) o
    ),
    'paid', (
        SELECT coalesce(json_agg(p ORDER BY p.at DESC), '[]'::json) FROM (
            SELECT x.student_name AS name, -x.amount_kobo AS kobo, x.recorded_at AS at
            FROM fees_feeledgerentry x
            WHERE x.term_id = %(term)s AND x.kind = 'payment'
            ORDER BY x.recorded_at DESC LIMIT 5
        ) p
    )
)
"""

_WORK = """
WITH sheets AS (
    SELECT s.id, s.class_group_id, s.state, s.created_at FROM results_resultsheet s
    JOIN academics_classgroup g ON g.id = s.class_group_id AND g.is_active
    WHERE s.term_id = %(term)s
)
SELECT json_build_object(
    'sheets', (
        SELECT coalesce(json_agg(json_build_array(
            s.class_group_id, s.state, coalesce(l.created_at, s.created_at), l.to_state, l.actor_id,
            CASE WHEN w.to_state IS NOT NULL THEN w.to_state
                 WHEN s.created_at <= %(week_ago)s THEN 'draft' END
        )), '[]'::json)
        FROM sheets s
        LEFT JOIN LATERAL (
            SELECT t.created_at, t.to_state, t.actor_id FROM results_resultsheettransition t
            WHERE t.sheet_id = s.id ORDER BY t.created_at DESC, t.id DESC LIMIT 1
        ) l ON true
        LEFT JOIN LATERAL (
            SELECT t.to_state FROM results_resultsheettransition t
            WHERE t.sheet_id = s.id AND t.created_at <= %(week_ago)s
            ORDER BY t.created_at DESC, t.id DESC LIMIT 1
        ) w ON true
    ),
    'steps', (
        SELECT coalesce(json_agg(json_build_array(x.class_group_id, x.to_state, x.actor_id, x.full_name, x.created_at)
                                 ORDER BY x.created_at DESC), '[]'::json)
        FROM (
            SELECT s.class_group_id, t.to_state, t.actor_id, u.full_name, t.created_at,
                   row_number() OVER (PARTITION BY s.class_group_id ORDER BY t.created_at DESC, t.id DESC) AS n
            FROM results_resultsheettransition t
            JOIN sheets s ON s.id = t.sheet_id
            LEFT JOIN accounts_user u ON u.id = t.actor_id
        ) x WHERE x.n <= 3
    ),
    'papers', (
        SELECT coalesce(json_agg(json_build_array(
            q.class_group_id, q.subject, q.paper, q.placed, q.scored, q.last_at
        ) ORDER BY q.class_group_id, q.position, q.subject), '[]'::json)
        FROM (
            SELECT p.class_group_id, sj.name AS subject, a.name AS paper, a.position,
                   count(*) AS placed, count(sc.id) AS scored, max(sc.created_at) AS last_at
            FROM academics_classplacement p
            JOIN academics_classgroup g ON g.id = p.class_group_id AND g.is_active
            JOIN gradebook_assessment a ON a.term_id = p.term_id
            JOIN gradebook_subject sj ON sj.id = a.subject_id
            LEFT JOIN gradebook_score sc
                   ON sc.assessment_id = a.id AND sc.student_membership_id = p.student_membership_id
            WHERE p.term_id = %(term)s
            GROUP BY p.class_group_id, a.id, sj.name, a.name, a.position
            HAVING count(sc.id) > 0
        ) q
    ),
    'remarks', (
        SELECT coalesce(json_agg(json_build_array(r.class_group_id, r.author, r.n)), '[]'::json) FROM (
            SELECT p.class_group_id, c.author, count(*) AS n
            FROM academics_classplacement p
            JOIN results_reportcardcomment c
                 ON c.student_membership_id = p.student_membership_id AND c.term_id = p.term_id
            WHERE p.term_id = %(term)s
            GROUP BY p.class_group_id, c.author
        ) r
    )
)
"""


__all__ = ["CACHE_SECONDS", "cache_key", "lagos_today", "load", "monday_of", "read"]
