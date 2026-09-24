"""How money moved, and the form it was posted from. Fees decisions 3(a) and 4,
2026-09-24.

`method` is required on a PAYMENT and a REFUND and empty on every other kind,
and a bank transfer names its reference — both as check constraints, so an
import or a shell session meets them too. `form_key` is unique where present,
which is what makes a double-submitted payment one payment.

**Adding the method constraint would refuse any payment already in the books
without one.** None exists: no school has posted to a ledger yet (no pilot data
at all), so there is nothing to backfill. A deployment that had real payments
would need a data migration naming each one's method first, and guessing
"cash" for them would be a record the school never made.

Adding the columns does not trip `fees_ledger_append_only`: `ADD COLUMN ...
DEFAULT ''` is DDL and fires no `UPDATE` trigger.
"""


from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0004_classteacher"),
        ("fees", "0003_fee_schedule_and_concession"),
    ]

    operations = [
        migrations.AddField(
            model_name="feeledgerentry",
            name="form_key",
            field=models.UUIDField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="feeledgerentry",
            name="method",
            field=models.CharField(
                blank=True,
                choices=[
                    ("cash", "Cash"),
                    ("bank_transfer", "Bank transfer"),
                    ("pos", "POS"),
                    ("cheque", "Cheque"),
                ],
                default="",
                max_length=16,
            ),
        ),
        migrations.AddConstraint(
            model_name="feeledgerentry",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("kind__in", ("payment", "refund")),
                        ("method__in", ["cash", "bank_transfer", "pos", "cheque"]),
                    ),
                    models.Q(
                        models.Q(("kind__in", ("payment", "refund")), _negated=True),
                        ("method", ""),
                    ),
                    _connector="OR",
                ),
                name="a_method_on_money_that_moved_and_nowhere_else",
            ),
        ),
        migrations.AddConstraint(
            model_name="feeledgerentry",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("method", "bank_transfer"), _negated=True),
                    ("reference__regex", "\\S"),
                    _connector="OR",
                ),
                name="a_bank_transfer_names_its_reference",
            ),
        ),
        migrations.AddConstraint(
            model_name="feeledgerentry",
            constraint=models.UniqueConstraint(
                condition=models.Q(("form_key__isnull", False)),
                fields=("form_key",),
                name="a_form_posts_once",
            ),
        ),
    ]
