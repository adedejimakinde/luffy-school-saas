"""A pretend Paystack, for tests: `urllib.request.urlopen` swapped for a router.

Nothing here reaches a network. It answers the few endpoints `fees.paystack`
calls, records every request (method, path, query, JSON body, headers) so a test
can say what was sent, and can be told to fail: `fail_next(status, body)` for an
HTTP failure, `down()` for no reply at all.
"""

import json
import urllib.error
import urllib.parse
from unittest import mock

from django.test import override_settings

TEST_KEY = "sk_test_0123456789abcdef"

BANKS = [
    {"name": "Wema Bank", "code": "035"},
    {"name": "Access Bank", "code": "044"},
    {"name": "Zenith Bank", "code": "057"},
]

#: Account number -> the name the (pretend) bank holds. Anything else does not resolve.
ACCOUNTS = {
    "0123456789": "ST MARYS COLLEGE",
    "1234567890": "GRACE ACADEMY LTD",
    "2222222222": "ST MARYS COLLEGE SAVINGS",
}


class _Response:
    def __init__(self, status, body):
        self.status = status
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakePaystack:
    def __init__(self):
        self.requests = []
        self.accounts = dict(ACCOUNTS)
        self._fail = []
        self._down = False
        self.subaccounts = 0
        self.splits = 0

    # -- what a test can arrange ---------------------------------------------
    def fail_next(self, status, body=b'{"status": false, "message": "boom"}'):
        self._fail.append((status, body))

    def down(self, value=True):
        self._down = value

    # -- what a test can read ------------------------------------------------
    def sent(self, method=None, path=None):
        return [
            r
            for r in self.requests
            if (method is None or r["method"] == method) and (path is None or r["path"] == path)
        ]

    # -- the router ----------------------------------------------------------
    def __call__(self, request, timeout=None):
        parsed = urllib.parse.urlparse(request.full_url)
        body = json.loads(request.data) if request.data else None
        record = {
            "method": request.get_method(),
            "path": parsed.path,
            "query": dict(urllib.parse.parse_qsl(parsed.query)),
            "body": body,
            "headers": {k.lower(): v for k, v in request.header_items()},
        }
        self.requests.append(record)
        if self._down:
            raise urllib.error.URLError("no route to host")
        if self._fail:
            status, payload = self._fail.pop(0)
            return _Response(status, payload)
        return self._route(record)

    def _route(self, r):
        method, path = r["method"], r["path"]
        if (method, path) == ("GET", "/bank"):
            return _Response(200, {"status": True, "message": "Banks retrieved", "data": BANKS})
        if (method, path) == ("GET", "/bank/resolve"):
            name = self.accounts.get(r["query"].get("account_number"))
            if name is None:
                return _Response(422, {"status": False, "message": "Could not resolve account name."})
            return _Response(
                200,
                {"status": True, "message": "Account number resolved",
                 "data": {"account_number": r["query"]["account_number"], "account_name": name}},
            )
        if (method, path) == ("POST", "/subaccount") or (method == "PUT" and path.startswith("/subaccount/")):
            # Paystack's Subaccount API names the bank field `bank_code`. Refuse
            # the old `settlement_bank`, so a drifted name fails loudly here too.
            if "bank_code" not in (r["body"] or {}) or "settlement_bank" in (r["body"] or {}):
                return _Response(400, {"status": False, "message": "bank_code is required"})
        if (method, path) == ("POST", "/subaccount"):
            self.subaccounts += 1
            return _Response(201, {"status": True, "message": "Subaccount created",
                                   "data": {"subaccount_code": f"ACCT_test{self.subaccounts:04d}"}})
        if method == "PUT" and path.startswith("/subaccount/"):
            return _Response(200, {"status": True, "message": "Subaccount updated",
                                   "data": {"subaccount_code": path.rsplit("/", 1)[1]}})
        if (method, path) == ("POST", "/split"):
            self.splits += 1
            return _Response(200, {"status": True, "message": "Split created",
                                   "data": {"split_code": f"SPL_test{self.splits:04d}"}})
        return _Response(404, {"status": False, "message": "Not found"})


class PaystackMixin:
    """`self.paystack` for the test, with the test key and no real network."""

    def setUp(self):
        super().setUp()
        self.paystack = FakePaystack()
        patcher = mock.patch("fees.paystack.urllib.request.urlopen", self.paystack)
        patcher.start()
        self.addCleanup(patcher.stop)
        override = override_settings(
            PAYSTACK_SECRET_KEY=TEST_KEY,
            PAYSTACK_WEBHOOK_SECRET=TEST_KEY,
            PAYSTACK_BASE_URL="https://api.paystack.test",
        )
        override.enable()
        self.addCleanup(override.disable)
