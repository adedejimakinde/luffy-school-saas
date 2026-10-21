"""The dependency pins hold: `scripts/check_pins.py` finds nothing to refuse.

CI also runs the script on its own, before the suite installs anything. This
keeps the same answer in the suite, so `run-tests.sh` catches an unpinned
requirement on a developer's machine, not only on a pull request.
"""

import importlib.util
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

SCRIPT = Path(settings.BASE_DIR) / "scripts" / "check_pins.py"


def load():
    spec = importlib.util.spec_from_file_location("check_pins", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PinsTests(SimpleTestCase):
    def test_the_repository_is_pinned(self):
        self.assertEqual(load().main(), 0)

    def test_a_range_is_refused(self):
        module = load()
        with self.subTest("range"):
            self.assertFalse(module.PIN.match("Django>=5.0"))
        with self.subTest("exact"):
            self.assertTrue(module.PIN.match("Django==5.2.18"))
        with self.subTest("floating base"):
            self.assertFalse(module.BASE.match("FROM python:3.11-slim-bookworm"))
