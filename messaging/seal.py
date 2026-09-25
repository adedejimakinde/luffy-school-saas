"""A code sealed for the broker, and opened again in the worker. `docs/messaging.md` D6.

`_mint_code()` promises the raw code "exists in memory for as long as it takes a
delivery channel to put it in an SMS or an email". A Celery message is not
memory: it sits in Redis, and Redis may write it to disk. So the code crosses the
broker sealed with Fernet (AES in CBC mode with an HMAC, from `cryptography`),
under a key derived from `SECRET_KEY` that the web and worker processes share.

**It dies with the code.** `open_sealed()` is given the seconds the code has left,
and Fernet refuses a token older than that. A message redelivered after the code
expired opens to nothing, and nothing is sent.

The key is derived rather than configured, so there is no second secret to rotate
or lose. It is labelled, so it can never be mistaken for any other use of
`SECRET_KEY`.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

_LABEL = b"classnode.messaging.code-on-the-broker.v1\x00"


def _fernet():
    key = hashlib.sha256(_LABEL + settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def seal(raw_code: str) -> str:
    """The code as a token that is safe to put on the queue."""
    return _fernet().encrypt(raw_code.encode("ascii")).decode("ascii")


def open_sealed(token: str, *, ttl_seconds: int):
    """The code again, or None if the token is forged, altered or older than `ttl_seconds`."""
    if ttl_seconds <= 0:
        return None
    try:
        return _fernet().decrypt(token.encode("ascii"), ttl=ttl_seconds).decode("ascii")
    except (InvalidToken, ValueError):
        return None
