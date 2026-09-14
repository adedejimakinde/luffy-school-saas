#!/bin/bash
export DJANGO_DEBUG=1
export INVITATION_ACCEPT_URL='http://localhost:3000/invitations/{token}/'
export EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
S=/tmp/claude-1000/-workspace/784012f8-b18d-4490-aec1-ada5b23e2f69/scratchpad

drop_stale () {
  python - <<'PY' 2>/dev/null
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")
django.setup()
from django.db import connection
with connection.cursor() as c:
    c.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
              "WHERE datname LIKE 'test_%' AND pid <> pg_backend_pid()")
PY
}

cd /home/vscode/worktrees/card-revision
python manage.py test \
  results.tests.test_revision.WhatTheOtherReadersSawTests \
  results.tests.test_sessions.TheChildWhoMovedAfterReleaseTests \
  --noinput > $S/recheck-revision.log 2>&1
echo "EXIT=$?" >> $S/recheck-revision.log

drop_stale

cd /home/vscode/worktrees/card-pdf
python manage.py test results.tests.test_pdf.TheRenderedPageTests \
  --noinput > $S/recheck-pdf.log 2>&1
echo "EXIT=$?" >> $S/recheck-pdf.log
echo BOTH-DONE
