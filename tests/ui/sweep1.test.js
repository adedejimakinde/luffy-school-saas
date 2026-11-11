/**
 * Portal polish, sweep PR 1, in a real browser: the fees list and setup at 320,
 * 390 and 1280, no month-first date anywhere, the header's short name at 320,
 * and the last row of a list clear of the floating bar at 390. Read only,
 * against the demo (`tests/ui/screens.test.js` says how it is served). Between
 * two URLs that differ by a `#` the page goes to about:blank, so each loads afresh.
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

let browser;
const contexts = new Map();

async function signedIn(as, width) {
  const key = `${as}@${width}`;
  if (contexts.has(key)) return contexts.get(key);
  const context = await browser.newContext({ viewport: { width, height: 800 } });
  await context.addInitScript(() => {
    if (typeof crypto.randomUUID !== "function") crypto.randomUUID = () => "10000000-1000-4000-8000-100000000000";
  });
  const page = await context.newPage();
  await page.goto(`${PORTAL}/staff-sign-in/`);
  const status = await page.evaluate(async ({ identifier, password }) => {
    const { csrf_token: token } = await (await fetch("/api/csrf/")).json();
    return (await fetch("/api/login/", {
      method: "POST",
      headers: { "content-type": "application/json", "X-CSRFToken": token },
      body: JSON.stringify({ identifier, password }),
    })).status;
  }, { identifier: as, password: PASSWORD });
  assert.equal(status, 200, `signing in as ${as}`);
  await page.close();
  contexts.set(key, context);
  return context;
}

async function open(as, width, url) {
  const context = await signedIn(as, width);
  const page = await context.newPage();
  await page.setViewportSize({ width, height: 800 });
  await page.goto("about:blank");
  await page.goto(url);
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => setTimeout(done, 80))));
  return page;
}

async function shoot(page, width, name) {
  mkdirSync(join(OUT, String(width)), { recursive: true });
  await page.screenshot({ path: join(OUT, String(width), `${name}.png`), fullPage: true });
}

const noSideways = (page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

before(async () => {
  browser = await chromium.launch({
    args: ["--font-render-hinting=full", `--host-resolver-rules=MAP *.${DOMAIN} 127.0.0.1, MAP ${DOMAIN} 127.0.0.1`],
  });
});
after(async () => {
  await browser?.close();
});

describe("the fees list", () => {
  for (const width of [320, 390, 1280]) {
    test(`is list rows in one card at ${width}px`, async () => {
      const page = await open("sunrise.bursar", width, `${SUNRISE}/fees/`);
      try {
        assert.ok((await noSideways(page)) <= 0, "the page scrolls sideways");
        assert.equal(await page.locator(".class-card").count(), 1);
        const rows = page.locator(".class-card .list-rows > li");
        assert.ok((await rows.count()) >= 2);
        // No class button floats outside the card.
        assert.equal(await page.locator('[data-action="open-class"]:not(.class-card *)').count(), 0);
        const first = rows.first();
        assert.ok(await first.locator(".list-row-title").evaluate((e) => Number(getComputedStyle(e).fontWeight) >= 700));
        assert.match(await first.locator(".list-row-sub").innerText(), /^\d+ child(ren)?$/);
        assert.match(await first.locator(".class-share").innerText(), /% collected|Not billed/);
        assert.equal(await first.locator("svg.icon").count(), 1, "a chevron");
        // Every row fits inside the card, and is a finger tall.
        const card = await page.locator(".class-card").boundingBox();
        for (const row of await rows.all()) {
          const box = await row.boundingBox();
          assert.ok(box.x >= card.x && box.x + box.width <= card.x + card.width + 0.5, "a row spills out of the card");
          assert.ok(box.height >= 44);
        }
        // Tapping a row opens that class's list, as before.
        await first.locator("button").click();
        await page.waitForSelector('[data-state="class"]');
        await shoot(page, width, "sweep1-fees-class");
      } finally {
        await page.close();
      }
    });
  }
});

describe("setup", () => {
  for (const width of [320, 390, 1280]) {
    test(`is stacked cards at ${width}px`, async () => {
      const page = await open("sunrise.admin", width, `${SUNRISE}/setup/`);
      try {
        assert.ok((await noSideways(page)) <= 0, "the page scrolls sideways");
        await shoot(page, width, "sweep1-setup");
        const cards = page.locator(".setup-card");
        assert.ok((await cards.count()) >= 6);
        // Every heading sits in a card, and the cards stack without overlapping.
        assert.equal(await page.locator("h2").evaluateAll((hs) => hs.filter((h) => !h.closest(".card, .empty-card")).length), 0);
        let bottom = -1;
        for (const card of await cards.all()) {
          const box = await card.boundingBox();
          assert.ok(box.y >= bottom, "cards overlap");
          assert.ok(box.x + box.width <= width + 0.5, "a card spills out");
          bottom = box.y + box.height;
        }
        assert.equal(await page.locator(".setup-card > h2").count(), await cards.count());
      } finally {
        await page.close();
      }
    });
  }
});

const US_DATE = /\b(0?[1-9]|1[0-2])\/(0?[1-9]|[12]\d|3[01])\/(19|20)\d\d\b/;
const PORTAL_PAGES = [
  ["sunrise.bursar", "fees/"], ["sunrise.bursar", "fees/?student=1"], ["sunrise.admin", "setup/"], ["sunrise.admin", "roll/"],
  ["sunrise.teacher", "register/"], ["sunrise.principal", "tests/"], ["sunrise.principal", "home/"], ["sunrise.principal", "absences/"],
];

describe("dates", () => {
  test("no portal page shows a month-first date, and every date field is day first", async () => {
    for (const [as, path] of PORTAL_PAGES) {
      const page = await open(as, 390, `${SUNRISE}/${path}`);
      try {
        const text = await page.evaluate(() => document.body.innerText);
        assert.doesNotMatch(text, US_DATE, `${path} shows a mm/dd/yyyy date`);
        // A date field is selects and an invisible native input: never the browser's own mm/dd/yyyy box.
        const bare = await page.evaluate(() =>
          [...document.querySelectorAll('input[type="date"], input[type="datetime-local"]')].filter((i) => !i.classList.contains("date-native")).length);
        assert.equal(bare, 0, `${path} has a native date box`);
      } finally {
        await page.close();
      }
    }
  });

  test("a term's start date is chosen day, month, year and stored as yyyy-mm-dd", async () => {
    const page = await open("sunrise.admin", 390, `${SUNRISE}/setup/`);
    try {
      const form = page.locator('form[data-form="term"]');
      const field = form.locator(".date-field").first();
      assert.deepEqual(await field.locator("select").evaluateAll((s) => s.map((x) => x.getAttribute("aria-label").split(": ")[1])), ["Day", "Month", "Year"]);
      await field.locator("select").nth(0).selectOption("8");
      await field.locator("select").nth(1).selectOption("11");
      assert.equal(await form.locator("#starts_on").inputValue(), "", "not a date until the year is chosen");
      await field.locator("select").nth(2).selectOption("2026");
      assert.equal(await form.locator("#starts_on").inputValue(), "2026-11-08");
      await field.locator("select").nth(0).selectOption("31");
      await field.locator("select").nth(1).selectOption("2");
      assert.equal(await form.locator("#starts_on").inputValue(), "2026-02-28");
    } finally {
      await page.close();
    }
  });
});

describe("the header", () => {
  test("shows the school's short name and never overflows at 320px", async () => {
    const page = await open("sunrise.principal", 320, `${SUNRISE}/home/`);
    try {
      const name = page.locator(".topbar .logo-name");
      const shown = (await name.innerText()).trim();
      assert.ok(shown.length > 0 && !shown.includes(","), `the header says "${shown}"`);
      const fit = await page.evaluate(() => {
        const bar = document.querySelector(".topbar");
        const n = document.querySelector(".topbar .logo-name");
        return {
          clipped: n.scrollWidth > n.clientWidth || n.scrollHeight > n.clientHeight + 1,
          bar: bar.scrollWidth - bar.clientWidth,
          page: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        };
      });
      assert.deepEqual(fit, { clipped: false, bar: 0, page: 0 });
      mkdirSync(join(OUT, "320"), { recursive: true });
      await page.screenshot({ path: join(OUT, "320", "sweep1-header.png"), clip: { x: 0, y: 0, width: 320, height: 72 } });
    } finally {
      await page.close();
    }
  });
});

describe("the floating bottom bar", () => {
  for (const [as, path] of [["sunrise.bursar", "fees/"], ["sunrise.admin", "setup/"], ["sunrise.principal", "absences/"], ["sunrise.admin", "roll/"]]) {
    test(`does not cover the last item of ${path} at 390px`, async () => {
      const page = await open(as, 390, `${SUNRISE}/${path}`);
      try {
        const bar = await page.locator(".tabbar").boundingBox();
        assert.ok(bar, "the phone's tab bar");
        await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
        const last = await page.evaluate(() => {
          const items = [...document.querySelectorAll("main li, main tr, main .card, main section, main p")].filter((e) => e.getBoundingClientRect().height > 0 && !e.closest(".tabbar"));
          return Math.max(...items.map((e) => e.getBoundingClientRect().bottom));
        });
        const barTop = (await page.locator(".tabbar").boundingBox()).y;
        assert.ok(last <= barTop - 8, `the last item ends at ${last}, the bar starts at ${barTop}`);
        const pad = await page.evaluate(() => ({
          padding: parseFloat(getComputedStyle(document.querySelector(".content")).paddingBottom),
          bar: document.querySelector(".tabbar").getBoundingClientRect().height,
        }));
        assert.ok(pad.padding >= pad.bar + 8, `foot padding ${pad.padding} is not the bar's ${pad.bar} plus a gap`);
      } finally {
        await page.close();
      }
    });
  }
});
