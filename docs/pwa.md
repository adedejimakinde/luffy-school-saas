# The installed app (PWA), basic version

Status: **built.** Each school's host can be installed on a phone as an app in the school's
name, crest and colour. Basic version: the app shell is kept, the app opens, and a page that
cannot be reached says so. It adds no new offline work: marking and the register keep the
offline code of [`offline.md`](offline.md), and `/sit/` keeps the exam's own
([`cbt.md`](cbt.md), "Offline").

## What a person gets

| | |
| --- | --- |
| **Android (Chrome)** | The menu has **Install app** once Chrome says the app can be installed (`beforeinstallprompt`). Tapping it shows Chrome's own prompt. |
| **iPhone and iPad (Safari)** | The menu has **Install app** at once. Tapping it opens a line: "Tap Share, then Add to Home Screen." |
| **Already installed** | Neither is shown. |
| **No connection, a page not kept** | "You're offline. Reconnect to continue." under the school's crest and name, and a Try again link. |

## The manifest, per host

`/site.webmanifest` is a view (`schools/pwa.py`), not a file, so it is answered in the name
of the host it is asked on. It used to be `webroot/site.webmanifest`, served by WhiteNoise
above the tenant middleware, the same bytes at every host; that file is gone.

| host | answer |
| --- | --- |
| A school's | `name` the school's name, `short_name` that name cut to fit under an icon (12 letters: generic words such as School, College and Academy go first), `theme_color` the school's brand colour, `start_url` `/home/`, `scope` `/`, `display` `standalone`, `icons` its crest. |
| The portal (`app.<domain>`) | Classnode's, `start_url` `/staff-sign-in/`, standalone. |
| The public site (`<domain>`) | Classnode's as it always was, `display: browser`: not installable. |

- **The colour** is `schools.brand.colour_for()`'s: the school's primary only if it reads on
  white at 4.5:1, else the design's navy.
- **The icons** are two files the upload service makes from the crest, `icon-192.png` and
  `icon-512.png` (`files.images.app_icon`): the crest shrunk into 60% of a square and set on
  opaque white, so a phone can cut it to a circle or a squircle (**maskable**: the mark stays
  inside the middle 80%) and iOS does not paint transparency black. The manifest lists each file
  as `any` and as `maskable`. They are made when a crest is processed. **A crest uploaded
  before this existed** has none, and is given them from its master the first time a manifest
  asks (`files.service.ensure_icons`), once, with no backfill to run.
- **A school with no crest** keeps its own name and colour and Classnode's two icons
  (`/icon-192.png`, `/icon-512.png`); an initials tile as an icon is a follow-up.
- **Read for this request's school, from its schema, and kept nowhere** (`schools/brand.py`
  says why). A browser fetches the manifest with no cookie, so, like a door, it names only
  what the school's public website already names. `/site.webmanifest` and `/offline/` are in
  `schools.paths.DOORS` so that a login from another school never meets a 403 there.
- Tested at three hosts that cannot trade places (`schools/tests/test_pwa.py`: two with
  crests, one without) and in a browser against the two demo schools (`tests/ui/pwa.test.js`).

## The worker

There is **one** portal worker, `sync/worker.js` served at `/sw.js` with scope `/`: the
marking-and-register worker of [`offline.md`](offline.md) S5, extended. Two workers cannot
share a scope, and a second one at `/` would have replaced the first.

| request | answer |
| --- | --- |
| Anything under **`/sit/`** | **None.** The first thing the fetch handler does; no `respondWith`, no cache. See below. |
| `/marking/` and `/register/`, a navigation | As S5 had it: the network, the last good copy if it cannot be reached. |
| Any other navigation | The network. If it cannot be reached: the offline page. The page is never kept. |
| A file under `/static/` | Hashed names: the cache, then the network. Unhashed (development): the network, then the cache. |
| `/api/` | Never. (Except the sign-out below.) |
| A POST to `/sign-out/` or `/api/logout/` | Passed on; if the server ended the session, **every cache named `luffy-` is deleted.** |

**What it keeps** is the app shell: CSS, JavaScript and fonts under `/static/`, the icons at
the root of the host, the offline page and the crest that page names. It also keeps the two
frames S5 always kept (`/marking/`, `/register/`, in `luffy-pages`), because opening the
marking page with no connection is the reason S5 exists; that cache is deleted at sign-out
with the rest. **It never keeps** a student record, a mark, a fee, a report card, any other
signed-in page, or any API answer; the tests assert the cache contents (below).

**Sign-out is the worker's.** The menu's Sign out is a plain form on every page, and the
cards and the doors sign out through the API; both go through the worker, which deletes its
caches once the server has ended the session and not before. A refusal (a failed CSRF check)
or no connection deletes nothing. The marking and register pages still hold the form to
warn about unsent work first (`web/offline.js`); they clear the same caches, and then the
worker clears again. After sign-out the next page with the menu asks the worker, by message,
to keep its shell again (`web/portal-app.js`). Pages without the menu (the doors, the public
site) do not.

### `/sit/` keeps full control of `/sit/`

The exam has its own worker (`cbt/sit_worker.js`, `/sit/sw.js`, scope `/sit/`). The brief was
that the portal worker's scope must not include `/sit/`. **A worker's scope is a path prefix
and `/` cannot leave one out**, and the app's pages are at the top level of the host, so the
portal worker's scope is `/`. Instead, three things hold, each with a test:

1. **The browser gives `/sit/` to the longer scope.** A page under `/sit/` is controlled by
   the registration with the longest matching scope, which is `/sit/`. In a real browser with
   both installed, the exam page's controller is `/sit/sw.js` and the portal page's is `/sw.js`
   (`tests/ui/pwa.test.js`).
2. **The portal worker answers none of it, if given it.** The handler returns on `/sit/`
   before it reads the method, answers nothing, fetches nothing and caches nothing, for every
   method and mode, online and off (`tests/js/service_worker.test.js`, `tests/js/coexist.test.js`).
   `/sit/` is read from the exam route's own constant (`cbt.sit_views.PATH`), not written again.
3. **Neither can remove the other.** No script of either worker, nor `web/portal-app.js`,
   unregisters or lists a registration (`schools/tests/test_pwa.py` reads the source). Caches
   are deleted by name: the portal's `luffy-` and the exam's `sit-`, and neither deletes the
   other's, on activation or at sign-out.

**The exam's offline saving is unchanged**: its answers are in the page's IndexedDB outbox;
`/sit/api/` goes to the network, where a missing network is the page's to keep the answer
through. `tests/ui/pwa.test.js` installs the portal's worker, sits a test as a child, goes
offline, answers, reloads and reconnects, and checks both registrations, the caches of each
and that nothing of `/sit/` is in the portal's.

## The page script

`static/web/portal-app.js`, loaded by `templates/design/shell_close.html` on every page that
has the menu, and on no other (not the public website, not the doors, not the exam). It asks
for the worker, posts the message to keep the shell, and runs the Install app button. It
imports nothing, so it needs no place in a page's import map; `tests/test_pages.py` lists it as
a page of one module, as it does the school website's.

## The page budget

The script, the button's markup, its icon and its rules weigh about 2.4 KB on every page with
the menu, and four pages had under 2 KB of the 150 KB to spare. To fit them the long comment
blocks of the two shared modules every page loads, `web/http.js` and `web/html.js`, were cut
to what a maintainer needs (the same facts, in a third of the words). No page is over; the
tightest, `/tests/`, has about 500 bytes. A page that adds more will have to find its own.

## Not in the basic version

An icon for a school with no crest; push notifications; a splash screen; background sync;
offline pages beyond the two frames; the exam shell outside `/sit/`.
