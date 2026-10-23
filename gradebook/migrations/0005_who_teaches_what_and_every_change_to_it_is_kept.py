# Who teaches which subject to which class, per term, and the append-only record of
# every change to it (`docs/subject-teachers.md`).

import django.db.models.deletion
from django.db import migrations, models


FUNCTION = """
CREATE OR REPLACE FUNCTION gradebook_subject_teacher_changes_are_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'gradebook_subjectteacherchange is append-only; % is not allowed. It is the '
        'record of who changed who teaches what, and when.', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;
"""

TRIGGER = """
CREATE TRIGGER gradebook_subject_teacher_changes_are_append_only
BEFORE UPDATE OR DELETE ON gradebook_subjectteacherchange
FOR EACH ROW EXECUTE FUNCTION gradebook_subject_teacher_changes_are_append_only();
"""

DROP = """
DROP TRIGGER IF EXISTS gradebook_subject_teacher_changes_are_append_only ON gradebook_subjectteacherchange;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("academics", "0005_a_child_has_details_beyond_a_name"),
        ("gradebook", "0004_a_subject_sits_in_a_department"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubjectTeacher",
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
                (
                    "teacher_membership_id",
                    models.PositiveBigIntegerField(db_index=True),
                ),
                (
                    "assigned_by_id",
                    models.PositiveBigIntegerField(blank=True, null=True),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "class_group",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="subject_teachers",
                        to="academics.classgroup",
                    ),
                ),
                (
                    "subject",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="subject_teachers",
                        to="gradebook.subject",
                    ),
                ),
                (
                    "term",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="subject_teachers",
                        to="academics.term",
                    ),
                ),
            ],
            options={
                "ordering": [
                    "term_id",
                    "class_group_id",
                    "subject_id",
                    "teacher_membership_id",
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("term", "class_group", "subject", "teacher_membership_id"),
                        name="one_subject_teacher_row_per_pair_and_teacher",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="SubjectTeacherChange",
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
                (
                    "kind",
                    models.CharField(
                        choices=[("added", "Added"), ("removed", "Removed")],
                        max_length=8,
                    ),
                ),
                ("class_group_id", models.PositiveBigIntegerField()),
                ("subject_id", models.PositiveBigIntegerField()),
                ("teacher_membership_id", models.PositiveBigIntegerField()),
                ("class_group_name", models.CharField(max_length=64)),
                ("subject_name", models.CharField(max_length=100)),
                ("teacher_name", models.CharField(max_length=255)),
                ("by_id", models.PositiveBigIntegerField()),
                ("by_name", models.CharField(max_length=255)),
                ("at", models.DateTimeField(auto_now_add=True)),
                (
                    "term",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="subject_teacher_changes",
                        to="academics.term",
                    ),
                ),
            ],
            options={
                "ordering": ["-at", "-id"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("kind__in", ["added", "removed"])),
                        name="a_subject_teacher_change_is_added_or_removed",
                    )
                ],
            },
        ),
        migrations.RunSQL(sql=FUNCTION, reverse_sql=migrations.RunSQL.noop),
        migrations.RunSQL(sql=TRIGGER, reverse_sql=DROP),
    ]
