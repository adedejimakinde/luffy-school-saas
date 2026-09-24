"""B2 controls: break one thing, run every module that can reach it, restore, assert clean."""

import os
import re
import subprocess
import sys

REPO = "/home/vscode/worktrees/billing"
OUT = "/tmp/claude-1000/-workspace/2cc48ace-4c10-4723-be8e-8639ca18e7ef/scratchpad/b2-controls"
LABELS = [
    "fees.tests.test_schedules",
    "fees.tests.test_schedule_concurrency",
    "fees.tests.test_billing",
    "fees.tests.test_billing_api",
]
S = "fees/schedules.py"
B = "fees/billing.py"


def only_after(marker, old, new):
    """Replace every `old` after `marker` — a control aimed at B2's routes
    and not B1's, which share the helper."""
    def apply(text):
        head, tail = text.split(marker, 1)
        assert old in tail
        return head + marker + tail.replace(old, new)
    return apply


CONTROLS = [
    ("B2-1-no-billed-elsewhere-skip", S,
     "    charged_here = [sid for sid in student_ids if sid not in billed_elsewhere]\n",
     "    charged_here = list(student_ids)\n"),
    ("B2-2-elsewhere-read-without-term", S,
     "            kind=FeeEntryKind.CHARGE,\n            term=term,\n            source_line__isnull=False,\n",
     "            kind=FeeEntryKind.CHARGE,\n            source_line__isnull=False,\n"),
    ("B2-3-elsewhere-read-includes-this-bill", S,
     "        .exclude(source_line__schedule_id=locked.pk)\n", ""),
    ("B2-4-elsewhere-read-counts-hand-charges", S,
     "            term=term,\n            source_line__isnull=False,\n            student_membership_id__in=student_ids,\n",
     "            term=term,\n            student_membership_id__in=student_ids,\n"),
    ("B2-5-no-term-lock", S,
     "    term = Term.objects.select_for_update(no_key=True).get(pk=locked.term_id)\n",
     "    term = locked.term\n"),
    ("B2-6-no-already-charged-skip", S,
     "            if (student_id, line.pk) in already_charged:\n",
     "            if False:\n"),
    ("B2-7-revoke-without-require-reason", B,
     "    reason = services._require_reason(reason)\n    if getattr(by, \"pk\", None) is None:\n",
     "    if getattr(by, \"pk\", None) is None:\n"),
    ("B2-8-no-says-why-constraint", "fees/migrations/0005_a_revocation_says_who_and_why.py",
     """                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("reason__regex", "\\\\S")),
                        name="a_revocation_says_why",
                    )
                ],
""", ""),
    ("B2-9-no-triggers", "fees/migrations/0006_a_concession_is_never_edited.py",
     "        migrations.RunSQL(sql=TRIGGERS, reverse_sql=DROP_TRIGGERS),\n", ""),
    ("B2-10-b2-routes-skip-read-check", "fees/api.py",
     only_after("# -- B2: bills and concessions", "    _require_reader(request.user, school)\n", ""), None),
    ("B2-11-remove-line-unlocked", B,
     "        FeeSchedule.objects.select_for_update().get(pk=line.schedule_id)\n", ""),
    ("B2-12-add-line-not-atomic", "fees/api.py",
     "        with transaction.atomic():\n            _, added = billing.add_line(",
     "        if True:\n            _, added = billing.add_line("),
]

only = set(sys.argv[1:])
os.makedirs(OUT, exist_ok=True)
env = dict(os.environ, DJANGO_DEBUG="1",
           INVITATION_ACCEPT_URL="http://localhost:3000/invitations/{token}/",
           EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend")


def clean():
    return subprocess.run(["git", "status", "--porcelain"], cwd=REPO, capture_output=True,
                          text=True, check=True).stdout.strip() == ""


assert clean(), "tree not clean before controls"
for name, path, old, new in CONTROLS:
    if only and name.split("-")[1] not in only:
        continue
    full = os.path.join(REPO, path)
    text = open(full).read()
    if callable(old):
        broken = old(text)
    else:
        assert text.count(old) == 1, (name, text.count(old))
        broken = text.replace(old, new)
    assert broken != text, name
    open(full, "w").write(broken)
    log = f"{OUT}/{name}.log"
    try:
        proc = subprocess.run(["scripts/run-tests.sh", *LABELS, "--noinput"], cwd=REPO,
                              env=dict(env, RUN_TESTS_LOG=log), capture_output=True, text=True)
    finally:
        subprocess.run(["git", "checkout", "--", path], cwd=REPO, check=True)
    assert clean(), f"tree not clean after {name}"
    body = open(log).read()
    ran = re.findall(r"^Ran .*$", body, re.M)
    res = re.findall(r"^(OK.*|FAILED.*)$", body, re.M)
    failing = sorted(set(re.findall(r"^(?:FAIL|ERROR): (\S+) \(", body, re.M)))
    exit_line = re.findall(r"^EXIT=.*$", proc.stdout, re.M)
    print(f"== {name}: {ran} {res} {exit_line} script_rc={proc.returncode}", flush=True)
    for f in failing:
        print(f"     {f}", flush=True)
print("CONTROLS DONE", flush=True)
