from django.apps import AppConfig


class MessagingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "messaging"

    def ready(self):
        # A check that is only registered when something happens to import the
        # module is not a check — `accounts.apps` says the same.
        from . import checks  # noqa: F401
