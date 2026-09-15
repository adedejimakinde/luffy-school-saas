"""A contact channel is written once, and takes exactly two one-way stamps after.

Operating rule 3: if a row must never change, a trigger or a constraint must
refuse the change, because a docstring saying "append-only" stops nobody — not a
management command, not a `psql` session, not the next service that grows a
second write path.

## Why a trigger and not a CheckConstraint

The rule is *NEW against OLD*. "This column may not change" and "this stamp goes
from NULL to a time and never moves again" are both comparisons between the row
being written and the row already there, and a `CHECK` constraint sees only one
row. That is a different reason from the one
`0008_guardianship_rules_are_a_trigger` gives — cross-*table* there, cross-
*version* here — and both end at the same place.

## What is permitted, and why both stamps are permitted now

`verified_at` and `revoked_at` may each go from NULL to a value, once.

* `verified_at` is written by `guardian_contacts.confirm_verification()`. It is
  D9's "the link does not go live until Classnode verifies the channel in-band".
* `revoked_at` is written by **nothing yet**. D11's contact-change flow — new
  channel entered, old binding revoked immediately, link suspended until the new
  one verifies — is the next slice.

The stamp it does not yet need is permitted deliberately rather than left for
that slice to add. A trigger is a copy of a rule, and this repository already
carries the cost of keeping copies in step: `Guardianship.clean()` spells out
three copies of two rules and says plainly that keeping them aligned is manual.
Landing D11 as a service against a trigger that already allows its one write is
one file; landing it against a trigger that refuses it is a second migration
rewriting this one, and a window where the rule lives in two versions.

`revoked_at` being unwritten is therefore a fact about the services, not about
the schema, and `a_revoked_channel_stays_revoked` below is live from today —
it will refuse a revoked channel being verified before any code exists that
could revoke one.

## The four refusals, each named

A trigger has no constraint name for Postgres to report, so every `RAISE`
opens with a stable identifier and `tests/refusals.py`'s `assertRefusedBy()`
matches on it. Issue #89 is about assertions that cannot tell one refusal from
another; four rules in one function is exactly where that goes wrong.

* `guardian_contact_is_append_only` — an identity column moved, or a DELETE.
* `guardian_contact_verifies_once` — `verified_at` moved after being set.
* `guardian_contact_revokes_once` — `revoked_at` moved after being set.
* `a_revoked_channel_stays_revoked` — a revoked row being verified. Not covered
  by the other three: a channel revoked while still unverified has
  `verified_at IS NULL`, so the one-way check passes and the stamp would land,
  quietly bringing a replaced channel back to life.

`ERRCODE = 'restrict_violation'` (SQLSTATE 23001) on all four, like every other
`RAISE EXCEPTION` in this repo's migrations: Django surfaces that class as
`IntegrityError`, and `assertRefusedBy` matches nothing else.

## Shared app, one trigger, every school

`accounts` is in `SHARED_APPS` only, so this runs once against `public` and the
one trigger guards every school's rows at once — the same shape
`0008_guardianship_rules_are_a_trigger` documents, and not the per-tenant shape
every trigger in `fees`, `gradebook` and `results` follows.

## Deliberately not on `accounts_guardiancontactcode`

Codes are not an audit trail. `attempts` counts up and `status` moves, which is
the whole mechanism — freezing them would mean a wrong guess could not be
counted. The append-only promise here is about the *channel*, which is what D11
says must be answerable as "who changed this and when".
"""

from django.db import migrations

FUNCTION = """
CREATE OR REPLACE FUNCTION accounts_guardian_contact_append_only() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION
            'guardian_contact_is_append_only: a contact channel cannot be '
            'deleted; contact % belongs to guardian %.', OLD.id, OLD.guardian_id
            USING ERRCODE = 'restrict_violation';
    END IF;

    IF NEW.guardian_id IS DISTINCT FROM OLD.guardian_id
        OR NEW.channel_type IS DISTINCT FROM OLD.channel_type
        OR NEW.value IS DISTINCT FROM OLD.value
        OR NEW.created_by_id IS DISTINCT FROM OLD.created_by_id
        OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION
            'guardian_contact_is_append_only: a contact channel is written '
            'once; change contact % by recording a new channel and revoking '
            'this one.', OLD.id
            USING ERRCODE = 'restrict_violation';
    END IF;

    IF OLD.revoked_at IS NOT NULL
        AND NEW.verified_at IS DISTINCT FROM OLD.verified_at THEN
        RAISE EXCEPTION
            'a_revoked_channel_stays_revoked: contact % was revoked at % and '
            'cannot be verified.', OLD.id, OLD.revoked_at
            USING ERRCODE = 'restrict_violation';
    END IF;

    IF OLD.verified_at IS NOT NULL
        AND NEW.verified_at IS DISTINCT FROM OLD.verified_at THEN
        RAISE EXCEPTION
            'guardian_contact_verifies_once: contact % was verified at % and '
            'that stamp does not move.', OLD.id, OLD.verified_at
            USING ERRCODE = 'restrict_violation';
    END IF;

    IF OLD.revoked_at IS NOT NULL
        AND NEW.revoked_at IS DISTINCT FROM OLD.revoked_at THEN
        RAISE EXCEPTION
            'guardian_contact_revokes_once: contact % was revoked at % and '
            'that stamp does not move.', OLD.id, OLD.revoked_at
            USING ERRCODE = 'restrict_violation';
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

TRIGGER = """
CREATE TRIGGER accounts_guardian_contact_append_only
BEFORE UPDATE OR DELETE ON accounts_guardiancontact
FOR EACH ROW EXECUTE FUNCTION accounts_guardian_contact_append_only();
"""

DROP_TRIGGER = (
    "DROP TRIGGER IF EXISTS accounts_guardian_contact_append_only "
    "ON accounts_guardiancontact;"
)
DROP_FUNCTION = "DROP FUNCTION IF EXISTS accounts_guardian_contact_append_only();"


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0010_guardian_contact_channel"),
    ]

    operations = [
        migrations.RunSQL(sql=FUNCTION, reverse_sql=DROP_FUNCTION),
        migrations.RunSQL(sql=TRIGGER, reverse_sql=DROP_TRIGGER),
    ]
