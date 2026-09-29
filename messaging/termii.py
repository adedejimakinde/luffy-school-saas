"""A real phone provider, behind the same seam the fake stands in for. D2, M11.

**Termii's messaging API, on the DND (transactional) route.** One `POST` to
`{TERMII_BASE_URL}/api/sms/send` with a JSON body of `to`, `from`, `sms`,
`type`, `channel` and `api_key`. `channel` is `"dnd"` and never `"generic"`:
the generic route skips numbers on Nigeria's do-not-disturb register, and a
sign-in code or a fee receipt must reach a parent who has opted out of
marketing. The cost is that the sender ID must be whitelisted for DND by
Termii; an unwhitelisted one is refused, and that refusal is the operator's to
fix (below).

**Configured by environment variables, all read per call** (so `override_settings`
works, as it does for every provider here): `TERMII_API_KEY`, `TERMII_SENDER_ID`,
`TERMII_BASE_URL` (default `https://api.ng.termii.com`; Termii documents a
base URL per account) and `TERMII_TIMEOUT` (seconds, default 10). The key is
sent in the request body, as the API requires, and is **never written into an
exception, a log line, or a `Refused`/`Unavailable` message**.

**Not the default anywhere.** A deploy selects it with
`MESSAGING_PHONE_PROVIDER=messaging.termii.TermiiProvider`. `FakeProvider` is
still what development and the test suite select, and this file is exercised
only by its own tests, against a mocked `urlopen`. Nothing here has been sent to
Termii's real servers.

**Two failures, D1's own distinction.** `Refused` is about the number: Termii
says the destination is invalid. `Unavailable` is everything else, and is
nobody's fault but the operator's or the network's: no reply, a timeout, a bad
API key, an empty wallet, a `5xx`, a reply that is not the shape a success has,
**and a refused sender ID** — the school cannot fix that by checking a number
with a family. Only a `2xx` carrying `message_id` is `Accepted`; a `200` that
does not say so is not treated as one.

**What is assumed, not read from Termii.** The request shape and the success
reply (`code: "ok"`, `message_id`, `balance`, `user`) are Termii's documented
ones. Their *error* replies were not available when this was written, so the
mapping from an error's HTTP status and `message` text to `Refused` or
`Unavailable` is a conservative guess: anything not clearly about the
destination number is `Unavailable`, which is retried rather than recorded as
the family's fault. Confirm against a real failing call before relying on it
(`docs/handover.md`).
"""

import json
import re
import urllib.error
import urllib.request

from django.conf import settings

from .providers import Accepted, NotConfigured, Refused, Unavailable

#: Words in a 4xx reply's `message` that put the fault on the sender ID or the
#: account, checked first: "Invalid sender ID for phone number" is a sender ID.
_OPERATOR = re.compile(r"sender|api[ _-]?key|balance|insufficient|not activated|not active|whitelist|unauthori[sz]ed", re.I)
#: ...and on the destination number.
_NUMBER = re.compile(r"phone|number|destination|recipient|\bto\b", re.I)


def _setting(name):
    return (getattr(settings, name, "") or "").strip()


class TermiiProvider:
    """The `phone` half of `MESSAGING_PROVIDERS`, for a deploy with a Termii account."""

    def check_configured(self):
        missing = [
            name
            for name in ("TERMII_API_KEY", "TERMII_SENDER_ID")
            if not _setting(name)
        ]
        if missing:
            raise NotConfigured(
                f"{' and '.join(missing)} not set, so the Termii SMS provider "
                f"cannot send. Set them, or select a different phone provider."
            )
        if not self._base_url().startswith("https://"):
            raise NotConfigured("TERMII_BASE_URL must be an https:// address.")

    @staticmethod
    def _base_url():
        return (_setting("TERMII_BASE_URL") or "https://api.ng.termii.com").rstrip("/")

    def send(self, outbound) -> Accepted:
        if outbound.channel_type != "phone":
            raise ValueError("The Termii provider sends to phone channels only.")
        self.check_configured()

        body = json.dumps(
            {
                # Termii wants the international form without the leading "+".
                "to": outbound.address.lstrip("+"),
                "from": _setting("TERMII_SENDER_ID"),
                "sms": outbound.text,
                "type": "plain",
                "channel": "dnd",
                "api_key": _setting("TERMII_API_KEY"),
            }
        ).encode()
        request = urllib.request.Request(
            f"{self._base_url()}/api/sms/send",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        timeout = getattr(settings, "TERMII_TIMEOUT", 10)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                status, payload = response.status, response.read()
        except urllib.error.HTTPError as exc:
            status, payload = exc.code, exc.read()
        except (urllib.error.URLError, OSError):
            # No exception text: a URLError can carry the request's URL, and
            # the failure is the same to the operator either way.
            raise Unavailable("Termii could not be reached.") from None

        return self._answer(status, payload)

    def _answer(self, status, payload) -> Accepted:
        try:
            data = json.loads(payload or b"{}")
        except ValueError:
            data = None
        if not isinstance(data, dict):
            data = {}
        message = str(data.get("message") or "")

        if 200 <= status < 300:
            ref = data.get("message_id")
            if ref and str(data.get("code", "ok")).lower() == "ok":
                return Accepted(provider_ref=str(ref))
            raise Unavailable("Termii answered, but not with an accepted message.")

        if status in (401, 403):
            raise Unavailable("Termii refused this deploy's API key.")
        if 400 <= status < 500 and status != 429:
            if _OPERATOR.search(message):
                raise Unavailable(
                    "Termii refused the sender ID or the account, not the number."
                )
            if _NUMBER.search(message):
                raise Refused("Termii will not deliver to this number.")
        raise Unavailable(f"Termii failed with HTTP {status}.")


__all__ = ["TermiiProvider"]
