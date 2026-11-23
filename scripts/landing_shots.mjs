/**
 * The screens on the public site's solution pages (`website/landing.py`), taken
 * from the two Crestfield demo schools.
 *
 * Run it against a demo the way `scripts/site_shots.mjs` says, on port 8000
 * under `PLATFORM_DOMAIN=classnode.test`, with both schools in one database:
 *
 *   migrate_schemas --shared, then `load_demo --showcase` (Crestfield Demo
 *   College, `schools/showcase.py`), then `setup_portal`, then
 *   `crestfield create` (`schools/crestfield/`, for CBT and the website).
 *
 * The CBT screen prints the school's name, and the sales demo's name carries
 * its town; the public site names no town but Lagos (`website/tests/test_location.py`),
 * so rename the local copy before the run (`School.name = "Crestfield College (Demo)"`).
 * The website shots are cut to sections that print no address.
 *
 * What it needs from the demo, as environment variables:
 *
 * - `SHOTS_PASSWORD`: the demo logins' password (`LOAD_DEMO_PASSWORD`, and the
 *   `CRESTFIELD_*_PASSWORD`s set to the same).
 * - `SHOTS_TEST_CODE`, `SHOTS_SIT` and `SHOTS_SIT_PHONE`: the CBT test code
 *   `crestfield create` prints, and two of the students it prints, each as
 *   `admission number,PIN`.
 * - `SHOTS_CHECK`: a showcase child's result-checker slip, `admission number,PIN`,
 *   printed for a lost slip from JSS 2A's row on the results page (or
 *   `results.checker.print_slips(sheet, actor=principal, admission_number=...)`).
 *
 * Writes PNGs at twice the pixels to `SHOTS_OUT` (default `shots/`);
 * `scripts/landing_shots.py` cuts them into `static/website/shots/landing-*.webp`.
 */

import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { chromium } from "playwright";

const DOMAIN = process.env.SCREENS_DOMAIN || "classnode.test";
const PORT = process.env.SCREENS_PORT || "8000";
const PASSWORD = process.env.SHOTS_PASSWORD || "demo-pass-2026";
const OUT = process.env.SHOTS_OUT || "shots";
const PORTAL = `http://app.${DOMAIN}:${PORT}`;
const SHOWCASE = `http://showcase-demo.${DOMAIN}:${PORT}`;
const CRESTFIELD = `http://crestfield.${DOMAIN}:${PORT}`;
const pair = (name) => (process.env[name] || "").split(",").map((s) => s.trim());

const PHONE = { width: 390, height: 844 };
const DESK = { width: 1280, height: 800 };

const browser = await chromium.launch({ args: [`--host-resolver-rules=MAP *.${DOMAIN} 127.0.0.1`] });
mkdirSync(OUT, { recursive: true });

async function open(size, who) {
  const context = await browser.newContext({ viewport: size, deviceScaleFactor: 2 });
  // The demo is plain http, where a browser has no `crypto.randomUUID`; the
  // fee page asks for one to key its forms. Served over https it has one.
  await context.addInitScript(() => {
    if (!crypto.randomUUID) {
      crypto.randomUUID = () => "10000000-1000-4000-8000-100000000000".replace(
        /[018]/g, (c) => (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16));
    }
  });
  const page = await context.newPage();
  if (who) {
    await page.goto(`${PORTAL}/staff-sign-in/`);
    const status = await page.evaluate(async ({ identifier, password }) => {
      const { csrf_token: token } = await (await fetch("/api/csrf/")).json();
      const response = await fetch("/api/login/", {
        method: "POST",
        headers: { "content-type": "application/json", "X-CSRFToken": token },
        body: JSON.stringify({ identifier, password }),
      });
      return response.status;
    }, { identifier: who, password: PASSWORD });
    if (status !== 200) throw new Error(`signing in as ${who}: ${status}`);
  }
  return { context, page };
}

async function settle(page) {
  await page.waitForLoadState("networkidle");
  await page.mouse.move(0, 0);
  await page.waitForTimeout(800);
}

async function shoot(size, who, url, name, steps = async () => {}, fullPage = false) {
  const { context, page } = await open(size, who);
  await page.goto(url);
  await settle(page);
  await steps(page);
  await settle(page);
  await page.screenshot({ path: join(OUT, `${name}.png`), fullPage });
  await context.close();
}

async function sit(page, [number, pin]) {
  const inputs = page.locator("input");
  await inputs.nth(0).fill(process.env.SHOTS_TEST_CODE || "");
  await inputs.nth(1).fill(number);
  await inputs.nth(2).fill(pin);
  await page.getByRole("button", { name: "Continue" }).click();
  await settle(page);
  // A student already in the test is taken straight back to it.
  const start = page.locator('[data-action="start"]');
  if (await start.count()) await start.click();
}

try {
  // Results: JSS 2A's released broadsheet, and the principal's results page.
  await shoot(DESK, "crestfield.principal", `${SHOWCASE}/broadsheet/`, "broadsheet", async (page) => {
    await page.locator('[data-action="open-class"]', { hasText: "JSS 2A" }).first().click();
  });
  await shoot(DESK, "crestfield.principal", `${SHOWCASE}/results/`, "chain");
  // Fees: JSS 2A's fee book.
  await shoot(DESK, "crestfield.bursar", `${SHOWCASE}/fees/`, "fee-class", async (page) => {
    await page.locator('[data-action="open-class"]', { hasText: "JSS 2A" }).first().click();
  });
  // Moving from Excel: importing a roll from a spreadsheet.
  await shoot(DESK, "crestfield.admin", `${SHOWCASE}/roll/import/`, "roll-import");
  // The result checker on a phone, filled in, then the card it opens.
  const [number, pin] = pair("SHOTS_CHECK");
  await shoot(PHONE, null, `${SHOWCASE}/check/`, "checker", async (page) => {
    const inputs = page.locator("input:visible");
    await inputs.nth(0).fill(number);
    await inputs.nth(1).fill(pin);
  });
  await shoot(PHONE, null, `${SHOWCASE}/check/`, "checker-card", async (page) => {
    const inputs = page.locator("input:visible");
    await inputs.nth(0).fill(number);
    await inputs.nth(1).fill(pin);
    await page.getByRole("button", { name: /Open the report card/ }).click();
  });
  // CBT: the test screen on a desk and on a phone, question 1 answered.
  for (const [size, name, student] of [[DESK, "sit", "SHOTS_SIT"], [PHONE, "sit-phone", "SHOTS_SIT_PHONE"]]) {
    await shoot(size, null, `${CRESTFIELD}/sit/`, name, async (page) => {
      await sit(page, pair(student));
      await settle(page);
      await page.locator('[data-action="choose"]').first().click();
    });
  }
  // The school website, whole, on a desk and a phone; the cut picks the sections.
  await shoot(DESK, null, `${CRESTFIELD}/`, "website", async () => {}, true);
  await shoot(PHONE, null, `${CRESTFIELD}/`, "website-phone", async () => {}, true);
} finally {
  await browser.close();
}
