/**
 * The product screenshots on the public homepage, taken from the demo.
 *
 * The same demo, the same sign-in and the same taps as `tests/ui/screens.test.js`
 * (run it the way the `screens` job does: `seed_demo` under
 * `PLATFORM_DOMAIN=classnode.test`, served on port 8000). Phones at 360x740 and
 * the laptop at 1280 wide, both at twice the pixels so they stay sharp in their
 * frames. Writes PNGs to `SHOTS_OUT` (default `shots/`); `scripts/site_shots.py`
 * turns them into the WebP files in `static/website/shots/`.
 *
 * Taken from the showcase school, `load_demo --showcase` (`schools/showcase.py`):
 * a school having a good day, with a bank and a child's account number of its
 * own, so nothing has to be added by hand. Laptop shots stop under the menu's
 * last whole item (`cropBelowTheMenu`).
 */

import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { chromium } from "playwright";

const DOMAIN = process.env.SCREENS_DOMAIN || "classnode.test";
const PORT = process.env.SCREENS_PORT || "8000";
const PASSWORD = process.env.SCREENS_PASSWORD || "demo-pass-2026";
const OUT = process.env.SHOTS_OUT || "shots";
const PORTAL = `http://app.${DOMAIN}:${PORT}`;
const SCHOOL = `http://showcase-demo.${DOMAIN}:${PORT}`;

const PHONE = { width: 360, height: 740 };
/** Tall enough that the staff menu fits whole above Sign out; see `cropBelowTheMenu`. */
const LAPTOP = { width: 1280, height: 1000 };

/** The showcase school (`load_demo --showcase`, `schools/showcase.py`): a good day. */
const SHOTS = [
  { name: "marks", as: "crestfield.teacher", url: `${SCHOOL}/marking/`, size: PHONE,
    steps: ['[data-action="pick-assessment"]', ['[data-action="pick-class"]', "SS 1A"]] },
  { name: "fees", as: "crestfield.bursar", url: `${SCHOOL}/fees/`, size: PHONE,
    steps: ['[data-action="open-class"]', '[data-action="open-account"]'] },
  // Today's register for SS 1A is the one the showcase leaves untaken: it is
  // photographed, then submitted on the page, before the home is photographed.
  { name: "register", as: "crestfield.teacher", url: `${SCHOOL}/register/`, size: PHONE,
    steps: [['[data-action="open"]', "SS 1A"]], then: '[data-action="submit"]' },
  { name: "card", as: "crestfield.parent", url: `${SCHOOL}/cards/`, size: PHONE, steps: [".cards a:visible"] },
  { name: "broadsheet", as: "crestfield.principal", url: `${SCHOOL}/broadsheet/`, size: LAPTOP,
    steps: ['[data-action="open-class"]'] },
  { name: "home", as: "crestfield.principal", url: `${SCHOOL}/home/`, size: LAPTOP },
];

/**
 * Where a laptop shot stops: just under the last menu item that is whole above
 * the menu's foot, so no item is cut in half and Sign out is not in the
 * picture. The same line for every laptop shot, since the menu is the same.
 */
async function cropBelowTheMenu(page) {
  return page.evaluate(() => {
    const end = document.querySelector("#sidebar .nav-end").getBoundingClientRect().top;
    const whole = [...document.querySelectorAll("#sidebar .nav-links a")]
      .map((a) => a.getBoundingClientRect().bottom)
      .filter((bottom) => bottom <= end);
    return Math.floor(Math.max(...whole) + 8);
  });
}

async function settle(page) {
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => setTimeout(done, 100))));
}

const browser = await chromium.launch({ args: [`--host-resolver-rules=MAP *.${DOMAIN} 127.0.0.1`] });
mkdirSync(OUT, { recursive: true });
try {
  for (const shot of SHOTS) {
    const context = await browser.newContext({ viewport: shot.size, deviceScaleFactor: 2 });
    // As in the screens test: the fees page needs `crypto.randomUUID()`, which
    // a browser gives only an HTTPS page, and the demo is plain HTTP.
    await context.addInitScript(() => {
      if (typeof crypto.randomUUID !== "function") {
        crypto.randomUUID = () =>
          "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) =>
            (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16),
          );
      }
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
    }, { identifier: shot.as, password: PASSWORD });
    if (status !== 200) throw new Error(`signing in as ${shot.as}: ${status}`);
    await page.goto(shot.url);
    await settle(page);
    for (const step of shot.steps || []) {
      const [selector, text] = Array.isArray(step) ? step : [step];
      const target = page.locator(selector);
      await (text ? target.filter({ hasText: text }) : target).first().click();
      await settle(page);
    }
    if (await page.locator(".already").count()) {
      throw new Error(`${shot.name}: the register is already taken. Load a fresh showcase first.`);
    }
    await page.mouse.move(0, 0); // no hover outline on whatever was last tapped
    await page.evaluate(() => window.scrollTo(0, 0));
    await settle(page);
    const clip = shot.size === LAPTOP ? { x: 0, y: 0, width: LAPTOP.width, height: await cropBelowTheMenu(page) } : undefined;
    await page.screenshot({ path: join(OUT, `${shot.name}.png`), clip });
    if (shot.then) {
      await page.locator(shot.then).first().click();
      await settle(page);
    }
    await context.close();
  }
} finally {
  await browser.close();
}
