/**
 * A school's public website in a real browser: its speed on a slow phone, its
 * layout at 320, 390 and 1280px and at 200% text, the header, the menu and the
 * hero's slideshow. `docs/school-sites.md` §4 and §11;
 * `docs/school-sites-theme-modern.md`.
 *
 * Against the demo (`screens.test.js` says how it is served): Harbour Demo
 * College has published its website (`schoolsite.demo`), in Modern Campus.
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
 * Harbour's home page opens on a slideshow of three hero photos (the first is
 * its largest paint on a wide screen; on a phone the words come first), and
 * shows the principal's portrait, four photos of a published album as a mosaic,
 * the admissions band and Visit us; the Gallery page lists the album, and the
 * album's page shows all six photos.
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
    // A fact's figure ("₦125,000", "98%") is read whole: it never breaks over two lines.
    for (const figure of document.querySelectorAll(".figure")) {
      const style = getComputedStyle(figure);
      if (figure.getBoundingClientRect().height > parseFloat(style.fontSize) * 1.6) faults.push(`the figure "${figure.textContent}" breaks`);
    }
    return faults;
  });
}

/** The widths the theme is held to (`docs/school-sites-theme-modern.md`): a small phone, a common one, a laptop. */
const WIDTHS = [320, 390, 1280];

describe("a school's website at 320, 390 and 1280px and at 200% text", () => {
  for (const url of [...PAGES.map((p) => `${HARBOUR}${p}`), `${SUNRISE}/`]) {
    test(`${url} fits 320, 390 and 1280px, and 390px with its text at 200%`, async () => {
      const context = await browser.newContext({ viewport: { width: 320, height: 640 } });
      const page = await context.newPage();
      await page.goto(url, { waitUntil: "load" });
      for (const width of WIDTHS) {
        await page.setViewportSize({ width, height: 800 });
        assert.deepEqual(await layoutFaults(page), [], `at ${width}px`);
      }

      await page.setViewportSize({ width: 390, height: 800 });
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

  test("on a phone the menu button drops a panel with every page, Sign in's two doors and Apply now", async () => {
    const context = await browser.newContext({ viewport: { width: 390, height: 800 } });
    const page = await context.newPage();
    await page.goto(`${HARBOUR}/`, { waitUntil: "load" });
    assert.equal(await page.isVisible(".links"), false, "no row of links on a phone");
    await page.click(".menu summary");
    await page.waitForTimeout(400); // the panel's short drop
    const panel = await page.$eval(".panel", (el) => {
      const box = el.getBoundingClientRect();
      const bar = document.querySelector(".bar").getBoundingClientRect();
      return { top: box.top, bar: bar.bottom, radius: getComputedStyle(el).borderTopLeftRadius,
        links: Array.from(el.querySelectorAll(".panel-links a")).map((a) => a.textContent) };
    });
    assert.ok(panel.top >= panel.bar - 1, "it drops from the bar");
    assert.ok(parseFloat(panel.radius) >= 20, "rounded");
    assert.deepEqual(panel.links, ["Home", "About", "Boarding", "Admissions", "Sports and clubs", "Gallery", "Contact"]);
    await page.click(".sign-in-big summary");
    const doors = await page.$$eval(".sign-in-big a", (as) => as.map((a) => [a.textContent, new URL(a.href).pathname]));
    assert.deepEqual(doors, [["Parent or guardian", "/sign-in/"], ["Staff", "/staff-sign-in/"]]);
    assert.ok(await page.isVisible('.panel-buttons a.accent:has-text("Apply now")'));
    assert.deepEqual(await layoutFaults(page), [], "with the menu open");
    await context.close();
  });

  test("with no script at all, the menu still opens as a list", async () => {
    const context = await browser.newContext({ viewport: { width: 320, height: 640 }, javaScriptEnabled: false });
    const page = await context.newPage();
    await page.goto(`${HARBOUR}/`, { waitUntil: "load" });
    await page.click(".menu summary");
    assert.ok(await page.isVisible('.panel-links a:has-text("Contact")'));
    await context.close();
  });

  test("on a laptop the bar holds the pages on one line each, Sign in and Apply now, and More for the rest", async () => {
    const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    const page = await context.newPage();
    await page.goto(`${HARBOUR}/`, { waitUntil: "load" });
    assert.equal(await page.isVisible(".menu summary"), false, "no menu button");
    for (const width of [880, 1100, 1280]) {
      await page.setViewportSize({ width, height: 800 });
      const wrapped = await page.$$eval(".links > ul > li > a, .more summary, .sign-in summary, .apply", (els) =>
        els.filter((el) => el.getBoundingClientRect().width > 0 && el.getClientRects().length > 1).map((el) => el.textContent));
      assert.deepEqual(wrapped, [], `nothing wraps at ${width}px`);
      const bar = await page.$eval(".bar", (el) => el.getBoundingClientRect().height);
      assert.ok(bar <= 80, `the bar stays slim at ${width}px: ${bar}px`);
    }
    await page.click(".sign-in summary");
    const doors = await page.$$eval(".sign-in a", (as) => as.map((a) => [a.textContent, new URL(a.href).pathname]));
    assert.deepEqual(doors, [["Parent or guardian", "/sign-in/"], ["Staff", "/staff-sign-in/"]]);
    await context.close();
  });

  test("the header stays at the top while the page scrolls, and a jump to a section is not hidden under it", async () => {
    for (const width of [390, 1280]) {
      const context = await browser.newContext({ viewport: { width, height: 700 } });
      const page = await context.newPage();
      await page.goto(`${HARBOUR}/contact/#map`, { waitUntil: "load" });
      const seen = await page.evaluate(() => ({
        header: document.querySelector(".site-header").getBoundingClientRect(),
        target: document.querySelector("#map").getBoundingClientRect().top,
      }));
      assert.equal(Math.round(seen.header.top), 0, `stuck to the top at ${width}px`);
      assert.ok(seen.target >= seen.header.bottom - 1, `the map starts below the header at ${width}px`);
      await context.close();
    }
  });

  test("the slideshow adds its other photos after load, moves on every 4 seconds, and the words never move", async () => {
    const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    const page = await context.newPage();
    await page.goto(`${HARBOUR}/`, { waitUntil: "load" });
    await page.waitForFunction(() => document.querySelectorAll(".slides .slide").length === 3);
    assert.ok(await page.isVisible(".dots"), "dots once the photos are there");
    const heading = await page.$eval(".hero h1", (h) => JSON.stringify(h.getBoundingClientRect()));
    await page.mouse.move(5, 790);
    await page.waitForFunction(() => document.querySelectorAll(".slide")[1].classList.contains("is-on"), null, { timeout: 6000 });
    assert.equal(await page.$eval(".hero h1", (h) => JSON.stringify(h.getBoundingClientRect())), heading, "the heading stayed put");
    await page.click(".dot >> nth=2");
    assert.equal(await page.$eval(".dot >> nth=2", (d) => d.getAttribute("aria-current")), "true");
    await page.hover(".slides");
    await page.waitForTimeout(4600);
    assert.ok(await page.$eval(".slide >> nth=2", (s) => s.classList.contains("is-on")), "hovering holds it");
    await context.close();
  });

  test("with reduced motion the slideshow never moves by itself and the line art is still", async () => {
    const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, reducedMotion: "reduce" });
    const page = await context.newPage();
    await page.goto(`${HARBOUR}/`, { waitUntil: "load" });
    await page.waitForFunction(() => document.querySelectorAll(".slides .slide").length === 3);
    await page.mouse.move(5, 790);
    await page.waitForTimeout(4600);
    assert.ok(await page.$eval(".slide >> nth=0", (s) => s.classList.contains("is-on")), "still the first photo");
    const moving = await page.$$eval(".art *", (els) => els.filter((el) => getComputedStyle(el).animationName !== "none").length);
    assert.equal(moving, 0);
    await context.close();
  });

  test("with data saver on, only the first photo is ever fetched", async () => {
    const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    await context.addInitScript(() => {
      Object.defineProperty(navigator, "connection", { value: { saveData: true }, configurable: true });
    });
    const page = await context.newPage();
    const heroes = new Set();
    page.on("request", (request) => {
      const match = /\/media\/([0-9a-f]{32})\//.exec(request.url());
      if (match) heroes.add(match[1]);
    });
    await page.goto(`${HARBOUR}/`, { waitUntil: "load" });
    await page.waitForTimeout(1000);
    assert.equal(await page.$$eval(".slides .slide", (s) => s.length), 1);
    const later = await page.$eval("template.later", (t) => t.innerHTML);
    for (const key of heroes) assert.ok(!later.includes(key), `a later slide was fetched: ${key}`);
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
