"""The fake provider, switched on for a test, and a worker to run what was queued.

The test runner starts every run with no provider at all
(`schools.tests.runner`), so a test that sends asks for the fake itself, here.
"""

import re
from unittest import mock

from django.test import override_settings

from messaging.codes import send_code
from messaging.models import FakeMessage

FAKE = "messaging.fake.FakeProvider"
BOTH_FAKE = {"email": FAKE, "phone": FAKE}

_CODE = re.compile(r"code is (\d{6})")


class SendsThroughTheFake:
    """Mixin for a `TestCase`. The fake is on for every test in the class."""

    def setUp(self):
        super().setUp()
        self.enterContext(override_settings(MESSAGING_PROVIDERS=BOTH_FAKE))

    def queued(self, act):
        """Run `act` and its commit. Returns `(result, [task args])`: what it queued, unsent."""
        with mock.patch("messaging.codes.send_code.apply_async") as publish:
            with self.captureOnCommitCallbacks(execute=True):
                result = act()
        return result, [call.kwargs["args"] for call in publish.call_args_list]

    def deliver(self, act):
        """Run `act`, then every send it queued, as a worker would. Returns `act`'s result."""
        result, jobs = self.queued(act)
        for args in jobs:
            send_code(*args)
        return result

    def sent_to(self, address):
        return list(FakeMessage.objects.filter(address=address).order_by("created_at", "id"))

    def code_sent_to(self, address):
        """The six digits in the last message the fake was given for `address`."""
        messages = self.sent_to(address)
        self.assertTrue(messages, f"nothing was sent to {address}")
        found = _CODE.search(messages[-1].text)
        self.assertIsNotNone(found, messages[-1].text)
        return found.group(1)
