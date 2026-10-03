/**
 * The service worker: the marking and register pages, and everything they load,
 * kept so both open with no connection. `docs/offline.md` slice S5, D10.
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
 * - **A page** (`CONFIG.pages`, a navigation): the network first, so a deploy
 *   shows at once, and the last good copy when the network cannot be reached or
 *   the server errs. A page that refused the caller (401, 403, 404) is shown as
 *   it was refused and not kept.
 * - **A static file**: from the cache when the names are hashed (a hashed name
 *   never changes its bytes), the network first when they are not (development).
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

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      // All of it or none of it: a worker that installed with half a shell
      // would open the page and fail on its first import.
      await (await caches.open(SHELL)).addAll(CONFIG.shell);
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
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate" && CONFIG.pages.includes(url.pathname)) {
    event.respondWith(page(request, url.pathname));
  } else if (url.pathname.startsWith(CONFIG.static)) {
    event.respondWith(CONFIG.hashed ? kept(request) : fresh(request));
  }
});

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
  return fetch(request);
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
