/**
 * Every page, in a real browser, at a phone's width, a tablet's and a desk's.
 *
 * `tests/js/` proves what each page draws; this proves how it lands on a
 * screen, which no amount of asserting on markup can. For each page and each of
 * 360, 768 and 1280 pixels it fails when:
 *
 * - **the page scrolls sideways.** A wide table scrolls inside its own box;
 *   the page itself never does, at any width;
 * - **something a finger has to hit is under 44px tall** — a button, a field,
 *   a select, a nav or tab link;
 * - **text on a phone is under 15px.** At 360 only, and not for the small
 *   labels the design sets smaller on purpose (`.label`, `.tag`, `.revised`,
 *   `.nav-heading`, `.tab-label`).
 *
 * And it saves a screenshot of every one, which CI uploads as the `screens`
 * artifact: `<width>/<screen>.png`.
 *
 * ## What it runs against
 *
 * The demo (`manage.py seed_demo`), served by the development server, with
 * `PLATFORM_DOMAIN=classnode.test`. `*.classnode.test` is pointed at this
 * machine by Chromium's own resolver, so nothing needs a hosts file, and the
 * session cookie is scoped to the domain every school's host shares — which is
 * how a sign-in on the portal reaches Sunrise's pages, as it does in
 * production. `.github/workflows/tests.yml` (`screens`) sets all of this up;
 * to run it by hand, do what that job does and then `npm run screens`.
 *
 * `playwright` is the one package this repository's tests use, installed by
 * that job and not a dependency of anything served: `tests/test_budget.py`
 * refuses a page module that imports a package.
 */

import assert from "node:assert/strict";
import { mkdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { after, before, describe, test } from "node:test";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const DOMAIN = process.env.SCREENS_DOMAIN || "classnode.test";
const PORT = process.env.SCREENS_PORT || "8000";
const PASSWORD = process.env.SCREENS_PASSWORD || "demo-pass-2026";
const OUT = process.env.SCREENS_OUT || "screens";
const HERE = dirname(fileURLToPath(import.meta.url));

const PORTAL = `http://app.${DOMAIN}:${PORT}`;
const SUNRISE = `http://sunrise-demo.${DOMAIN}:${PORT}`;
const HARBOUR = `http://harbour-demo.${DOMAIN}:${PORT}`;

export const WIDTHS = [360, 768, 1280];

/** Labels the design sets below body size on purpose. */
const SMALL_ON_PURPOSE = ".label, .tag, .revised, .nav-heading, .tab-label";

/**
 * Every screen: who opens it, where, and the taps that reach its main state.
 * Each step is a selector to click (the first match), and each step's result is
 * a screenshot of its own.
 */
export const SCREENS = [
  // The doors, and what a family with no account uses.
  { name: "sign-in", as: null, url: `${PORTAL}/sign-in/` },
  { name: "staff-sign-in", as: null, url: `${PORTAL}/staff-sign-in/` },
  { name: "invitation", as: null, url: `${PORTAL}/invitations/not-a-token/` },
  { name: "checker", as: null, url: `${SUNRISE}/check/` },
  { name: "outbox", as: null, url: `${PORTAL}/dev/outbox/` },
  // Signed in at one school, asking for another's page.
  { name: "not-allowed", as: "sunrise.teacher", url: `${HARBOUR}/register/`, status: 403 },

  // The teacher.
  {
    name: "register",
    as: "sunrise.teacher",
    url: `${SUNRISE}/register/`,
    steps: [["register-class", '[data-action="open"]']],
  },
  {
    name: "marking",
    as: "sunrise.teacher",
    url: `${SUNRISE}/marking/`,
    steps: [
      ["marking-classes", '[data-action="pick-assessment"]'],
      ["marking-sheet", '[data-action="pick-class"]'],
    ],
  },
  // No drill-down: the frame never says which class, so the page asks for
  // class 0 and draws its wrong-host state for everybody (issue in the PR).
  { name: "comments", as: "sunrise.teacher", url: `${SUNRISE}/comments/` },
  { name: "timetable", as: "sunrise.teacher", url: `${SUNRISE}/timetable/` },

  // The principal.
  { name: "results", as: "sunrise.principal", url: `${SUNRISE}/results/` },
  {
    name: "broadsheet",
    as: "sunrise.principal",
    url: `${SUNRISE}/broadsheet/`,
    steps: [["broadsheet-class", '[data-action="open-class"]']],
  },
  { name: "absences", as: "sunrise.principal", url: `${SUNRISE}/absences/` },

  // The bursar.
  {
    name: "fees",
    as: "sunrise.bursar",
    url: `${SUNRISE}/fees/`,
    steps: [
      ["fees-class", '[data-action="open-class"]'],
      ["fees-account", '[data-action="open-account"]'],
    ],
  },

  // The office.
  { name: "setup", as: "sunrise.admin", url: `${SUNRISE}/setup/` },
  {
    name: "roll",
    as: "sunrise.admin",
    url: `${SUNRISE}/roll/`,
    steps: [["roll-guardians", '[data-action="guardians"]']],
  },
  { name: "staff", as: "sunrise.admin", url: `${SUNRISE}/staff/` },

  // A parent.
  // The demo releases no card, so the index is its empty state and there is
  // no card to open from it yet.
  { name: "cards", as: "sunrise.parent", url: `${SUNRISE}/cards/` },

  // The design's own parts, drawn from `specimen.html` against the served
  // stylesheet: the shell, stat cards, a wide table, labels, messages.
  {
    name: "specimen",
    as: null,
    url: `${PORTAL}/__specimen__/`,
    specimen: true,
    steps: [["specimen-menu-open", ".menu-button:visible"]],
  },
];

/** What a screen breaks, measured in the page. Pure, so it can run anywhere. */
function measure({ smallOnPurpose, phone }) {
  const problems = [];
  const root = document.documentElement;
  if (root.scrollWidth > root.clientWidth) {
    problems.push(`scrolls sideways: ${root.scrollWidth}px of content in ${root.clientWidth}px`);
  }

  const visible = (el) => {
    const box = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return box.width > 0 && box.height > 0 && style.visibility !== "hidden" && style.display !== "none";
  };
  const describe = (el) =>
    `<${el.tagName.toLowerCase()}${el.className ? ` class="${el.className}"` : ""}> "${(el.textContent || el.value || el.getAttribute("aria-label") || "").trim().slice(0, 30)}"`;

  const targets = document.querySelectorAll(
    'button, select, textarea, input:not([type="checkbox"]):not([type="radio"]):not([type="hidden"]), .btn, .nav a, .tabbar a',
  );
  for (const el of targets) {
    if (!visible(el)) continue;
    const height = el.getBoundingClientRect().height;
    if (height < 43.5) problems.push(`target ${Math.round(height)}px tall: ${describe(el)}`);
  }

  if (phone) {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const seen = new Set();
    while (walker.nextNode()) {
      const el = walker.currentNode.parentElement;
      if (!el || seen.has(el) || !walker.currentNode.textContent.trim()) continue;
      seen.add(el);
      if (!visible(el) || el.closest(smallOnPurpose) || el.closest("script, style, noscript")) continue;
      const size = parseFloat(getComputedStyle(el).fontSize);
      if (size < 14.95) problems.push(`text ${size}px on a phone: ${describe(el)}`);
    }
  }
  return problems;
}

let browser;
const contexts = new Map();

async function signedIn(as) {
  if (contexts.has(as)) return contexts.get(as);
  const context = await browser.newContext({ viewport: { width: WIDTHS[0], height: 800 } });
  // Production is HTTPS, and the fees page names each payment with
  // `crypto.randomUUID()`, which a browser gives only a secure context. The
  // demo is plain HTTP on made-up names, so the one call is supplied here, as
  // the HTTPS browser it stands in for would supply it.
  await context.addInitScript(() => {
    if (typeof crypto.randomUUID !== "function") {
      crypto.randomUUID = () =>
        "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) =>
          (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16),
        );
    }
  });
  await context.route(`${PORTAL}/__specimen__/`, (route) =>
    route.fulfill({ contentType: "text/html", body: readFileSync(join(HERE, "specimen.html")) }),
  );
  if (as) {
    const page = await context.newPage();
    await page.goto(`${PORTAL}/staff-sign-in/`);
    const status = await page.evaluate(
      async ({ identifier, password }) => {
        const { csrf_token: token } = await (await fetch("/api/csrf/")).json();
        const response = await fetch("/api/login/", {
          method: "POST",
          headers: { "content-type": "application/json", "X-CSRFToken": token },
          body: JSON.stringify({ identifier, password }),
        });
        return response.status;
      },
      { identifier: as, password: PASSWORD },
    );
    assert.equal(status, 200, `signing in as ${as}`);
    await page.close();
  }
  contexts.set(as, context);
  return context;
}

async function settle(page) {
  await page.waitForLoadState("networkidle");
  // Every page draws from its module after its first fetch; give the last
  // draw a frame to land.
  await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => setTimeout(done, 50))));
}

async function check(page, width, name) {
  mkdirSync(join(OUT, String(width)), { recursive: true });
  await page.screenshot({ path: join(OUT, String(width), `${name}.png`), fullPage: true });
  return (await page.evaluate(measure, { smallOnPurpose: SMALL_ON_PURPOSE, phone: width < 640 })).map(
    (problem) => `${width}px ${name}: ${problem}`,
  );
}

before(async () => {
  browser = await chromium.launch({
    args: [
      `--host-resolver-rules=MAP *.${DOMAIN} 127.0.0.1`,
      // The specimen is handed to the browser by this test rather than fetched,
      // so Chromium counts it as a public page asking a loopback server for its
      // stylesheet, and blocks it. Every real page comes from that server.
      "--disable-features=BlockInsecurePrivateNetworkRequests,PrivateNetworkAccessSendPreflights,PrivateNetworkAccessRespectPreflightResults,LocalNetworkAccessChecks",
    ],
  });
});

after(async () => {
  await browser?.close();
});

describe("every page, at every width", () => {
  for (const screen of SCREENS) {
    test(screen.name, async () => {
      const context = await signedIn(screen.as);
      const page = await context.newPage();
      const problems = [];
      try {
        for (const width of WIDTHS) {
          await page.setViewportSize({ width, height: 800 });
          const response = await page.goto(screen.url);
          assert.equal(response.status(), screen.status || 200, `${screen.url} at ${width}px`);
          await settle(page);
          problems.push(...(await check(page, width, screen.name)));

          for (const [name, selector] of screen.steps || []) {
            const target = page.locator(selector).first();
            if (!(await target.count())) {
              // A drill-down whose first step is not on screen at this width
              // (the specimen's menu button, above 1024px) has nothing to show.
              if (screen.specimen) continue;
              assert.fail(`${screen.name}: nothing to tap for ${name} (${selector}) at ${width}px`);
            }
            await target.click();
            await settle(page);
            problems.push(...(await check(page, width, name)));
          }
        }
      } finally {
        await page.close();
      }
      assert.deepEqual(problems, []);
    });
  }
});
