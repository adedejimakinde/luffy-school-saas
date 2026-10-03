from django.contrib import admin

from .models import DemoRequest


@admin.register(DemoRequest)
class DemoRequestAdmin(admin.ModelAdmin):
    """Read only: a request is what a school typed, and nobody edits that."""

    list_display = ("created_at", "school", "name", "phone", "email", "students")
    search_fields = ("school", "name", "phone", "email")
    readonly_fields = [f.name for f in DemoRequest._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
