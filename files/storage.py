"""Where the bytes are: a directory tree on the server's data volume.

    <FILES_ROOT>/<schema>/<first two of the key>/<key>-<variant>
    <FILES_ROOT>/.incoming/<schema>/<key>          (until processed)

The schema is the first directory, so a school's files are one subtree: the
backup, a per-school total and a school's removal all work on it, and the path
Caddy is told to send can be checked to be under the current school's.

Names never change once written, because a key's variants are written once and
a new upload is a new key. That is what lets them be cached for a year, and
lets the nightly backup copy only what is new.

A write goes to a temporary name in the same directory and is renamed into
place, so a reader (or the backup) never sees half a file.
"""

import os
import re
import shutil
import tempfile
from pathlib import Path

from django.conf import settings

#: A variant's name: lowercase letters, digits and hyphens, then an extension
#: from a fixed list. Checked before any path is built from one.
VARIANT = re.compile(r"^[a-z0-9][a-z0-9-]{0,23}\.(avif|webp|jpg|png|pdf|mp4)$")
KEY = re.compile(r"^[0-9a-f]{32}$")
SCHEMA = re.compile(r"^[a-z0-9_]{1,63}$")

CONTENT_TYPES = {
    "avif": "image/avif",
    "webp": "image/webp",
    "jpg": "image/jpeg",
    "png": "image/png",
    "pdf": "application/pdf",
    "mp4": "video/mp4",
}

INCOMING = ".incoming"
#: Where a file made on the server (`Family.MADE`) is built before it is put in
#: place: under the same root, so the last step is a rename, not a copy.
BUILDING = ".building"


class BadName(ValueError):
    """A schema, key or variant that does not have the shape a name must have."""


def root() -> Path:
    return Path(settings.FILES_ROOT)


def _check(schema: str, key: str, variant: str = None):
    if not SCHEMA.match(schema or ""):
        raise BadName(f"schema {schema!r}")
    if not KEY.match(key or ""):
        raise BadName(f"key {key!r}")
    if variant is not None and not VARIANT.match(variant or ""):
        raise BadName(f"variant {variant!r}")


def relative(schema: str, key: str, variant: str) -> str:
    """The path below the root, as Caddy is told it: `st_marys/ab/ab12...-828.webp`."""
    _check(schema, key, variant)
    return f"{schema}/{key[:2]}/{key}-{variant}"


def path_of(schema: str, key: str, variant: str) -> Path:
    return root() / relative(schema, key, variant)


def incoming_path(schema: str, key: str) -> Path:
    _check(schema, key)
    return root() / INCOMING / schema / key


def content_type(variant: str) -> str:
    return CONTENT_TYPES[variant.rsplit(".", 1)[1]]


def _write_atomically(target: Path, chunks) -> int:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=target.parent, prefix=".part-")
    written = 0
    try:
        with os.fdopen(handle, "wb") as out:
            for chunk in chunks:
                out.write(chunk)
                written += len(chunk)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return written


def write_incoming(schema: str, key: str, upload) -> int:
    """Keep what was sent until the worker has made what is kept from it.

    `upload` is a Django `UploadedFile` (streamed in chunks, so a 50 MB video
    is never held in memory here) or bytes.
    """
    if isinstance(upload, (bytes, bytearray)):
        chunks = [bytes(upload)]
    else:
        upload.seek(0)
        chunks = upload.chunks()
    return _write_atomically(incoming_path(schema, key), chunks)


def read_incoming(schema: str, key: str) -> bytes:
    return incoming_path(schema, key).read_bytes()


def drop_incoming(schema: str, key: str):
    try:
        incoming_path(schema, key).unlink()
    except FileNotFoundError:
        pass


def building_dir(schema: str) -> Path:
    """A new, empty directory to build one made file in. The caller removes it."""
    if not SCHEMA.match(schema or ""):
        raise BadName(f"schema {schema!r}")
    parent = root() / BUILDING / schema
    parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(dir=parent, prefix="job-"))


def place(schema: str, key: str, variant: str, source: Path) -> int:
    """Move a file built in `building_dir()` to where `key`'s variant lives.

    A rename on one filesystem, so the file is never read into memory here and
    no reader ever sees half of it. Returns its size.
    """
    target = path_of(schema, key, variant)
    target.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(source, 0o644)
    os.replace(source, target)
    return target.stat().st_size


def forget_building(schema: str, older_than: float) -> int:
    """Remove build directories a killed job left behind. Returns how many."""
    parent = root() / BUILDING / schema
    removed = 0
    if not parent.is_dir():
        return 0
    for entry in parent.iterdir():
        try:
            if entry.is_dir() and entry.stat().st_mtime < older_than:
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1
        except FileNotFoundError:
            pass
    return removed


def write_variant(schema: str, key: str, variant: str, data: bytes) -> int:
    return _write_atomically(path_of(schema, key, variant), [data])


def read_variant(schema: str, key: str, variant: str) -> bytes:
    return path_of(schema, key, variant).read_bytes()


def delete_variants(schema: str, key: str, variants):
    for variant in variants:
        try:
            path_of(schema, key, variant).unlink()
        except FileNotFoundError:
            pass


def disk_usage():
    """`(used, total)` bytes of the filesystem the files live on."""
    where = root()
    where.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(where)
    return usage.total - usage.free, usage.total


def percent_used() -> float:
    used, total = disk_usage()
    return 100.0 * used / total if total else 0.0


__all__ = [
    "BUILDING",
    "BadName",
    "CONTENT_TYPES",
    "INCOMING",
    "content_type",
    "building_dir",
    "delete_variants",
    "forget_building",
    "disk_usage",
    "drop_incoming",
    "incoming_path",
    "path_of",
    "percent_used",
    "place",
    "read_incoming",
    "read_variant",
    "relative",
    "root",
    "write_incoming",
    "write_variant",
]
