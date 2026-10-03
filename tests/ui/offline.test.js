/**
 * The marking page with no connection, in a real browser: the service worker,
 * IndexedDB and the network going away, none of which `tests/js/` can have.
 *
 * `docs/offline.md` slice S5. `tests/js/` proves the rules against fakes; this
 * proves the fakes are what the browser does. A teacher opens the page online,
 * the phone loses its connection, and the page must open again from the worker
 * and the copy, say that it is a copy, queue a mark, and send it when the
 * connection is back. Signing out must leave no copy behind.
 *
 * Runs against the same demo as `screens.test.js` (see its header), as Sunrise's
 * teacher. A service worker needs a secure context and `*.classnode.test` over
 * plain HTTP is not one, so the browser is told to treat that one origin as
 * secure; production is HTTPS.
 */

import assert from "node:assert/strict";
import { after, before, describe, test } from "node:test";

import { chromium } from "playwright";

const DOMAIN = process.env.SCREENS_DOMAIN || "classnode.test";
const PORT = process.env.SCREENS_PORT || "8000";
const PASSWORD = process.env.SCREENS_PASSWORD || "demo-pass-2026";
const PORTAL = `http://app.${DOMAIN}:${PORT}`;
const SUNRISE = `http://sunrise-demo.${DOMAIN}:${PORT}`;

let browser;
let context;
let page;

const marking = () => page.locator("#marking").innerHTML();

before(async () => {
  browser = await chromium.launch({
    // Full Chromium in its new headless mode: the headless shell ignores the
    // flag below, and with it a service worker never starts.
    channel: "chromium",
    args: [
      `--host-resolver-rules=MAP *.${DOMAIN} 127.0.0.1, MAP ${DOMAIN} 127.0.0.1`,
      `--unsafely-treat-insecure-origin-as-secure=${SUNRISE}`,
    ],
  });
  context = await browser.newContext({ serviceWorkers: "allow" });
  page = await context.newPage();
  await page.goto(`${PORTAL}/staff-sign-in/`);
  const status = await page.evaluate(async (password) => {
    const { csrf_token: token } = await (await fetch("/api/csrf/")).json();
    const response = await fetch("/api/login/", {
      method: "POST",
      headers: { "content-type": "application/json", "X-CSRFToken": token },
      body: JSON.stringify({ identifier: "sunrise.teacher", password }),
    });
    return response.status;
  }, PASSWORD);
  assert.equal(status, 200, "signing in as sunrise.teacher");
});

after(async () => {
  await browser?.close();
});

async function openSheet() {
  await page.locator('[data-action="pick-assessment"]').first().click();
  await page.locator('[data-action="pick-class"]').first().click();
  await page.waitForSelector("ul.roster");
}

describe("the marking page with no connection", () => {
  let shown;
  let typed;

  test("online, the worker is installed and takes over the page", async () => {
    await page.goto(`${SUNRISE}/marking/`);
    await page.waitForSelector('[data-action="pick-assessment"]');
    await page.evaluate(() => navigator.serviceWorker.ready);
    await page.reload();
    await page.waitForSelector('[data-action="pick-assessment"]');

    assert.equal(await page.evaluate(() => Boolean(navigator.serviceWorker.controller)), true, "controlled");
    const caches = await page.evaluate(async () => (await window.caches.keys()).sort());
    assert.ok(caches.some((name) => name.startsWith("luffy-shell-")), `shell cache in ${caches}`);
    assert.ok(caches.includes("luffy-pages"), `pages cache in ${caches}`);

    await openSheet();
    assert.doesNotMatch(await marking(), /This is a copy/, "a live sheet is not a copy");
    const first = page.locator("ul.roster input").first();
    shown = { value: await first.inputValue(), child: await first.getAttribute("data-child"), version: await first.getAttribute("data-version") };
  });

  test("offline, the page opens from the worker and the sheet from the copy, and says so", async () => {
    await context.setOffline(true);
    await page.reload();
    await page.waitForSelector("#marking .state", { timeout: 15000 });

    assert.match(await marking(), /This is a copy from today \d\d:\d\d\. You are not connected\./);
    await openSheet();
    assert.match(await marking(), /This is a copy from/);
    assert.equal(await page.locator("ul.roster input").first().inputValue(), shown.value, "the marks it was shown");
  });

  test("offline, a mark is queued in IndexedDB with the version the copy showed", async () => {
    const cell = page.locator("ul.roster input").first();
    // Never the number already there: a box left as it was drawn sends nothing.
    typed = (Number(shown.value) + 1) % 20;
    await cell.fill(String(typed));
    await cell.blur();
    await page.waitForSelector("text=Not sent yet");

    const queued = await page.evaluate(
      () =>
        new Promise((resolve) => {
          const open = indexedDB.open("luffy-marks-outbox");
          open.onsuccess = () => {
            const all = open.result.transaction("outboxes").objectStore("outboxes").getAll();
            all.onsuccess = () => resolve(all.result.flatMap((record) => record.entries.map((e) => [e.value, e.expectedVersion])));
          };
        }),
    );
    assert.deepEqual(queued, [[typed, shown.version === "" ? null : Number(shown.version)]]);
  });

  test("back online, the mark is sent and the copy gives way to the server's sheet", async () => {
    await context.setOffline(false);
    await page.evaluate(() => window.dispatchEvent(new Event("online")));
    await page.waitForFunction(
      () => !/Not sent yet|This is a copy/.test(document.getElementById("marking").innerHTML),
      null,
      { timeout: 15000 },
    );

    assert.equal(await page.locator("ul.roster input").first().inputValue(), String(typed));
  });

  test("signing out leaves no copy and no cached page of the signed-in person", async () => {
    // The demo lands a sign-out on the portal over HTTPS, which nothing here
    // serves, so the page it ends on is an error page; the POST is what counts.
    await Promise.all([
      page.waitForResponse((response) => response.url().endsWith("/sign-out/")),
      page.evaluate(() => document.querySelector('form[action="/sign-out/"]').requestSubmit()),
    ]);
    // The school's public page is the same origin as the marking page and draws
    // nothing from the copies, so what it sees is what sign-out left.
    page = await context.newPage();
    await page.goto(`${SUNRISE}/check/`);

    const copies = await page.evaluate(
      () =>
        new Promise((resolve) => {
          const open = indexedDB.open("luffy-snapshots");
          open.onsuccess = () => {
            const all = open.result.transaction("snapshots").objectStore("snapshots").getAll();
            all.onsuccess = () => resolve(all.result.length);
          };
        }),
    );
    assert.equal(copies, 0, "no copy of a sheet is left");

    const menu = await page.evaluate(async () => {
      const kept = await (await window.caches.open("luffy-pages")).match("/marking/");
      return kept ? (await kept.text()).includes('action="/sign-out/"') : false;
    });
    assert.equal(menu, false, "no cached page holds the signed-in menu");
  });
});
