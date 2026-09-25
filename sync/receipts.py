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
"""

from django.db import IntegrityError, transaction

from .models import SyncReceipt


class KeyAlreadyUsed(Exception):
    """The key already landed a different write, or somebody else's.

    Not a replay. A device that reuses a key for a second write has a bug, and
    answering it with the first write's result would tell it that the second one
    landed when it did not.
    """


class _Refused(Exception):
    """Carries a refusal out of the atomic block, so the receipt goes with it."""

    def __init__(self, answer):
        super().__init__()
        self.answer = answer


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
    `request` are what a second arrival must match to be the first one again.

    The receipt goes in first, in a savepoint, so that a second arrival waits on
    the unique index until the first has committed and then finds its receipt.
    A refusal — a status outside 2xx, or an exception — rolls the receipt back
    with everything else the attempt did.
    """
    try:
        with transaction.atomic():
            try:
                with transaction.atomic():
                    receipt = SyncReceipt.objects.create(
                        key=key, made_by_id=actor.pk, write=write, request=request
                    )
            except IntegrityError as exc:
                if not _is_the_key_colliding(exc):
                    raise
                return _the_first_answer(key, actor, write, request)

            status, answer = act()
            if not 200 <= status < 300:
                raise _Refused((status, answer))

            receipt.status = status
            receipt.answer = answer.model_dump(mode="json")
            receipt.save(update_fields=["status", "answer"])
            return status, answer
    except _Refused as refused:
        return refused.answer


def _the_first_answer(key, actor, write, request):
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
    return earlier.status, earlier.answer
