"""The demo request form on the homepage."""

import re

from django import forms

from .models import DemoRequest

#: The honeypot's name. A person never sees the field (it is off screen and out
#: of the tab order); a script filling every input it finds fills this one too.
HONEYPOT = "website"

_PHONE = re.compile(r"^\+?[0-9][0-9 ()-]{5,22}[0-9]$")


class DemoRequestForm(forms.ModelForm):
    website = forms.CharField(required=False)

    class Meta:
        model = DemoRequest
        fields = ["name", "school", "phone", "email", "students"]

    def clean_phone(self):
        phone = self.cleaned_data["phone"].strip()
        if not _PHONE.match(phone):
            raise forms.ValidationError("phone")
        return phone

    def clean_students(self):
        students = self.cleaned_data["students"]
        if not 1 <= students <= 100_000:
            raise forms.ValidationError("students")
        return students

    def is_bait_taken(self):
        """Whether the honeypot was filled: a script, not a school."""
        return bool((self.data.get(HONEYPOT) or "").strip())
