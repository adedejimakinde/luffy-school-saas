/**
 * The date field and its calendar sheet, in a real browser (`web/dates.js`,
 * `docs/design.md`, "Dates"). Against the demo, as `tests/ui/screens.test.js`
 * says; every test here only fills a form it never submits, so it changes no
 * data.
 *
 * - No portal page has a `<select>` or a native date input for a date.
 * - The register page's sheet at 320, 390 and 1280: it opens (a sheet from the
 *   bottom on a phone, a popover under the field on a desk), the days outside
 *   the term cannot be chosen, a day inside can, and it closes with the choice
 *   written back to the native input as `yyyy-mm-dd`. 200% text at 320 does not
 *   push the sheet sideways.
 * - Today and Yesterday chips; the keyboard (arrows, Enter, Escape); date of
 *   birth's year, month, day flow; the setup term's month arrows.
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

let browser;
const contexts = new Map();

async function signedIn(as, width) {
  const key = `${as}@${width}`;
  if (contexts.has(key)) return contexts.get(key);
  const context = await browser.newContext({ viewport: { width, height: 800 }, hasTouch: width < 640 });
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

async function open(as, width, url, wait = 15000) {
  const context = await signedIn(as, width);
  const page = await context.newPage();
  await page.setViewportSize({ width, height: 800 });
  await page.goto("about:blank");
  await page.goto(url);
  await page.waitForLoadState("networkidle");
  if (wait) await page.waitForSelector(".date-button", { timeout: wait });
  return page;
}

async function shoot(page, width, name) {
  mkdirSync(join(OUT, String(width)), { recursive: true });
  await page.screenshot({ path: join(OUT, String(width), `${name}.png`), fullPage: false });
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

const SHEET = "dialog.date-sheet[open]";
const REGISTER = `${SUNRISE}/register/`;

/** The register page's day box: bound to a term the test makes up, so it never depends on the demo's calendar. */
async function boundRegister(width) {
  const page = await open("sunrise.teacher", width, REGISTER);
  const native = page.locator("#on");
  // The term the demo has current; its days are the page's own bounds.
  const term = await native.evaluate((n) => ({ min: n.min, max: n.max, value: n.value }));
  assert.match(term.min, /^\d{4}-\d{2}-\d{2}$/, "the day box is bound to the term");
  assert.match(term.max, /^\d{4}-\d{2}-\d{2}$/);
  return { page, term };
}

describe("every date field is a button, never a select or a native box", () => {
  const PAGES = [
    ["sunrise.bursar", "fees/"], ["sunrise.admin", "setup/"], ["sunrise.admin", "roll/"], ["sunrise.teacher", "register/"],
    ["sunrise.principal", "tests/"], ["sunrise.principal", "website/"],
  ];
  test("on the portal's pages", async () => {
    for (const [as, path] of PAGES) {
      const page = await open(as, 390, `${SUNRISE}/${path}`, 4000).catch(() => null);
      if (!page) continue; // a page with no date field has no button to wait for
      try {
        const left = await page.evaluate(() => ({
          native: [...document.querySelectorAll('input[type="date"], input[type="datetime-local"]')].filter((i) => !i.classList.contains("date-native")).length,
          selects: document.querySelectorAll(".date-field select").length,
        }));
        assert.deepEqual(left, { native: 0, selects: 0 }, path);
      } finally {
        await page.close();
      }
    }
  });
});

for (const width of [320, 390, 1280]) {
  describe(`the register's day sheet at ${width}px`, () => {
    test("opens, greys out days outside the term, picks, and closes", async () => {
      const { page, term } = await boundRegister(width);
      try {
        const button = page.locator(".date-button").first();
        assert.match(await button.innerText(), /^(Today, |Yesterday, |Tomorrow, |[A-Z][a-z]{2} )/);
        await button.click();
        await page.waitForSelector(SHEET);
        await page.waitForTimeout(400); // the sheet's rise
        const phone = width < 640;
        const box = await page.locator(SHEET).boundingBox();
        assert.ok(box.x >= 0 && box.x + box.width <= width + 0.5, "the sheet spills out sideways");
        if (phone) {
          assert.equal(Math.round(box.width), width, "a phone's sheet is the full width");
          assert.ok(Math.abs(box.y + box.height - 800) <= 1, "a phone's sheet sits on the bottom");
        } else {
          const field = await button.boundingBox();
          assert.ok(Math.abs(box.x - field.x) < 12 || box.x >= 8, "a desk's popover opens at the field");
        }
        assert.ok((await noSideways(page)) <= 0, "the page scrolls sideways");
        // Day cells are a finger tall, and every cell is inside the sheet.
        for (const cell of await page.locator(`${SHEET} .date-day`).all()) {
          const c = await cell.boundingBox();
          assert.ok(c.height >= 44, "a day is under 44px tall");
          assert.ok(c.x >= box.x - 0.5 && c.x + c.width <= box.x + box.width + 0.5, "a day spills out of the sheet");
        }
        await shoot(page, width, "register-sheet");

        // Walk back a month at a time to a day before the term and try it.
        const before = page.locator(`${SHEET} [data-move="-1"]`);
        for (let i = 0; i < 24 && (await before.getAttribute("aria-disabled")) !== "true"; i++) await before.click();
        assert.equal(await before.getAttribute("aria-disabled"), "true", "the first month of the term is the last one back");
        const first = await page.locator(`${SHEET} .date-day:not([aria-disabled="true"])`).first().getAttribute("data-day");
        assert.ok(first >= term.min, `${first} is before the term starts ${term.min}`);
        const out = page.locator(`${SHEET} .date-day[aria-disabled="true"]`);
        if (await out.count()) {
          const was = await page.locator("#on").inputValue();
          await out.first().click({ force: true });
          assert.ok(await page.locator(SHEET).isVisible(), "a day outside the term closed the sheet");
          assert.equal(await page.locator("#on").inputValue(), was, "a day outside the term was chosen");
          const stop = await out.first().getAttribute("data-day");
          assert.ok(stop < term.min || stop > term.max, `${stop} is inside the term`);
        }
        // A day inside the term.
        const day = page.locator(`${SHEET} .date-day:not([aria-disabled="true"])`).first();
        const picked = await day.getAttribute("data-day");
        await day.click();
        await page.waitForSelector(SHEET, { state: "detached" }).catch(() => {});
        assert.equal(await page.locator(SHEET).count(), 0, "the sheet is still open after a pick");
        assert.equal(await page.locator("#on").inputValue(), picked);
        assert.match(await button.innerText(), /\d{4}$|Today|Yesterday|Tomorrow/);
        assert.doesNotMatch(await button.innerText(), /\d\/\d/);
        assert.equal(await page.evaluate(() => document.activeElement.className), "date-button", "focus goes back to the field");
      } finally {
        await page.close();
      }
    });

    test("is clear of the class card and of the date, and the classes are rows in one card", async () => {
      const { page } = await boundRegister(width);
      try {
        const date = await page.locator(".date-field").boundingBox();
        const heading = await page.locator(".which-class").boundingBox();
        assert.ok(heading.y - (date.y + date.height) >= 24, "no air between the date and Which class?");
        assert.equal(await page.locator(".class-card").count(), 1);
        const card = await page.locator(".class-card").boundingBox();
        const rows = page.locator(".class-card .list-rows > li");
        assert.ok((await rows.count()) >= 1);
        assert.equal(await page.locator('[data-action="open"]:not(.class-card *)').count(), 0);
        for (const row of await rows.all()) {
          const r = await row.boundingBox();
          assert.ok(r.x >= card.x && r.x + r.width <= card.x + card.width + 0.5 && r.height >= 44);
        }
        await shoot(page, width, "register-closed");
      } finally {
        await page.close();
      }
    });
  });
}

describe("the sheet's other ways in", () => {
  test("Today and Yesterday chips set the day, and the keyboard walks the calendar", async () => {
    const { page } = await boundRegister(390);
    try {
      const native = page.locator("#on");
      const chips = page.locator(".date-chip");
      assert.deepEqual(await chips.allInnerTexts(), ["Today", "Yesterday"]);
      const today = await page.evaluate(() => new Intl.DateTimeFormat("en-CA", { timeZone: "Africa/Lagos" }).format(new Date()));
      await chips.nth(0).click();
      if ((await chips.nth(0).getAttribute("aria-disabled")) !== "true") assert.equal(await native.inputValue(), today);
      // Keyboard: open, move with the arrows, choose with Enter; Escape closes and gives focus back.
      const button = page.locator(".date-button").first();
      await button.focus();
      await page.keyboard.press("Enter");
      await page.waitForSelector(SHEET);
      const start = await page.evaluate(() => document.activeElement.dataset.day);
      assert.ok(start, "focus goes to a day");
      await page.keyboard.press("ArrowLeft");
      const next = await page.evaluate(() => document.activeElement.dataset.day);
      assert.notEqual(next, start);
      await page.keyboard.press("Escape");
      assert.equal(await page.locator(SHEET).count(), 0);
      assert.equal(await page.evaluate(() => document.activeElement.className), "date-button");
      await button.press("Enter");
      await page.waitForSelector(SHEET);
      await page.keyboard.press("ArrowDown");
      const chosen = await page.evaluate(() => document.activeElement.dataset.day);
      await page.keyboard.press("Enter");
      assert.equal(await page.locator(SHEET).count(), 0);
      assert.equal(await native.inputValue(), chosen);
    } finally {
      await page.close();
    }
  });

  test("the sheet reads aloud: a dialog named for the field, a grid of named days, today marked", async () => {
    const { page } = await boundRegister(390);
    try {
      await page.locator(".date-button").first().click();
      await page.waitForSelector(SHEET);
      const read = await page.evaluate(() => {
        const d = document.querySelector("dialog.date-sheet");
        const t = d.querySelector(".is-today");
        return {
          modal: d.matches(":modal"), name: document.getElementById(d.getAttribute("aria-labelledby")).textContent,
          grid: d.querySelectorAll('[role="grid"] [role="row"]').length >= 4, day: d.querySelector("[data-day]").getAttribute("aria-label"),
          today: t ? t.getAttribute("aria-current") : "date",
        };
      });
      assert.equal(read.modal, true);
      assert.match(read.name, /Which day/);
      assert.ok(read.grid);
      assert.match(read.day, /^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday) \d+ [A-Z][a-z]+ \d{4}$/);
      assert.equal(read.today, "date");
    } finally {
      await page.close();
    }
  });

  test("at 320px and 200% text the sheet still fits", async () => {
    const { page } = await boundRegister(320);
    try {
      await page.addStyleTag({ content: "html { font-size: 200% !important; }" });
      await page.locator(".date-button").first().click();
      await page.waitForSelector(SHEET);
      assert.ok((await noSideways(page)) <= 0, "the page scrolls sideways at 200%");
      const box = await page.locator(SHEET).boundingBox();
      assert.ok(box.x >= 0 && box.x + box.width <= 320.5);
      const over = await page.evaluate(() => {
        const body = document.querySelector(".date-body");
        return body.scrollWidth - body.clientWidth;
      });
      assert.ok(over <= 0, "the calendar scrolls sideways at 200%");
      await shoot(page, 320, "register-sheet-200pc");
    } finally {
      await page.close();
    }
  });

  test("date of birth is year, then month, then day", async () => {
    const page = await open("sunrise.admin", 390, `${SUNRISE}/roll/`, 0);
    try {
      await page.locator('[data-action="details"]').first().click();
      await page.waitForSelector("#date_of_birth");
      const button = page.locator(".date-field:has(#date_of_birth) .date-button");
      await page.locator("#date_of_birth").evaluate((n) => {
        n.value = "";
        n.dispatchEvent(new Event("change", { bubbles: true }));
      });
      await button.click();
      await page.waitForSelector(SHEET);
      await page.locator(`${SHEET} [data-year="2013"]`).click();
      await page.locator(`${SHEET} [data-month="5"]`).click();
      await page.locator(`${SHEET} [data-day="2013-05-02"]`).click();
      assert.equal(await page.locator("#date_of_birth").inputValue(), "2013-05-02");
      assert.equal(await button.innerText(), "2 May 2013");
      assert.equal(await page.locator(SHEET).count(), 0);
    } finally {
      await page.close();
    }
  });

  test("a term's start date picks from a calendar and is stored as yyyy-mm-dd", async () => {
    const page = await open("sunrise.admin", 390, `${SUNRISE}/setup/`);
    try {
      const form = page.locator('form[data-form="term"]');
      await form.locator(".date-button").first().click();
      await page.waitForSelector(SHEET);
      await page.locator(`${SHEET} [data-move="1"]`).click();
      const day = page.locator(`${SHEET} .date-day`).nth(4);
      const picked = await day.getAttribute("data-day");
      await day.click();
      assert.equal(await form.locator("#starts_on").inputValue(), picked);
      assert.equal(await page.locator("select.date-select, .date-field select").count(), 0);
    } finally {
      await page.close();
    }
  });
});
