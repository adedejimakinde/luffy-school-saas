"""What gunicorn serves: `gunicorn wsgi:application`.

The project has no package directory — `settings.py`, `urls.py` and this file
sit at the top level beside `manage.py` — so the settings module is `settings`,
exactly as `manage.py` names it.
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")

application = get_wsgi_application()

# A server that holds a demo school and is neither a development machine nor the
# demo server does not start. After `get_wsgi_application()`, which is what
# sets Django up, so the models can be read. `schools/demo_slugs.py` says why
# this and the creation guard are two locks and not one.
from schools.demo_slugs import refuse_if_demo_schools_exist  # noqa: E402

refuse_if_demo_schools_exist()
