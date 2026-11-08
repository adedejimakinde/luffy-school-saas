/**
 * The portal's service worker: the app shell of an installed school app, and the
 * marking and register pages, kept so both open with no connection.
 * `docs/offline.md` slice S5, D10; `docs/pwa.md`.
 *
 * Served as `/sw.js` by `sync.views.service_worker()`, which puts one `CONFIG`
 * in front of this file: the pages, the list of static files they load (as the
 * pages' own import maps name them, so the hashed URLs a deploy changes), and a
 * version. Nothing else is in it. The same bytes go to every school's host and
 * to a caller who is signed out; it holds no school, no person and no data, and
 * `sync/tests/test_service_worker.py` pins that.
 *
 * ## What it answers, and what it never touches
 *
 * - **The exam, never** (`CONFIG.leave`, `/sit/`). Its own worker, scoped to `/sit/`,
 *   has full control there. A worker's scope is a path prefix and `/` cannot leave one
 *   out, so this is said three ways: the browser hands a `/sit/` page to the longer
 *   scope, this fetch handler returns before it reads anything else (no `respondWith`,
 *   no cache), and no code here unregisters a worker or touches a cache whose name does
 *   not begin `luffy-`. That is the first thing the handler does and the first thing
 *   `tests/js/service_worker.test.js` and `tests/ui/pwa.test.js` hold.
 * - **Sign-out** (a POST to `CONFIG.signOut`): passed on, and when the server ended the
 *   session, every cache whose name begins `luffy-` is deleted. The page script then asks
 *   for the shell again when the next page with the menu opens.
 * - **A page** (`CONFIG.pages`, a navigation): the network first, so a deploy
 *   shows at once, and the last good copy when the network cannot be reached or
 *   the server errs. A page that refused the caller (401, 403, 404) is shown as
 *   it was refused and not kept. These two frames are the only pages ever kept
 *   (S5, D10) and sign-out deletes them.
 * - **Any other page** (a navigation): the network, always. If the network cannot be
 *   reached, the offline page (`CONFIG.offline`) instead of the browser's error. The
 *   page itself is never kept: it is a signed-in person's.
 * - **A static file**: from the cache when the names are hashed (a hashed name
 *   never changes its bytes), the network first when they are not (development).
 *   These, the app's icons and the offline page with the crest it names are the app
 *   shell, and the whole of what is kept besides the two frames.
 * - **Everything else, including all of `/api/`: not at all.** What the server
 *   said about a sheet or a register is kept by the page, under a person's name
 *   (`static/web/snapshots.js`). A worker cannot tell whose answer it is looking
 *   at, and a copy kept under nobody's name is a copy for anybody.
 *
 * The pages are kept in their own cache, `luffy-pages`, apart from the static
 * files: a rendered page holds the signed-in person's menu, so it is cleared at
 * sign-out (`static/web/offline.js`) and the static files, which hold nobody's,
 * are not.
 */

/* global CONFIG */

const SHELL = `luffy-shell-${CONFIG.version}`;
// The same name as `PAGES_CACHE` in `static/web/offline.js`.
const PAGES = "luffy-pages";

/** Whether `path` is one this worker must never answer or keep: the exam's. */
const leaves = (path) => CONFIG.leave.some((prefix) => path === prefix.replace(/\/$/, "") || path.startsWith(prefix));

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      // All of it or none of it: a worker that installed with half a shell
      // would open the page and fail on its first import.
      await (await caches.open(SHELL)).addAll(CONFIG.shell);
      await keepOffline();
      const pages = await caches.open(PAGES);
      await Promise.all(
        CONFIG.pages.map(async (path) => {
          try {
            const response = await fetch(path, { credentials: "same-origin" });
            if (response.ok) await pages.put(path, response);
          } catch {
            // Not reachable now. The first visit that can will keep it.
          }
        }),
      );
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      for (const name of await caches.keys()) {
        if (name.startsWith("luffy-shell-") && name !== SHELL) await caches.delete(name);
      }
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  // First, before the method and before everything: the exam is not ours.
  if (leaves(url.pathname)) return;
  // The API is the page's to ask, never the worker's (see the top of this file).
  if (url.pathname.startsWith(CONFIG.api) && !CONFIG.signOut.includes(url.pathname)) return;
  if (request.method === "POST" && CONFIG.signOut.includes(url.pathname)) {
    event.respondWith(signedOut(request));
    return;
  }
  if (request.method !== "GET") return;

  if (request.mode === "navigate" && CONFIG.pages.includes(url.pathname)) {
    event.respondWith(page(request, url.pathname));
  } else if (request.mode === "navigate") {
    event.respondWith(reachable(request));
  } else if (url.pathname.startsWith(CONFIG.static)) {
    event.respondWith(CONFIG.hashed ? kept(request) : fresh(request));
  }
});

// A page asks for the shell again after sign-out emptied it. Only when the offline
// page is gone, so a page that asks on every load costs a lookup and nothing more.
self.addEventListener("message", (event) => {
  if (!event.data || event.data.type !== "prime") return;
  event.waitUntil(
    (async () => {
      if (await caches.match(CONFIG.offline, { cacheName: SHELL })) return;
      try {
        await (await caches.open(SHELL)).addAll(CONFIG.shell);
      } catch {
        // Not reachable now. The next page that asks will try again.
      }
      await keepOffline();
    })(),
  );
});

/**
 * Sign-out: pass it on, and once the server has ended the session, delete everything this
 * worker keeps. Here and not in the page, so every way of signing out is covered (the
 * menu's form on any page, the API's button on the cards and the doors) and no page needs
 * a script for it. A refusal (a failed CSRF check) or no connection ends nothing, so
 * nothing is deleted.
 */
async function signedOut(request) {
  const response = await fetch(request);
  // The menu's form is answered with a redirect (opaque to a worker); the API with 200,
  // or 401 when nobody was signed in. All three leave no session.
  if (response.type === "opaqueredirect" || response.ok || response.status === 401) await forget();
  return response;
}

/** Delete every cache of the portal's worker. The exam's (`sit-`) are not named `luffy-`. */
async function forget() {
  for (const name of await caches.keys()) {
    if (name.startsWith(CONFIG.prefix)) await caches.delete(name);
  }
}

/** The offline page, the crest it names, and the icons: what draws "You're offline". */
async function keepOffline() {
  const cache = await caches.open(SHELL);
  const once = async (path) => {
    try {
      const response = await fetch(path);
      if (response.ok) await cache.put(path, response.clone());
      return response;
    } catch {
      // Not reachable now. The first visit that can will keep it.
      return null;
    }
  };
  const page = await once(CONFIG.offline);
  // The pictures the page draws with and nothing else: its own crest, on this host.
  const crests = page ? [...(await page.text()).matchAll(/\bsrc="(\/media\/[^"]+)"/g)].map((m) => m[1]) : [];
  await Promise.all([...CONFIG.icons, ...crests].map(once));
}

/** A page that is not kept: the network, and the offline page if it cannot be reached. */
async function reachable(request) {
  try {
    return await fetch(request);
  } catch (error) {
    const offline = await caches.match(CONFIG.offline, { cacheName: SHELL });
    if (offline) return offline;
    throw error;
  }
}

async function page(request, path) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      await (await caches.open(PAGES)).put(path, response.clone());
      return response;
    }
    if (response.status < 500) return response;
  } catch {
    // Offline: the copy below.
  }
  const copy = await caches.match(path, { cacheName: PAGES, ignoreSearch: true, ignoreVary: true });
  if (copy) return copy;
  return reachable(request);
}

async function kept(request) {
  const hit = await caches.match(request, { cacheName: SHELL, ignoreVary: true });
  if (hit) return hit;
  const response = await fetch(request);
  if (response.ok) await (await caches.open(SHELL)).put(request, response.clone());
  return response;
}

async function fresh(request) {
  try {
    const response = await fetch(request);
    if (response.ok) await (await caches.open(SHELL)).put(request, response.clone());
    return response;
  } catch (error) {
    const hit = await caches.match(request, { cacheName: SHELL, ignoreVary: true });
    if (hit) return hit;
    throw error;
  }
}
