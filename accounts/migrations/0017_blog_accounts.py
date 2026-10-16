"""Blog accounts: `User.blog_role`, and the two rules that keep one apart from schools.

A writer or an editor of Classnode's own blog (`docs/blog.md`) is a login with
`blog_role` set, and that login reaches the blog and nothing else. Two rules
hold that, and both are Postgres's here rather than a view's:

- **Never platform staff, never a superuser**: `blog_account_is_not_staff`, a
  check on the row, because platform staff reach every school.
- **Never a membership at a school.** Cross-table, so a trigger on each side,
  in the shape `0008` and `0009` set for this shared app: `BEFORE INSERT OR
  UPDATE`, `restrict_violation` so Django raises `IntegrityError`, and a stable
  rule identifier opening each message so a test can say which side refused.
  `blog_account_holds_no_membership` on `accounts_membership`, and
  `membership_holder_gets_no_blog_role` on `accounts_user`.

The membership side reads the user with `FOR SHARE`, so a membership granted
while another transaction is giving the same login a blog role waits for it and
then sees the role; the user side reads the memberships the same way.
"""

from django.db import migrations, models

_FORWARD = """
CREATE FUNCTION blog_account_holds_no_membership() RETURNS trigger AS $$
BEGIN
    PERFORM 1 FROM accounts_user
     WHERE id = NEW.user_id AND blog_role <> ''
       FOR SHARE;
    IF FOUND THEN
        RAISE EXCEPTION 'blog_account_holds_no_membership: a blog account cannot hold a membership at a school'
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER blog_account_holds_no_membership
    BEFORE INSERT OR UPDATE OF user_id ON accounts_membership
    FOR EACH ROW EXECUTE FUNCTION blog_account_holds_no_membership();

CREATE FUNCTION membership_holder_gets_no_blog_role() RETURNS trigger AS $$
BEGIN
    IF NEW.blog_role <> '' THEN
        PERFORM 1 FROM accounts_membership WHERE user_id = NEW.id FOR SHARE;
        IF FOUND THEN
            RAISE EXCEPTION 'membership_holder_gets_no_blog_role: a login with a membership at a school cannot be a blog account'
                USING ERRCODE = 'restrict_violation';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER membership_holder_gets_no_blog_role
    BEFORE INSERT OR UPDATE OF blog_role ON accounts_user
    FOR EACH ROW EXECUTE FUNCTION membership_holder_gets_no_blog_role();
"""

_REVERSE = """
DROP TRIGGER IF EXISTS membership_holder_gets_no_blog_role ON accounts_user;
DROP FUNCTION IF EXISTS membership_holder_gets_no_blog_role();
DROP TRIGGER IF EXISTS blog_account_holds_no_membership ON accounts_membership;
DROP FUNCTION IF EXISTS blog_account_holds_no_membership();
"""



class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0016_a_login_records_its_first_sign_in"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="blog_role",
            field=models.CharField(
                blank=True,
                choices=[("writer", "Writer"), ("editor", "Editor")],
                default="",
                max_length=8,
            ),
        ),
        migrations.AlterField(
            model_name="signinattempts",
            name="scope",
            field=models.CharField(
                choices=[
                    ("identifier", "Identifier"),
                    ("address", "Network address"),
                    ("channel", "Guardian contact channel"),
                    ("checker_number", "Result checker admission number"),
                    ("checker_address", "Result checker network address"),
                    ("blog_email", "Blog sign-in email"),
                ],
                max_length=16,
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(("blog_role__in", ["", "writer", "editor"])),
                name="blog_role_is_known",
            ),
        ),
        migrations.AddConstraint(
            model_name="user",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("blog_role", ""),
                    models.Q(("is_platform_staff", False), ("is_superuser", False)),
                    _connector="OR",
                ),
                name="blog_account_is_not_staff",
            ),
        ),
        migrations.RunSQL(_FORWARD, _REVERSE),
    ]
