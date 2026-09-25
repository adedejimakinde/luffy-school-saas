"""`once()`: a write sent with a key lands once, however many times it is sent.

`docs/offline.md` D3 and correctness requirement 1. A device that sent a write
and never heard back sends it again; offline, that is the ordinary case rather
than the rare one. Before this, a replayed mark was recognised by inference —
`gradebook.api._is_our_write_arriving_twice()`, same value and same person — and
a replayed register was simply applied again, on top of whatever the office had
corrected since. A key makes "this exact write already landed" a fact the
database holds.

It sits in front of the HTTP routes rather than inside the services, because a
key is a property of a request a device queued. An import or a shell has no
device and no queue to be protected from.

## A write that landed is answered "already saved", and nothing more (#161)

The same write sent again by the person who sent it is told it is already
saved, and is **not** told what the cell or the register holds now. Two
reasons, one per half of that sentence:

- **Asked before authority** (`already_saved()`, called by each route ahead of
  its authority check). A teacher whose write landed, and whose role changed
  before the answer reached them, is owed the truth that it landed — not a 403
  that their device would take as final and show as "not saved". Asked that
  early, the answer may say nothing a 403 would have withheld: it is only ever
  given for a key this person minted, on this path, with this body, at this
  school, and it carries no mark, no version and no total.
- **No cell data.** The first arrival's answer described the cell as it was
  then. Handed to a replay, it was drawn as the cell as it is now, and a
  teacher who had entered 18 on another device since was shown 17 at the old
  version — their next edit a conflict with themselves (the review of #160).
  A device that needs what the cell holds now asks for the sheet.
"""

from django.db import IntegrityError, transaction
from ninja import Schema

from .models import SyncReceipt

#: What a write that already landed is told when it arrives again.
ALREADY_SAVED = "Already saved."


class AlreadySavedOut(Schema):
    """A write that landed before, arriving again. No mark, no version, no total."""

    detail: str = ALREADY_SAVED
    already_saved: bool = True


class KeyAlreadyUsed(Exception):
    """The key already landed a different write, or somebody else's.

    Not a replay. A device that reuses a key for a second write has a bug, and
    answering it as saved would tell it that the second one landed when it did
    not.
    """


class _Refused(Exception):
    """Carries a refusal out of the atomic block, so the receipt goes with it."""

    def __init__(self, answer):
        super().__init__()
        self.answer = answer


def matched_on(http_request, payload):
    """What a receipt is matched on: the method and path, and the body less the key.

    One derivation for both places that ask — `already_saved()` before the
    route's authority check and `once()` after it. Two copies would be two
    chances to differ, and an early check that derived the body differently
    from the receipt would never match, silently, and every resend would fall
    through to the authority check this exists to precede.
    """
    return (
        f"{http_request.method} {http_request.path}",
        payload.model_dump(mode="json", exclude={"key"}),
    )


def already_saved(*, key, actor, write, request) -> bool:
    """Did this person's exact write, under this key, land here already?

    A read, and the only question asked before the route's authority check:
    the same person, the same path, the same body. The school is the schema
    the request is on — a receipt at St Mary's is not in Grace's table to be
    found. Anything short of all of that is not this person's replay, and goes
    through the route as any other request does.
    """
    return SyncReceipt.objects.filter(
        key=key, made_by_id=actor.pk, write=write, request=request
    ).exists()


def _is_the_key_colliding(exc) -> bool:
    """Did `a_queued_write_lands_once` fire, or something else?

    `fees.services._is_the_form_key_colliding()` is the same question, asked
    for the same reason: `IntegrityError` says a rule refused the row and not
    which, and only this one means "this write already landed".
    """
    diag = getattr(getattr(exc, "__cause__", None), "diag", None)
    return getattr(diag, "constraint_name", None) == "a_queued_write_lands_once"


def once(*, key, actor, write, request, act):
    """Run `act()` at most once for `key`. Returns `(status, answer)`.

    `act` is the route's own body. It returns `(status, schema)`, exactly what a
    ninja view returns, and a status outside 2xx is a refusal. `write` and
    `request` are `matched_on()`'s, what a second arrival must match to be the
    first one again.

    The receipt goes in first, in a savepoint, so that a second arrival waits on
    the unique index until the first has committed, and is then answered as
    already saved. That is the one replay `already_saved()` cannot catch: two
    copies in flight together both find nothing to read. A refusal — a status
    outside 2xx, or an exception — rolls the receipt back with everything else
    the attempt did.
    """
    try:
        with transaction.atomic():
            try:
                with transaction.atomic():
                    SyncReceipt.objects.create(
                        key=key, made_by_id=actor.pk, write=write, request=request
                    )
            except IntegrityError as exc:
                if not _is_the_key_colliding(exc):
                    raise
                return _already_landed(key, actor, write, request)

            status, answer = act()
            if not 200 <= status < 300:
                raise _Refused((status, answer))
            return status, answer
    except _Refused as refused:
        return refused.answer


def _already_landed(key, actor, write, request):
    earlier = SyncReceipt.objects.get(key=key)
    if (earlier.made_by_id, earlier.write, earlier.request) != (
        actor.pk,
        write,
        request,
    ):
        raise KeyAlreadyUsed(
            "This write's key was already used for a different write. Nothing "
            "was saved. Reload the page and enter it again."
        )
    return 200, AlreadySavedOut()
