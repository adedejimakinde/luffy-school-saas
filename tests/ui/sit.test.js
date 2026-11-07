/**
 * The exam screen in a real browser (`docs/cbt.md`, step 4): its layout at 320, 390 and
 * 1280px and at 200% text, the keyboard, the calculator, leaving the page, a second
 * computer, the offline outbox with a reload in between, the finished screen, and the
 * door on a slow phone.
 *
 * Against the demo, as `screens.test.js` says how. `manage.py seed_ui` gives this file
 * its own class, **UI Sit**: six children, each with a known exam PIN (`2026000n`), one
 * approved Mathematics test with the calculator on, its sitting opened by hand, and a
 * known test code. Each test below signs in as a different child, because an attempt is
 * one per child and a test here submits or leaves one behind.
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
const SUNRISE = `http://sunrise-demo.${DOMAIN}:${PORT}`;
const PORTAL = `http://app.${DOMAIN}:${PORT}`;

/** `seed_ui`'s class for this file, its code, and each child's number and PIN. */
const OWN_CLASS = "UI Sit";
const CODE = "UISITQ";
const child = (n) => ({ number: `SUN/UI-SIT-0${n}`, pin: `2026000${n}` });

/** Lighthouse's "Slow 4G", as `school_site.test.js` measures a public page. */
const SLOW_4G = { offline: false, latency: 150, downloadThroughput: (1.6 * 1024 * 1024) / 8, uploadThroughput: (750 * 1024) / 8 };
const BUDGET = 150 * 1024;

/** The labels the design sets small on purpose, as `screens.test.js` lists its own. */
const SMALL_ON_PURPOSE = ".sit-timer-label, .sit-count, .kbd, .eyebrow, .label";

let browser;

before(async () => {
  browser = await chromium.launch({
    // Full Chromium, and the demo's one origin treated as secure, as `offline.test.js`
    // does: a service worker needs a secure context, and production is HTTPS.
    channel: "chromium",
    args: [
      `--host-resolver-rules=MAP *.${DOMAIN} 127.0.0.1, MAP ${DOMAIN} 127.0.0.1`,
      `--unsafely-treat-insecure-origin-as-secure=${SUNRISE}`,
      "--font-render-hinting=full",
    ],
  });
});

after(async () => {
  await browser?.close();
});

async function device(width = 1280) {
  const context = await browser.newContext({ viewport: { width, height: 800 }, serviceWorkers: "allow" });
  const page = await context.newPage();
  return { context, page };
}

/** Through the door and the "Is this you?" screen, to the first question. */
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

async function settle(page) {
  await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => setTimeout(done, 80))));
}

/** What a screen breaks: sideways scroll, small targets, small text on a phone. */
function faults({ phone, small }) {
  const problems = [];
  const root = document.documentElement;
  if (root.scrollWidth > root.clientWidth) problems.push(`scrolls sideways: ${root.scrollWidth} in ${root.clientWidth}`);
  const visible = (el) => {
    const box = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return box.width > 0 && box.height > 0 && style.visibility !== "hidden" && style.display !== "none";
  };
  for (const el of document.querySelectorAll("button, input, .btn")) {
    if (visible(el) && el.getBoundingClientRect().height < 43.5) problems.push(`target ${Math.round(el.getBoundingClientRect().height)}px: ${el.textContent.trim().slice(0, 20)}`);
  }
  if (phone) {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const el = walker.currentNode.parentElement;
      if (!el || !walker.currentNode.textContent.trim() || !visible(el) || el.closest(small) || el.closest(".sr")) continue;
      const size = parseFloat(getComputedStyle(el).fontSize);
      if (size < 14.95) problems.push(`text ${size}px: ${el.textContent.trim().slice(0, 20)}`);
    }
  }
  return problems;
}

function layout() {
  const box = (selector) => {
    const el = document.querySelector(selector);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return { left: r.left, right: r.right, top: r.top, bottom: r.bottom, width: r.width, height: r.height, shown: r.width > 0 && style.display !== "none", position: style.position };
  };
  const tiles = [...document.querySelectorAll(".sit-grid .tile")].map((t) => Math.round(t.getBoundingClientRect().top));
  return {
    main: box(".sit-main"),
    side: box(".sit-side"),
    grid: box(".sit-grid-card"),
    strip: box(".sit-strip"),
    bar: box(".sit-bar"),
    timer: getComputedStyle(document.querySelector(".sit-timer-value")).fontVariantNumeric,
    firstRow: tiles.filter((t) => t === tiles[0]).length,
    viewport: window.innerHeight,
  };
}

describe("the exam screen", () => {
  test("at 320, 390 and 1280: two columns on a desk, the strip and the bar on a phone", async () => {
    const { context, page } = await device(1280);
    const problems = [];
    try {
      await sitDown(page, 1);
      await page.keyboard.press("b");
      await page.keyboard.press("n");
      await page.keyboard.press("f");
      await settle(page);
      for (const width of [320, 390, 1280]) {
        await page.setViewportSize({ width, height: 800 });
        // Each width loads the screen afresh, from a blank page, as `screens.test.js` does.
        await page.goto("about:blank");
        await page.goto(`${SUNRISE}/sit/`);
        await page.waitForSelector('[data-state="exam"]');
        await settle(page);
        mkdirSync(join(OUT, String(width)), { recursive: true });
        await page.screenshot({ path: join(OUT, String(width), "sit-exam.png"), fullPage: true });
        problems.push(...(await page.evaluate(faults, { phone: width < 640, small: SMALL_ON_PURPOSE })).map((p) => `${width}px: ${p}`));
        const shape = await page.evaluate(layout);
        assert.equal(shape.timer, "tabular-nums", "the countdown's figures do not jump");
        if (width >= 768) {
          assert.ok(shape.side.left >= shape.main.right, `${width}px: the grid and summary sit to the right of the question`);
          assert.ok(shape.grid.shown, `${width}px: the number grid is shown`);
          assert.equal(shape.firstRow, 6, "six numbers to a row");
          assert.ok(!shape.bar.shown && !shape.strip.shown, `${width}px: no phone bar or strip`);
        } else {
          assert.ok(shape.strip.shown, `${width}px: the strip of numbers`);
          assert.ok(shape.bar.shown && shape.bar.position === "fixed", `${width}px: the bar fixed at the foot`);
          assert.ok(Math.abs(shape.bar.bottom - shape.viewport) <= 1, `${width}px: the bar sits on the bottom edge`);
          assert.ok(!shape.grid.shown, `${width}px: the strip stands in for the grid`);
        }
      }
      // The calculator and the submit question, photographed at 1280 and 390.
      for (const width of [1280, 390]) {
        await page.setViewportSize({ width, height: 800 });
        await page.locator('[data-action="calculator"]:visible').first().click();
        for (const key of ["1", "2", "*", "3", "="]) await page.click(`[data-calc="${key}"]`);
        assert.equal((await page.textContent(".sit-calc-shown")).trim(), "36");
        await page.screenshot({ path: join(OUT, String(width), "sit-calculator.png") });
        problems.push(...(await page.evaluate(faults, { phone: width < 640, small: SMALL_ON_PURPOSE })).map((p) => `${width}px calculator: ${p}`));
        await page.locator('[data-action="calculator"]:visible').first().click();
        await page.locator('[data-action="ask-submit"]').click();
        assert.match(await page.textContent(".sit-dialog-ask"), /You have 9 unanswered and 1 flagged questions\. Submit anyway\?/);
        await page.screenshot({ path: join(OUT, String(width), "sit-submit-question.png") });
        await page.click('[data-action="keep"]');
      }
    } finally {
      await context.close();
    }
    assert.deepEqual(problems, []);
  });

  test("at 200% text on a phone nothing scrolls sideways", async () => {
    const { context, page } = await device(390);
    try {
      await sitDown(page, 2);
      await page.addStyleTag({ content: "html { font-size: 200% !important; }" });
      await settle(page);
      await page.screenshot({ path: join(OUT, "390", "sit-exam-200.png"), fullPage: true });
      const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      assert.ok(over <= 0, `${over}px past the screen`);
    } finally {
      await context.close();
    }
  });

  test("keys A to D choose, N and P move, F flags, and a choice says it is saved", async () => {
    const { context, page } = await device(1280);
    try {
      await sitDown(page, 3);
      await page.keyboard.press("c");
      await page.waitForSelector(".sit-saved:not(.sit-saved-none)");
      assert.match(await page.textContent(".sit-saved"), /Answer saved/);
      assert.equal(await page.getAttribute(".sit-option.chosen", "data-key"), "C");
      await page.keyboard.press("f");
      assert.equal(await page.getAttribute(".sit-flag", "aria-pressed"), "true");
      await page.keyboard.press("n");
      assert.match(await page.textContent(".sit-count"), /Question 2 of 10/i);
      await page.keyboard.press("p");
      assert.match(await page.textContent(".sit-count"), /Question 1 of 10/i);
      assert.match(await page.getAttribute(".sit-grid .tile:first-child", "aria-label"), /Question 1, answered, flagged for review, the one shown/);
      // Focus rings: a tile reached by Tab is outlined.
      await page.focus(".sit-grid .tile:nth-child(3)");
      await page.keyboard.press("Tab");
      const ring = await page.evaluate(() => getComputedStyle(document.activeElement).outlineStyle);
      assert.notEqual(ring, "none");
    } finally {
      await context.close();
    }
  });

  test("offline: answers are kept, the page reloads with no network, and each is sent once when back", async () => {
    const { context, page } = await device(390);
    try {
      await sitDown(page, 4);
      // The worker that keeps the page has to be in charge before the network goes.
      await page.evaluate(async () => {
        await navigator.serviceWorker.ready;
      });
      await page.reload();
      await page.waitForSelector('[data-state="exam"]');
      // The worker controls `/sit/` and keeps the page and its files: nothing outside
      // `/sit/` but the static files the page names, and never an answer from the API.
      const kept = await page.evaluate(async () => {
        const out = { controlled: Boolean(navigator.serviceWorker.controller), scope: (await navigator.serviceWorker.getRegistration()).scope, urls: [] };
        for (const name of await caches.keys()) {
          for (const request of await (await caches.open(name)).keys()) out.urls.push([name, new URL(request.url).pathname]);
        }
        return out;
      });
      assert.ok(kept.controlled, "the page is controlled by its worker");
      assert.ok(kept.scope.endsWith("/sit/"), kept.scope);
      assert.ok(kept.urls.length > 3, "the page and its files are kept");
      for (const [name, path] of kept.urls) {
        assert.ok(name.startsWith("sit-"), `${name} is the exam page's cache`);
        assert.ok(path === "/sit/" || path.startsWith("/static/"), `${path} is the page or a file it names`);
        assert.ok(!path.includes("/api/"), `${path}: no answer from the school is cached`);
      }
      await context.setOffline(true);
      await page.evaluate(() => window.dispatchEvent(new Event("offline")));
      await page.click('.sit-option[data-key="A"]');
      await page.click('.sit-bar [data-action="next"]');
      await page.click('.sit-option[data-key="D"]');
      await page.waitForSelector(".sit-banner-offline");
      assert.match(await page.textContent(".sit-banner-offline"), /You're offline\. Your answers are saved on this device and will send when you reconnect\./);
      await page.screenshot({ path: join(OUT, "390", "sit-offline.png") });

      // A reload with no network: the kept page, the kept answers, the time still running.
      const before = await page.textContent("[data-timer-value]");
      await page.reload();
      await page.waitForSelector('[data-state="exam"]');
      assert.match(await page.textContent(".sit-count"), /Question 2 of 10/i);
      assert.equal(await page.getAttribute(".sit-option.chosen", "data-key"), "D");
      assert.ok((await page.textContent("[data-timer-value]")) <= before, "the clock did not go back");

      await context.setOffline(false);
      await page.evaluate(() => window.dispatchEvent(new Event("online")));
      await page.waitForFunction(() => !document.querySelector(".sit-banner-offline"));
      await page.waitForTimeout(1500);
      const held = await page.evaluate(async () => (await (await fetch("/sit/api/attempt/")).json()).answers);
      assert.equal(Object.values(held).filter((v) => v !== null).length, 2, "both answers reached the school");
    } finally {
      await context.close();
    }
  });

  test("leaving the page is told to the student and counted in the sitting log", async () => {
    const { context, page } = await device(1280);
    try {
      await sitDown(page, 5);
      await page.evaluate(() => window.dispatchEvent(new Event("blur")));
      await page.waitForTimeout(1200);
      await page.evaluate(() => window.dispatchEvent(new Event("focus")));
      await page.waitForSelector(".sit-banner-left");
      assert.match(await page.textContent(".sit-banner-left"), /You left the test's page\. This has been recorded\./);
      await page.waitForTimeout(1200);

      // The principal's sitting log.
      const staff = await browser.newContext({ viewport: { width: 1280, height: 900 } });
      const desk = await staff.newPage();
      await desk.goto(`${PORTAL}/staff-sign-in/`);
      const status = await desk.evaluate(async (password) => {
        const { csrf_token: token } = await (await fetch("/api/csrf/")).json();
        const response = await fetch("/api/login/", { method: "POST", headers: { "content-type": "application/json", "X-CSRFToken": token }, body: JSON.stringify({ identifier: "sunrise.principal", password }) });
        return response.status;
      }, PASSWORD);
      assert.equal(status, 200);
      await desk.goto(`${SUNRISE}/tests/`);
      await desk.locator('a[href^="#sitting/"]').first().waitFor();
      const tests = await desk.evaluate(async () => (await (await fetch("/api/cbt/tests/")).json()).tests);
      const own = tests.find((t) => t.classes.some((c) => c.name === "UI Sit"));
      await desk.goto("about:blank");
      await desk.goto(`${SUNRISE}/tests/#sitting/${own.id}`);
      await desk.waitForSelector('[data-state="sitting"]');
      const row = desk.locator(".sit-student-row", { hasText: "Efe Sit" });
      assert.equal((await row.locator('[data-count="Left the page"] dd').textContent()).trim(), "1");
      await desk.screenshot({ path: join(OUT, "1280", "sit-log.png"), fullPage: true });
      await staff.close();
    } finally {
      await context.close();
    }
  });

  test("a second computer takes the attempt over, and the first says so", async () => {
    const first = await device(1280);
    const second = await device(1280);
    try {
      await sitDown(first.page, 6);
      await sitDown(second.page, 6);
      assert.match(await second.page.textContent(".sit-who, body"), /Ada|Bayo|Chidi|Dayo|Efe|Funmi/);
      await first.page.waitForSelector('[data-state="replaced"]', { timeout: 30_000 }).catch(async () => {
        await first.page.reload();
        await first.page.waitForSelector('[data-state="replaced"]');
      });
      assert.match(await first.page.textContent("h1"), /open on another computer/);

      // The second submits, and its finished screen shows no score.
      await second.page.click('.sit-option[data-key="B"]');
      await second.page.click('[data-action="ask-submit"]');
      await second.page.click('.sit-dialog [data-action="submit"]');
      await second.page.waitForSelector('[data-state="finished"]');
      const done = await second.page.textContent('[data-state="finished"]');
      assert.match(done, /Your score will show when your teacher releases it/);
      assert.match(done, /Received by the school\s*All 1/);
      assert.equal(await second.page.evaluate(async () => (await fetch("/sit/api/attempt/")).status), 401, "the cookie is gone");
      await second.page.screenshot({ path: join(OUT, "1280", "sit-finished.png") });
    } finally {
      await first.context.close();
      await second.context.close();
    }
  });
});

describe("the door on a slow phone", () => {
  test("it draws within 2.5 seconds on Slow 4G, inside the page budget", async () => {
    const runs = [];
    for (let i = 0; i < 3; i += 1) {
      const context = await browser.newContext({ viewport: { width: 360, height: 740 }, deviceScaleFactor: 2 });
      const page = await context.newPage();
      const cdp = await context.newCDPSession(page);
      await cdp.send("Network.enable");
      await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
      await cdp.send("Network.emulateNetworkConditions", SLOW_4G);
      await cdp.send("Emulation.setCPUThrottlingRate", { rate: 4 });
      let bytes = 0;
      cdp.on("Network.loadingFinished", (event) => {
        bytes += event.encodedDataLength;
      });
      const started = Date.now();
      await page.goto(`${SUNRISE}/sit/`, { waitUntil: "load" });
      await page.waitForSelector('[data-state="door"]');
      const drawn = Date.now() - started;
      // What it took to draw the door. The worker then keeps a copy of the same files,
      // after the door is up, which is the next visit's saving and not this one's cost.
      runs.push({ drawn, bytes });
      await context.close();
    }
    const median = (values) => [...values].sort((a, b) => a - b)[1];
    const drawn = median(runs.map((r) => r.drawn));
    const bytes = median(runs.map((r) => r.bytes));
    console.log(`/sit/: the door drawn in ${drawn}ms, ${Math.round(bytes / 1024)} KB`);
    assert.ok(drawn <= 2500, `the door took ${drawn}ms`);
    assert.ok(bytes <= BUDGET, `${Math.round(bytes / 1024)} KB moved`);
  });
});
