# The public site: classnode.co

Classnode's own homepage, for a school that is not a customer yet. It lives on
the bare platform domain (`SITE_HOST`, which is `PLATFORM_DOMAIN` unless set),
and `www.` is the same site (django-tenants drops `www.` before it looks a host
up). The legal pages join it in their own change.

## Where it answers, and where it does not

- **Not a `Domain` row and not a school.** A row for the bare domain would make
  it the portal, with the admin and both sign-in doors on it.
  `schools.middleware.PlatformTenantMiddleware` (django-tenants' own middleware,
  plus this one host) sends it to `urls_site.py`, which routes the homepage and
  nothing else. Every other host is resolved exactly as before, and an unknown
  one is still a 404.
- **The doors stay on the portal.** "Staff sign in" and "Parent sign in" link to
  `//app.<domain>/staff-sign-in/` and `/sign-in/` (`schools.hosts.portal_host()`).
- `/healthz/` answers here as on every host: it is answered before any of this.
- **Deploying it needs nothing new.** The apex A record and the certificate
  already cover the bare domain (`docs/demo-server.md`); `migrate_schemas` adds
  the one table.

## The demo request form

`website.DemoRequest`, in the public schema (the school has no schema yet).
A plain form post, CSRF-checked, that works with no script.

- **Saved first, then emailed** to every active platform staff login with an
  email address (`website/notify.py`), after the row commits. A send that fails
  is logged and the row stays: the admin (on the portal) lists every request,
  read only.
- **Honeypot**: a field named `website`, off screen and out of the tab order. A
  post that fills it is answered exactly like a real one and nothing is saved
  or sent.
- **Rate limit**: `DEMO_REQUESTS_PER_HOUR` (5) per network address, counted
  from the saved rows, so it holds across worker processes. The address is
  `accounts.throttling.client_address()`'s. Over the limit is a 429.
- The two refusals (a field missing or wrong, too many requests) show a visible
  **TODO** for their wording: no copy was given for them, so none was written.

## The page

- **The words are the copy as given, word for word**, and every fact still to
  be decided (the price, the setup fee, the call-back time, the city) is a
  visible `TODO`. `website/tests/test_homepage.py` holds the page to that copy
  and to the writing rules: no en or em dash, no exclamation or question mark,
  no sentence starting "Imagine", none of the banned words.
- **One Blue** (`docs/design.md`): the tokens from `design.css`, Hanken
  Grotesk, no gradient. The one dark band is the fees section, on the ink. It
  is the one thing that runs edge to edge; everything else stops at 1200px.
- **Screenshots** are real screens from the demo, as WebP with their sizes set.
  `scripts/site_shots.mjs` takes them (the screens job's demo, signed in the
  same way) and `scripts/site_shots.py` cuts them to size into
  `static/website/shots/`. Their `alt` is empty: the words beside each say what
  it shows. The fees shot needs a bank and a child's account at Sunrise, which
  `seed_demo` does not make; add them in `manage.py shell` first:

  ```python
  from django_tenants.utils import schema_context
  from accounts.models import Membership
  from fees.models import SchoolBank, VirtualAccount
  from schools.models import School
  school = School.objects.get(slug="sunrise-demo")
  with schema_context(school.schema_name):
      SchoolBank.objects.create(bank_code="035", bank_name="Wema Bank", account_number="0123456789",
          account_name=school.name, subaccount_code="ACCT_demo", split_code="SPL_demo",
          connected_by_id=1, connected_by_name="Demo")
      ada = Membership.objects.get(school=school, role="student", user__full_name="Ada Adeyemi")
      VirtualAccount.objects.create(student_membership_id=ada.pk, customer_code="CUS_demo",
          account_number="8123456008", account_name=f"{school.name} / Ada Adeyemi",
          bank_name="Wema Bank", split_code="SPL_demo", created_by_id=1, created_by_name="Demo")
  school.contact_email = "office@sunrise-demo.example"  # hides the home page's reminder
  school.save(update_fields=["contact_email"])
  ```
- **Drawings** are inline SVG built from the mark's shapes (rounded square,
  nodes, lines), styled from the tokens, under 15 KB together: the logo, which
  draws itself once on load (nodes, then lines, 1 second); the results and fees
  flows, which play once when scrolled into view (the fees one runs top to
  bottom on a phone); and the still pattern behind the hero, at 2.5%, a contrast
  of about 1.04:1.
- **Motion** is the slides (every 6 seconds, a 400ms crossfade, held on hover,
  focus or a touch), the fade-up of each section, and the drawings. All of it
  plays once, and all of it is off under `prefers-reduced-motion`: then the
  slides change only from their dots, with no fade, and everything is drawn
  finished. Without the script the page reads in full, on its first slide.
- **Weight**: under 400 KB with every image counted, lazy ones too (about
  250 KB today, the drawings about 3 KB). One module, `static/website/site.js`, no imports, nothing from
  another host.

## What holds it

- `website/tests/test_homepage.py`: the hosts, the copy and the writing rules,
  the form, the 400 KB and 15 KB budgets, that no motion sits outside
  `no-preference` and nothing loops, and the pattern's contrast, worked out
  from the stylesheet.
- `tests/ui/screens.test.js`: the homepage at 320, 360, 414, 768, 1024, 1280
  and 1920, photographed finished, and held to the layout above; and its motion
  (`the homepage's motion`) on a fake clock: the 6 seconds, the 400ms fade, the
  three holds, nothing moving under reduced motion, every animation once.
