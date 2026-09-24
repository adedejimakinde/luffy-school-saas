import os, re, subprocess
REPO = "/home/vscode/worktrees/seed-try"
S = "/tmp/claude-1000/-workspace/2cc48ace-4c10-4723-be8e-8639ca18e7ef/scratchpad"
P = "schools/management/commands/seed_demo.py"
CONTROLS = [
    ("seed-3-no-combined-lesson",
     "                    if day == Weekday.FRIDAY and p == last:\n                        subject = science\n                    elif ",
     "                    if "),
    ("seed-4-bursary-not-revoked",
     '        billing.revoke_concession(bursary, reason="The bursary ended with last session", by=bursar)\n', ""),
]
env = dict(os.environ, DJANGO_DEBUG="1", POSTGRES_DB="luffy_seedtry",
           INVITATION_ACCEPT_URL="http://localhost:3000/invitations/{token}/",
           EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend")
full = os.path.join(REPO, P)
original = open(full).read()
for name, old, new in CONTROLS:
    assert original.count(old) == 1, name
    open(full, "w").write(original.replace(old, new))
    log = f"{S}/{name}.log"
    try:
        proc = subprocess.run(["scripts/run-tests.sh", "schools.tests.test_seed_demo", "--noinput"], cwd=REPO,
                              env=dict(env, RUN_TESTS_LOG=log), capture_output=True, text=True)
    finally:
        open(full, "w").write(original)
    body = open(log).read()
    print(name, re.findall(r"^Ran .*$", body, re.M), re.findall(r"^(OK.*|FAILED.*)$", body, re.M),
          re.findall(r"^EXIT=.*$", proc.stdout, re.M), flush=True)
    for m in sorted(set(re.findall(r"^AssertionError: .*$", body, re.M)))[:4]:
        print("    ", m[:160], flush=True)
    for m in sorted(set(re.findall(r"^(?:FAIL|ERROR): (\S+)", body, re.M))):
        print("    ", m, flush=True)
print("DONE")
