"""A concession's revocation becomes a row: who, when and why. Issue #75.

Two migrations and not one: this one writes rows, the next alters the table
they point at, and keeping the data change and the schema change in separate
transactions keeps each one's failure its own.

**The backfill.** A concession already switched off (`is_active = false`)
becomes a revocation dated by its `updated_at` — the only "when" the old column
kept — with no person, because nobody recorded one, and a reason that says so
rather than inventing one. `revoked_by_id` is nullable for these rows alone;
`fees.billing.revoke_concession()` refuses to write one without a person.

Reversed, it switches each revoked concession off again, which is what the
flag said; the reason and the person, where there was one, are lost, which is
the state the reverse returns to.
"""

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

#: What a backfilled revocation says. Plain about what is not known.
BACKFILLED = (
    "Switched off before revocations were recorded; who revoked it and why "
    "were not kept."
)


def revocations_from_the_flag(apps, schema_editor):
    FeeConcession = apps.get_model("fees", "FeeConcession")
    FeeConcessionRevocation = apps.get_model("fees", "FeeConcessionRevocation")
    FeeConcessionRevocation.objects.bulk_create(
        FeeConcessionRevocation(
            concession_id=pk, reason=BACKFILLED, revoked_by_id=None, revoked_at=when
        )
        for pk, when in FeeConcession.objects.filter(is_active=False)
        .order_by("pk")
        .values_list("pk", "updated_at")
    )


def the_flag_from_revocations(apps, schema_editor):
    FeeConcession = apps.get_model("fees", "FeeConcession")
    FeeConcession.objects.filter(revocation__isnull=False).update(is_active=False)


class Migration(migrations.Migration):

    dependencies = [
        ("fees", "0004_money_says_how_it_moved"),
    ]

    operations = [
        migrations.CreateModel(
            name="FeeConcessionRevocation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "reason",
                    models.CharField(
                        help_text="Why it was revoked, in the school's words.", max_length=255
                    ),
                ),
                (
                    "revoked_by_id",
                    models.PositiveBigIntegerField(
                        blank=True,
                        help_text="accounts.User id of whoever revoked it. Null only for the backfill.",
                        null=True,
                    ),
                ),
                (
                    "revoked_by_name",
                    models.CharField(
                        blank=True,
                        help_text="Their name as it stood when they revoked it. Empty only for the backfill.",
                        max_length=255,
                    ),
                ),
                ("revoked_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "concession",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="revocation",
                        to="fees.feeconcession",
                    ),
                ),
            ],
            options={
                "ordering": ["revoked_at", "id"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("reason__regex", "\\S")),
                        name="a_revocation_says_why",
                    )
                ],
            },
        ),
        migrations.RunPython(revocations_from_the_flag, the_flag_from_revocations),
    ]
