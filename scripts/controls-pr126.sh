#!/usr/bin/env bash
# PR B controls. One at a time, module scope, NEVER --parallel.
#
# `--parallel` cost the first run entirely: a control that reddens a test whose
# failure carries a TransactionManagementError cannot be pickled back to the
# parent ("TypeError: cannot pickle 'traceback' object"), the worker pool dies,
# and the run reports EXIT=1 with no OK/FAILED line at all. A legitimate red
# became an unreportable crash. Serial runs report the failure.
set -uo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DJANGO_DEBUG=1
PY="accounts.tests.test_login accounts.tests.test_staff_sign_in_page attendance.tests.test_api attendance.tests.test_register_page"

run_one () {
  echo "################ CONTROL: $1"
  local js; js="$(npm test 2>&1)"
  echo "JS: $(printf '%s' "$js" | grep -E '^. (pass|fail)' | tr '\n' ' ')"
  printf '%s' "$js" | grep -E "^✖ " | sed 's/ ([0-9.]*ms)//' | sort -u | head -6
  RUN_TESTS_LOG=/tmp/ctlb2.log scripts/run-tests.sh --noinput $PY >/dev/null 2>&1
  local st=$?
  echo "PY: EXIT=$st RESULT=$(grep -E '^(OK|FAILED)' /tmp/ctlb2.log | tail -1 || echo '<none>')"
  grep -E "^(FAIL|ERROR): " /tmp/ctlb2.log | sed 's/ (\(accounts\|attendance\|results\)\..*//' | sort -u | head -8
  echo ""
  git checkout -- api.py attendance/ static/ accounts/ results/ 2>/dev/null
}

run_one "BASELINE (nothing broken — must be green both)"

python3 - <<'PY'
p="api.py"; s=open(p).read()
s=s.replace("may_take_a_register=not parent_scoped and school.pk in markers,",
            "may_take_a_register=True,  # CONTROL")
open(p,"w").write(s)
PY
run_one "1a. the payload claims every school is markable"

python3 - <<'PY'
p="static/staff-signin/states.js"; s=open(p).read()
s=s.replace("  if (entry.may_take_a_register) {","  if (true) {  // CONTROL")
open(p,"w").write(s)
PY
run_one "1b. the LANDING draws the register link regardless of the boolean"

python3 - <<'PY'
p="api.py"; s=open(p).read()
s=s.replace("may_take_a_register=not parent_scoped and school.pk in markers,",
            "may_take_a_register=bool(markers),  # CONTROL")
s=s.replace("has_children_here=school.pk in families,",
            "has_children_here=bool(families),  # CONTROL")
open(p,"w").write(s)
PY
run_one "2. booleans answered for the login, not per school"

python3 - <<'PY'
p="accounts/refusals.py"; s=open(p).read()
i=s.index("class NoMembershipHere"); j=s.index("class CodeSessionCannotEscalate")
open(p,"w").write(s[:i]+s[i:j].replace("a_password_fixes_it = False","a_password_fixes_it = True")+s[j:])
PY
run_one "3. NoMembershipHere.a_password_fixes_it -> True"

python3 - <<'PY'
p="accounts/models.py"; s=open(p).read()
s=s.replace("""            memberships__user=self, memberships__status__in=ACCESS_STATUSES
        ).distinct()""","""            memberships__user=self, memberships__status__in=LIVE_STATUSES
        ).distinct()  # CONTROL""")
open(p,"w").write(s)
PY
run_one "4. user.schools() scoped to LIVE_STATUSES"

python3 - <<'PY'
p="attendance/api.py"; s=open(p).read()
s=s.replace("""def _refuse_non_markers(request, school):""","""def _refuse_non_markers(request, school):
    return None  # CONTROL""",1)
open(p,"w").write(s)
PY
run_one "5. _refuse_non_markers() refuses nobody"

python3 - <<'PY'
p="api.py"; s=open(p).read()
s=s.replace("schools=_schools_of(user, parent_scoped=True),","schools=_schools_of(user),  # CONTROL")
open(p,"w").write(s)
PY
run_one "6. the code door stops narrowing the payload"

echo "=== tree after restore ==="; git status --short
