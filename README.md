# luffy-school-saas
This Project is still being built.

**Before changing anything in `results`, read [docs/operating-rules.md](docs/operating-rules.md).**
It is the seven rules Phase 1 established, each with the mistake that taught it.

Per-area design notes live in [`docs/`](docs/).

The working history behind them: session records, control runs and review output; is kept out of this repository, in the private [`luffy-school-saas-history`](https://github.com/adedejimakinde/luffy-school-saas-history) repository (the link 404s without access).

## Run the demo in a Codespace

A Codespace forwards one port, so the demo runs on one host: one school's. Development only. `DEMO_SINGLE_HOST=1`
is refused unless `DJANGO_DEBUG=1` (the devcontainer sets it), and the server will not start with it in production.
In the Codespace terminal:

```bash
python manage.py migrate_schemas --shared
python manage.py seed_demo
export HOST="$CODESPACE_NAME-8000.$GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN"
python manage.py shell -c "from schools.models import Domain; Domain.objects.filter(domain='sunrise-demo.localhost').update(domain='$HOST')"
DEMO_SINGLE_HOST=1 python manage.py runserver 0.0.0.0:8000
```

Open `https://$HOST/staff-sign-in/` from the Ports tab. Sign in as `sunrise.teacher`, `sunrise.principal`,
`sunrise.bursar` or `sunrise.admin`; every password is `demo-pass-2026`. The host is Sunrise Demo Academy's, so
Harbour Demo College's logins do not open there. Run `seed_demo` once per database; reset the database to start again.
