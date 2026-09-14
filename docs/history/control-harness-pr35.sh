#!/bin/bash
set -o pipefail
# One control per blocker fix. Each reverts exactly that fix and nothing else,
# runs the module, and records which tests stop passing. A fix whose control
# shows no new failure is a fix nothing is testing.
W=/home/vscode/worktrees/score-write-guard
SP=/tmp/claude-1000/-workspace/2fc7add9-961e-4c68-ae5f-e7dbaf89e8d5/scratchpad
cd "$W" || exit 1

run () {
  DJANGO_DEBUG=1 \
  INVITATION_ACCEPT_URL='http://localhost:3000/invitations/{token}/' \
  EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend \
  python manage.py test gradebook.tests.test_release_guard > "$SP/control_$1.log" 2>&1
  echo "########## CONTROL $1"
  grep -E "^Ran [0-9]+ test|^OK$|^FAILED" "$SP/control_$1.log"
  grep -E "^(FAIL|ERROR): test" "$SP/control_$1.log" | sed 's/ (gradebook.*//' | sort
  echo
}

# Restores from copies taken before the first control, NOT with `git checkout`.
# The first version of this used `git checkout --`, which reverts to HEAD — so
# after control 1 it silently wiped every uncommitted fix and controls 2-4 ran
# against the unfixed code, which is what a control is supposed to look like.
SAFE="$SP/safe"
mkdir -p "$SAFE"
cp gradebook/services.py "$SAFE/services.py"
cp gradebook/api.py "$SAFE/api.py"
cp gradebook/migrations/0002_a_released_mark_stays_released.py "$SAFE/0002.py"

restore () {
  cp "$SAFE/services.py" gradebook/services.py
  cp "$SAFE/api.py" gradebook/api.py
  cp "$SAFE/0002.py" gradebook/migrations/0002_a_released_mark_stays_released.py
}

# -- 1. blocker 2, service half: drop the artefact guard call sites only ------
sed -i '/^        _require_this_card_has_not_gone_home(assessment, membership)$/d' \
    gradebook/services.py
run "1_no_artefact_guard_service"
restore

# -- 2. blocker 2, database half: revert the trigger to placement-only -------
python3 - <<'PY' || { echo "EDIT FAILED — control skipped"; exit 1; }
import io, re
p = "gradebook/migrations/0002_a_released_mark_stays_released.py"
s = io.open(p, encoding="utf-8").read()
start = s.index("    -- Has a card for this child already been frozen")
end = s.index("    -- And is the child's current class released?")
s = s[:start] + s[end:]
s = s.replace("    card_went_home boolean;\n", "")
io.open(p, "w", encoding="utf-8").write(s)
PY
run "2_no_artefact_branch_trigger"
restore

# -- 3. blocker 3: put the guards back in front of the idempotent early exit --
python3 - <<'PY' || { echo "EDIT FAILED — control skipped"; exit 1; }
import io
p = "gradebook/services.py"
s = io.open(p, encoding="utf-8").read()
old = ("        if _current(assessment, membership.pk) is None:\n"
       "            return  # Already clear. Nothing to write, so nothing to guard.\n\n")
assert s.count(old) == 1
io.open(p, "w", encoding="utf-8").write(s.replace(old, ""))
PY
run "3_guard_before_idempotent_exit"
restore

# -- 4. blocker 1: drop the two API handlers, keeping the exception ----------
python3 - <<'PY' || { echo "EDIT FAILED — control skipped"; exit 1; }
import io
p = "gradebook/api.py"
s = io.open(p, encoding="utf-8").read()
for marker in ("    except services.MarksLocked as exc:\n        # 423, and see",
               "    except services.MarksLocked as exc:\n        # As in `save_score()`"):
    i = s.index(marker)
    j = s.index("    except services.NotThisSchoolsStudent:", i)
    s = s[:i] + s[j:]
io.open(p, "w", encoding="utf-8").write(s)
PY
run "4_no_api_handler"
restore

echo "########## controls complete; tree restored"
git status --short
