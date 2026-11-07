/**
 * The exam page's service worker, at `/sit/sw.js` with scope `/sit/`. `docs/cbt.md`,
 * "Offline": "a small service worker keeps the /sit/ page itself, so a reload with no
 * network reopens the attempt from IndexedDB".
 *
 * Served by `cbt.sit_views.sit_worker()`, which puts one `CONFIG` in front of this file:
 * the page's path, the static files the page names (its import map's modules, its two
 * stylesheets and the fonts), and a version. The same bytes for every school and every
 * caller: it holds no student, no test and no answer.
 *
 * - **The page** (a navigation to `/sit/`): the network first, the kept copy when the
 *   network cannot be reached. The frame holds nobody's data, so keeping it is safe on a
 *   shared computer.
 * - **The page's static files**: the kept copy first, refreshed from the network.
 * - **A picture in the paper** (`/sit/pictures/`): kept once fetched, in its own cache,
 *   which the page deletes when the attempt is submitted.
 * - **Everything else, all of `/sit/api/` above all: not at all.** Answers live in the
 *   page's own outbox, never in a cache.
 *
 * Its scope is `/sit/`, so it controls no other page of the school's host, and it never
 * touches the root worker's caches (`luffy-shell-*`, `luffy-pages`).
 */

/* global CONFIG */

const SHELL = `sit-shell-${CONFIG.version}`;
const PICTURES = "sit-pictures";

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(SHELL);
      await cache.addAll(CONFIG.shell);
      try {
        const page = await fetch(CONFIG.page, { credentials: "same-origin" });
        if (page.ok) await cache.put(CONFIG.page, page);
      } catch {
        // Not reachable now: the first visit that can will keep it.
      }
      await self.skipWaiting();
    })(),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      for (const name of await caches.keys()) {
        if (name.startsWith("sit-shell-") && name !== SHELL) await caches.delete(name);
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
  if (request.mode === "navigate" && url.pathname === CONFIG.page) {
    event.respondWith(page(request));
  } else if (url.pathname.startsWith(CONFIG.pictures)) {
    event.respondWith(picture(request));
  } else if (CONFIG.shell.includes(url.pathname)) {
    event.respondWith(kept(request));
  }
});

async function page(request) {
  const cache = await caches.open(SHELL);
  try {
    const response = await fetch(request);
    if (response.ok) await cache.put(CONFIG.page, response.clone());
    return response;
  } catch {
    const copy = await cache.match(CONFIG.page);
    if (copy) return copy;
    throw new Error("offline, and the exam page was never kept");
  }
}

async function kept(request) {
  const cache = await caches.open(SHELL);
  const copy = await cache.match(request, { ignoreSearch: false });
  const fresh = fetch(request)
    .then((response) => {
      if (response.ok) cache.put(request, response.clone());
      return response;
    })
    .catch(() => null);
  return copy || (await fresh) || Response.error();
}

async function picture(request) {
  const cache = await caches.open(PICTURES);
  const copy = await cache.match(request);
  if (copy) return copy;
  const response = await fetch(request);
  if (response.ok) await cache.put(request, response.clone());
  return response;
}
