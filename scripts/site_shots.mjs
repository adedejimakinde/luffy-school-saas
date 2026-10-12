/**
 * The product screens in the homepage's slider, taken from the showcase school.
 *
 * Run it the way the `screens` job runs its demo: `load_demo --showcase`
 * (`schools/showcase.py`, Crestfield Demo College) under
 * `PLATFORM_DOMAIN=classnode.test`, served on port 8000, **on a weekday**: on
 * a Saturday or Sunday the home says there are no registers on a weekend. The
 * homepage's floating cards print the figures these screens show (93.8% was a
 * Thursday's), so check them against the new screens after every retake.
 *
 * The homepage's slides show Thursday 15 October 2026 ("Thu 15 Oct" on every
 * screen, and the 93.8% in the floating card). To take them on that day from
 * another, run the server and `load_demo --showcase` with their clock set to
 * it (libfaketime or `time_machine`) and give this script the same moment as
 * `SHOTS_NOW` (say `2026-10-15T09:30:00+01:00`): the pages' own scripts read
 * today from the browser's clock, the register's date among them.
 *
 * Writes PNGs at twice the pixels to `SHOTS_OUT` (default `shots/`);
 * `scripts/site_shots.py` cuts them into the WebP files in
 * `static/website/shots/`.
 *
 * Load a fresh showcase before each run: SS 1A's register for today is left
 * untaken on purpose, photographed being taken, then submitted on the page, so
 * the home photographed next has every register in. On a second run the
 * script stops and says so.
 */

import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { chromium } from "playwright";

const DOMAIN = process.env.SCREENS_DOMAIN || "classnode.test";
const PORT = process.env.SCREENS_PORT || "8000";
const PASSWORD = process.env.SCREENS_PASSWORD || "demo-pass-2026";
const OUT = process.env.SHOTS_OUT || "shots";
const NOW = process.env.SHOTS_NOW;
const PORTAL = `http://app.${DOMAIN}:${PORT}`;
const SCHOOL = `http://showcase-demo.${DOMAIN}:${PORT}`;

const PHONE = { width: 390, height: 844 };
const DESK = { width: 1280, height: 800 };

const browser = await chromium.launch({ args: [`--host-resolver-rules=MAP *.${DOMAIN} 127.0.0.1`] });
mkdirSync(OUT, { recursive: true });

async function as(who, size) {
  const context = await browser.newContext({ viewport: size, deviceScaleFactor: 2 });
  if (NOW) await context.clock.install({ time: new Date(NOW) });
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
  }, { identifier: who, password: PASSWORD });
  if (status !== 200) throw new Error(`signing in as ${who}: ${status}`);
  return { context, page };
}

async function settle(page) {
  await page.waitForLoadState("networkidle");
  await page.mouse.move(0, 0); // no hover outline on whatever was last tapped
  await page.waitForTimeout(400);
}

try {
  // The register on a phone: SS 1A, two children tapped absent, then submitted.
  {
    const { context, page } = await as("crestfield.teacher", PHONE);
    await page.goto(`${SCHOOL}/register/`);
    await settle(page);
    await page.locator('[data-action="open"]').filter({ hasText: /^\s*SS 1A\s*$/ }).first().click();
    await settle(page);
    if (await page.locator(".already").count()) {
      throw new Error("SS 1A's register is already taken. Load a fresh showcase first.");
    }
    for (const n of [3, 8]) await page.locator('[data-action="toggle"]').nth(n).click();
    await settle(page);
    await page.screenshot({ path: join(OUT, "register.png") });
    await page.locator('[data-action="submit"]').click();
    await settle(page);
    await context.close();
  }
  // The principal's home, the star's report sheet and the bursar's home, at both sizes.
  for (const [who, path, name, open] of [
    ["crestfield.principal", "/home/", "home", null],
    ["crestfield.parent", "/cards/", "card", ["a", "First term"]],
    ["crestfield.bursar", "/home/", "bursar", null],
  ]) {
    for (const [size, suffix] of [[DESK, "desk"], [PHONE, "phone"]]) {
      const { context, page } = await as(who, size);
      await page.goto(`${SCHOOL}${path}`);
      await settle(page);
      if (open) {
        await page.locator(open[0], { hasText: open[1] }).first().click();
        await settle(page);
      }
      await page.screenshot({ path: join(OUT, `${name}-${suffix}.png`), fullPage: true });
      await context.close();
    }
  }
} finally {
  await browser.close();
}
