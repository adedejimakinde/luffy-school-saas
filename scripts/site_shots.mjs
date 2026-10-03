/**
 * The product screenshots on the public homepage, taken from the demo.
 *
 * The same demo, the same sign-in and the same taps as `tests/ui/screens.test.js`
 * (run it the way the `screens` job does: `seed_demo` under
 * `PLATFORM_DOMAIN=classnode.test`, served on port 8000). Phones at 360x740 and
 * the laptop at 1280x800, both at twice the pixels so they stay sharp in their
 * frames. Writes PNGs to `SHOTS_OUT` (default `shots/`); `scripts/site_shots.py`
 * turns them into the WebP files in `static/website/shots/`.
 *
 * The fees shot needs a bank and a child's account at Sunrise, which the demo
 * does not make (no Paystack in the demo): `docs/website.md` has the two rows to
 * add by hand first.
 */

import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { chromium } from "playwright";

const DOMAIN = process.env.SCREENS_DOMAIN || "classnode.test";
const PORT = process.env.SCREENS_PORT || "8000";
const PASSWORD = process.env.SCREENS_PASSWORD || "demo-pass-2026";
const OUT = process.env.SHOTS_OUT || "shots";
const PORTAL = `http://app.${DOMAIN}:${PORT}`;
const SUNRISE = `http://sunrise-demo.${DOMAIN}:${PORT}`;

const PHONE = { width: 360, height: 740 };
const LAPTOP = { width: 1280, height: 800 };

const SHOTS = [
  { name: "marks", as: "sunrise.teacher", url: `${SUNRISE}/marking/`, size: PHONE,
    steps: ['[data-action="pick-assessment"]', '[data-action="pick-class"]'] },
  { name: "pay", as: "sunrise.parent", url: `${SUNRISE}/cards/`, size: PHONE },
  { name: "fees", as: "sunrise.bursar", url: `${SUNRISE}/fees/`, size: PHONE,
    steps: ['[data-action="open-class"]', '[data-action="open-account"]'] },
  { name: "register", as: "sunrise.teacher", url: `${SUNRISE}/register/`, size: PHONE,
    steps: ['[data-action="open"]'] },
  { name: "card", as: "sunrise.parent", url: `${SUNRISE}/cards/`, size: PHONE, steps: [".child-switcher button:nth-of-type(2)", ".cards a:visible"] },
  { name: "broadsheet", as: "sunrise.principal", url: `${SUNRISE}/broadsheet/`, size: LAPTOP,
    steps: ['[data-action="open-class"]'] },
  { name: "home", as: "sunrise.principal", url: `${SUNRISE}/home/`, size: LAPTOP },
];

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
    for (const selector of shot.steps || []) {
      await page.locator(selector).first().click();
      await settle(page);
    }
    await page.screenshot({ path: join(OUT, `${shot.name}.png`) });
    await context.close();
  }
} finally {
  await browser.close();
}
