"""The test runner that builds the tenant template, once per test database.

`settings.TEST_RUNNER` points here. The only thing this adds to Django's
`DiscoverRunner` is *when* the template is built, and that timing is the whole
reason it is a runner rather than a fixture — see `schools/tests/tenants.py`
for what the template is and what it costs.

## The ordering, and why it needs an override at all

`django.test.utils.setup_databases()` does two things in one call:

    connection.creation.create_test_db(...)          # the test database
    if parallel > 1:
        for index in range(parallel):
            connection.creation.clone_test_db(...)   # one per worker

The template has to be built **between** them. Every worker gets its own
database, made with `CREATE DATABASE ... TEMPLATE ...` from the one above, so a
template schema that exists before that line is inherited by all N workers for
the ~0.11s the copy already costs. Built after, each worker would have to
migrate its own — N × 1.65s, and N is the core count.

Django offers no hook between those two statements, so this asks for the test
database with `parallel` temporarily set to 0, builds the template into it, and
then makes the worker clones itself. `clone_test_db(suffix=str(i + 1))` is the
same call with the same arguments Django would have made, and produces the same
`..._1 … _N` names its workers connect to.

Teardown is untouched: `DiscoverRunner.teardown_databases()` reads `self.parallel`
at the time it runs, which is back to its real value, so it destroys the worker
databases it would have destroyed anyway.
"""

from django.test.runner import DiscoverRunner

from schools.tests.tenants import build_template


class TenantTemplateRunner(DiscoverRunner):
    def setup_databases(self, **kwargs):
        requested_parallel = self.parallel

        # Ask for the test database without the worker clones, so that the
        # template lands in what those clones are about to be copied from.
        self.parallel = 0
        try:
            old_config = super().setup_databases(**kwargs)
        finally:
            self.parallel = requested_parallel

        # `destroy` is True for exactly the first alias of each distinct test
        # database, which is the same set Django clones for.
        for connection, _old_name, destroy in old_config:
            if not destroy:
                continue
            build_template(using=connection.alias, verbosity=self.verbosity)
            if self.parallel > 1:
                for index in range(self.parallel):
                    connection.creation.clone_test_db(
                        suffix=str(index + 1),
                        verbosity=self.verbosity,
                        keepdb=self.keepdb,
                    )

        return old_config
