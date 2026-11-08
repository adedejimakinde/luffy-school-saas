/**
 * The installed app in a real browser (`docs/pwa.md`): each host's manifest, the portal's
 * service worker beside the exam's, the offline page, the install button on Android and on an
 * iPhone, and sign-out emptying what the portal's worker kept.
 *
 * Against the same demo as `screens.test.js` (see its header), as Sunrise's principal and
 * Harbour's, and as **UI PWA**'s child (`manage.py seed_ui`): two children, a test of their own
 * and fixed exam PINs, because the other files' children are sat as in parallel. A service
 * worker needs a secure context and `*.classnode.test` over plain HTTP is not one, so the
 * browser is told to treat the two school origins as secure; production is HTTPS.
 */

import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { after, before, describe, test } from "./timed.js";

import { chromium } from "playwright";

const DOMAIN = process.env.SCREENS_DOMAIN || "classnode.test";
const PORT = process.env.SCREENS_PORT || "8000";
const PASSWORD = process.env.SCREENS_PASSWORD || "demo-pass-2026";
const OUT = process.env.SCREENS_OUT || "screens";
const PORTAL = `http://app.${DOMAIN}:${PORT}`;
const SUNRISE = `http://sunrise-demo.${DOMAIN}:${PORT}`;
const HARBOUR = `http://harbour-demo.${DOMAIN}:${PORT}`;

/** `seed_ui`'s class for this file, the test code, and each child's number and PIN. */
const OWN_CLASS = "UI PWA";
const CODE = "UIPWAQ";
const child = (n) => ({ number: `SUN/UI-PWA-0${n}`, pin: `2026000${n}` });

const IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1";

// Playwright 1.56 (the version CI pins) takes `context.setOffline()` to the page and not to a
// service worker's own `fetch`: the worker reached the school, got a live page, and Chromium
// refused to show it ("This page is not working") instead of the worker answering with the
// offline page. With this on, the worker's requests go through the context's routes, so
// `offline()` below cuts them as well. Read when a worker starts, so it is set before any does.
process.env.PW_EXPERIMENTAL_SERVICE_WORKER_NETWORK_EVENTS = "1";

let browser;

before(async () => {
  browser = await chromium.launch({
    // Full Chromium, as `offline.test.js` says why: the headless shell ignores the flag below.
    channel: "chromium",
    args: [
      `--host-resolver-rules=MAP *.${DOMAIN} 127.0.0.1, MAP ${DOMAIN} 127.0.0.1`,
      `--unsafely-treat-insecure-origin-as-secure=${SUNRISE},${HARBOUR}`,
    ],
  });
});

after(async () => {
  await browser?.close();
});

/** A context signed in as `identifier` (the API's own login, as `offline.test.js` does). */
async function signedIn(identifier, options = {}) {
  const context = await browser.newContext({ serviceWorkers: "allow", ...options });
  const door = await context.newPage();
  await door.goto(`${PORTAL}/staff-sign-in/`);
  const status = await door.evaluate(
    async ({ identifier, password }) => {
      const { csrf_token: token } = await (await fetch("/api/csrf/")).json();
      const response = await fetch("/api/login/", {
        method: "POST",
        headers: { "content-type": "application/json", "X-CSRFToken": token },
        body: JSON.stringify({ identifier, password }),
      });
      return response.status;
    },
    { identifier, password: PASSWORD },
  );
  assert.equal(status, 200, `signing in as ${identifier}`);
  await door.close();
  return context;
}

/** Wait for this origin's `/` worker to be in charge of the page, reloading once if need be. */
async function controlled(page) {
  await page.evaluate(() => navigator.serviceWorker.ready);
  if (!(await page.evaluate(() => Boolean(navigator.serviceWorker.controller)))) await page.reload();
  await page.waitForFunction(() => Boolean(navigator.serviceWorker.controller));
}

const cutOff = (route) => route.abort("internetdisconnected");

/** Take the whole context off the network, the portal's worker with the pages, or put it back. */
async function offline(context, off) {
  await context.setOffline(off);
  if (off) await context.route("**/*", cutOff);
  else await context.unroute("**/*", cutOff);
}

/** Every registration the page's origin holds, and the cache each name holds as pathnames. */
const inventory = (page) =>
  page.evaluate(async () => {
    const registrations = (await navigator.serviceWorker.getRegistrations()).map((r) => ({
      scope: new URL(r.scope).pathname,
      script: r.active && new URL(r.active.scriptURL).pathname,
    }));
    const held = {};
    for (const name of await caches.keys()) {
      held[name] = (await (await caches.open(name)).keys()).map((r) => new URL(r.url).pathname);
    }
    return { registrations: registrations.sort((a, b) => a.scope.localeCompare(b.scope)), held, controller: navigator.serviceWorker.controller && new URL(navigator.serviceWorker.controller.scriptURL).pathname };
  });

const portalCaches = (held) => Object.keys(held).filter((n) => n.startsWith("luffy-"));
const examCaches = (held) => Object.keys(held).filter((n) => n.startsWith("sit-"));

/** Through the exam door and the "Is this you?" screen, to the first question. */
async function sitDown(page, n) {
  const { number, pin } = child(n);
  await page.goto(`${SUNRISE}/sit/`);
  await page.waitForSelector('[data-state="door"]');
  await page.fill("#code", CODE);
  await page.fill("#number", number);
  await page.fill("#pin", pin);
  await page.click('button[type="submit"]');
  await page.waitForSelector('[data-state="confirm"]');
  assert.match(await page.textContent(".sit-who"), new RegExp(OWN_CLASS));
  await page.click('[data-action="start"]');
  await page.waitForSelector('[data-state="exam"]');
}

describe("each school's manifest is its own", () => {
  test("the host's name, short name, colour and icons; nothing of the other school", async () => {
    const context = await browser.newContext();
    try {
      const fetched = {};
      for (const [host, name] of [[SUNRISE, "Sunrise Demo Academy"], [HARBOUR, "Harbour Demo College"], [PORTAL, "Classnode"]]) {
        // From a page on the host, as the browser asks: the same origin, no say in who is signed in.
        const page = await context.newPage();
        await page.goto(`${host}/${host === PORTAL ? "staff-sign-in/" : "sign-in/"}`);
        const got = await page.evaluate(async () => {
          const response = await fetch(document.querySelector('link[rel="manifest"]').href);
          const manifest = await response.json();
          const icons = [];
          for (const icon of manifest.icons) {
            const r = await fetch(icon.src);
            icons.push([icon.src, r.status, r.headers.get("content-type")]);
          }
          return { status: response.status, type: response.headers.get("content-type"), manifest, icons };
        });
        await page.close();
        const { manifest } = got;
        fetched[host] = JSON.stringify(manifest);
        assert.equal(got.status, 200, host);
        assert.match(got.type, /^application\/manifest\+json/);
        assert.equal(manifest.name, name, host);
        assert.ok(manifest.short_name && manifest.short_name.length <= 12, `${host}: ${manifest.short_name}`);
        assert.equal(manifest.display, "standalone");
        assert.match(manifest.theme_color, /^#[0-9A-F]{6}$/);
        assert.equal(manifest.start_url, host === PORTAL ? "/staff-sign-in/" : "/home/");
        const sizes = manifest.icons.map((i) => i.sizes);
        assert.ok(sizes.includes("192x192") && sizes.includes("512x512"), `${host}: ${sizes}`);
        for (const [src, status, type] of got.icons) {
          assert.equal(status, 200, `${host}${src}`);
          assert.match(type, /^image\/png/);
        }
      }
      for (const [host, others] of [[SUNRISE, ["Harbour"]], [HARBOUR, ["Sunrise"]], [PORTAL, ["Sunrise", "Harbour"]]]) {
        for (const other of others) assert.ok(!fetched[host].includes(other), `${host}'s manifest names nothing of ${other}`);
      }
    } finally {
      await context.close();
    }
  });

  test("the page links its own host's manifest, and Chrome finds the app installable", async () => {
    const context = await signedIn("sunrise.principal");
    try {
      const page = await context.newPage();
      await page.goto(`${SUNRISE}/home/`);
      await controlled(page);
      const link = await page.evaluate(() => document.querySelector('link[rel="manifest"]').href);
      assert.equal(link, `${SUNRISE}/site.webmanifest`);
      const cdp = await context.newCDPSession(page);
      const { url, errors, data } = await cdp.send("Page.getAppManifest");
      assert.equal(url, link);
      assert.deepEqual(errors, [], "the manifest parses cleanly");
      assert.equal(JSON.parse(data).name, "Sunrise Demo Academy");
      const { installabilityErrors } = await cdp.send("Page.getInstallabilityErrors");
      // A test browser is always incognito, which Chrome will not install from: the one error allowed.
      assert.deepEqual(installabilityErrors.map((e) => e.errorId).filter((id) => id !== "in-incognito"), [], "nothing else stops Chrome offering to install it");
    } finally {
      await context.close();
    }
  });
});

describe("the portal's worker and the exam's", () => {
  test("both are installed side by side, neither takes the other's pages, and exam answers save offline", async () => {
    const context = await signedIn("sunrise.principal", { viewport: { width: 390, height: 800 } });
    const page = await context.newPage();
    try {
      // The portal's worker first, from a page with the menu.
      await page.goto(`${SUNRISE}/home/`);
      await controlled(page);
      let seen = await inventory(page);
      assert.deepEqual(seen.registrations, [{ scope: "/", script: "/sw.js" }]);
      assert.equal(seen.controller, "/sw.js");

      // Then the exam, as a child. The exam's worker is registered and takes over `/sit/` alone.
      await sitDown(page, 1);
      await controlled(page);
      seen = await inventory(page);
      assert.deepEqual(
        seen.registrations,
        [{ scope: "/", script: "/sw.js" }, { scope: "/sit/", script: "/sit/sw.js" }],
        "both registrations are there: neither unregistered the other",
      );
      assert.equal(seen.controller, "/sit/sw.js", "the exam page is the exam's worker's");
      assert.ok(portalCaches(seen.held).length > 0 && examCaches(seen.held).length > 0);
      for (const name of portalCaches(seen.held)) {
        assert.ok(!seen.held[name].some((p) => p.startsWith("/sit")), `${name} holds nothing of the exam: ${seen.held[name]}`);
      }
      for (const name of examCaches(seen.held)) {
        assert.ok(seen.held[name].every((p) => p.startsWith("/sit/") || p.startsWith("/static/")), `${name}: ${seen.held[name]}`);
        assert.ok(!seen.held[name].some((p) => p.includes("/api/")), "no answer from the school is cached");
      }

      // Offline saving with both installed.
      await offline(context, true);
      await page.evaluate(() => window.dispatchEvent(new Event("offline")));
      await page.click('.sit-option[data-key="A"]');
      await page.click('.sit-bar [data-action="next"]');
      await page.click('.sit-option[data-key="D"]');
      await page.waitForSelector(".sit-banner-offline");
      assert.match(await page.textContent(".sit-banner-offline"), /You're offline\. Your answers are saved on this device and will send when you reconnect\./);
      await page.reload();
      await page.waitForSelector('[data-state="exam"]');
      assert.match(await page.textContent(".sit-count"), /Question 2 of 10/i);
      assert.equal(await page.getAttribute(".sit-option.chosen", "data-key"), "D");
      assert.equal(await page.evaluate(() => document.body.textContent.includes("Reconnect to continue")), false, "the portal's offline page never stands in for the exam");
      assert.equal((await inventory(page)).controller, "/sit/sw.js");

      await offline(context, false);
      await page.evaluate(() => window.dispatchEvent(new Event("online")));
      await page.waitForFunction(() => !document.querySelector(".sit-banner-offline"));
      await page.waitForTimeout(1500);
      const held = await page.evaluate(async () => (await (await fetch("/sit/api/attempt/")).json()).answers);
      assert.equal(Object.values(held).filter((v) => v !== null).length, 2, "both answers reached the school");

      // The portal's page again: its worker updates and neither registration has gone.
      await page.goto(`${SUNRISE}/home/`);
      await controlled(page);
      seen = await inventory(page);
      assert.deepEqual(seen.registrations.map((r) => r.scope), ["/", "/sit/"]);
      assert.equal(seen.controller, "/sw.js", "back on the portal it is the portal's worker");
      for (const name of portalCaches(seen.held)) {
        assert.ok(!seen.held[name].some((p) => p.startsWith("/sit")), `${name}: ${seen.held[name]}`);
      }
    } finally {
      await context.close();
    }
  });

  test("a sign-out empties the portal's caches and leaves the exam's frame and both registrations", async () => {
    const context = await signedIn("sunrise.principal");
    const page = await context.newPage();
    try {
      await page.goto(`${SUNRISE}/home/`);
      await controlled(page);
      // The exam's worker too, from the door (no one sits).
      await page.goto(`${SUNRISE}/sit/`);
      await page.waitForSelector('[data-state="door"]');
      await controlled(page);
      await page.goto(`${SUNRISE}/home/`);
      await page.waitForSelector("#sign-out");
      await controlled(page);
      const before = await inventory(page);
      assert.ok(portalCaches(before.held).length > 0 && examCaches(before.held).length > 0);

      // The demo lands a sign-out on the portal over HTTPS, which nothing here serves: the POST
      // is what counts. What is left is read at once, from the exam's own page: its worker
      // answers that, and never keeps a file for the portal, so it shows what sign-out left.
      await Promise.all([
        page.waitForResponse((response) => response.url().endsWith("/sign-out/")),
        page.evaluate(() => document.querySelector('form[action="/sign-out/"]').requestSubmit()),
      ]);
      const reader = await context.newPage();
      await reader.goto(`${SUNRISE}/sit/`);
      await reader.waitForSelector('[data-state="door"]');
      const names = await reader.evaluate(() => caches.keys());
      assert.deepEqual(names.filter((n) => n.startsWith("luffy-")), [], "every cache of the portal is gone");
      assert.deepEqual(names.filter((n) => n.startsWith("sit-")).sort(), examCaches(before.held).sort(), "the exam's are not touched");

      // And the exam's frame is still there to open, and both workers still registered.
      const next = await context.newPage();
      await next.goto(`${SUNRISE}/check/`);
      await next.evaluate(() => navigator.serviceWorker.ready);
      const after = await inventory(next);
      for (const name of examCaches(before.held)) assert.deepEqual([...after.held[name]].sort(), [...before.held[name]].sort(), `${name} is as it was`);
      assert.deepEqual(after.registrations.map((r) => r.scope), ["/", "/sit/"], "no worker was removed");
      // Anything the portal keeps again is a public file the next page asked for: never a page.
      for (const name of portalCaches(after.held)) {
        assert.ok(after.held[name].every((p) => p.startsWith("/static/")), `${name}: ${after.held[name]}`);
      }
      const signedOut = await next.evaluate(async () => (await fetch("/api/home/summary/")).status);
      assert.ok(signedOut >= 400, `and nobody is signed in: ${signedOut}`);
    } finally {
      await context.close();
    }
  });
});

describe("what the portal's worker keeps", () => {
  test("the shell and the two frames: no signed-in page and no answer from the API", async () => {
    const context = await signedIn("sunrise.principal");
    const page = await context.newPage();
    try {
      await page.goto(`${SUNRISE}/home/`);
      await controlled(page);
      for (const path of ["/fees/", "/roll/", "/results/", "/tests/", "/timetable/", "/marking/", "/register/", "/home/"]) {
        await page.goto(`${SUNRISE}${path}`);
        await page.waitForSelector("#sign-out");
      }
      await page.evaluate(async () => {
        for (const path of ["/api/home/summary/", "/api/auth/whoami/", "/api/gradebook/where/", "/api/csrf/"]) await fetch(path).catch(() => {});
      });
      const { held } = await inventory(page);
      const everything = Object.values(held).flat();
      for (const private_ of ["/home/", "/fees/", "/roll/", "/results/", "/tests/", "/timetable/", "/cards/", "/api/", "/files/", "/sit"]) {
        assert.ok(!everything.some((p) => p.startsWith(private_)), `${private_} is not kept: ${everything.filter((p) => p.startsWith(private_))}`);
      }
      const pages = Object.entries(held).filter(([, keys]) => keys.some((p) => !p.startsWith("/static/")));
      for (const [name, keys] of pages) {
        for (const p of keys.filter((p) => !p.startsWith("/static/"))) {
          assert.ok(["/marking/", "/register/", "/offline/", "/icon-192.png", "/icon-512.png", "/favicon.svg"].includes(p) || p.startsWith("/media/"), `${name} keeps ${p}`);
        }
      }
      assert.ok(everything.includes("/offline/"), "the offline page is kept");
    } finally {
      await context.close();
    }
  });

  test("with no connection a page that is not kept says so, in the school's name", async () => {
    const context = await signedIn("sunrise.principal");
    const page = await context.newPage();
    try {
      await page.goto(`${SUNRISE}/home/`);
      await controlled(page);
      // The worker keeps the offline page while it installs, before it takes the page over:
      // say so, so a failure names this and not the browser's error page.
      assert.ok(
        await page.evaluate(async () => Boolean(await caches.match("/offline/"))),
        "the offline page is in a cache before the connection goes",
      );
      await offline(context, true);
      await page.goto(`${SUNRISE}/fees/`);
      assert.equal(await page.textContent("h1"), "You’re offline.");
      assert.match(await page.textContent("main"), /Reconnect to continue\./);
      assert.match(await page.textContent(".logo-name"), /Sunrise Demo Academy/);
      assert.equal(await page.evaluate(() => document.body.textContent.includes("Harbour")), false);
      mkdirSync(join(OUT, "375"), { recursive: true });
      await page.setViewportSize({ width: 375, height: 700 });
      await page.screenshot({ path: join(OUT, "375", "pwa-offline.png") });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), true, "nothing scrolls sideways");
      await offline(context, false);
      await page.getByRole("link", { name: "Try again" }).click();
      await page.waitForURL(/\/home\//);
    } finally {
      await context.close();
    }
  });
});

describe("Install app", () => {
  test("Android: the menu's button appears when the browser offers, and asks it", async () => {
    const context = await signedIn("sunrise.principal", { viewport: { width: 375, height: 740 } });
    const page = await context.newPage();
    try {
      await page.goto(`${SUNRISE}/home/`);
      await page.evaluate(() => navigator.serviceWorker.ready);
      await page.locator(".menu-button").click();
      assert.equal(await page.locator("#install-app").isVisible(), false, "hidden until the browser says it can");
      await page.evaluate(() => {
        const event = new Event("beforeinstallprompt", { cancelable: true });
        event.prompt = () => {
          window.__prompted = (window.__prompted || 0) + 1;
        };
        window.dispatchEvent(event);
      });
      await page.waitForSelector("#install-app", { state: "visible" });
      mkdirSync(join(OUT, "375"), { recursive: true });
      await page.screenshot({ path: join(OUT, "375", "pwa-install-android.png") });
      const box = await page.locator("#install-app").boundingBox();
      assert.ok(box.height >= 43.5, `a target of ${box.height}px`);
      await page.locator("#install-app").click();
      assert.equal(await page.evaluate(() => window.__prompted), 1);
      assert.equal(await page.locator("#install-howto").isVisible(), false, "no how-to on Android");
    } finally {
      await context.close();
    }
  });

  test("iPhone: the button is there and says Share, then Add to Home Screen", async () => {
    const context = await signedIn("sunrise.principal", { viewport: { width: 375, height: 740 }, userAgent: IPHONE, hasTouch: true, isMobile: true });
    const page = await context.newPage();
    try {
      await page.goto(`${SUNRISE}/home/`);
      await page.locator(".menu-button").click();
      await page.waitForSelector("#install-app", { state: "visible" });
      assert.equal(await page.locator("#install-howto").isVisible(), false);
      await page.locator("#install-app").click();
      await page.waitForSelector("#install-howto", { state: "visible" });
      assert.match(await page.textContent("#install-howto"), /Share, then Add to Home Screen/);
      const small = await page.evaluate(() => parseFloat(getComputedStyle(document.getElementById("install-howto")).fontSize));
      assert.ok(small >= 14.95, `${small}px`);
      mkdirSync(join(OUT, "375"), { recursive: true });
      await page.screenshot({ path: join(OUT, "375", "pwa-install-iphone.png") });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), true);
    } finally {
      await context.close();
    }
  });

  test("a desktop browser that never offers shows no button", async () => {
    const context = await signedIn("sunrise.principal", { viewport: { width: 1280, height: 800 } });
    const page = await context.newPage();
    try {
      await page.goto(`${SUNRISE}/home/`);
      await page.waitForSelector("#sign-out");
      assert.equal(await page.locator("#install-app").isVisible(), false);
    } finally {
      await context.close();
    }
  });
});
