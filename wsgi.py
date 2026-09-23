"""What gunicorn serves: `gunicorn wsgi:application`.

The project has no package directory — `settings.py`, `urls.py` and this file
sit at the top level beside `manage.py` — so the settings module is `settings`,
exactly as `manage.py` names it.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")

application = get_wsgi_application()
