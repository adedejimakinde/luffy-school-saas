#!/usr/bin/env python
"""Fail if any Python dependency is unpinned, or the image base floats.

Builds are reproducible only while three things hold, and each is checked here:

* `requirements.txt` (the lock `pip-compile --generate-hashes` writes from
  `requirements.in`) holds nothing but `name==version` requirements, each with
  at least one `--hash=sha256:`. No range, no URL or VCS requirement, no
  editable install, no requirement without a hash.
* Every direct dependency named in `requirements.in` is in the lock, so the lock
  is not older than the file it came from.
* The Dockerfile's Python base is an exact `X.Y.Z` tag with an `@sha256:` digest,
  and its `pip install` passes `--require-hashes`.

Standard library only, so CI runs it before installing anything.

    python scripts/check_pins.py        # exit 1, one line per problem
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9._+!-]*)$")
NAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")
HASH = re.compile(r"^--hash=sha256:[0-9a-f]{64}$")
BASE = re.compile(r"^FROM\s+python:(\d+\.\d+\.\d+)(-[\w.-]+)?@sha256:[0-9a-f]{64}(\s+AS\s+\w+)?$", re.I)


def canonical(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def logical_lines(text):
    """Requirement lines with continuations joined and comments dropped."""
    text = text.replace("\\\n", " ")
    for raw in text.splitlines():
        line = raw.split(" #")[0].strip()
        if line and not line.startswith("#"):
            yield line


def check_lock(path):
    problems, names = [], set()
    for line in logical_lines(path.read_text()):
        spec, *options = line.split()
        if spec.startswith("-"):
            problems.append(f"{path.name}: option or editable/URL requirement not allowed: {line[:60]}")
            continue
        match = PIN.match(spec)
        if not match:
            problems.append(f"{path.name}: not pinned with '==': {spec}")
            continue
        names.add(canonical(match.group(1)))
        hashes = [o for o in options if HASH.match(o)]
        if not hashes or len(hashes) != len(options):
            problems.append(f"{path.name}: {spec} has no sha256 hash (or an unrecognised option)")
    if not names:
        problems.append(f"{path.name}: no requirements found")
    return problems, names


def check_direct_in_lock(path, locked):
    problems = []
    for line in logical_lines(path.read_text()):
        match = NAME.match(line)
        if line.startswith("-") or not match:
            problems.append(f"{path.name}: unsupported line: {line[:60]}")
        elif canonical(match.group(1)) not in locked:
            problems.append(f"{path.name}: {match.group(1)} is not in requirements.txt; re-run pip-compile")
    return problems


def check_dockerfile(path):
    problems, bases, installs = [], 0, 0
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if re.match(r"^FROM\s+python[:@\s]", stripped, re.I):
            bases += 1
            if not BASE.match(stripped):
                problems.append(f"{path.name}: base image must be python:X.Y.Z[-variant]@sha256:<digest>: {stripped}")
        if re.search(r"\bpip3?\s+install\b", stripped) and not stripped.startswith("#"):
            installs += 1
            if "--require-hashes" not in stripped:
                problems.append(f"{path.name}: pip install without --require-hashes: {stripped}")
    if not bases:
        problems.append(f"{path.name}: no python base image found")
    if not installs:
        problems.append(f"{path.name}: no pip install found")
    return problems


def main():
    problems, locked = check_lock(ROOT / "requirements.txt")
    problems += check_direct_in_lock(ROOT / "requirements.in", locked)
    problems += check_dockerfile(ROOT / "Dockerfile")
    for problem in problems:
        print(problem)
    if problems:
        print(f"{len(problems)} problem(s): builds are not reproducible.")
        return 1
    print(f"{len(locked)} locked requirements, all pinned and hashed; image base is exact.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
