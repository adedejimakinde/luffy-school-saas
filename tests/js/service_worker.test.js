/**
 * The offline worker (`sync/worker.js`) run against a fake cache and a
 * fake network, at two schools' origins.
 *
 * `docs/offline.md` slice S5, D10. The script is evaluated as a browser would:
 * as a classic script in a scope that has `self`, `caches`, `fetch` and a
 * `CONFIG` in front of it, the way `sync.views.service_worker()` serves it.
 * Events are fired by hand and what the worker answers with is read back.
 *
 * Each origin gets its own caches, as a browser gives them: nothing one
 * school's worker keeps is visible to another's.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const SOURCE = readFileSync(new URL("../../sync/worker.js", import.meta.url), "utf8");

const SHELL = ["/static/web/html.aaa.js", "/static/marking/app.bbb.js", "/static/web/design.ccc.css"];
const config = (over = {}) => ({
  version: "v1",
  pages: ["/marking/", "/register/"],
  shell: SHELL,
  static: "/static/",
  hashed: true,
  ...over,
});

const response = (body, status = 200) => ({
  ok: status >= 200 && status < 300,
  status,
  body,
  clone() {
    return { ...this };
  },
});

/** One origin: its caches, its network, and a worker evaluated against them. */
function origin(host, cfg = config()) {
  const stores = new Map();
  const network = {
    online: true,
    // What the server answers, by path. A function for a changing answer.
    routes: new Map(),
    requests: [],
  };
  const cache = (name) => {
    if (!stores.has(name)) stores.set(name, new Map());
    const entries = stores.get(name);
    return {
      async addAll(urls) {
        for (const url of urls) {
          const answer = await doFetch(url);
          if (!answer.ok) throw new TypeError(`addAll: ${url} answered ${answer.status}`);
          entries.set(url, answer);
        }
      },
      async put(key, value) {
        entries.set(typeof key === "string" ? key : new URL(key.url).pathname, value);
      },
      async match(key) {
        return entries.get(typeof key === "string" ? key : new URL(key.url).pathname);
      },
    };
  };
  const caches = {
    open: async (name) => cache(name),
    keys: async () => [...stores.keys()],
    delete: async (name) => stores.delete(name),
    async match(key, { cacheName } = {}) {
      return cacheName ? cache(cacheName).match(key) : undefined;
    },
  };
  const doFetch = async (input) => {
    const path = typeof input === "string" ? input : new URL(input.url).pathname;
    network.requests.push(path);
    if (!network.online) throw new TypeError("Failed to fetch");
    const route = network.routes.get(path);
    if (route === undefined) return response("not found", 404);
    return typeof route === "function" ? route() : route;
  };

  const handlers = {};
  const waiting = [];
  const self = {
    location: { origin: `https://${host}` },
    addEventListener: (type, handler) => (handlers[type] = handler),
    clients: { claim: async () => {} },
    skipWaiting: async () => {},
  };
  vm.runInNewContext(`const CONFIG = ${JSON.stringify(cfg)};\n${SOURCE}`, {
    self,
    caches,
    fetch: doFetch,
    URL,
    console,
  });

  return {
    host,
    network,
    stores,
    async install() {
      await handlers.install({ waitUntil: (p) => waiting.push(p) });
      await Promise.all(waiting.splice(0));
    },
    async activate() {
      await handlers.activate({ waitUntil: (p) => waiting.push(p) });
      await Promise.all(waiting.splice(0));
    },
    /** What the worker answers a request with, or `undefined` if it lets it go. */
    async ask(path, { method = "GET", mode = "navigate", host: from = host } = {}) {
      let answered;
      handlers.fetch({
        request: { method, mode, url: `https://${from}${path}` },
        respondWith: (p) => (answered = p),
      });
      return answered === undefined ? undefined : answered;
    },
  };
}

const SCHOOLS = ["st-marys.example.ng", "grace.example.ng"];

function serving(site) {
  site.network.routes.set("/marking/", response(`marking page of ${site.host}`));
  site.network.routes.set("/register/", response(`register page of ${site.host}`));
  for (const url of SHELL) site.network.routes.set(url, response(`file ${url}`));
}

test("installing keeps the whole shell and both pages", async () => {
  for (const host of SCHOOLS) {
    const site = origin(host);
    serving(site);
    await site.install();

    assert.deepEqual([...site.stores.get("luffy-shell-v1").keys()], SHELL, host);
    assert.deepEqual([...site.stores.get("luffy-pages").keys()], ["/marking/", "/register/"], host);
  }
});

test("a worker that cannot fetch the whole shell does not install", async () => {
  for (const host of SCHOOLS) {
    const site = origin(host);
    serving(site);
    site.network.routes.delete(SHELL[1]);

    await assert.rejects(() => site.install(), /addAll/, host);
  }
});

test("offline, both pages open from the last good copy and the files from the shell", async () => {
  for (const host of SCHOOLS) {
    const site = origin(host);
    serving(site);
    await site.install();
    site.network.online = false;

    for (const path of ["/marking/", "/register/"]) {
      const answer = await (await site.ask(path));
      assert.equal(answer.body, `${path.slice(1, -1)} page of ${host}`, `${host} ${path}`);
    }
    for (const url of SHELL) {
      assert.equal((await site.ask(url, { mode: "no-cors" })).body, `file ${url}`, `${host} ${url}`);
    }
  }
});

test("online, a page comes from the network and replaces the copy", async () => {
  for (const host of SCHOOLS) {
    const site = origin(host);
    serving(site);
    await site.install();
    site.network.routes.set("/marking/", response("a newer marking page"));

    assert.equal((await site.ask("/marking/")).body, "a newer marking page", host);
    site.network.online = false;
    assert.equal((await site.ask("/marking/")).body, "a newer marking page", `${host}: and kept`);
  }
});

test("a server error serves the copy; a refusal is shown as it was and not kept", async () => {
  for (const host of SCHOOLS) {
    const site = origin(host);
    serving(site);
    await site.install();

    site.network.routes.set("/marking/", response("down", 503));
    assert.equal((await site.ask("/marking/")).body, `marking page of ${host}`, `${host}: 503`);

    site.network.routes.set("/marking/", response("not yours", 403));
    assert.equal((await site.ask("/marking/")).status, 403, `${host}: 403 shown`);
    site.network.online = false;
    assert.equal((await site.ask("/marking/")).body, `marking page of ${host}`, `${host}: 403 not kept`);
  }
});

test("nothing under /api/ is ever answered by the worker, online or off", async () => {
  for (const host of SCHOOLS) {
    const site = origin(host);
    serving(site);
    await site.install();

    for (const online of [true, false]) {
      site.network.online = online;
      for (const mode of ["cors", "same-origin", "navigate"]) {
        assert.equal(
          await site.ask("/api/gradebook/where/", { mode }),
          undefined,
          `${host} online=${online} ${mode}`,
        );
      }
    }
    assert.ok(![...site.stores.values()].some((entries) => [...entries.keys()].some((k) => k.includes("/api/"))), host);
  }
});

test("only GETs from its own origin are touched", async () => {
  for (const host of SCHOOLS) {
    const site = origin(host);
    serving(site);
    await site.install();

    assert.equal(await site.ask("/marking/", { method: "POST" }), undefined, `${host}: POST`);
    assert.equal(await site.ask("/marking/", { host: "elsewhere.example" }), undefined, `${host}: other origin`);
    assert.equal(await site.ask("/timetable/"), undefined, `${host}: another page`);
  }
});

test("activating deletes an old shell and keeps the pages", async () => {
  for (const host of SCHOOLS) {
    const site = origin(host);
    serving(site);
    site.stores.set("luffy-shell-old", new Map([["x", response("old")]]));
    site.stores.set("luffy-pages", new Map([["/marking/", response("kept")]]));
    site.stores.set("somebody-elses", new Map());
    await site.install();
    await site.activate();

    assert.deepEqual([...site.stores.keys()].sort(), ["luffy-pages", "luffy-shell-v1", "somebody-elses"], host);
  }
});

test("unhashed files (development) come from the network first, and the copy when it is gone", async () => {
  for (const host of SCHOOLS) {
    const site = origin(host, config({ hashed: false }));
    serving(site);
    await site.install();
    site.network.routes.set(SHELL[0], response("edited"));

    assert.equal((await site.ask(SHELL[0], { mode: "no-cors" })).body, "edited", host);
    site.network.online = false;
    assert.equal((await site.ask(SHELL[0], { mode: "no-cors" })).body, "edited", `${host}: the copy`);
  }
});
