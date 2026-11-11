"""The jobs `accounts` hands the worker, named where the worker looks for them.

`celery_app` imports each app's `tasks` module and nothing else, and a task is
registered when its module is imported. The two emails "Forgot password" sends
are written beside the rules they belong to (`accounts.password_reset`), so
this imports them: without it the worker would know them only if something
else happened to import that module first, and a job the worker has no name
for is dropped.
"""

from .password_reset import send_password_changed, send_reset_link

__all__ = ["send_password_changed", "send_reset_link"]
