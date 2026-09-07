"""The fee gate: a switch with a phone number, and an append-only log of decisions.

Three things land together because none of them is safe alone.

## 1. The switch cannot be on without somebody to call

`withhold_for_fees_enabled` and `withholding_contact` go on
`results_reportcardsettings`, and `a_withholding_school_names_who_to_call`
refuses the pair where the switch is on and the contact is blank.

A `CHECK` rather than a form validator, for `0002`'s reason: a validator is a
promise kept by one code path, and the admin, a shell, a data migration and a
test fixture are four others. What is being promised here is read by a **parent**
— the 403 in `results.card_api` tells a family who to ring — and a dead end
reachable by any of those four is still a dead end for the person standing at it.
`schools.School` has no contact fields at all, so there is nowhere else the
platform could find the number to keep the promise.

The switch defaults to **off**, which is why this migration needs no data step
for the existing rows: every school that has never heard of the feature keeps
behaving exactly as it did, and `AddField` fills the column with the default.

## 2. The decision is a table, not a boolean

`results_withholdingdecision` is `results_promotiondecision`'s shape — one act by
one person about one child, kept. More than one row per `(child, term)` is the
feature, so there is no unique constraint: withheld on the 3rd and lifted on the
12th is two rows and both stand. `a_withholding_says_why` requires a reason on a
withholding and allows a silent lifting, following `a_revision_says_why`
including its `\\S` regex — a reason of one space is not a reason.

`term` is a real ForeignKey with `PROTECT`, unlike `PromotionDecision.session`,
because a term is a row in this schema and a session is not.

## 3. Append-only, held by Postgres

`results_withholding_decisions_are_append_only()`, `BEFORE UPDATE OR DELETE FOR
EACH ROW`, `ERRCODE = 'restrict_violation'` — `0013`'s decision trigger by
another name, and for the same reason: `save()` and `delete()` refuse, which is
the error a developer sees, and this refuses, which is the error a `psql`
session, a data import or a bulk `.update()` runs into. None of those go near a
model method and every one of them is a real way a school's data gets edited in
anger.

**Not on INSERT**, again for `0013`'s reason: the table is written once by the
code that owns it, and refusing INSERT would refuse the write that creates the
row.

Created **unqualified**, so it lands in whichever schema is on the search path —
which is how every trigger in this app is created and what makes it per-school.

## What this migration deliberately does not do

Nothing here touches a frozen table, `release()`, or `cards.freeze_for_release()`.
**The card is still frozen for every child, unconditionally**; what these rows
gate is whether it is *served*. Making the freeze conditional would leave an
unpaid child with no frozen record of that term, permanently — the failure #31,
#33 and #34 converged on, and it must not come back through the fee door.
"""

import django.db.models.deletion
from django.db import migrations, models
from django.db.models import Q


FUNCTION = """
CREATE OR REPLACE FUNCTION results_withholding_decisions_are_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'results_withholdingdecision is append-only; % is not allowed. Record a '
        'new decision instead — both stand, and the later one is what holds.',
        TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

TRIGGER = """
CREATE TRIGGER results_withholding_decisions_append_only
BEFORE UPDATE OR DELETE ON results_withholdingdecision
FOR EACH ROW EXECUTE FUNCTION results_withholding_decisions_are_append_only();
"""

DROP = """
DROP TRIGGER IF EXISTS results_withholding_decisions_append_only ON results_withholdingdecision;
DROP FUNCTION IF EXISTS results_withholding_decisions_are_append_only();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0001_initial"),
        ("results", "0022_a_card_owes_a_file_from_the_moment_it_is_released"),
    ]

    operations = [
        migrations.AddField(
            model_name="reportcardsettings",
            name="withhold_for_fees_enabled",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Hold a released card back from the family while fees are owed."
                ),
            ),
        ),
        migrations.AddField(
            model_name="reportcardsettings",
            name="withholding_contact",
            field=models.CharField(
                blank=True,
                help_text=(
                    "Who a family should contact about a held card. Required to "
                    "hold one."
                ),
                max_length=255,
            ),
        ),
        migrations.AddConstraint(
            model_name="reportcardsettings",
            constraint=models.CheckConstraint(
                condition=(
                    ~Q(withhold_for_fees_enabled=True)
                    | Q(withholding_contact__regex=r"\S")
                ),
                name="a_withholding_school_names_who_to_call",
            ),
        ),
        migrations.CreateModel(
            name="WithholdingDecision",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("student_membership_id", models.PositiveBigIntegerField()),
                ("status", models.CharField(choices=[("withheld", "Held back from the family"), ("lifted", "Released to the family")], max_length=16)),
                ("reason", models.TextField(blank=True)),
                ("balance_kobo_at_decision", models.BigIntegerField(blank=True, null=True)),
                ("decided_by_id", models.PositiveBigIntegerField(blank=True, null=True)),
                ("decided_at", models.DateTimeField(auto_now_add=True)),
                (
                    "term",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="withholding_decisions",
                        to="academics.term",
                    ),
                ),
            ],
            options={
                "ordering": [
                    "student_membership_id",
                    "term_id",
                    "-decided_at",
                    "-id",
                ],
            },
        ),
        migrations.AddIndex(
            model_name="withholdingdecision",
            index=models.Index(
                fields=["student_membership_id", "term", "-decided_at", "-id"],
                name="the_latest_withholding",
            ),
        ),
        migrations.AddConstraint(
            model_name="withholdingdecision",
            constraint=models.CheckConstraint(
                condition=~Q(status="withheld") | Q(reason__regex=r"\S"),
                name="a_withholding_says_why",
            ),
        ),
        migrations.RunSQL(sql=FUNCTION, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(sql=TRIGGER, reverse_sql=DROP),
    ]
