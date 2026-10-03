"""What the public site keeps: the demo requests a school leaves on it."""

from django.db import models
from django.utils import timezone


class DemoRequest(models.Model):
    """A school asking to be called about a demo.

    In the public schema, because the school is not on the platform yet: there
    is no schema of its own to put this in. Platform staff are emailed one when
    it is saved (`website.notify`), and the admin lists them, so an email that
    did not arrive loses nothing.

    `address` is the network address it came from, as
    `accounts.throttling.client_address()` reads it. It is what the hourly
    limit counts (`website.views`), and the one field a burst of junk requests
    is investigated from.
    """

    name = models.CharField(max_length=120)
    school = models.CharField(max_length=200)
    phone = models.CharField(max_length=32)
    email = models.EmailField(blank=True)
    students = models.PositiveIntegerField()
    address = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["address", "created_at"], name="demo_request_by_address")]

    def __str__(self):
        return f"{self.school} ({self.name})"
