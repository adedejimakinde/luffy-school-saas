# The settings every Postgres in this repository starts with, in one place.
#
# Sourced by `entrypoint.sh` (production's database), `restore-serve.sh` (the
# weekly restore test's) and `.github/actions/test-database` (the one the suite
# and the screens job run against); `docker-compose.yml`'s development database
# repeats the number, and `schools/tests/test_lock_budget.py` holds all of them
# to it. Add a setting here and every one of them starts with it.
#
# ## max_locks_per_transaction
#
# Postgres's lock table is one shared pool of `max_locks_per_transaction x
# (max_connections + max_prepared_transactions)` slots, 64 x 100 = 6,400 by
# default. A transaction that creates tables holds a lock on every table and
# every index it made until it ends, and **making a school is one transaction**:
# `School.save()` runs CREATE SCHEMA and every migration inside the caller's
# `transaction.atomic()` (`schools.onboarding.create_school`). Today that holds
# about 1,350 locks (69 tables, 222 indexes), a fifth of the default pool. The
# suite does the same for every test (`schools/tests/tenants.py`, `make_school`,
# a clone that holds about 1,700) and runs four workers side by side, each
# holding up to three schools until its test ends, so a few overlapping tests
# used the pool up: CI failed with `out of shared memory` in whichever test was
# unlucky, never the same one twice.
#
# 512 makes the pool 51,200: about thirty schools being made at once, twice the
# suite's worst case (twelve, with a quarter to spare). It also gives a `pg_dump`
# of the whole database, which locks every table of every school (69 each, today),
# room for hundreds of schools where the default had room for about ninety. The
# cost is shared memory for the lock table, tens of megabytes. 256 was not enough
# for the suite's own worst case, measured (`schools/tests/test_lock_budget.py`).
#
# It is read at server start, so a running server cannot change it: a change here
# reaches production when the `db` container is recreated (`docs/deployment.md`,
# "Postgres settings").
#
# **A server restored from a backup must start with at least what the server
# that made the backup had** (Postgres refuses to recover with fewer), which is
# why `restore-serve.sh` takes these too.
CLASSNODE_PG_SETTINGS=(
  max_locks_per_transaction=512
)

CLASSNODE_PG_ARGS=()
for _setting in "${CLASSNODE_PG_SETTINGS[@]}"; do
  CLASSNODE_PG_ARGS+=(-c "$_setting")
done
unset _setting
