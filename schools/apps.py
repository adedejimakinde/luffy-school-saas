from django.apps import AppConfig


class SchoolsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "schools"

    def ready(self):
        """Make the project's Celery app the current one, in every process.

        Without this, `@shared_task` in a web process binds to a default Celery
        app whose broker is `amqp://guest@localhost:5672//`, and `.delay()`
        returns happily having sent the job nowhere. `celery_app` explains that
        failure in full; this is the hook that prevents it.

        It lives on *this* app because `schools` is the platform itself — the
        tenant, its domains, its logging — and because it is the first entry in
        SHARED_APPS, so the binding is in place before any other app's `ready()`
        can reach for a task. There is no project package to put it in, which is
        where the Django documentation would otherwise have it.
        """
        import celery_app  # noqa: F401
