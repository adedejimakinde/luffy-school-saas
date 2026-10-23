# A term that has had a subject assignment stays restricted until the principal opens
# it, the switch is written to the same append-only log, and a new term can carry the
# last one's assignments forward (`docs/subject-teachers.md`). Only DDL: the log's
# trigger refuses UPDATE and DELETE on rows, and nothing here touches a row.


import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0005_a_child_has_details_beyond_a_name"),
        ("gradebook", "0005_who_teaches_what_and_every_change_to_it_is_kept"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubjectTeacherCarry",
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
                ("copied", models.PositiveIntegerField()),
                ("skipped", models.PositiveIntegerField()),
                ("at", models.DateTimeField(auto_now_add=True)),
                ("seen_at", models.DateTimeField(blank=True, null=True)),
                ("seen_by_id", models.PositiveBigIntegerField(blank=True, null=True)),
            ],
        ),
        migrations.RemoveConstraint(
            model_name="subjectteacherchange",
            name="a_subject_teacher_change_is_added_or_removed",
        ),
        migrations.AddField(
            model_name="subjectteacherchange",
            name="from_term",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="academics.term",
            ),
        ),
        migrations.AddField(
            model_name="subjectteacherchange",
            name="from_term_name",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="subjectteacherchange",
            name="reason",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AlterField(
            model_name="subjectteacherchange",
            name="by_id",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="subjectteacherchange",
            name="by_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AlterField(
            model_name="subjectteacherchange",
            name="class_group_id",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="subjectteacherchange",
            name="class_group_name",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AlterField(
            model_name="subjectteacherchange",
            name="kind",
            field=models.CharField(
                choices=[
                    ("added", "Added"),
                    ("removed", "Removed"),
                    ("skipped", "Not copied"),
                    ("opened", "Opened to all"),
                    ("restricted", "Restricted"),
                ],
                max_length=10,
            ),
        ),
        migrations.AlterField(
            model_name="subjectteacherchange",
            name="subject_id",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="subjectteacherchange",
            name="subject_name",
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AlterField(
            model_name="subjectteacherchange",
            name="teacher_membership_id",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="subjectteacherchange",
            name="teacher_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddConstraint(
            model_name="subjectteacherchange",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        "kind__in",
                        ["added", "removed", "skipped", "opened", "restricted"],
                    )
                ),
                name="a_subject_teacher_change_is_one_of_five",
            ),
        ),
        migrations.AddConstraint(
            model_name="subjectteacherchange",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("kind__in", ["opened", "restricted"]),
                    models.Q(
                        ("class_group_id__isnull", False),
                        ("subject_id__isnull", False),
                        ("teacher_membership_id__isnull", False),
                    ),
                    _connector="OR",
                ),
                name="a_subject_teacher_change_names_its_pair",
            ),
        ),
        migrations.AddConstraint(
            model_name="subjectteacherchange",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("by_id__isnull", False),
                    ("from_term__isnull", False),
                    _connector="OR",
                ),
                name="a_subject_teacher_change_is_by_somebody_or_carried",
            ),
        ),
        migrations.AddConstraint(
            model_name="subjectteacherchange",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("kind", "skipped"), _negated=True),
                    ("from_term__isnull", False),
                    _connector="OR",
                ),
                name="only_a_carry_forward_skips",
            ),
        ),
        migrations.AddField(
            model_name="subjectteachercarry",
            name="from_term",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="academics.term",
            ),
        ),
        migrations.AddField(
            model_name="subjectteachercarry",
            name="term",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="subject_teacher_carry",
                to="academics.term",
            ),
        ),
    ]
