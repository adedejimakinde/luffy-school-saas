"""Timetable controls: break one thing, run at module scope, restore, assert clean."""

import os
import re
import subprocess
import sys

REPO = "/home/vscode/worktrees/timetable"
OUT = "/tmp/claude-1000/-workspace/2cc48ace-4c10-4723-be8e-8639ca18e7ef/scratchpad/tt-controls"
LABELS = ["timetable", "schools.tests.test_tenant_template"]
MIG = "timetable/migrations/0001_the_bell_and_the_week.py"

EXCLUDE_BLOCK = """                    django.contrib.postgres.constraints.ExclusionConstraint(
                        expressions=[
                            ("term", "="),
                            ("weekday", "="),
                            ("period", "="),
                            ("teacher_membership_id", "="),
                            ("subject", "<>"),
                        ],
                        name="a_teacher_teaches_one_subject_at_a_time",
                    ),
"""

CONTROLS = [
    ("1-no-clash-constraint", MIG, EXCLUDE_BLOCK, ""),
    ("2-no-subject-clause", MIG, '                            ("subject", "<>"),\n', ""),
    ("3-closed-range", "timetable/models.py", "%(expressions)s, '[)')", "%(expressions)s, '[]')"),
    ("4-no-emptiness-check", "timetable/services.py",
     "        if TimetableSlot.objects.filter(term=term).exists():\n",
     "        if False:\n"),
    ("5-no-read-check", "timetable/api.py",
     '    if not services.may_read(actor, school):\n        raise Http404("No such timetable.")\n',
     "    pass\n"),
    ("6-no-edit-check", "timetable/api.py",
     "    if not services.may_edit(actor, school):\n        return 403, MessageOut(detail=_MAY_NOT_EDIT)\n",
     "    pass\n"),
    ("7-teacher-lookup-unscoped", "timetable/api.py",
     ".filter(pk=payload.teacher_membership_id, school=school, role=Role.TEACHER.value)",
     ".filter(pk=payload.teacher_membership_id, role=Role.TEACHER.value)"),
    ("8-copy-read-unscoped", "timetable/services.py",
     "                school__schema_name=connection.schema_name,\n", ""),
    ("9-may-read-every-membership", "timetable/services.py",
     "return bool(set(actor.roles_at(school)) & READING_ROLES)",
     'return bool(set(actor.memberships.filter(school=school).values_list("role", flat=True)) & READING_ROLES)'),
    ("10-may-edit-every-membership", "timetable/services.py",
     "return bool(set(actor.roles_at(school)) & EDITING_ROLES)",
     'return bool(set(actor.memberships.filter(school=school).values_list("role", flat=True)) & EDITING_ROLES)'),
    ("11-clone-skips-exclude", "schools/tests/clone_tenant_schema.sql",
     "con.contype IN ('c', 'p', 'u', 'x')", "con.contype IN ('c', 'p', 'u')"),
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
    if only and name.split("-")[0] not in only:
        continue
    full = os.path.join(REPO, path)
    text = open(full).read()
    assert text.count(old) == 1, (name, text.count(old))
    open(full, "w").write(text.replace(old, new))
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
    failing = sorted(set(re.findall(r"^(?:FAIL|ERROR): (\S+ \(\S+\))", body, re.M)))
    exit_line = re.findall(r"^EXIT=.*$", proc.stdout, re.M)
    print(f"== {name}: {ran} {res} {exit_line} script_rc={proc.returncode}", flush=True)
    for f in failing:
        print(f"     {f}", flush=True)
print("CONTROLS DONE", flush=True)
