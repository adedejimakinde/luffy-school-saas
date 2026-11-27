/**
 * The smallest phone, with a large system font: no key page scrolls sideways at
 * 320px, with text at 100% and at 130%. Budget Androids (a Redmi 13C, an
 * Oukitel C66) are 360px or narrower, and their owners often turn the font up;
 * `docs/phone-width-sweep.md` is the sweep this guards.
 *
 * 130% is the browser's default font size raised from 16px to 21px
 * (`Page.setFontSizes`), which scales every `rem` the design uses, as a large
 * system font does in Chrome on Android. Each page is also asked that every
 * amount, date and class name it draws stays on one line.
 *
 * Read only, against the demo `screens.test.js` runs against (its header says
 * how it is served): nothing here writes, so it shares the demo's classes.
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
const SITE = `http://${DOMAIN}:${PORT}`;
const PORTAL = `http://app.${DOMAIN}:${PORT}`;
const SUNRISE = `http://sunrise-demo.${DOMAIN}:${PORT}`;
const HARBOUR = `http://harbour-demo.${DOMAIN}:${PORT}`;

const WIDTH = 320;
const SIZES = [100, 130];

/** [name, who, url, taps]: the pages a school opens every day, by every role. */
const KEY_PAGES = [
  ["homepage", null, `${SITE}/`],
  ["pricing", null, `${SITE}/pricing/`],
  ["staff-sign-in", null, `${SUNRISE}/staff-sign-in/`],
  ["sign-in", null, `${SUNRISE}/sign-in/`],
  ["checker", null, `${SUNRISE}/check/`],
  ["sit-door", null, `${SUNRISE}/sit/`],
  ["test-scores-door", null, `${SUNRISE}/test-scores/`],
  ["school-website", null, `${HARBOUR}/`],
  ["home-principal", "sunrise.principal", `${SUNRISE}/home/`],
  ["home-bursar", "sunrise.bursar", `${SUNRISE}/home/`],
  ["home-teacher", "sunrise.teacher", `${SUNRISE}/home/`],
  ["results", "sunrise.principal", `${SUNRISE}/results/`],
  ["broadsheet", "sunrise.principal", `${SUNRISE}/broadsheet/`, ['[data-action="open-class"]']],
  ["absences", "sunrise.principal", `${SUNRISE}/absences/`],
  ["tests", "sunrise.principal", `${SUNRISE}/tests/`],
  ["exam-slips", "sunrise.principal", `${SUNRISE}/exam-slips/`],
  ["fees", "sunrise.bursar", `${SUNRISE}/fees/`, ['[data-action="open-class"]', '[data-action="open-account"]']],
  ["bank", "sunrise.bursar", `${SUNRISE}/bank/`],
  ["setup", "sunrise.admin", `${SUNRISE}/setup/`],
  ["roll", "sunrise.admin", `${SUNRISE}/roll/`],
  ["staff", "sunrise.admin", `${SUNRISE}/staff/`],
  ["register", "sunrise.teacher", `${SUNRISE}/register/`, ['[data-action="open"]']],
  ["marking", "sunrise.teacher", `${SUNRISE}/marking/`],
  ["timetable", "sunrise.teacher", `${SUNRISE}/timetable/`],
  ["cards", "sunrise.parent", `${SUNRISE}/cards/`, [".child-switcher button:nth-of-type(2)", ".cards a:visible"]],
];

/** What does not fit, measured in the page. Pure. */
function fit() {
  const problems = [];
  const root = document.documentElement;
  if (root.scrollWidth > root.clientWidth) problems.push(`scrolls sideways: ${root.scrollWidth}px of content in ${root.clientWidth}px`);
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden";
  };
  // An amount, a date or a class name is never split over two lines. `\s` is
  // any space, the non-breaking one that holds them together included.
  const KEEP = /₦-?[\d,]+(?:\.\d+)?|\b(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s)?\d{1,2}\s(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*(?:\s\d{4})?\b|\b(?:JSS|SSS|SS|Primary|Basic)\s\d+(?:\s?[A-Z]\b)?/g;
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walk.nextNode()) {
    const node = walk.currentNode;
    const el = node.parentElement;
    if (!el || !visible(el) || el.closest("script, style, option, .sr, .visually-hidden, .mini, .sheet, .float-card, .hero-screen")) continue;
    for (const m of node.textContent.matchAll(KEEP)) {
      const range = document.createRange();
      range.setStart(node, m.index);
      range.setEnd(node, m.index + m[0].length);
      const lines = new Set([...range.getClientRects()].filter((r) => r.width > 0).map((r) => Math.round(r.top / 4)));
      if (lines.size > 1) problems.push(`"${m[0]}" is broken across lines`);
    }
  }
  return problems;
}

let browser;
const contexts = new Map();

async function signedIn(as) {
  if (contexts.has(as)) return contexts.get(as);
  const context = await browser.newContext({ viewport: { width: WIDTH, height: 800 }, reducedMotion: "reduce" });
  // The fees page names each payment with `crypto.randomUUID()`, which plain HTTP lacks (`screens.test.js`).
  await context.addInitScript(() => {
    if (typeof crypto.randomUUID !== "function") crypto.randomUUID = () => "10000000-1000-4000-8000-100000000000";
  });
  if (as) {
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
  }
  contexts.set(as, context);
  return context;
}

async function settle(page) {
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => setTimeout(done, 80))));
}

before(async () => {
  browser = await chromium.launch({
    args: ["--font-render-hinting=full", `--host-resolver-rules=MAP *.${DOMAIN} 127.0.0.1, MAP ${DOMAIN} 127.0.0.1`],
  });
});

after(async () => {
  await browser?.close();
});

describe(`every key page at ${WIDTH}px`, () => {
  for (const [name, as, url, taps = []] of KEY_PAGES) {
    test(`${name} does not scroll sideways, with text at ${SIZES.join("% and ")}%`, async () => {
      const context = await signedIn(as);
      const problems = [];
      for (const size of SIZES) {
        const page = await context.newPage();
        try {
          const cdp = await context.newCDPSession(page);
          await cdp.send("Page.setFontSizes", { fontSizes: { standard: Math.round(16 * size / 100), fixed: Math.round(13 * size / 100) } });
          const response = await page.goto(url);
          assert.equal(response.status(), 200, `${url} with text at ${size}%`);
          await settle(page);
          const shots = [name, ...taps.map((_, k) => `${name}-${k + 1}`)];
          for (let k = 0; k < shots.length; k++) {
            if (k > 0) {
              await page.locator(taps[k - 1]).first().click();
              await settle(page);
            }
            mkdirSync(join(OUT, `${WIDTH}-${size}`), { recursive: true });
            await page.screenshot({ path: join(OUT, `${WIDTH}-${size}`, `${shots[k]}.png`), fullPage: true });
            problems.push(...(await page.evaluate(fit)).map((p) => `${shots[k]} at ${size}%: ${p}`));
          }
        } finally {
          await page.close();
        }
      }
      assert.deepEqual(problems, []);
    });
  }
});
