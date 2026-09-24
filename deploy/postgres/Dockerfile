# Postgres 15 with WAL-G: the production database, and the throwaway one the
# weekly restore test recovers into.
#
# **Debian (bookworm), not Alpine, and CI and the devcontainer moved with it.**
# WAL-G publishes glibc builds only, and Postgres itself runs WAL-G (it is the
# `archive_command`), so they share a C library. Text sorts by the C library's
# collation, so the database the tests run against has to be the same one:
# `postgres:15-bookworm` everywhere.
#
# WAL-G is pinned by version *and* checksum (published beside the release):
# a backup tool is the last binary to take on trust from a moving target.
FROM postgres:15-bookworm

ARG WALG_VERSION=v3.0.9
ARG WALG_ASSET=wal-g-pg-22.04-amd64
ARG WALG_SHA256=d6795c663894d836ba20840bffe8970aed81bbe25d3151bd4951f6f9c362def9

# ca-certificates for HTTPS to B2; curl for the backup's heartbeat; python3
# for the retention planner; the rest are libraries WAL-G's Ubuntu build may
# link against.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl python3 libsodium23 liblzo2-2 libbrotli1 \
    && curl -fsSL -o /usr/local/bin/wal-g \
        "https://github.com/wal-g/wal-g/releases/download/${WALG_VERSION}/${WALG_ASSET}" \
    && echo "${WALG_SHA256}  /usr/local/bin/wal-g" | sha256sum -c - \
    && chmod 0755 /usr/local/bin/wal-g \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /usr/local/bin/classnode-postgres
COPY backup.sh /usr/local/bin/classnode-backup
COPY restore-serve.sh /usr/local/bin/classnode-restore-serve
COPY retention.py /usr/local/lib/classnode/retention.py
RUN chmod 0755 /usr/local/bin/classnode-*

ENTRYPOINT ["classnode-postgres"]
