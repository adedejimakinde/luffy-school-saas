#!/usr/bin/env bash
# Local only, never committed: serve the seeded dev database on two forwarded
# Codespaces ports — the portal on 8002, Sunrise Demo Academy on 8001.
S=/home/vscode/luffy-handover/demo
cd /workspace
export DJANGO_DEBUG=1 PYTHONPATH=$S DJANGO_SETTINGS_MODULE=demo_settings \
  PLATFORM_DOMAIN=app.github.dev \
  PORTAL_HOST="$CODESPACE_NAME-8002.$GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN" \
  EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
for port in 8002 8001; do
  setsid nohup python manage.py runserver --noreload "0.0.0.0:$port" \
    > "$S/port-$port.log" 2>&1 < /dev/null &
  echo "port $port pid $!"
done
