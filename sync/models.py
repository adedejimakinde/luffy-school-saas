"""What a queued write leaves behind so that sending it twice is sending it once.

`docs/offline.md` D3, decided in review as OPEN-2: a `SyncReceipt` table with a
unique key, rather than a key column on `Score` and `Register`. A column holds
one key per row and the next write to that row replaces it, so a replay that
arrives after a later write would find nothing to recognise. A table keeps
every key.

Tenant-side, like the writes it records. A key is a fact about one school's
database: a receipt at St Mary's says nothing to Grace, and a request to Grace's
host cannot read St Mary's answer back out of it.

**The unique index is the whole mechanism**, which is the lesson
`fees.FeeLedgerEntry.form_key` records (`a_form_posts_once`). Two copies of one
write racing each other both pass any read; only the index sees them both.
`receipts.once()` inserts the receipt *before* the write it guards, in the same
transaction, so the second copy waits on the index until the first commits or
rolls back.
"""

from django.db import models


class SyncReceipt(models.Model):
    """One write that landed, keyed by the key its sender minted.

    Only writes that **landed** have one. A refused write — 403, 409, 422,
    423 — rolls its receipt back with it, so sending it again is judged again
    rather than answered from a refusal that may no longer hold.
    """

    #: Minted by the device when the write was queued, and sent with every
    #: attempt at it. Unique (`a_queued_write_lands_once`).
    key = models.UUIDField(editable=False)

    #: Who sent it. A bare id, the platform's policy for a user from a tenant
    #: table (`docs/tenancy.md`). A key sent again by somebody else is not a
    #: replay, and is refused rather than answered with the first sender's result.
    made_by_id = models.PositiveBigIntegerField()

    #: The method and path, "PUT /api/gradebook/assessments/3/scores/7/". With
    #: `request`, what a second arrival must match to be the first one again.
    write = models.CharField(max_length=255)

    #: The body, less the key.
    request = models.JSONField()

    # No answer is kept. A write that arrives again is told it is already
    # saved and nothing about the cell (`receipts.py`, #161): the first
    # arrival's answer described the cell as it was then, and a replay drew it
    # as the cell as it is now.

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["key"], name="a_queued_write_lands_once"),
        ]

    def __str__(self):
        return f"{self.write} ({self.key})"
