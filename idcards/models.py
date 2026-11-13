"""Student ID cards: the QR code's record, and the print log. `docs/id-cards.md`.

Two tables, both in the school's own schema, so a card issued by one school
does not exist at another: a token read on the wrong host finds no row, which
is what "refuses another school's card" rests on.
"""

import secrets

from django.db import models
from django.db.models import Q



class PrintState(models.TextChoices):
    """Where one "Print ID cards" job has got to.

    The same four words and the same meaning as `results.models.PrintState`,
    declared here so that this app's schema never changes because that one did.
    `BUILDING` carries a heartbeat, written after every sheet, so a second
    worker handed the same message leaves a live job alone and takes over a
    dead one (`idcards.printing.claim`).
    """

    PENDING = "pending", "Waiting to start"
    BUILDING = "building", "Being made"
    READY = "ready", "Ready to download"
    FAILED = "failed", "Could not be made"


def new_token() -> str:
    """16 URL-safe characters, 96 bits: long enough that nobody guesses a card's page."""
    return secrets.token_urlsafe(12)


class IdCard(models.Model):
    """The card a child holds for one session: what its QR code points at.

    One row per child per session, made the first time the card is printed and
    **reused by every later print**, so a reprinted card is the same card and
    the one already in the child's bag still verifies. The row holds a random
    token and a date, and nothing else about the child: the verification page
    reads the name, class and photo live, so a corrected name is corrected on
    the page too, and it can say only what this table lets it find.

    The child is a bare id: memberships are in `public`, and a school's table
    does not point across schemas (`docs/tenancy.md`).
    """

    token = models.CharField(max_length=24, unique=True, default=new_token)
    student_membership_id = models.PositiveBigIntegerField(db_index=True)
    #: The academic session it was printed for ("2025/2026").
    session = models.CharField(max_length=9)
    #: The last day it is valid: the end of that session's last term.
    expires_on = models.DateField()
    issued_at = models.DateTimeField(auto_now_add=True)
    issued_by_id = models.PositiveBigIntegerField(null=True, blank=True)
    #: Set when a card is withdrawn (lost, or replaced). A withdrawn card reads
    #: as expired. Nothing sets it yet; the column is here so that a later
    #: "lost card" button does not need a migration of a table in every school.
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["session", "student_membership_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["student_membership_id", "session"], name="idcards_one_card_per_child_per_session"
            ),
        ]

    def __str__(self):
        return f"ID card of membership {self.student_membership_id}, {self.session}"


class IdCardPrint(models.Model):
    """One press of "Print ID cards": who asked, for what, and what was made.

    **This row is the print log, and it is kept.** The file it made is removed
    a day later (`files.service.sweep`), and this row stays, saying who printed
    which class's cards for which term and how many. It is `results.ClassCardPrint`'s
    twin and is read the same way; names are copied when it is written so the
    log still reads correctly after a class or a person is renamed.
    """

    class_group = models.ForeignKey(
        "academics.ClassGroup", related_name="id_card_prints", on_delete=models.PROTECT
    )
    term = models.ForeignKey("academics.Term", related_name="id_card_prints", on_delete=models.PROTECT)
    class_group_name = models.CharField(max_length=255)
    term_label = models.CharField(max_length=255)
    session = models.CharField(max_length=9)

    requested_by_id = models.PositiveBigIntegerField()
    requested_by_name = models.CharField(max_length=255)
    #: The roles they printed in, as they were then ("principal").
    requested_by_roles = models.CharField(max_length=100, blank=True, default="")

    #: The children asked for, by membership id; empty for the whole class.
    student_ids = models.JSONField(default=list, blank=True)
    #: How many cards are in the file. Null until it is made.
    card_count = models.PositiveIntegerField(null=True, blank=True)

    state = models.CharField(max_length=8, choices=PrintState, default=PrintState.PENDING)
    done = models.PositiveIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    #: The `files.StoredFile` key of the PDF, once made.
    file_key = models.CharField(max_length=32, blank=True, default="")
    #: What went wrong, for whoever debugs it. Not shown to the person.
    error = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    last_enqueued_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=~Q(state="ready") | (~Q(file_key="") & Q(card_count__isnull=False)),
                name="idcards_a_ready_print_has_its_file",
            ),
            models.CheckConstraint(
                condition=~Q(state="failed") | ~Q(error=""),
                name="idcards_a_failed_print_says_why",
            ),
        ]

    def __str__(self):
        return f"ID cards {self.class_group_name} {self.term_label} ({self.state})"


__all__ = ["IdCard", "IdCardPrint", "new_token"]
