/**
 * The portal's worker (`sync/worker.js`, scope `/`) and the exam's (`cbt/sit_worker.js`,
 * scope `/sit/`) on one origin, as a browser holds them: one set of caches, one network, and
 * for each request the registration with the longest scope that contains it.
 *
 * `docs/pwa.md`. The exam keeps full control of `/sit/`: the portal's worker is never given a
 * `/sit/` request by the browser, answers none if it is, keeps nothing of it, deletes none of
 * its caches, and neither worker's activation or sign-out removes the other's. The same claims
 * in a real browser are `tests/ui/pwa.test.js`.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const PORTAL_SOURCE = readFileSync(new URL("../../sync/worker.js", import.meta.url), "utf8");
const SIT_SOURCE = readFileSync(new URL("../../cbt/sit_worker.js", import.meta.url), "utf8");

const ok = (body, status = 200, type = "basic") => ({
  ok: status >= 200 && status < 300,
  status,
  body,
  type,
  clone() {
    return { ...this };
  },
  async text() {
    return String(body);
  },
});

const PORTAL_CONFIG = {
  version: "p1",
  pages: ["/marking/", "/register/"],
  shell: ["/static/web/design.css", "/static/marking/app.js"],
  static: "/static/",
  hashed: true,
  leave: ["/sit/"],
  signOut: ["/sign-out/", "/api/logout/"],
  api: "/api/",
  prefix: "luffy-",
  offline: "/offline/",
  icons: ["/icon-192.png"],
};
const SIT_CONFIG = {
  version: "s1",
  page: "/sit/",
  shell: ["/static/sit/app.js", "/static/web/design.css", "/static/sit/sit.css"],
  pictures: "/sit/pictures/",
};

/** One origin: caches and a network every worker on it shares. */
function origin(host) {
  const stores = new Map();
  const network = { online: true, routes: new Map(), requests: [] };
  const cache = (name) => {
    if (!stores.has(name)) stores.set(name, new Map());
    const entries = stores.get(name);
    const key = (k) => (typeof k === "string" ? k : new URL(k.url).pathname);
    return {
      async addAll(urls) {
        for (const url of urls) entries.set(url, await doFetch(url));
      },
      async put(k, v) {
        entries.set(key(k), v);
      },
      async match(k) {
        return entries.get(key(k));
      },
    };
  };
  const caches = {
    open: async (name) => cache(name),
    keys: async () => [...stores.keys()],
    delete: async (name) => stores.delete(name),
    async match(k, { cacheName } = {}) {
      return cacheName ? cache(cacheName).match(k) : undefined;
    },
  };
  const doFetch = async (input) => {
    const path = typeof input === "string" ? input : new URL(input.url).pathname;
    network.requests.push(path);
    if (!network.online) throw new TypeError("Failed to fetch");
    const route = network.routes.get(path);
    return route === undefined ? ok("not found", 404) : route;
  };

  function worker(source, config) {
    const handlers = {};
    const waiting = [];
    const self = {
      location: { origin: `https://${host}` },
      addEventListener: (type, handler) => (handlers[type] = handler),
      clients: { claim: async () => {} },
      skipWaiting: async () => {},
    };
    vm.runInNewContext(`const CONFIG = ${JSON.stringify(config)};\n${source}`, { self, caches, fetch: doFetch, URL, console });
    const settle = async () => Promise.all(waiting.splice(0));
    return {
      async install() {
        await handlers.install({ waitUntil: (p) => waiting.push(p) });
        await settle();
      },
      async activate() {
        await handlers.activate({ waitUntil: (p) => waiting.push(p) });
        await settle();
      },
      async tell(data) {
        handlers.message({ data, waitUntil: (p) => waiting.push(p) });
        await settle();
      },
      /** What this worker answers with, or `undefined` if it lets the request go to the network. */
      ask(path, { method = "GET", mode = "navigate" } = {}) {
        let answered;
        handlers.fetch({ request: { method, mode, url: `https://${host}${path}` }, respondWith: (p) => (answered = p) });
        return answered;
      },
    };
  }

  const portal = worker(PORTAL_SOURCE, PORTAL_CONFIG);
  const sit = worker(SIT_SOURCE, SIT_CONFIG);
  const kept = () => Object.fromEntries([...stores].map(([name, entries]) => [name, [...entries.keys()]]));

  /** A browser: the worker whose scope is the longest to contain the path gets the request, else the network. */
  async function browse(path, options = {}) {
    const scoped = path === "/sit" || path.startsWith("/sit/") ? sit : portal;
    const answer = scoped.ask(path, options);
    if (answer !== undefined) return { by: scoped === sit ? "sit" : "portal", response: await answer };
    try {
      return { by: "network", response: await doFetch(`https://${host}${path}`) };
    } catch (error) {
      return { by: "network", error: error.message };
    }
  }

  const site = { host, network, stores, portal, sit, kept, browse };
  network.routes.set("/sit/", ok(`the exam frame at ${host}`));
  network.routes.set("/offline/", ok(`You're offline. Reconnect to continue. ${host}`));
  network.routes.set("/marking/", ok(`marking at ${host}`));
  network.routes.set("/register/", ok(`register at ${host}`));
  for (const url of [...PORTAL_CONFIG.shell, ...SIT_CONFIG.shell, "/icon-192.png"]) network.routes.set(url, ok(`file ${url}`));
  return site;
}

const SCHOOLS = ["st-marys.example.ng", "grace.example.ng"];

for (const order of [["portal", "sit"], ["sit", "portal"]]) {
  test(`installed ${order.join(" then ")}, each keeps its own caches and neither removes the other's`, async () => {
    for (const host of SCHOOLS) {
      const site = origin(host);
      for (const which of order) {
        await site[which].install();
        await site[which].activate();
      }
      const names = Object.keys(site.kept());
      assert.ok(names.includes("luffy-shell-p1") && names.includes("luffy-pages"), `${host}: ${names}`);
      assert.ok(names.includes("sit-shell-s1"), `${host}: ${names}`);
      assert.deepEqual(site.kept()["sit-shell-s1"].filter((k) => k !== "/sit/").sort(), [...SIT_CONFIG.shell].sort(), host);
      // Nothing of the exam is in the portal's caches and nothing of the portal's in the exam's.
      for (const [name, keys] of Object.entries(site.kept())) {
        if (name.startsWith("luffy-")) assert.ok(!keys.some((k) => k.startsWith("/sit/") || k.includes("/sit/")), `${host} ${name}`);
        if (name.startsWith("sit-")) assert.ok(!keys.some((k) => ["/marking/", "/register/", "/offline/"].includes(k)), `${host} ${name}`);
      }
    }
  });
}

test("a new version of either worker cleans up its own old shell and only its own", async () => {
  const site = origin(SCHOOLS[0]);
  await site.portal.install();
  await site.sit.install();
  site.stores.set("luffy-shell-old", new Map());
  site.stores.set("sit-shell-old", new Map());
  await site.portal.activate();
  assert.deepEqual(Object.keys(site.kept()).filter((n) => n.endsWith("old")), ["sit-shell-old"], "the portal's activation left the exam's old cache");
  site.stores.set("luffy-shell-old", new Map());
  await site.sit.activate();
  assert.deepEqual(Object.keys(site.kept()).filter((n) => n.endsWith("old")), ["luffy-shell-old"], "the exam's activation left the portal's old cache");
});

test("the browser gives /sit/ to the exam's worker and the portal to the portal's, online and off", async () => {
  for (const host of SCHOOLS) {
    const site = origin(host);
    await site.portal.install();
    await site.sit.install();

    for (const online of [true, false]) {
      site.network.online = online;
      const exam = await site.browse("/sit/");
      assert.equal(exam.by, "sit", `${host} online=${online}`);
      assert.equal(exam.response.body, `the exam frame at ${host}`);
      assert.equal((await site.browse("/marking/")).by, "portal");
      assert.equal((await site.browse("/fees/")).by, "portal", "any other page is the portal's, to show the offline page if need be");
    }
    assert.match((await site.browse("/fees/")).response.body, /You're offline\. Reconnect to continue\./);
  }
});

test("asked about /sit/ by mistake, the portal's worker answers nothing, fetches nothing and keeps nothing", async () => {
  for (const host of SCHOOLS) {
    const site = origin(host);
    await site.portal.install();
    await site.sit.install();
    const before = JSON.stringify(site.kept());
    const asked = site.network.requests.length;

    for (const online of [true, false]) {
      site.network.online = online;
      for (const path of ["/sit/", "/sit", "/sit/sw.js", "/sit/api/sync/", "/sit/api/attempt/", "/sit/api/submit/", "/sit/pictures/k/full.webp"]) {
        for (const [method, mode] of [["GET", "navigate"], ["GET", "same-origin"], ["POST", "same-origin"], ["POST", "cors"]]) {
          assert.equal(site.portal.ask(path, { method, mode }), undefined, `${host} ${method} ${mode} ${path}`);
        }
      }
    }
    assert.equal(JSON.stringify(site.kept()), before, host);
    assert.equal(site.network.requests.length, asked, host);
  }
});

test("the exam's saving offline is untouched: its API goes to the network, where a missing network is the page's to hold", async () => {
  for (const host of SCHOOLS) {
    const site = origin(host);
    await site.portal.install();
    await site.sit.install();
    site.network.online = false;

    for (const [method, path] of [["POST", "/sit/api/sync/"], ["GET", "/sit/api/attempt/"], ["POST", "/sit/api/submit/"]]) {
      const got = await site.browse(path, { method, mode: "same-origin" });
      assert.equal(got.by, "network", `${host} ${path}: no worker answers it`);
      assert.match(got.error, /Failed to fetch/, "so the page's outbox sees the failure and keeps the answer");
    }
    // And the frame still opens from the exam's own copy, with the portal's worker installed.
    assert.equal((await site.browse("/sit/")).response.body, `the exam frame at ${host}`);
  }
});

test("signing out empties the portal's caches and leaves the exam's frame and pictures", async () => {
  for (const host of SCHOOLS) {
    const site = origin(host);
    await site.portal.install();
    await site.sit.install();
    site.stores.set("sit-pictures", new Map([["/sit/pictures/k/full.webp", ok("picture")]]));
    site.network.routes.set("/sign-out/", ok("", 0, "opaqueredirect"));

    const out = await site.browse("/sign-out/", { method: "POST" });
    assert.equal(out.by, "portal");

    assert.deepEqual(Object.keys(site.kept()).sort(), ["sit-pictures", "sit-shell-s1"], host);
    site.network.online = false;
    assert.equal((await site.browse("/sit/")).response.body, `the exam frame at ${host}`, "the exam still opens");
  }
});

test("two schools: one school's caches never hold the other's pages", async () => {
  const [one, two] = SCHOOLS.map(origin);
  for (const site of [one, two]) {
    await site.portal.install();
    await site.sit.install();
  }
  for (const [site, other] of [[one, two], [two, one]]) {
    const held = JSON.stringify([...site.stores.values()].map((entries) => [...entries.values()].map((r) => r.body)));
    assert.ok(!held.includes(other.host), site.host);
  }
});
