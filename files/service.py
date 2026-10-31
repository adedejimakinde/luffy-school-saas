"""The one upload service: every upload in the portal and the websites comes here.

    stored = service.accept(Kind.CREST, request.FILES["crest"], slot="crest", by=request.user)
    ...
    current = service.current("crest")          # the ready one, or None
    data = service.read(current, "card.png")    # bytes, for a PDF render

## In the request: the cheap checks, then hand over

`accept()` runs only what is quick and says no early: the size, the file's
type **from its own bytes** (Pillow's header read for a picture, `%PDF-` for a
document, the container's magic for a video; never the name or the browser's
MIME type), the pixel count from the header, the school's quota and the disk.
It then keeps the upload in an incoming directory, writes a `pending` row and,
once the transaction commits, queues the work. The request returns at once.

## In the worker: everything else

`process()` decodes, strips every bit of metadata, and makes what the kind
keeps (`files.images`, `files.pdf`, `files.video`), writes it to disk, and only
then, in one transaction, checks the quota against what was actually made,
marks the row `ready` and retires the slot's previous file. The upload itself
is deleted whatever happened. A refusal found here (a corrupt photo, a video
that is too long) is written on the row as a sentence, and the screen that
asked shows it.

The job is idempotent, because the queue redelivers under `acks_late`: it does
nothing to a row that is no longer `pending`, and the files it writes have
names that only this row can have.
"""

import hashlib
import logging
from datetime import timedelta

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Count, Sum
from django.utils import timezone

from . import images, pdf, storage, video
from .kinds import Family, profile_for
from .models import State, StoredFile

logger = logging.getLogger(__name__)

#: How long a `pending` row waits before a status read queues it again.
RE_ENQUEUE_AFTER = timedelta(seconds=60)
#: A `pending` row this old is given up on by the hourly check.
GIVE_UP_AFTER = timedelta(hours=6)
#: A failed row is kept this long so its screen can say why, then removed.
FORGET_FAILED_AFTER = timedelta(days=7)
#: A replaced public file is still sent this long (`State.RETIRED`).
KEEP_RETIRED_FOR = timedelta(days=1)

GENERIC_FAILURE = (
    "That file could not be processed. Try saving it again, or send a different copy."
)


class UploadRefused(Exception):
    """An upload this will not take. The message is for the person who sent it."""


# -- where we are --------------------------------------------------------------


def schema_here() -> str:
    return connection.schema_name


def _here():
    """Every query filters on its schema as well as `search_path` (`files.models`)."""
    return StoredFile.objects.filter(schema_name=schema_here())


def school_here():
    tenant = getattr(connection, "tenant", None)
    if tenant is None or getattr(tenant, "schema_name", "public") == "public":
        return None
    return tenant


# -- the quota and the disk ----------------------------------------------------


def quota_for(school) -> int:
    if school is None:
        return settings.FILES_DEFAULT_QUOTA_BYTES
    return school.storage_quota_bytes or settings.FILES_DEFAULT_QUOTA_BYTES


def usage() -> dict:
    """What this schema keeps: bytes and files, ready ones only."""
    totals = _here().filter(state=State.READY).aggregate(bytes=Sum("bytes"), files=Count("pk"))
    return {"bytes": totals["bytes"] or 0, "files": totals["files"]}


def _refuse_when_full(profile, incoming_bytes):
    if storage.percent_used() >= settings.FILES_DISK_REFUSE_PERCENT:
        raise UploadRefused(
            "Uploads are paused for a short while because the server's storage is nearly full. "
            "Classnode has been told. Please try again later."
        )
    school = school_here()
    if school is None:
        return
    quota = quota_for(school)
    used = usage()["bytes"]
    if used + min(incoming_bytes, profile.typical_bytes) > quota:
        raise UploadRefused(_over_quota_sentence(used, quota))


def _over_quota_sentence(used, quota):
    return (
        f"Your school has used {_size(used)} of its {_size(quota)} of storage. "
        "Remove photos or files you no longer need, or ask Classnode for more space."
    )


def _size(n):
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.1f} GB"
    return f"{max(n, 0) / 1024 ** 2:.0f} MB"


# -- in the request ------------------------------------------------------------


def _size_of(upload) -> int:
    return len(upload) if isinstance(upload, (bytes, bytearray)) else upload.size


def _head(upload, n=1024) -> bytes:
    if isinstance(upload, (bytes, bytearray)):
        return bytes(upload[:n])
    upload.seek(0)
    head = upload.read(n)
    upload.seek(0)
    return head


def check(kind, upload):
    """The checks `accept()` makes before it keeps anything. Raises `UploadRefused`."""
    profile = profile_for(kind)
    size = _size_of(upload) if upload is not None else 0
    if not size:
        raise UploadRefused(f"Choose a file to upload. {profile.noun} cannot be empty.")
    if size > profile.max_bytes:
        raise UploadRefused(f"{profile.noun} can be at most {profile.max_mb} MB. Save it smaller and try again.")
    try:
        if profile.family == Family.DOCUMENT:
            if not pdf.looks_like_pdf(_head(upload)):
                raise images.Refused("A document is a PDF file.")
        elif profile.family == Family.VIDEO:
            if not video.looks_like_video(_head(upload, 16)):
                raise images.Refused(
                    "A video is an MP4, MOV or WebM file. For a longer video, add a YouTube or Vimeo link instead."
                )
        else:
            fmt, width, height = images.header(upload, profile)
            return {"format": fmt, "width": width, "height": height, "bytes": size}
    except images.Refused as exc:
        raise UploadRefused(str(exc))
    return {"bytes": size}


def accept(kind, upload, *, slot: str = "", by=None, public=None) -> StoredFile:
    """Check an upload, keep it for the worker, and queue it. Returns the pending row."""
    profile = profile_for(kind)
    facts = check(kind, upload)
    _refuse_when_full(profile, facts["bytes"])
    schema = schema_here()
    with transaction.atomic():
        stored = StoredFile.objects.create(
            schema_name=schema,
            kind=str(kind),
            slot=slot,
            public=profile.public if public is None else bool(public),
            incoming_bytes=facts["bytes"],
            uploaded_by_id=getattr(by, "pk", None),
            width=facts.get("width"),
            height=facts.get("height"),
        )
        storage.write_incoming(schema, stored.key, upload)
        _queue(stored)
    if settings.FILES_PROCESS_INLINE:
        stored.refresh_from_db()
    return stored


def _queue(stored):
    if settings.FILES_PROCESS_INLINE:
        process(stored.schema_name, stored.key)
        return
    StoredFile.objects.filter(pk=stored.pk).update(last_enqueued_at=timezone.now())
    schema, key = stored.schema_name, stored.key
    transaction.on_commit(lambda: _publish(schema, key))


def _publish(schema, key):
    """Hand the job to the media queue. A broker that is down loses nothing:
    the row stays `pending`, and the next status read asks again (`nudge`)."""
    from . import tasks

    try:
        if schema == "public":
            tasks.process_platform_upload.apply_async(args=[key], retry=False)
        else:
            tasks.process_upload.apply_async(args=[schema, key], retry=False)
    except Exception:  # noqa: BLE001 — after the commit; see the docstring
        logger.exception("Could not queue upload %s; it stays pending and will be asked for again.", key)


def nudge(stored):
    """Queue again a pending upload whose job seems to have been lost."""
    if stored is None or stored.state != State.PENDING or settings.FILES_PROCESS_INLINE:
        return
    stale = timezone.now() - RE_ENQUEUE_AFTER
    claimed = _here().filter(pk=stored.pk, state=State.PENDING, last_enqueued_at__lt=stale).update(
        last_enqueued_at=timezone.now()
    )
    if claimed:
        schema, key = stored.schema_name, stored.key
        transaction.on_commit(lambda: _publish(schema, key))


# -- in the worker -------------------------------------------------------------


def _make(profile, raw):
    if profile.family == Family.DOCUMENT:
        return pdf.optimise(raw, profile)
    if profile.family == Family.VIDEO:
        return video.hero_loop(raw, profile)
    return images.PROCESSORS[profile.family](raw, profile)


def _lock_schema(schema):
    """One upload at a time per school past this point, so two cannot both fit
    a quota that holds only one of them."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"files:{schema}"])


def process(schema, key):
    """Turn a pending upload into what is kept. Safe to run twice."""
    if schema != schema_here():
        raise RuntimeError(f"process({schema!r}) called on the {schema_here()!r} connection")
    stored = _here().filter(key=key).first()
    if stored is None or stored.state != State.PENDING:
        return stored
    profile = profile_for(stored.kind)
    try:
        raw = storage.read_incoming(schema, key)
    except FileNotFoundError:
        return _fail(stored, GENERIC_FAILURE)
    try:
        made = _make(profile, raw)
    except images.Refused as exc:
        return _fail(stored, str(exc))
    except Exception:  # noqa: BLE001 — anything else is ours, and is logged
        logger.exception("Processing upload %s (%s) failed", key, stored.kind)
        return _fail(stored, GENERIC_FAILURE)
    finally:
        del raw

    written = []
    try:
        for variant, data in made["data"].items():
            storage.write_variant(schema, key, variant, data)
            written.append(variant)
    except OSError:
        logger.exception("Writing upload %s to disk failed", key)
        storage.delete_variants(schema, key, written)
        return _fail(stored, "That file could not be saved just now. Please try again in a few minutes.")

    total = sum(meta["bytes"] for meta in made["variants"].values())
    retired = []
    with transaction.atomic():
        _lock_schema(schema)
        stored = _here().select_for_update().filter(pk=stored.pk).first()
        if stored is None or stored.state != State.PENDING:
            storage.delete_variants(schema, key, written)
            return stored
        school = school_here()
        if school is not None:
            used = usage()["bytes"]
            previous = _here().filter(slot=stored.slot, state=State.READY).exclude(slot="")
            freed = sum(p.bytes for p in previous)
            quota = quota_for(school)
            if used - freed + total > quota:
                transaction.on_commit(lambda: storage.delete_variants(schema, key, written))
                return _fail(stored, _over_quota_sentence(used, quota), locked=True)
        if stored.slot:
            newer = _here().filter(slot=stored.slot, state=State.READY, created_at__gt=stored.created_at)
            if newer.exists():
                # A later upload to the same slot finished first: it wins.
                transaction.on_commit(lambda: storage.delete_variants(schema, key, written))
                stored.delete()
                return None
            for old in _here().filter(slot=stored.slot).exclude(pk=stored.pk).exclude(state=State.PENDING):
                if old.public and old.state == State.READY:
                    old.state, old.processed_at = State.RETIRED, timezone.now()
                    old.save(update_fields=["state", "processed_at"])
                elif old.state != State.RETIRED:
                    retired.append((old.key, list(old.variants)))
                    old.delete()
        master = made["data"][made["master"]]
        stored.state = State.READY
        stored.error = ""
        stored.variants = made["variants"]
        stored.bytes = total
        stored.sha256 = hashlib.sha256(master).hexdigest()
        stored.width = made.get("width")
        stored.height = made.get("height")
        stored.colour = made.get("colour", "")
        stored.seconds = made.get("seconds")
        stored.pages = made.get("pages")
        stored.incoming_bytes = 0
        stored.processed_at = timezone.now()
        stored.save()

        def tidy():
            storage.drop_incoming(schema, key)
            for old_key, old_variants in retired:
                storage.delete_variants(schema, old_key, old_variants)

        transaction.on_commit(tidy)
    return stored


def _fail(stored, sentence, *, locked=False):
    schema, key = stored.schema_name, stored.key
    updated = _here().filter(pk=stored.pk, state=State.PENDING).update(
        state=State.FAILED, error=sentence[:300], incoming_bytes=0, processed_at=timezone.now()
    )
    transaction.on_commit(lambda: storage.drop_incoming(schema, key))
    if updated:
        stored.state, stored.error = State.FAILED, sentence[:300]
    return stored


# -- reading -------------------------------------------------------------------


def current(slot: str):
    """The ready file in `slot`, or None."""
    return _here().filter(slot=slot, state=State.READY).first()


def latest(slot: str):
    """The newest row in `slot`, whatever its state: what a screen reports on."""
    return _here().filter(slot=slot).order_by("-created_at", "-pk").first()


def find(key: str):
    if not storage.KEY.match(key or ""):
        return None
    return _here().filter(key=key).first()


def read(stored, variant: str) -> bytes:
    if stored is None or stored.state not in (State.READY, State.RETIRED) or not stored.has(variant):
        raise FileNotFoundError(variant)
    return storage.read_variant(stored.schema_name, stored.key, variant)


def status_of(slot: str) -> dict:
    """What a screen needs to say about a slot: ready, being processed, or why not."""
    newest = latest(slot)
    ready = current(slot)
    if newest is not None and newest.state == State.PENDING:
        nudge(newest)
    return {
        "ready": ready is not None,
        "version": ready.key[:12] if ready else None,
        "processing": newest is not None and newest.state == State.PENDING,
        "problem": newest.error if newest is not None and newest.state == State.FAILED else "",
    }


# -- removing ------------------------------------------------------------------


def discard(stored):
    """Remove a file, its row and its bytes. Its slot is then empty."""
    if stored is None:
        return
    schema, key, variants = stored.schema_name, stored.key, list(stored.variants or {})
    stored.delete()
    transaction.on_commit(lambda: (storage.delete_variants(schema, key, variants), storage.drop_incoming(schema, key)))


def clear_slot(slot: str):
    for stored in list(_here().filter(slot=slot)):
        discard(stored)


def sweep(now=None):
    """Give up on uploads stuck pending, and forget old failures. Returns counts."""
    now = now or timezone.now()
    stuck = list(_here().filter(state=State.PENDING, created_at__lt=now - GIVE_UP_AFTER))
    for stored in stuck:
        _fail(stored, "That upload took too long to process. Please try again.")
    old = list(_here().filter(state=State.FAILED, processed_at__lt=now - FORGET_FAILED_AFTER))
    for stored in old:
        discard(stored)
    replaced = list(_here().filter(state=State.RETIRED, processed_at__lt=now - KEEP_RETIRED_FOR))
    for stored in replaced:
        discard(stored)
    return {"gave_up": len(stuck), "forgotten": len(old), "removed": len(replaced)}


__all__ = [
    "UploadRefused",
    "accept",
    "check",
    "clear_slot",
    "current",
    "discard",
    "find",
    "latest",
    "nudge",
    "process",
    "quota_for",
    "read",
    "school_here",
    "status_of",
    "sweep",
    "usage",
]
