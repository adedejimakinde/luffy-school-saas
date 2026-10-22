/**
 * The states a data page is in besides "drawn", in a real browser: waiting (grey
 * bars, not a line of words), unable to reach the server (the connection
 * dropped, with Try again) or answered with a fault (ours, with the same
 * button), and Back on the pages that open a class or an account in place.
 *
 * Reads only: nothing here writes to the demo, so it can run beside the other
 * files in this folder.
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
const contexts = new Map();

async function signedIn(as) {
  if (contexts.has(as)) return contexts.get(as);
  const context = await browser.newContext({ viewport: { width: 375, height: 800 } });
  await context.addInitScript(() => {
    if (typeof crypto.randomUUID !== "function") crypto.randomUUID = () => "10000000-1000-4000-8000-100000000000";
  });
  const page = await context.newPage();
  await page.goto(`${PORTAL}/staff-sign-in/`);
  const status = await page.evaluate(async ({ identifier, password }) => {
    const { csrf_token: token } = await (await fetch("/api/csrf/")).json();
    const response = await fetch("/api/login/", {
      method: "POST",
      headers: { "content-type": "application/json", "X-CSRFToken": token },
      body: JSON.stringify({ identifier, password }),
    });
    return response.status;
  }, { identifier: as, password: PASSWORD });
  assert.equal(status, 200, `signing in as ${as}`);
  await page.close();
  contexts.set(as, context);
  return context;
}

const settle = async (page, ms = 400) => {
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(ms);
};
const heading = (page) => page.evaluate(() => ((document.querySelector("main h1, main h2") || {}).innerText || "").trim());
const here = (page) => page.url().replace(/^https?:\/\/[^/]+/, "");

before(async () => {
  browser = await chromium.launch({ args: [`--host-resolver-rules=MAP *.${DOMAIN} 127.0.0.1, MAP ${DOMAIN} 127.0.0.1`] });
});
after(async () => {
  await browser?.close();
});

describe("Back on a page that opens a class or an account in place", () => {
  // [who, page, taps to the deepest view, the heading Back must return to after each tap, back]
  const CASES = [
    ["the bursar's fees", "sunrise.bursar", "/fees/", ['[data-action="open-class"]', '[data-action="open-account"]']],
    ["the register", "sunrise.teacher", "/register/", ['[data-action="open"]']],
    ["the broadsheet", "sunrise.principal", "/broadsheet/", ['[data-action="open-class"]']],
    // Choosing a paper stays in the list; the class opens the sheet, which is the one view up.
    ["marks entry", "sunrise.teacher", "/marking/", ['[data-action="pick-assessment"]', '[data-action="pick-class"]'], 1],
    ["subjects", "sunrise.admin", "/teaching/", ['[data-action="open-subject"]']],
  ];
  for (const [name, as, path, taps, depth = taps.length] of CASES) {
    test(`${name}: Back goes up a view, and only then leaves the page`, async () => {
      const page = await (await signedIn(as)).newPage();
      try {
        await page.goto(`${SUNRISE}/help/`);
        await page.goto(`${SUNRISE}${path}`);
        await settle(page);
        const list = await heading(page);
        const trail = [list];
        for (const tap of taps) {
          await page.locator(tap).first().click();
          await settle(page, 500);
          trail.push(await heading(page));
        }
        // Each Back is one view up, by the page's own way up: the same screens in reverse.
        const views = [trail[0], ...trail.slice(taps.length - depth + 1)];
        for (let i = depth - 1; i >= 0; i--) {
          await page.goBack();
          await settle(page, 500);
          assert.equal(here(page), path, `Back from ${views[i + 1]} left the page`);
          assert.equal(await heading(page), views[i], `Back from ${views[i + 1]}`);
        }
        await page.goBack();
        await settle(page);
        assert.equal(here(page), "/help/", "Back from the list goes where the page was opened from");
      } finally {
        await page.close();
      }
    });
  }

  test("using the page's own way up, then Back, leaves the page and not a view that is gone", async () => {
    const page = await (await signedIn("sunrise.bursar")).newPage();
    try {
      await page.goto(`${SUNRISE}/help/`);
      await page.goto(`${SUNRISE}/fees/`);
      await settle(page);
      await page.locator('[data-action="open-class"]').first().click();
      await settle(page, 500);
      await page.locator('[data-action="back-to-books"]').click();
      await settle(page, 500);
      await page.goBack();
      await settle(page);
      assert.equal(here(page), "/help/");
    } finally {
      await page.close();
    }
  });
});

describe("when the page cannot draw", () => {
  test("a dropped connection says so, offers Try again, and Try again loads the page", async () => {
    const page = await (await signedIn("sunrise.bursar")).newPage();
    try {
      let down = true;
      await page.route("**/api/fees/**", (route) => (down ? route.abort("connectionfailed") : route.continue()));
      await page.goto(`${SUNRISE}/fees/`);
      await settle(page);
      const said = await page.evaluate(() => document.querySelector("main").innerText);
      assert.match(said, /Your connection dropped/);
      assert.doesNotMatch(said, /our side/);
      down = false;
      await page.click('[data-action="reload"]');
      await settle(page, 600);
      assert.equal(await heading(page), "Fees");
    } finally {
      await page.close();
    }
  });

  test("an answer that is a fault says it is ours, with the same button", async () => {
    const page = await (await signedIn("sunrise.bursar")).newPage();
    try {
      await page.route("**/api/fees/**", (route) => route.fulfill({ status: 500, contentType: "application/json", body: "{}" }));
      await page.goto(`${SUNRISE}/fees/`);
      await settle(page);
      const said = await page.evaluate(() => document.querySelector("main").innerText);
      assert.match(said, /Something went wrong on our side/);
      assert.equal(await page.locator('[data-action="reload"]').count(), 1);
    } finally {
      await page.close();
    }
  });

  test("while the API is slow the page is grey bars, read out as loading", async () => {
    const page = await (await signedIn("sunrise.principal")).newPage();
    try {
      await page.route("**/api/**", async (route) => {
        if (/csrf|login/.test(route.request().url())) return route.continue();
        await new Promise((done) => setTimeout(done, 2500));
        return route.continue().catch(() => {});
      });
      await page.goto(`${SUNRISE}/results/`, { waitUntil: "domcontentloaded" });
      await page.waitForTimeout(700);
      const found = await page.evaluate(() => ({
        bars: document.querySelectorAll(".skeleton i").length,
        status: document.querySelector(".skeleton[role=status] .sr").textContent,
        words: [...document.querySelectorAll("main p")].some((p) => /^Loading/.test(p.textContent)),
        shown: getComputedStyle(document.querySelector(".skeleton i")).display,
      }));
      assert.equal(found.bars, 4);
      assert.match(found.status, /^Finding your classes/);
      assert.equal(found.words, false, "a line of words is still standing in for the page");
      assert.equal(found.shown, "block");
    } finally {
      await page.close();
    }
  });
});

describe("the roll: search, class filter and pages", () => {
  // The other files in this folder admit children into their own classes while
  // this runs, so nothing here counts the roll: it reads what the page says.
  const rowsOf = (page) => page.locator("li.child").count();

  test("a long roll is 25 to a page, and Next and Previous move through it", async () => {
    const page = await (await signedIn("sunrise.admin")).newPage();
    try {
      await page.goto(`${SUNRISE}/roll/`);
      await settle(page);
      assert.equal(await rowsOf(page), 25);
      assert.match(await page.locator(".roll-count").innerText(), /^Showing 1 to 25 of \d+/);
      await page.click('[data-action="page"]:has-text("Next")');
      assert.match(await page.locator(".roll-count").innerText(), /^Showing 26 to /);
      assert.equal(await page.evaluate(() => document.activeElement.className), "roll-count", "focus moves to the count");
      await page.click('[data-action="page"]:has-text("Previous")');
      assert.match(await page.locator(".roll-count").innerText(), /^Showing 1 to 25/);
      assert.equal(await page.locator('button:has-text("Previous")').isDisabled(), true);
    } finally {
      await page.close();
    }
  });

  test("typing a name finds the child, and the box keeps what is being typed and the focus", async () => {
    const page = await (await signedIn("sunrise.admin")).newPage();
    try {
      await page.goto(`${SUNRISE}/roll/`);
      await settle(page);
      await page.locator("#roll-search").click();
      await page.keyboard.type("kemi joh", { delay: 30 });
      assert.equal(await page.evaluate(() => document.activeElement.id), "roll-search");
      assert.equal(await page.locator("#roll-search").inputValue(), "kemi joh");
      assert.equal(await rowsOf(page), 1);
      assert.match(await page.locator("li.child .name").first().innerText(), /Kemi Johnson/);
      await page.locator("#roll-search").fill("zzzz");
      assert.match(await page.locator(".roll-count").innerText(), /No child matches/);
      await page.click('[data-action="clear-search"]');
      assert.equal(await rowsOf(page), 25);
    } finally {
      await page.close();
    }
  });

  test("the class filter shows only that class", async () => {
    const page = await (await signedIn("sunrise.admin")).newPage();
    try {
      await page.goto(`${SUNRISE}/roll/`);
      await settle(page);
      await page.selectOption("#roll-class", { label: "JSS 1B" });
      const classes = await page.locator("li.child select[data-child]").evaluateAll((els) => els.map((e) => e.options[e.selectedIndex].text));
      assert.ok(classes.length > 0 && classes.every((c) => c === "JSS 1B"), `${classes}`);
    } finally {
      await page.close();
    }
  });

  test("on a phone and at the largest text the tools fit the screen", async () => {
    const page = await (await signedIn("sunrise.admin")).newPage();
    try {
      await page.setViewportSize({ width: 320, height: 700 });
      await page.goto(`${SUNRISE}/roll/`);
      await settle(page);
      await page.addStyleTag({ content: "html { font-size: 200% !important; }" });
      const over = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      assert.ok(over <= 0, `${over}px past the screen`);
    } finally {
      await page.close();
    }
  });
});
