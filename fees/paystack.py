"""Paystack's HTTP API, the few calls this platform makes, in **test mode only**.

**Classnode never holds a school's money.** Every payment is split at Paystack
to the school's own subaccount, 100% to it, and Paystack settles that to the
school's own bank account. The platform takes no share (`percentage_charge` 0),
and the school bears Paystack's fees (`bearer_type: "subaccount"` on the split).

**Keys come from the environment**, read per call (`settings.PAYSTACK_*`, so
`override_settings` works, as for every provider here) and **never written into
an exception, a log line or a message**. A key that does not start `sk_test_` is
refused: this build is for Paystack's test mode, and a live key found in a
test deploy is a mistake to stop, not to honour.

**Stdlib `urllib`, no new dependency**, as `messaging.termii` does, so the tests
mock `urllib.request.urlopen` and nothing here reaches Paystack's servers under
test.

Two failures, for `messaging.providers`' reason: `PaystackRefused` is Paystack
saying no to what was asked (the account does not resolve, a bank is not
recognised) and carries a sentence for the person; `PaystackUnavailable` is
everything else — no reply, a timeout, a bad key, a `5xx`, a reply that is not
the shape a success has — and is nobody's fault but the operator's.

**What is assumed, not read from Paystack.** Paystack's documentation was not
reachable when this was written. The review of #217 checked the subaccount
calls and the split's fields (and `percentage_charge` 0) against Paystack's
current docs, and a second review checked `GET /bank` (`perPage` at most 100, cursor
paging with `use_cursor` and `next`) and `GET /bank/resolve`. Nothing here has been
called against the real service (`docs/handover.md`). The subaccount's bank field is
`bank_code` on both create and update (per the review of #217, against
Paystack's current Subaccount docs); `tests/test_bank` pins it.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings


class PaystackNotConfigured(Exception):
    """No test-mode secret key is set, or the one set is not a test key."""


class PaystackRefused(Exception):
    """Paystack said no to what was asked. `str()` is Paystack's own sentence."""


class PaystackUnavailable(Exception):
    """Paystack could not be reached, or failed. Not the caller's fault."""


def secret_key():
    key = getattr(settings, "PAYSTACK_SECRET_KEY", "") or ""
    if not key:
        raise PaystackNotConfigured("PAYSTACK_SECRET_KEY is not set.")
    if not key.startswith("sk_test_"):
        raise PaystackNotConfigured(
            "Only Paystack's test mode is supported: PAYSTACK_SECRET_KEY must start sk_test_."
        )
    return key


def _request(method, path, *, params=None, body=None, meta=False):
    """One call. Returns Paystack's `data` (`(data, meta)` if `meta`). Raises the two failures above."""
    key = secret_key()
    url = f"{settings.PAYSTACK_BASE_URL.rstrip('/')}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=getattr(settings, "PAYSTACK_TIMEOUT", 15)) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    except (urllib.error.URLError, OSError):
        # No exception text: a URLError can carry the URL, and the failure is the
        # same to the operator whatever it says.
        raise PaystackUnavailable("Paystack could not be reached.") from None

    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        payload = None
    if not isinstance(payload, dict):
        raise PaystackUnavailable(f"Paystack answered {status} with something unreadable.")

    message = str(payload.get("message") or "")
    if status in (401, 403):
        raise PaystackUnavailable("Paystack did not accept this platform's key.")
    if status in (400, 404, 422):
        raise PaystackRefused(message or "Paystack refused that.")
    if not (200 <= status < 300) or payload.get("status") is not True:
        raise PaystackUnavailable(f"Paystack answered {status}.")
    if meta:
        page = payload.get("meta")
        return payload.get("data"), page if isinstance(page, dict) else {}
    return payload.get("data")


#: Paystack's largest page (`perPage`), and a ceiling on how many pages one list
#: may take, so a cursor that never ends is a failure and not a loop.
BANKS_PER_PAGE = 100
MAX_BANK_PAGES = 20


def list_banks():
    """`[{name, code}, ...]` for Nigeria, by name, every page.

    Paged with a cursor (`use_cursor=true`, then `next` from each reply's
    `meta`) until there is none: `perPage` tops out at 100 and Nigeria has more
    banks than that. A cursor seen twice, or more than `MAX_BANK_PAGES` pages, is
    Paystack misbehaving and is `PaystackUnavailable`.
    """
    banks, seen, cursor = [], set(), None
    for _ in range(MAX_BANK_PAGES):
        params = {"country": "nigeria", "currency": "NGN", "perPage": BANKS_PER_PAGE, "use_cursor": "true"}
        if cursor:
            params["next"] = cursor
        data, page = _request("GET", "/bank", params=params, meta=True)
        if not isinstance(data, list):
            raise PaystackUnavailable("Paystack's bank list was not a list.")
        banks += [
            {"name": str(b["name"]), "code": str(b["code"])}
            for b in data
            if isinstance(b, dict) and b.get("name") and b.get("code")
        ]
        cursor = page.get("next")
        if not cursor:
            return sorted(banks, key=lambda b: b["name"].lower())
        if cursor in seen:
            raise PaystackUnavailable("Paystack's bank list did not end.")
        seen.add(cursor)
    raise PaystackUnavailable("Paystack's bank list was too long.")


def resolve_account(*, account_number, bank_code):
    """The name the bank holds for this account. `PaystackRefused` if it has none."""
    data = _request(
        "GET", "/bank/resolve", params={"account_number": account_number, "bank_code": bank_code}
    )
    name = (data or {}).get("account_name") if isinstance(data, dict) else None
    if not name:
        raise PaystackUnavailable("Paystack's answer had no account name.")
    return str(name)


def create_subaccount(*, business_name, bank_code, account_number):
    """A subaccount settling to this account, with **no share for the platform**."""
    data = _request(
        "POST",
        "/subaccount",
        body={
            "business_name": business_name,
            "bank_code": bank_code,
            "account_number": account_number,
            "percentage_charge": 0,
        },
    )
    return _code(data, "subaccount_code")


def update_subaccount(code, *, bank_code, account_number):
    """Point an existing subaccount at a different bank account."""
    data = _request(
        "PUT",
        f"/subaccount/{urllib.parse.quote(code, safe='')}",
        body={"bank_code": bank_code, "account_number": account_number},
    )
    return _code(data, "subaccount_code", default=code)


def create_split(*, name, subaccount_code):
    """A split that gives the subaccount 100% and makes it bear Paystack's fees."""
    data = _request(
        "POST",
        "/split",
        body={
            "name": name,
            "type": "percentage",
            "currency": "NGN",
            "subaccounts": [{"subaccount": subaccount_code, "share": 100}],
            "bearer_type": "subaccount",
            "bearer_subaccount": subaccount_code,
        },
    )
    return _code(data, "split_code")


def _code(data, field, default=None):
    value = data.get(field) if isinstance(data, dict) else None
    if value:
        return str(value)
    if default:
        return default
    raise PaystackUnavailable(f"Paystack's answer had no {field}.")
