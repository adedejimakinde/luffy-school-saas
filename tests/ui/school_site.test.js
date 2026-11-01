/**
 * A school's public website in a real browser: its speed on a slow phone, its
 * layout at 320px, and at 200% text. `docs/school-sites.md` §4 and §11.
 *
 * Against the demo (`screens.test.js` says how it is served): Harbour Demo
 * College has published its website (`schoolsite.demo`), in the starter theme.
 * `screens.test.js` photographs its pages and holds them to the shared rules
 * at 360, 768 and 1280; this adds what only a public page is held to.
 *
 * **Speed** is measured as Lighthouse's mobile "Slow 4G" measures it: 150ms
 * round trip, 1.6 Mbit/s down, 750 kbit/s up, the CPU four times slower. Each
 * number is the median of three cold loads, each in a fresh browser context, so
 * one slow runner second does not flip it:
 *
 * - the largest contentful paint by 2.5 seconds;
 * - a cumulative layout shift of at most 0.05;
 * - at most 400 KB transferred before the visitor scrolls, or 600 KB on the
 *   Gallery page and an album's page (§4.1).
 *
 * Since PR 5 Harbour's home page opens on a hero photo (its largest paint) and
 * shows the principal's portrait and three photos of a published album; the
 * Gallery page lists the album, and the album's page shows all six photos.
 *
 * The demo is served by the development server, uncompressed and unhashed, so
 * the bytes counted here are more than production sends, never fewer.
 */

import assert from "node:assert/strict";
import { after, before, describe, test } from "node:test";

import { chromium } from "playwright";

const DOMAIN = process.env.SCREENS_DOMAIN || "classnode.test";
const PORT = process.env.SCREENS_PORT || "8000";
const HARBOUR = `http://harbour-demo.${DOMAIN}:${PORT}`;
const SUNRISE = `http://sunrise-demo.${DOMAIN}:${PORT}`;

const ALBUM = "/gallery/inter-house-sports-2026/";
const PAGES = ["/", "/about/", "/admissions/", "/contact/", "/pages/boarding/", "/gallery/", ALBUM];

/** Lighthouse's "Slow 4G", in the units the DevTools protocol takes. */
const SLOW_4G = { offline: false, latency: 150, downloadThroughput: (1.6 * 1024 * 1024) / 8, uploadThroughput: (750 * 1024) / 8 };
const CPU_SLOWDOWN = 4;

const LCP_BUDGET_MS = 2500;
const CLS_BUDGET = 0.05;
const BYTES_BUDGET = 400 * 1024;
/** §4.1: a gallery page may move more before the visitor scrolls. */
const GALLERY_BYTES_BUDGET = 600 * 1024;
const bytesBudget = (path) => (path.startsWith("/gallery/") ? GALLERY_BYTES_BUDGET : BYTES_BUDGET);

let browser;

before(async () => {
  browser = await chromium.launch({
    args: [`--host-resolver-rules=MAP *.${DOMAIN} 127.0.0.1, MAP ${DOMAIN} 127.0.0.1`],
  });
});

after(async () => {
  await browser?.close();
});

/** One cold load of `url` on a throttled phone: its LCP, its CLS, and the bytes it moved. */
async function coldLoad(url) {
  const context = await browser.newContext({ viewport: { width: 360, height: 740 }, deviceScaleFactor: 2 });
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });
  await cdp.send("Network.emulateNetworkConditions", SLOW_4G);
  await cdp.send("Emulation.setCPUThrottlingRate", { rate: CPU_SLOWDOWN });
  let bytes = 0;
  cdp.on("Network.loadingFinished", (event) => {
    bytes += event.encodedDataLength;
  });
  await page.goto(url, { waitUntil: "load" });
  const measured = await page.evaluate(
    () =>
      new Promise((resolve) => {
        let lcp = 0;
        let cls = 0;
        new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) lcp = Math.max(lcp, entry.renderTime || entry.loadTime);
        }).observe({ type: "largest-contentful-paint", buffered: true });
        new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) if (!entry.hadRecentInput) cls += entry.value;
        }).observe({ type: "layout-shift", buffered: true });
        setTimeout(() => resolve({ lcp, cls }), 500);
      }),
  );
  await context.close();
  return { ...measured, bytes };
}

const median = (values) => [...values].sort((a, b) => a - b)[Math.floor(values.length / 2)];

describe("a school's website on a slow phone", () => {
  for (const path of PAGES) {
    test(`${path} paints its largest content within ${LCP_BUDGET_MS}ms on Slow 4G, without shifting`, async () => {
      const runs = [];
      for (let i = 0; i < 3; i += 1) runs.push(await coldLoad(`${HARBOUR}${path}`));
      const lcp = median(runs.map((r) => r.lcp));
      const cls = median(runs.map((r) => r.cls));
      const bytes = median(runs.map((r) => r.bytes));
      console.log(`${path}: LCP ${Math.round(lcp)}ms, CLS ${cls.toFixed(3)}, ${Math.round(bytes / 1024)} KB`);
      assert.ok(lcp > 0, "no largest contentful paint was reported");
      assert.ok(lcp <= LCP_BUDGET_MS, `largest contentful paint ${Math.round(lcp)}ms`);
      assert.ok(cls <= CLS_BUDGET, `layout shift ${cls.toFixed(3)}`);
      assert.ok(bytes <= bytesBudget(path), `${Math.round(bytes / 1024)} KB moved`);
    });
  }
});

/** Whether the page scrolls sideways, and every control a finger has to hit that is under 44px. */
async function layoutFaults(page) {
  return page.evaluate(() => {
    const faults = [];
    if (document.documentElement.scrollWidth > window.innerWidth + 1) {
      faults.push(`scrolls sideways: ${document.documentElement.scrollWidth} > ${window.innerWidth}`);
    }
    for (const element of document.querySelectorAll("a, button, summary")) {
      const box = element.getBoundingClientRect();
      if (box.width === 0 && box.height === 0) continue; // closed menus, the skip link
      if (element.classList.contains("skip")) continue;
      if (box.height < 44) faults.push(`${element.tagName} "${element.textContent.trim().slice(0, 30)}" is ${Math.round(box.height)}px tall`);
    }
    return faults;
  });
}

describe("a school's website at 320px and at 200% text", () => {
  for (const url of [...PAGES.map((p) => `${HARBOUR}${p}`), `${SUNRISE}/`]) {
    test(`${url} fits 320px, and 360px with its text at 200%`, async () => {
      const context = await browser.newContext({ viewport: { width: 320, height: 640 } });
      const page = await context.newPage();
      await page.goto(url, { waitUntil: "load" });
      assert.deepEqual(await layoutFaults(page), [], "at 320px");

      await page.setViewportSize({ width: 360, height: 740 });
      // What the browser's own text size setting does: the root font doubled,
      // everything sized in rem and em with it (WCAG 1.4.4).
      await page.evaluate(() => {
        document.documentElement.style.fontSize = "200%";
      });
      const zoomed = await page.evaluate(() =>
        document.documentElement.scrollWidth > window.innerWidth + 1
          ? `scrolls sideways: ${document.documentElement.scrollWidth} > ${window.innerWidth}`
          : "",
      );
      assert.equal(zoomed, "", "at 200% text");
      await context.close();
    });
  }

  test("the Sign in menu opens with a tap and offers both doors, at 320px", async () => {
    const context = await browser.newContext({ viewport: { width: 320, height: 640 } });
    const page = await context.newPage();
    await page.goto(`${HARBOUR}/`, { waitUntil: "load" });
    await page.click(".sign-in summary");
    const links = await page.$$eval(".sign-in a", (as) => as.map((a) => [a.textContent, new URL(a.href).pathname]));
    assert.deepEqual(links, [["Parent or guardian", "/sign-in/"], ["Staff", "/staff-sign-in/"]]);
    assert.deepEqual(await layoutFaults(page), [], "with the menu open");
    await context.close();
  });

  test("a gallery photo opens over the page with a tap, and Escape closes it, at 320px", async () => {
    const context = await browser.newContext({ viewport: { width: 320, height: 640 } });
    const page = await context.newPage();
    await page.goto(`${HARBOUR}${ALBUM}`, { waitUntil: "load" });
    await page.click("a.photo >> nth=0");
    await page.waitForSelector("dialog.lightbox[open] img");
    const shown = await page.$eval("dialog.lightbox", (d) => ({
      alt: d.querySelector("img").alt, caption: d.querySelector(".lightbox-caption").textContent, url: location.pathname,
    }));
    assert.equal(shown.url, ALBUM, "the page stayed where it was");
    assert.ok(shown.alt.length > 0, "the photo keeps its description");
    assert.ok(shown.caption.length > 0, "and its caption");
    await page.click(".lightbox-next");
    assert.notEqual(await page.$eval("dialog.lightbox img", (img) => img.alt), shown.alt, "Next shows the next photo");
    await page.keyboard.press("Escape");
    assert.equal(await page.$eval("dialog.lightbox", (d) => d.open), false);
    await context.close();
  });

  test("the map loads only when asked for, on the contact page", async () => {
    const context = await browser.newContext({ viewport: { width: 360, height: 740 } });
    const page = await context.newPage();
    const google = [];
    page.on("request", (request) => {
      if (new URL(request.url()).hostname.endsWith("google.com")) google.push(request.url());
    });
    await page.route("**://www.google.com/**", (route) => route.fulfill({ status: 200, body: "<p>map</p>", contentType: "text/html" }));
    await page.goto(`${HARBOUR}/contact/`, { waitUntil: "load" });
    assert.equal(await page.$("iframe"), null);
    assert.deepEqual(google, [], "nothing of Google's before the tap");
    await page.click("a.map-tap");
    await page.waitForSelector("#map iframe");
    assert.equal(new URL(page.url()).search, "?map=1");
    await context.close();
  });
});
