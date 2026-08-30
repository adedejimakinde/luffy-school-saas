FROM mcr.microsoft.com/vscode/devcontainers/python:3.11

ENV PYTHONUNBUFFERED 1

# PostgreSQL client, and the operating-system half of WeasyPrint.
#
# WeasyPrint installs from a wheel with none of these present and imports only
# once they are: the text layout is Pango's, not Python's. The list is the one
# WeasyPrint's own Debian instructions give, plus fonts — a container with Pango
# and no font family renders a page of boxes rather than failing, which is the
# worse of the two outcomes because the PDF still arrives.
#
# Today's base image already carries all of them. That is an accident of which
# image this is, not a promise it makes, and a report card that stops rendering
# because the upstream image slimmed down is not a failure anybody would think
# to look for here.
RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends \
        postgresql-client \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libffi8 \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
