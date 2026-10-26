"""What changed in a school's setup, by whom and when. Kept for good.

One table, in each school's own schema, so one school's log is not on another
school's connection at all (`docs/tenancy.md`). Every change to a setup item
writes one row: a contact email saved or put off, a crest uploaded, the setup
started again, and (as the later pull requests land) a class or a term renamed,
archived, deleted or merged, a student renamed, a member of staff suspended.

## Append-only, twice

`Change.save()` refuses a second save and `.delete()` refuses outright: that
is the error a developer sees. The rule itself is a trigger
(`migrations/0002_a_change_is_never_rewritten`), which refuses UPDATE and
DELETE from anywhere, a `psql` session or a bulk `.update()` included, the
same way `fees_feeledgerentry` is kept. Like that one it does not fire on
TRUNCATE: emptying a schema wholesale is a different act from quietly
rewriting a row, and a TRUNCATE guard would also stop the test suite's own
teardown.

## Names are copied when the row is written

`by_name` and `item_name` are what they were at that moment, so the log still
reads correctly after a class or a person is renamed
(`docs/operating-rules.md` rule 2). The ids are bare: the person is a shared
`accounts.User`, and a tenant table holds no foreign key into `accounts`.
"""

from django.db import models


class ChangeIsKept(Exception):
    """A row of the log was asked to change or go. It never does."""


class Change(models.Model):
    at = models.DateTimeField(auto_now_add=True, db_index=True)

    #: Who did it: the `accounts.User` id, their name and the roles they acted
    #: in, as they were then.
    by_id = models.PositiveBigIntegerField()
    by_name = models.CharField(max_length=255)
    by_roles = models.CharField(max_length=100, blank=True, default="")

    #: What was done, as a short key ("renamed", "archived", "started-again").
    action = models.CharField(max_length=32)
    #: What kind of thing it was done to ("class", "term", "contact-email", "setup").
    kind = models.CharField(max_length=32)
    #: Which one, when it is a row with an id, and its name at the time.
    item_id = models.PositiveBigIntegerField(null=True, blank=True)
    item_name = models.CharField(max_length=255, blank=True, default="")

    #: One sentence a person reads: "Renamed JSS 1A to JSS 1 Gold."
    summary = models.CharField(max_length=500)
    #: What it was and what it became, for whoever needs more than the sentence.
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ["-at", "-id"]

    def __str__(self):
        return f"{self.at:%Y-%m-%d %H:%M} {self.by_name}: {self.summary}"

    def save(self, *args, **kwargs):
        if self.pk is not None and not self._state.adding:
            raise ChangeIsKept(f"Change {self.pk} is a record and does not change.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ChangeIsKept(f"Change {self.pk} is a record and is never deleted.")
