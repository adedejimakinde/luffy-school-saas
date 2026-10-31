"""One row per upload, in the schema of the school it belongs to.

The bytes are on disk (`files.storage`), never in Postgres: this row is the
key, what kind of thing it is, who may see it, the variants made from it and
how many bytes they take. A school's rows are in its own schema like the rest
of its data (docs/tenancy.md), and Classnode's own blog has its rows in
`public`, because the app is in both lists (`settings.SHARED_APPS` and
`TENANT_APPS`).

**Each row also names its schema** (`schema_name`), and every lookup filters on
it as well as relying on `search_path`. A school schema always has this table,
but if one ever did not, an unqualified query would fall through to `public`'s
table: the second entry on every school's search path. The column turns that
from a leak into an empty result.

## A slot is "the current one of these"

A crest, a child's photo and a principal's signature are one-at-a-time things:
uploading a new one replaces the old, but only once the new one is ready, so a
crest never disappears for the seconds the worker takes, and a failed upload
leaves the old one in place. `slot` names that thing ("crest",
"student_photo:42"), and at most one *ready* row may hold a slot. A gallery
image has no slot: there are many, and the sections that use them say which.
"""

import secrets

from django.db import models
from django.db.models import Q
from django.utils import timezone

from .kinds import Kind


def new_key() -> str:
    """128 random bits as hex: an address that says nothing about any other."""
    return secrets.token_hex(16)


class State(models.TextChoices):
    PENDING = "pending", "Being processed"
    READY = "ready", "Ready"
    FAILED = "failed", "Could not be used"
    #: A public file replaced in its slot. Still sent for a day, because a page
    #: cached a minute ago (the site's HTML, the dashboard) still points at it;
    #: then removed by the hourly check (`files.service.sweep`).
    RETIRED = "retired", "Replaced"


class StoredFile(models.Model):
    key = models.CharField(max_length=32, unique=True, default=new_key, editable=False)
    schema_name = models.CharField(max_length=63)
    kind = models.CharField(max_length=24, choices=Kind)
    slot = models.CharField(max_length=80, blank=True, default="")
    public = models.BooleanField(default=False)
    state = models.CharField(max_length=8, choices=State, default=State.PENDING)
    #: What went wrong, in a sentence for the person who uploaded it.
    error = models.CharField(max_length=300, blank=True, default="")

    #: The size of what was sent, until it is processed and thrown away.
    incoming_bytes = models.PositiveBigIntegerField(default=0)
    #: Everything kept on disk for this row: master and every variant.
    bytes = models.PositiveBigIntegerField(default=0)
    #: `{"828.webp": {"bytes": 41000, "width": 828, "height": 552}, ...}`.
    variants = models.JSONField(default=dict, blank=True)
    #: SHA-256 of the master as kept, for the backup's restore check.
    sha256 = models.CharField(max_length=64, blank=True, default="")
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    #: The picture's dominant colour, drawn behind it while it loads (§4.2).
    colour = models.CharField(max_length=7, blank=True, default="")
    seconds = models.FloatField(null=True, blank=True)
    pages = models.PositiveIntegerField(null=True, blank=True)

    #: Where it came from: an upload, or `move_files_to_disk` copying bytes
    #: that used to be in a database column. The rollback removes only the
    #: second kind.
    origin = models.CharField(max_length=8, default="upload")
    #: A user id, not a foreign key: users are in `public`, and a school's
    #: table does not point across schemas (docs/tenancy.md, option 2).
    uploaded_by_id = models.PositiveBigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    #: When the job was last handed to the queue, so a status read can ask
    #: again for one the broker lost (`files.service.nudge`).
    last_enqueued_at = models.DateTimeField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["slot", "state"])]
        constraints = [
            models.UniqueConstraint(
                fields=["slot"],
                condition=Q(state="ready") & ~Q(slot=""),
                name="files_one_ready_file_per_slot",
            ),
            models.CheckConstraint(
                condition=~Q(state="ready") | ~Q(sha256=""),
                name="files_a_ready_file_has_a_hash",
            ),
            models.CheckConstraint(
                condition=~Q(state="failed") | ~Q(error=""),
                name="files_a_failed_file_says_why",
            ),
        ]

    def __str__(self):
        return f"{self.kind} {self.key} ({self.state})"

    @property
    def is_ready(self) -> bool:
        return self.state == State.READY

    def has(self, variant: str) -> bool:
        return variant in (self.variants or {})


__all__ = ["State", "StoredFile", "new_key"]
