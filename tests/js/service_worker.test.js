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
  // What `sync.views.config()` adds for the installed app (`docs/pwa.md`).
  leave: ["/sit/"],
  signOut: ["/sign-out/", "/api/logout/"],
  api: "/api/",
  prefix: "luffy-",
  offline: "/offline/",
  icons: ["/icon-192.png"],
  ...over,
});

const response = (body, status = 200, type = "basic") => ({
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
    /** A message from a page. */
    async tell(data) {
      handlers.message({ data, waitUntil: (p) => waiting.push(p) });
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
    // Another page is passed on to the network and is never kept (see the portal tests).
    assert.equal((await site.ask("/timetable/")).body, "not found", `${host}: another page`);
    assert.ok(!site.stores.get("luffy-pages").has("/timetable/"), host);
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

// -- the installed app (`docs/pwa.md`) ------------------------------------------------

const OFFLINE_PAGE = (host) => `<main>You're offline. Reconnect to continue. ${host} <img src="/media/${host}/site.png"></main>`;

/** `serving()`, and what the installed app also keeps: the offline page, its crest, an icon. */
function installed(site) {
  serving(site);
  site.network.routes.set("/offline/", response(OFFLINE_PAGE(site.host)));
  site.network.routes.set(`/media/${site.host}/site.png`, response(`crest of ${site.host}`));
  site.network.routes.set("/icon-192.png", response("icon"));
}

/** Everything every cache holds, as `cache name -> [keys]`. */
const kept = (site) => Object.fromEntries([...site.stores].map(([name, entries]) => [name, [...entries.keys()]]));

test("installing also keeps the offline page, the crest it names and the icons, at each school", async () => {
  for (const host of SCHOOLS) {
    const site = origin(host);
    installed(site);
    await site.install();

    const shell = kept(site)["luffy-shell-v1"];
    for (const path of [...SHELL, "/offline/", "/icon-192.png", `/media/${host}/site.png`]) assert.ok(shell.includes(path), `${host} keeps ${path}`);
    // And nothing of the other school's: the crest it names is its own.
    const other = SCHOOLS.find((h) => h !== host);
    assert.ok(!shell.some((k) => k.includes(other)), `${host} holds nothing of ${other}`);
  }
});

test("a signed-in page or an API answer is never kept: the caches hold the shell and the two frames, nothing else", async () => {
  for (const host of SCHOOLS) {
    const site = origin(host);
    installed(site);
    for (const path of ["/home/", "/fees/", "/cards/1/2/", "/tests/", "/roll/", "/api/home/summary/", "/api/gradebook/sheet/", "/files/abc/card.pdf"]) {
      site.network.routes.set(path, response(`private ${path} of ${host}`));
    }
    await site.install();
    await site.activate();

    // A person uses the app: pages opened by navigation, data asked for by the pages.
    for (const path of ["/home/", "/fees/", "/cards/1/2/", "/tests/", "/roll/", "/marking/", "/register/"]) await site.ask(path);
    for (const path of ["/api/home/summary/", "/api/gradebook/sheet/", "/files/abc/card.pdf"]) {
      for (const mode of ["cors", "same-origin", "no-cors"]) await site.ask(path, { mode });
    }
    for (const url of SHELL) await site.ask(url, { mode: "no-cors" });

    const held = kept(site);
    const everything = Object.values(held).flat();
    for (const private_ of ["/home/", "/fees/", "/cards/", "/tests/", "/roll/", "/api/", "/files/"]) {
      assert.ok(!everything.some((k) => k.startsWith(private_)), `${host}: ${private_} is not kept`);
    }
    // The only pages kept at all are S5's two frames (`docs/offline.md` D10), in their own cache.
    assert.deepEqual(held["luffy-pages"], ["/marking/", "/register/"], host);
    const shell = held["luffy-shell-v1"];
    assert.ok(shell.every((k) => k.startsWith("/static/") || ["/offline/", "/icon-192.png"].includes(k) || k.startsWith("/media/")), `${host}: ${shell}`);
  }
});

test("a page that cannot be reached is the offline page, and the page itself is not kept", async () => {
  for (const host of SCHOOLS) {
    const site = origin(host);
    installed(site);
    site.network.routes.set("/fees/", response("the fees"));
    await site.install();

    assert.equal((await site.ask("/fees/")).body, "the fees", `${host}: online, the network's page`);
    site.network.online = false;
    const answer = await site.ask("/fees/");
    assert.match(answer.body, /You're offline\. Reconnect to continue\./, host);
    assert.match(answer.body, new RegExp(`/media/${host}/site.png`), `${host}: its own crest`);
    assert.ok(!Object.values(kept(site)).flat().includes("/fees/"), host);
  }
});

test("the exam is never answered, kept or touched: not a page, a file, a picture, an api call or its worker", async () => {
  for (const host of SCHOOLS) {
    const site = origin(host);
    installed(site);
    await site.install();
    await site.activate();
    const before = JSON.stringify(kept(site));
    const requests = site.network.requests.length;

    for (const online of [true, false]) {
      site.network.online = online;
      for (const path of ["/sit/", "/sit", "/sit/sw.js", "/sit/api/sync/", "/sit/api/attempt/", "/sit/pictures/abc/full.webp", "/sit/anything/"]) {
        for (const [method, mode] of [["GET", "navigate"], ["GET", "same-origin"], ["POST", "same-origin"], ["POST", "navigate"], ["PUT", "cors"]]) {
          assert.equal(await site.ask(path, { method, mode }), undefined, `${host} ${method} ${mode} ${path} online=${online}`);
        }
      }
    }
    assert.equal(JSON.stringify(kept(site)), before, `${host}: no cache changed`);
    assert.equal(site.network.requests.length, requests, `${host}: the worker asked the network for nothing`);
  }
});

test("a sign-out leaves the exam's caches and everyone else's alone, and deletes every cache of the portal", async () => {
  for (const host of SCHOOLS) {
    const site = origin(host);
    installed(site);
    await site.install();
    site.stores.set("luffy-shell-older", new Map([["x", response("older")]]));
    site.stores.set("sit-shell-abc", new Map([["/sit/", response("the exam page")]]));
    site.stores.set("sit-pictures", new Map([["/sit/pictures/k/full.webp", response("picture")]]));
    site.stores.set("somebody-elses", new Map([["y", response("theirs")]]));
    assert.ok(Object.keys(kept(site)).filter((n) => n.startsWith("luffy-")).length >= 3);

    // The menu's form: the server answers with a redirect, which a worker sees as opaque.
    site.network.routes.set("/sign-out/", response("", 0, "opaqueredirect"));
    await site.ask("/sign-out/", { method: "POST" });

    assert.deepEqual(Object.keys(kept(site)).sort(), ["sit-pictures", "sit-shell-abc", "somebody-elses"], host);
    assert.deepEqual(kept(site)["sit-shell-abc"], ["/sit/"], host);
  }
});

test("the API's sign-out clears too; a refused or unreachable one clears nothing", async () => {
  const site = origin(SCHOOLS[0]);
  installed(site);
  await site.install();
  const full = JSON.stringify(kept(site));

  site.network.routes.set("/sign-out/", response("csrf", 403));
  await site.ask("/sign-out/", { method: "POST" });
  site.network.routes.set("/api/logout/", response("{}", 500));
  await site.ask("/api/logout/", { method: "POST", mode: "cors" });
  assert.equal(JSON.stringify(kept(site)), full, "refused: kept");

  site.network.online = false;
  await assert.rejects(() => site.ask("/sign-out/", { method: "POST" }), /Failed to fetch/);
  assert.equal(JSON.stringify(kept(site)), full, "unreachable: kept");

  site.network.online = true;
  site.network.routes.set("/api/logout/", response("{}", 200));
  await site.ask("/api/logout/", { method: "POST", mode: "cors" });
  assert.deepEqual(kept(site), {}, "ended: empty");

  // Nobody signed in is a 401, and also leaves no session.
  await site.install();
  site.network.routes.set("/api/logout/", response("{}", 401));
  await site.ask("/api/logout/", { method: "POST", mode: "cors" });
  assert.deepEqual(kept(site), {}, "401: empty");
});

test("after a sign-out a page asks for the shell again, and only then is it fetched", async () => {
  const site = origin(SCHOOLS[0]);
  installed(site);
  await site.install();

  const fetched = site.network.requests.length;
  await site.tell({ type: "prime" });
  assert.equal(site.network.requests.length, fetched, "kept already: not fetched again");

  site.network.routes.set("/sign-out/", response("", 0, "opaqueredirect"));
  await site.ask("/sign-out/", { method: "POST" });
  assert.deepEqual(kept(site), {});

  await site.tell({ type: "anything else" });
  assert.deepEqual(kept(site), {}, "only the one message asks");
  await site.tell({ type: "prime" });
  for (const path of [...SHELL, "/offline/"]) assert.ok(Object.values(kept(site)).flat().includes(path), path);
  assert.ok(!Object.keys(kept(site)).includes("luffy-pages"), "the signed-in frames are not brought back");
});
