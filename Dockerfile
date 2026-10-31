# The production image: what `deploy/compose.yml` runs as `web` and `worker`.
#
# Built by CI (`.github/workflows/tests.yml`, job `image`) after the suite has
# passed, tagged with the full commit SHA, and only ever deployed by that tag —
# so "the code that passed CI" and "the code that is running" are one claim.
# The devcontainer's image (`.devcontainer/Dockerfile`) is a development
# environment and is never deployed.

# Pinned to the exact patch release and to the digest of that tag's multi-arch
# index, so a rebuild cannot pick up a different interpreter or OS layer than the
# one that passed CI. Moving it is a deliberate edit: look up the new digest,
# change both together. `scripts/check_pins.py` (CI) refuses a floating tag.
FROM python:3.11.17-slim-bookworm@sha256:f06d01d4ba3f8ad5af45a3ec87df19c1d317d8e8961edc0fabda61811af6f7cf

# Links the package to this repository on GHCR, so a private repository's workflow
# token may push it and the repository's access rules apply to it.
LABEL org.opencontainers.image.source="https://github.com/adedejimakinde/luffy-school-saas"

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

# `requirements.txt` is the hashed lock generated from `requirements.in`;
# --require-hashes makes pip refuse any file whose hash is not in it.
COPY requirements.txt .
RUN pip install --require-hashes -r requirements.txt

COPY . .

# Collected at build time, into the image, so every container started from it
# serves the same hashed files. DEBUG is off here, so this writes the manifest
# `CompressedManifestStaticFilesStorage` refuses to serve without. The key is a
# build-time placeholder: collectstatic signs nothing, and settings.py refuses to
# import without one.
RUN DJANGO_SECRET_KEY=build-time-collectstatic-only python manage.py collectstatic --noinput

# restic, for the nightly backup of the uploaded files to B2
# (deploy/media-backup.sh, the `media-backup` service). Pinned by version *and*
# by the SHA-256 the release publishes beside it, as WAL-G is in the database
# image: a download that does not match stops the build. Fetched and unpacked
# with Python, which the image already has, so no curl or bzip2 is added.
ARG RESTIC_VERSION=0.18.1
ARG RESTIC_SHA256=680838f19d67151adba227e1570cdd8af12c19cf1735783ed1ba928bc41f363d
RUN python -c "import bz2, hashlib, sys, urllib.request; \
url = 'https://github.com/restic/restic/releases/download/v${RESTIC_VERSION}/restic_${RESTIC_VERSION}_linux_amd64.bz2'; \
data = urllib.request.urlopen(url, timeout=60).read(); \
got = hashlib.sha256(data).hexdigest(); \
sys.exit('restic checksum mismatch: ' + got) if got != '${RESTIC_SHA256}' else None; \
open('/usr/local/bin/restic', 'wb').write(bz2.decompress(data))" \
    && chmod 755 /usr/local/bin/restic \
    && restic version

# Not root. A home directory because fontconfig — under WeasyPrint — writes its
# cache there, and without one every render logs a warning and rebuilds it.
# restic keeps its index cache there too (the `media-backup-cache` volume).
RUN useradd --create-home --uid 10001 app && install -d -o app -g app /home/app/.cache
USER app

EXPOSE 8000
CMD ["gunicorn", "wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "60", "--access-logfile", "-"]
