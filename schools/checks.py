"""The bare-id policy, refused at `manage.py check` rather than found in CI.

`docs/tenancy.md` forbids a relation field from a tenant model to a model that
lives only in `public`: `on_delete` is resolved against whichever schema the
connection is on, so `PROTECT` does not protect, `CASCADE` cascades one school's
rows only, and the breakage surfaces at `COMMIT` rather than at the delete.
`schools/tests/test_cross_schema_fk.py` measured all three.

That file also enforces the rule *as built*:
`test_no_shipped_tenant_model_reaches_into_public` reads `pg_constraint` in a
real school's schema and fails on any foreign key that leaves it. It is the
stronger of the two, and the only one that sees a constraint added by raw SQL in
a migration. What it cannot do is fail early. It lives in `schools`, so a
developer adding a `ForeignKey` to an attendance model and running the
attendance tests never reaches it, and the first signal is a red CI run on a
migration already written. And the failure class is invisible at one tenant, so
nothing in their own app's tests would have looked wrong either (#92).

This is the early half. It reads the declared model graph, so it runs on every
`manage.py` command that checks — `runserver`, `makemigrations`, `migrate`, the
test runner — before any migration exists to be undone.
"""

from django.apps import apps
from django.conf import settings
from django.core.checks import Error, Tags, register
from django.db.models import ForeignObjectRel


def tenant_relations_into_public(models):
    """Every relation field on `models` whose target lives only in `public`.

    "Only in `public`" is SHARED_APPS minus TENANT_APPS, and the subtraction is
    the point: `django.contrib.contenttypes` is in both lists, so each school has
    its own `django_content_type` and a relation to it binds inside the school's
    schema, which is the thing the policy allows. Tenant-to-tenant relations are
    allowed for the same reason, and `fees.FeeLedgerEntry` relies on two.

    Forward relations only: a reverse accessor is the other model's field seen
    from this side, and it is reported on that model if anywhere. That includes
    the parent link a subclass of a shared model would carry, which is a
    `OneToOneField` into `public` like any other. A `GenericForeignKey` has no
    single target and keeps its object id in a bare column, which is the
    policy's own shape, so there is nothing to report.
    """
    public_only = set(settings.SHARED_APPS) - set(settings.TENANT_APPS)
    found = []
    for model in models:
        for field in model._meta.get_fields(include_parents=False):
            if not field.is_relation or isinstance(field, ForeignObjectRel):
                continue
            target = field.related_model
            if target is None or isinstance(target, str):
                continue
            if target._meta.app_config.name in public_only:
                found.append(field)
    return found


def _tenant_models():
    tenant_only = set(settings.TENANT_APPS) - set(settings.SHARED_APPS)
    return [
        model
        for config in apps.get_app_configs()
        if config.name in tenant_only
        for model in config.get_models()
    ]


@register(Tags.models)
def no_tenant_model_has_a_relation_into_public(app_configs, **kwargs):
    """A tenant model refers to a shared row by bare id, never by relation field.

    Not `deploy=True`: a cross-schema foreign key is wrong in every environment,
    and development is where it is cheapest to hear about it.
    """
    return [
        Error(
            f"{field.model._meta.label}.{field.name} is a {type(field).__name__} "
            f"into {field.related_model._meta.label}, which lives only in "
            "`public`. A tenant table must not hold a relation into a shared one.",
            hint=(
                "Store the id as a PositiveBigIntegerField and check it in the "
                "service layer, as fees.FeeLedgerEntry.student_membership_id does. "
                "docs/tenancy.md, 'HARD BLOCKER: tenant → shared foreign keys', "
                "says why on_delete cannot be trusted across schemas."
            ),
            obj=field,
            id="schools.E001",
        )
        for field in tenant_relations_into_public(_tenant_models())
    ]
