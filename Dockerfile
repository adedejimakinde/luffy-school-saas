# The production image: what `deploy/compose.yml` runs as `web` and `worker`.
#
# Built by CI (`.github/workflows/tests.yml`, job `image`) after the suite has
# passed, tagged with the full commit SHA, and only ever deployed by that tag —
# so "the code that passed CI" and "the code that is running" are one claim.
# The devcontainer's image (`.devcontainer/Dockerfile`) is a development
# environment and is never deployed.

FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# The operating-system half of WeasyPrint — the same list as the devcontainer
# and CI, which say why, plus `libharfbuzz-subset0`: the slim image carries
# nothing it does not have to, so what a fuller base happened to bring along has
# to be named here. CI renders a page inside this image before pushing it, so a
# missing library fails the build rather than a parent's first download.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libharfbuzz-subset0 \
        libffi8 \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Collected at build time, into the image, so every container started from it
# serves the same hashed files. DEBUG is off here, so this writes the manifest
# `CompressedManifestStaticFilesStorage` refuses to serve without. The key is a
# build-time placeholder: collectstatic signs nothing, and settings.py refuses to
# import without one.
RUN DJANGO_SECRET_KEY=build-time-collectstatic-only python manage.py collectstatic --noinput

# Not root. A home directory because fontconfig — under WeasyPrint — writes its
# cache there, and without one every render logs a warning and rebuilds it.
RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000
CMD ["gunicorn", "wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "60", "--access-logfile", "-"]
