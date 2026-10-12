/**
 * Every page, in a real browser, at a phone's width, a tablet's and a desk's.
 *
 * `tests/js/` proves what each page draws; this proves how it lands on a
 * screen, which no amount of asserting on markup can. For each page and each of
 * 360, 768 and 1280 pixels it fails when:
 *
 * - **the page scrolls sideways.** A wide table scrolls inside its own box;
 *   the page itself never does, at any width;
 * - **something a finger has to hit is under 44px tall**: a button, a field,
 *   a select, a nav or tab link;
 * - **text on a phone is under 15px.** At 360 only, and not for the small
 *   labels the design sets smaller on purpose (`.label`, `.tag`, `.revised`,
 *   `.nav-heading`, `.tab-label`);
 * - **a table is wider than a phone's screen.** Below 640px a list table is a
 *   stack of cards (`design.css`'s `table.stack`). Only the three whose columns
 *   are the point may scroll sideways, `WIDE_TABLES`, and each of those needs
 *   a `.wide` scroller and a visible "swipe for more" cue before it;
 * - **"Waiting for you" says a bare number** where it means days;
 * - **a dashboard tile's figure wraps or spills out of its tile** at 1024px or
 *   wider, where the tiles run four across and are narrowest. A screen can
 *   ask for extra widths (`widths`) to be measured at that edge exactly.
 *
 * And it saves a screenshot of every one, which CI uploads as the `screens`
 * artifact: `<width>/<screen>.png`.
 *
 * Classnode's own public site (`website/`, on the bare platform domain: the
 * homepage, the privacy notice and the terms) is photographed at nine widths, `SITE_WIDTHS`, under reduced motion so every
 * section is in its finished state, with its lazy images scrolled in. It is
 * also held to its own layout: content stops at 1160px and sits in the middle,
 * the nav is a menu button below 1024px, and on a phone the page has 16px each
 * side, the hero's buttons are full width, every screen is in the phone
 * frame, the principal's face is clear of it and of the card, and the one card
 * shows only beside a screen that does not already print its figure. Its motion (the slider, the network, the floating
 * cards, the counting figures) is checked in its own `describe` below.
 *
 * ## What it runs against
 *
 * The demo (`manage.py seed_demo`), served by the development server, with
 * `PLATFORM_DOMAIN=classnode.test`. `*.classnode.test` is pointed at this
 * machine by Chromium's own resolver, so nothing needs a hosts file, and the
 * session cookie is scoped to the domain every school's host shares, which is
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

const SITE = `http://${DOMAIN}:${PORT}`;
const PORTAL = `http://app.${DOMAIN}:${PORT}`;
const SUNRISE = `http://sunrise-demo.${DOMAIN}:${PORT}`;
const HARBOUR = `http://harbour-demo.${DOMAIN}:${PORT}`;

export const WIDTHS = [360, 768, 1280];

/** The public site's extra widths: a small Android, a small iPhone, a current iPhone, a large phone, a tablet held sideways, a desk monitor. */
export const SITE_WIDTHS = [320, 375, 390, 414, 1024, 1920];

/**
 * The only tables that may be wider than a phone: the broadsheet, the
 * timetable and the marking sheet (which is a list today, and would join
 * here if it ever became a table).
 */
const WIDE_TABLES = "table.broadsheet, table.week, table.marking-sheet, table.ogun-grid";

/**
 * Labels the design sets below body size on purpose. The dashboard's are its
 * small uppercase labels, its status chips and the captions under its two
 * drawings (`home/dashboard.css`).
 */
const SMALL_ON_PURPOSE =
  ".label, .tag, .revised, .nav-heading, .tab-label, .marks-summary, " +
  ".eyebrow, .chip, .spark-axis, .week-labels, .fee-split dt, " +
  // The administrator's setup chip in the top bar: a status chip like `.chip`,
  // 13px so the bar still fits a 360px phone beside the logo and the avatar.
  ".setup-chip, " +
  // The homepage's drawings of the product: pictures, each read by its
  // description (`role="img"` and `aria-label`, or `aria-hidden` beside a
  // screen that has one), like the screenshots beside them.
  ".mini, .float-card, .browser-bar, " +
  // The Ogun State sheet beside the report card's words: a drawing of the
  // paper sheet at its own sizes, its labels small as the paper's are.
  ".sheet, " +
  // The public footer: the owner's spec sets its links at 14px and its
  // column headings at 12px, white on navy at 9.3:1 and 5.6:1.
  ".site-foot";

/**
 * Every screen: who opens it, where, and the taps that reach its main state.
 * Each step is a selector to click (the first match), and each step's result is
 * a screenshot of its own.
 */
export const SCREENS = [
  // Classnode's own public site, on the bare domain.
  { name: "homepage", as: null, url: `${SITE}/`, widths: SITE_WIDTHS, site: true },
  { name: "privacy", as: null, url: `${SITE}/privacy/`, widths: SITE_WIDTHS, site: true },
  { name: "terms", as: null, url: `${SITE}/terms/`, widths: SITE_WIDTHS, site: true },

  // The doors, and what a family with no account uses.
  { name: "sign-in", as: null, url: `${PORTAL}/sign-in/` },
  { name: "staff-sign-in", as: null, url: `${PORTAL}/staff-sign-in/` },
  { name: "invitation", as: null, url: `${PORTAL}/invitations/not-a-token/` },
  { name: "checker", as: null, url: `${SUNRISE}/check/` },
  // The school's own public page, at its root, open to anyone.
  { name: "school-site", as: null, url: `${SUNRISE}/` },
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

  // The dashboard, as each role sees it. 1024 too: the tiles run four
  // across from there and are narrowest at that edge.
  { name: "home", as: "sunrise.principal", url: `${SUNRISE}/home/`, widths: [1024] },
  { name: "home-admin", as: "sunrise.admin", url: `${SUNRISE}/home/` },
  { name: "home-teacher", as: "sunrise.teacher", url: `${SUNRISE}/home/` },
  { name: "home-bursar", as: "sunrise.bursar", url: `${SUNRISE}/home/` },

  // Onboarding: Start here, a step, a locked step's page and Help, as the
  // demo's administrator (whose school is part set up), and Help as a teacher.
  { name: "start-here", as: "sunrise.admin", url: `${SUNRISE}/start/` },
  { name: "start-step", as: "sunrise.admin", url: `${SUNRISE}/start/school-details/` },
  { name: "start-report-card", as: "sunrise.admin", url: `${SUNRISE}/start/report-card/` },
  { name: "help", as: "sunrise.admin", url: `${SUNRISE}/help/` },
  { name: "help-teacher", as: "sunrise.teacher", url: `${SUNRISE}/help/` },

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

  { name: "bank", as: "sunrise.bursar", url: `${SUNRISE}/bank/` },

  // The office.
  { name: "setup", as: "sunrise.admin", url: `${SUNRISE}/setup/` },
  {
    name: "roll",
    as: "sunrise.admin",
    url: `${SUNRISE}/roll/`,
    steps: [
      ["roll-guardians", '[data-action="guardians"]'],
      ["roll-details", '[data-action="details"]'],
    ],
  },
  { name: "staff", as: "sunrise.admin", url: `${SUNRISE}/staff/` },
  // Subjects, this term's papers and the class teachers: the office's, one tap into a subject.
  {
    name: "teaching",
    as: "sunrise.admin",
    url: `${SUNRISE}/teaching/`,
    steps: [["teaching-subject", '[data-action="open-subject"]']],
  },
  { name: "roll-import", as: "sunrise.admin", url: `${SUNRISE}/roll/import/` },
  // The OGSERA filler. The demo school prints the Standard card, so this is
  // the page telling the office where the Ogun template is chosen.
  { name: "ogsera", as: "sunrise.admin", url: `${SUNRISE}/ogsera/` },

  // A parent, of one child with a released card and one without:
  // `seed_demo`'s own reason for releasing one class and not the other. The
  // switcher sorts by name (`_children_of()`'s own order), so "Ada", child 0
  // of JSS 1A, is always first and "Kemi", child 10 of JSS 1B, is always
  // second: a fact about the alphabet, not a guess about a random surname.
  // The second switcher tab is Kemi's, whichever school this is.
  {
    name: "cards",
    as: "sunrise.parent",
    url: `${SUNRISE}/cards/`,
    steps: [
      ["cards-second-child", ".child-switcher button:nth-of-type(2)"],
      ["card", ".cards a"],
    ],
  },

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
function measure({ smallOnPurpose, phone, wide, wideTables }) {
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

  if (wide) {
    for (const el of document.querySelectorAll(".kpi-value")) {
      if (!visible(el)) continue;
      const line = parseFloat(getComputedStyle(el).lineHeight);
      if (el.getBoundingClientRect().height > line * 1.5) problems.push(`tile figure wraps: ${describe(el)}`);
      if (el.scrollWidth > el.clientWidth + 1) problems.push(`tile figure spills out of its tile: ${describe(el)}`);
    }
  }

  if (phone) {
    for (const table of document.querySelectorAll("table")) {
      if (!visible(table)) continue;
      const holder = table.parentElement;
      const room = Math.min(root.clientWidth, holder ? holder.clientWidth : root.clientWidth);
      const width = Math.round(table.getBoundingClientRect().width);
      if (!table.matches(wideTables)) {
        if (width > room + 1) problems.push(`table ${width}px wide in ${room}px, and not one of the three that may scroll: ${describe(table)}`);
        continue;
      }
      const scroller = table.closest(".wide");
      if (!scroller) problems.push(`a wide table outside a .wide scroller: ${describe(table)}`);
      const cue = scroller && scroller.previousElementSibling;
      if (width > room + 1 && !(cue && cue.matches(".swipe-cue") && visible(cue))) {
        problems.push(`a wide table with no visible "swipe for more" cue: ${describe(table)}`);
      }
    }
    for (const cell of document.querySelectorAll(".waiting td.days")) {
      if (visible(cell) && /^\d+$/.test(cell.textContent.trim())) {
        problems.push(`"Waiting for you" says a bare "${cell.textContent.trim()}", not days`);
      }
    }

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

/** The public site's own layout rules, measured in the page. */
function measureSite({ width }) {
  const problems = [];
  const visible = (el) => {
    const box = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return box.width > 0 && box.height > 0 && style.visibility !== "hidden" && style.display !== "none";
  };
  const box = (el) => el.getBoundingClientRect();
  const overlaps = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
  const home = Boolean(document.querySelector("[data-slider]"));
  const room = document.documentElement.clientWidth;
  for (const wrap of document.querySelectorAll(".wrap")) {
    if (!visible(wrap)) continue;
    const r = box(wrap);
    if (r.width > 1160.5) problems.push(`a .wrap is ${Math.round(r.width)}px wide, past 1160`);
    if (width >= 1280 && Math.abs(r.left - (room - r.right)) > 1) problems.push("the content is not centred");
  }
  for (const img of document.images) {
    if (!img.alt || img.alt.length < 12) problems.push(`an image without a description: ${img.currentSrc || img.src}`);
  }
  const nav = document.querySelector(".site-nav");
  const toggle = document.querySelector(".menu-toggle");
  if (width < 1024 && (visible(nav) || !visible(toggle))) problems.push("the nav is not a menu button here");
  if (width >= 1024 && (!visible(nav) || visible(toggle))) problems.push("the nav is folded away on a wide screen");
  if (width < 640) {
    const size = (el) => parseFloat(getComputedStyle(el).fontSize);
    const gutter = box(document.querySelector("main .wrap")).left;
    if (Math.round(gutter) !== 16) problems.push(`the page padding is ${Math.round(gutter)}px, not 16`);
    for (const p of document.querySelectorAll("main p, main li, main summary")) {
      if (!visible(p) || p.closest(".mini, .float-card, .sheet, .todo, .slider-bar, .eyebrow")) continue;
      if (size(p) < 14.5) problems.push(`body text is ${size(p)}px, under 15: "${p.textContent.trim().slice(0, 30)}"`);
    }
    // The footer on a phone: all of it on the left, its links a thumb tall.
    const foot = document.querySelector(".site-foot");
    for (const el of foot.querySelectorAll("*")) {
      if (["right", "end", "center"].includes(getComputedStyle(el).textAlign)) {
        problems.push(`the footer's ${el.className || el.tagName} is not left-aligned`);
      }
    }
    const legal = foot.querySelector(".foot-legal");
    if (Math.round(box(legal).left) !== 16) problems.push("the footer's legal line is off the left edge");
    // It may wrap: text kept on one line runs past its box on a small phone.
    if (legal.scrollWidth > legal.clientWidth) problems.push(`the footer's legal line is ${legal.scrollWidth}px in ${legal.clientWidth}px`);
    for (const a of foot.querySelectorAll(".foot-col a")) {
      if (box(a).height < 44) problems.push(`a footer link is ${Math.round(box(a).height)}px tall, under 44: "${a.textContent.trim()}"`);
    }
  }
  if (width < 640 && home) {
    for (const button of document.querySelectorAll(".hero-actions .btn, .demo-form button")) {
      if (!visible(button)) continue;
      if (Math.abs(box(button).width - box(button.parentElement).width) > 1) {
        problems.push(`a button is not full width: "${button.textContent.trim()}"`);
      }
    }
  }
  return problems;
}

/**
 * The hero on a phone, on whichever screen is showing: that screen is in the
 * phone frame (the register's), at the left, the same box as every other
 * screen's; the principal's face, down to her shoulders, is under neither the
 * phone nor a card; and the "Fees collected" card shows only beside a screen
 * that does not already print that figure (`data-shows-fees`), clear of the
 * phone. Pure, like `measureSite`; [] on a page with no slider.
 */
function heroOnAPhone() {
  const problems = [];
  const slider = document.querySelector("[data-slider]");
  if (!slider) return problems;
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && style.visibility !== "hidden" && style.display !== "none";
  };
  const box = (el) => el.getBoundingClientRect();
  const overlaps = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
  const on = slider.querySelector(".slide.is-on");
  const name = on.dataset.name;
  const frames = [...slider.querySelectorAll(".slide")].map((s) => s.querySelector(".browser, .phone-frame"));
  const frame = on.querySelector(".browser, .phone-frame");
  const f = box(frame);
  const style = getComputedStyle(frame);
  if (style.backgroundColor !== getComputedStyle(slider.querySelector(".phone-frame")).backgroundColor || parseFloat(style.borderRadius) < 24) {
    problems.push(`${name}: not in the phone frame`);
  }
  if ([...frame.querySelectorAll(".browser-bar")].some(visible)) problems.push(`${name}: a browser bar on a phone`);
  const shot = box(frame.querySelector("img"));
  if (Math.abs(shot.width / shot.height - 300 / 649) > 0.01) problems.push(`${name}: the screen is not a phone's shape`);
  for (const other of frames) {
    const o = box(other);
    if (Math.abs(o.width - f.width) > 0.5 || Math.abs(o.left - f.left) > 0.5) problems.push(`${name}: the frames are not one size and place`);
  }
  if (Math.round(f.left) !== Math.round(box(slider).left)) problems.push(`${name}: the phone is not at the left`);

  const photo = box(document.querySelector(".photo-hero"));
  // Her face and shoulders: the top 56% of the photo, but for its outer edges.
  const face = {
    left: photo.left + photo.width * 0.1,
    right: photo.right - photo.width * 0.05,
    top: photo.top,
    bottom: photo.top + photo.height * 0.56,
  };
  if (overlaps(f, face)) problems.push(`${name}: the phone covers the principal's face`);
  const cards = [...document.querySelectorAll(".hero .float-card")].filter(visible);
  const want = on.hasAttribute("data-shows-fees") ? 0 : 1;
  if (cards.length !== want) problems.push(`${name}: ${cards.length} floating cards in the hero on a phone, not ${want}`);
  for (const card of cards) {
    if (overlaps(box(card), f)) problems.push(`${name}: a floating card covers the screen`);
    if (overlaps(box(card), face)) problems.push(`${name}: a floating card covers the principal's face`);
  }
  return problems;
}

/** Every lazy image in, by scrolling the page through once, then back to the top. */
async function loadEverything(page) {
  await page.evaluate(async () => {
    for (let y = 0; y < document.body.scrollHeight; y += 400) {
      window.scrollTo(0, y);
      await new Promise((done) => setTimeout(done, 30));
    }
    window.scrollTo(0, 0);
    await Promise.all(
      [...document.images].map((img) => (img.complete ? null : new Promise((done) => img.addEventListener("load", done, { once: true })))),
    );
  });
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

async function check(page, width, name, site = false) {
  mkdirSync(join(OUT, String(width)), { recursive: true });
  const siteProblems = site ? await page.evaluate(measureSite, { width }) : [];
  if (site && width < 640) siteProblems.push(...(await page.evaluate(heroOnAPhone)));
  await page.screenshot({ path: join(OUT, String(width), `${name}.png`), fullPage: true });
  return (
    await page.evaluate(measure, {
      smallOnPurpose: SMALL_ON_PURPOSE,
      phone: width < 640,
      wide: width >= 1024,
      wideTables: WIDE_TABLES,
    })
  )
    .concat(siteProblems)
    .map((problem) => `${width}px ${name}: ${problem}`);
}

before(async () => {
  browser = await chromium.launch({
    args: [
      `--host-resolver-rules=MAP *.${DOMAIN} 127.0.0.1, MAP ${DOMAIN} 127.0.0.1`,
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
        // The public site is photographed finished and still: its motion is
        // the next `describe`'s.
        if (screen.site) await page.emulateMedia({ reducedMotion: "reduce" });
        for (const width of [...WIDTHS, ...(screen.widths || [])]) {
          await page.setViewportSize({ width, height: 800 });
          const response = await page.goto(screen.url);
          assert.equal(response.status(), screen.status || 200, `${screen.url} at ${width}px`);
          await settle(page);
          if (screen.site) await loadEverything(page);
          problems.push(...(await check(page, width, screen.name, screen.site)));

          for (const [name, selector] of screen.steps || []) {
            const target = page.locator(selector).first();
            // The previous tap's page can still be drawing from its fetch when
            // `settle()` returns (the fees class did, once, on CI), so give the
            // step's target a moment to arrive before calling it missing. The
            // specimen's menu button never arrives above 1024px, which is why
            // it is only a wait and not the assertion.
            await target.waitFor({ state: "attached", timeout: screen.specimen ? 1 : 5000 }).catch(() => {});
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

describe("the phone menu", () => {
  // The principal has the longest menu, and a phone held sideways is the
  // shortest screen a staff room has. Sign out sits at the menu's foot on
  // both, with nothing to scroll to reach it: the links above it scroll.
  for (const [width, height] of [[360, 740], [360, 560], [740, 360]]) {
    test(`sign out is on screen when the menu opens at ${width}x${height}`, async () => {
      const context = await signedIn("sunrise.principal");
      const page = await context.newPage();
      try {
        await page.setViewportSize({ width, height });
        await page.goto(`${SUNRISE}/home/`);
        await settle(page);
        await page.click(".menu-button");
        await page.waitForFunction(() => document.querySelector("#sidebar").matches(":popover-open"));
        mkdirSync(join(OUT, String(width)), { recursive: true });
        await page.screenshot({ path: join(OUT, String(width), `menu-${width}x${height}.png`) });

        const button = page.locator("#sidebar .nav-end button");
        const box = await button.boundingBox();
        assert.ok(box, "no Sign out in the menu");
        assert.ok(box.y >= 0 && box.y + box.height <= height, `Sign out is at ${box.y}px of a ${height}px screen`);
        assert.equal(await button.textContent(), "Sign out");
        // And it is the foot: nothing of the menu below it.
        const foot = await page.evaluate(() => {
          const menu = document.querySelector("#sidebar").getBoundingClientRect();
          const end = document.querySelector("#sidebar .nav-end").getBoundingClientRect();
          return Math.round(menu.bottom - end.bottom);
        });
        assert.ok(foot <= 16, `${foot}px of menu below Sign out`);
      } finally {
        await page.close();
      }
    });
  }
});

describe("a phone's 390px", () => {
  // The four teacher screens that carry the fixed bottom tab bar. Scrolled to
  // the foot, the last control must sit above the bar, and the page's own
  // bottom padding must be the bar's height: a bar over the last button is a
  // button nobody can press.
  const WITH_TAB_BAR = [
    ["register", "/register/", ['[data-action="open"]']],
    ["marking", "/marking/", ['[data-action="pick-assessment"]', '[data-action="pick-class"]']],
    ["remarks", "/comments/", []],
    ["timetable", "/timetable/", []],
  ];
  for (const [name, path, steps] of WITH_TAB_BAR) {
    for (const height of [844, 640]) {
      test(`${name}: the last control clears the tab bar on a ${height}px screen`, async () => {
        const context = await signedIn("sunrise.teacher");
        const page = await context.newPage();
        try {
          await page.setViewportSize({ width: 390, height });
          await page.goto(`${SUNRISE}${path}`);
          await settle(page);
          for (const selector of steps) {
            await page.locator(selector).first().click();
            await settle(page);
          }
          const found = await page.evaluate(() => {
            window.scrollTo(0, document.documentElement.scrollHeight);
            const bar = document.querySelector(".tabbar").getBoundingClientRect();
            const content = getComputedStyle(document.querySelector(".content"));
            const controls = [...document.querySelectorAll(".content button, .content a, .content input, .content select")].filter((el) => {
              const box = el.getBoundingClientRect();
              return box.width > 0 && box.height > 0 && getComputedStyle(el).visibility !== "hidden";
            });
            const foot = Math.max(...controls.map((el) => el.getBoundingClientRect().bottom));
            const all = [...document.querySelectorAll(".content *")].filter((el) => el.getBoundingClientRect().height > 0);
            return {
              barTop: bar.top,
              barHeight: bar.height,
              padding: parseFloat(content.paddingBottom),
              foot,
              content: Math.max(...all.map((el) => el.getBoundingClientRect().bottom)),
              controls: controls.length,
            };
          });
          assert.ok(found.controls > 0, `${name}: no control on the page`);
          assert.ok(Math.abs(found.padding - found.barHeight) <= 1, `${name}: ${found.padding}px of bottom padding under a ${found.barHeight}px bar`);
          assert.ok(found.foot <= found.barTop + 0.5, `${name}: the last control ends at ${found.foot}px, under the bar at ${found.barTop}px`);
          assert.ok(found.content <= found.barTop + 0.5, `${name}: content runs to ${found.content}px, under the bar at ${found.barTop}px`);
        } finally {
          await page.close();
        }
      });
    }
  }

  test("marks entry: every box is one width, right-aligned, with its right edges on one line", async () => {
    const context = await signedIn("sunrise.teacher");
    const page = await context.newPage();
    try {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(`${SUNRISE}/marking/`);
      await settle(page);
      for (const selector of ['[data-action="pick-assessment"]', '[data-action="pick-class"]']) {
        await page.locator(selector).first().click();
        await settle(page);
      }
      await page.waitForSelector(".roster input");
      const boxes = await page.evaluate(() =>
        [...document.querySelectorAll(".roster input")].map((el) => {
          const box = el.getBoundingClientRect();
          return { width: Math.round(box.width * 10) / 10, right: Math.round(box.right * 10) / 10, align: getComputedStyle(el).textAlign };
        }),
      );
      assert.ok(boxes.length > 3, "the sheet has no mark boxes");
      assert.equal(new Set(boxes.map((b) => b.width)).size, 1, `box widths: ${[...new Set(boxes.map((b) => b.width))]}`);
      assert.equal(new Set(boxes.map((b) => b.right)).size, 1, "the right edges do not line up");
      assert.ok(boxes.every((b) => b.align === "right" || b.align === "end"), "a box is not right-aligned");
      // 1, 2 and 3 digits in the same boxes, and the boxes do not move.
      const input = page.locator(".roster input").first();
      const before = await input.boundingBox();
      for (const value of ["7", "70", "100"]) {
        await input.fill(value);
        const box = await input.boundingBox();
        assert.equal(Math.round(box.width * 10), Math.round(before.width * 10), `the box changed width at ${value}`);
        assert.equal(Math.round(box.x * 10), Math.round(before.x * 10), `the box moved at ${value}`);
      }
      await input.fill("");
    } finally {
      await page.close();
    }
  });
});

describe("the roll import's preview", () => {
  // A file is chosen, not tapped, so the drill-down above cannot reach the
  // preview. One good row and one with three problems, checked and never
  // admitted: the demo's roll is the same after this test as before it.
  const FILE = [
    "Full name,Class group,Reference,Username,Guardian name,Guardian contact",
    "Adaeze Okonkwo-Bamidele,JSS 1A,SD/2026/9001,,Mrs Chinwe Okonkwo-Bamidele,08031234567",
    ",JSS 9Z,SD/2026/9001,,Mr Eze,not a number",
  ].join("\r\n");

  test("roll-import-preview", async () => {
    const context = await signedIn("sunrise.admin");
    const page = await context.newPage();
    const problems = [];
    try {
      for (const width of WIDTHS) {
        await page.setViewportSize({ width, height: 800 });
        await page.goto(`${SUNRISE}/roll/import/`);
        await settle(page);
        await page.setInputFiles("#file", { name: "jss1.csv", mimeType: "text/csv", buffer: Buffer.from(FILE) });
        await page.click('[data-form="check"] button[type="submit"]');
        await page.waitForSelector('[data-state="preview"]');
        await settle(page);
        assert.equal(await page.locator('[data-action="admit"]').count(), 0, "a file with problems offered to admit");
        assert.equal(await page.locator("tr.to-fix").count(), 1);
        problems.push(...(await check(page, width, "roll-import-preview")));
      }
    } finally {
      await page.close();
    }
    assert.deepEqual(problems, []);
  });
});

describe("the homepage's sizes", () => {
  // The owner's sizing rules, measured finished and still on a 375 x 812 phone
  // and a 1280 x 800 desk: the hero 30 to 36px and 48 to 56px with a line
  // height about 1.1, section headlines 24 to 28px and 32 to 40px, other
  // headings at most 28px and 40px, body copy 15 to 16px and 16 to 17px,
  // small labels 13 to 14px, buttons 44 to 48px tall with 15 to 16px words and
  // 8 to 10px corners, sections 48 to 64px and 80 to 112px top and bottom,
  // cards 20 to 24px in and 12 to 16px round, content at most 1200px wide, two
  // font weights a section at most, no long centred paragraph, and the phone's
  // first screen holding the headline, its subline, the main button and the
  // top of the screens.
  for (const [width, height, phone] of [[375, 812, true], [1280, 800, false]]) {
    test(`at ${width} x ${height}`, async () => {
      const context = await browser.newContext({ viewport: { width, height }, reducedMotion: "reduce" });
      const page = await context.newPage();
      try {
        await page.goto(`${SITE}/`);
        await page.waitForLoadState("networkidle");
        // The deferred screens in, so the first screen is the one a visitor keeps.
        await page.waitForTimeout(2000);
        const problems = await page.evaluate((phone) => {
          const found = [];
          const visible = (el) => {
            const box = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            return box.width > 0 && box.height > 0 && style.display !== "none" && style.visibility !== "hidden";
          };
          const size = (el) => parseFloat(getComputedStyle(el).fontSize);
          const within = (what, value, low, high) => {
            if (value < low - 0.5 || value > high + 0.5) found.push(`${what} is ${Math.round(value * 10) / 10}px, not ${low} to ${high}`);
          };
          const main = document.querySelector("main");
          const h1 = main.querySelector("h1");
          within("the hero headline", size(h1), ...(phone ? [30, 36] : [48, 56]));
          within("the hero's line height x 10", (parseFloat(getComputedStyle(h1).lineHeight) / size(h1)) * 10, 10.5, 11.5);
          for (const h of main.querySelectorAll("h2")) {
            if (visible(h)) within(`the headline "${h.textContent.trim().slice(0, 24)}"`, size(h), ...(phone ? [24, 28] : [32, 40]));
          }
          for (const h of main.querySelectorAll("h3")) {
            if (visible(h)) within(`"${h.textContent.trim().slice(0, 24)}"`, size(h), 0, phone ? 28 : 40);
          }
          const copy = [...main.querySelectorAll("p, li, summary, label")].filter(
            (el) => visible(el) && !el.closest(".mini, .float-card, .sheet, .slider-bar, .eyebrow, .bait"),
          );
          for (const el of copy) within(`body copy "${el.textContent.trim().slice(0, 24)}"`, size(el), ...(phone ? [15, 16] : [16, 17]));
          const labels = ".eyebrow, .chip, .mark, .fc-label, .fc-of, .sheet-title, .sheet-label, .sheet-who dt, .sheet-grid thead th, .tile";
          for (const el of main.querySelectorAll(labels)) {
            if (visible(el)) within(`the label "${el.textContent.trim().slice(0, 18)}"`, size(el), 13, 14);
          }
          for (const b of document.querySelectorAll(".btn, button")) {
            if (!visible(b)) continue;
            const what = `the button "${b.textContent.trim().slice(0, 18)}"`;
            within(`${what}'s height`, b.getBoundingClientRect().height, 44, 48);
            // The slider's own controls (its dots and Pause) are the slider's, and kept as they are.
            if (b.closest(".slider-bar")) continue;
            within(`${what}'s words`, size(b), 15, 16);
            within(`${what}'s corners`, parseFloat(getComputedStyle(b).borderTopLeftRadius), 8, 10);
          }
          for (const c of main.querySelectorAll(".step, .price-band, .included, .demo-card")) {
            const style = getComputedStyle(c);
            for (const side of ["paddingTop", "paddingRight", "paddingBottom", "paddingLeft"]) {
              within(`the card .${c.classList[0]} ${side}`, parseFloat(style[side]), 20, 24);
            }
          }
          for (const c of main.querySelectorAll(".step, .price-card, .demo-card, .faq-list")) {
            within(`the card .${c.classList[0]}'s corners`, parseFloat(getComputedStyle(c).borderTopLeftRadius), 12, 16);
          }
          for (const s of main.querySelectorAll(".hero, .feature-row, .section, .cta")) {
            const weights = new Set();
            const walk = document.createTreeWalker(s, NodeFilter.SHOW_TEXT);
            while (walk.nextNode()) {
              const el = walk.currentNode.parentElement;
              if (walk.currentNode.textContent.trim() && visible(el)) weights.add(getComputedStyle(el).fontWeight);
            }
            if (weights.size > 2) found.push(`.${s.classList[0]} uses ${weights.size} font weights`);
          }
          for (const p of main.querySelectorAll("p, li")) {
            if (visible(p) && getComputedStyle(p).textAlign === "center" && p.textContent.trim().length > 90) {
              found.push(`a long centred paragraph: "${p.textContent.trim().slice(0, 24)}"`);
            }
          }
          for (const s of main.querySelectorAll(".section, .cta, .feature-row")) {
            const style = getComputedStyle(s);
            for (const side of ["paddingTop", "paddingBottom"]) {
              within(`${s.className.split(" ").slice(0, 2).join(".")} ${side}`, parseFloat(style[side]), ...(phone ? [48, 64] : [80, 112]));
            }
          }
          for (const w of document.querySelectorAll(".wrap")) {
            if (visible(w) && w.getBoundingClientRect().width > 1200.5) found.push(`a .wrap is ${Math.round(w.getBoundingClientRect().width)}px wide`);
          }
          if (document.documentElement.scrollWidth > innerWidth) found.push(`scrolls sideways: ${document.documentElement.scrollWidth}px`);
          if (phone) {
            for (const [what, sel] of [["the headline", ".hero h1"], ["the subline", ".hero-lead"], ["the main button", ".hero-actions .btn"]]) {
              if (document.querySelector(sel).getBoundingClientRect().bottom > innerHeight) found.push(`${what} is below the first screen`);
            }
            const screens = document.querySelector(".slider").getBoundingClientRect().top;
            if (screens > innerHeight - 96) found.push(`the screens start at ${Math.round(screens)}px, under 96px of them on the first screen`);
          }
          return found;
        }, phone);
        mkdirSync(join(OUT, String(width)), { recursive: true });
        await page.screenshot({ path: join(OUT, String(width), "homepage-first-screen.png") });
        assert.deepEqual(problems, []);
      } finally {
        await context.close();
      }
    });
  }
});

describe("the hero on a phone", () => {
  // Every screen in turn, by its dot, held to `heroOnAPhone`: each one in the
  // register's phone frame, her face clear, the fees card beside only the
  // screens that do not print it. From 640px the desk keeps its frames.
  for (const width of [320, 375, 414]) {
    test(`every screen at ${width}px`, async () => {
      const context = await browser.newContext({ viewport: { width, height: 812 }, reducedMotion: "reduce" });
      const page = await context.newPage();
      try {
        await page.goto(`${SITE}/`);
        await page.waitForLoadState("networkidle");
        const problems = [];
        for (let n = 0; n < 4; n++) {
          await page.click(`[data-go="${n}"]`);
          await page.mouse.move(0, 0);
          problems.push(...(await page.evaluate(heroOnAPhone)));
        }
        assert.deepEqual(problems, []);
      } finally {
        await context.close();
      }
    });
  }

  for (const width of [640, 768]) {
    test(`the desk's frames from ${width}px`, async () => {
      const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: "reduce" });
      const page = await context.newPage();
      try {
        await page.goto(`${SITE}/`);
        const bars = await page.evaluate(() =>
          [...document.querySelectorAll(".slide")].map((s) => {
            const bar = s.querySelector(".browser-bar");
            return bar ? getComputedStyle(bar).display !== "none" : "phone";
          }),
        );
        assert.deepEqual(bars, [true, true, "phone", true]);
      } finally {
        await context.close();
      }
    });
  }
});

describe("the homepage's motion", () => {
  // The slider runs on `setTimeout`, so the page's clock is Playwright's here
  // and five seconds pass when the test says so. The network, the floating
  // cards, the dot grids and the fade and rise are CSS, on the browser's own
  // clock, and are read from `getAnimations()`.
  const current = (page) => page.locator("[data-slider]").getAttribute("data-current");

  async function open(options = {}) {
    const context = await browser.newContext({ viewport: { width: 1280, height: 800 }, ...options });
    const page = await context.newPage();
    return { context, page };
  }

  async function at(page) {
    // Paused before the page exists, so no timer of the page's runs until the
    // test moves the clock.
    await page.clock.install({ time: new Date("2026-10-05T08:00:00Z") });
    await page.clock.pauseAt(new Date("2026-10-05T08:00:01Z"));
    await page.goto(`${SITE}/`);
    await page.waitForLoadState("networkidle");
  }

  test("the slider moves every 5 seconds, crossfading in 600ms, and holds on hover, keyboard focus, a touch and its pause button", async () => {
    const { context, page } = await open({ hasTouch: true });
    try {
      await at(page);
      await page.mouse.move(5, 795);
      assert.equal(await current(page), "0");
      await page.clock.runFor(4900);
      assert.equal(await current(page), "0", "moved before 5 seconds");
      await page.clock.runFor(200);
      assert.equal(await current(page), "1");
      for (const next of ["2", "3", "0"]) {
        await page.clock.runFor(5000);
        assert.equal(await current(page), next);
      }
      const fade = await page.locator(".slide").first().evaluate((el) => {
        const style = getComputedStyle(el);
        return [style.transitionProperty, style.transitionDuration];
      });
      assert.match(fade[0], /^opacity/);
      assert.match(fade[1], /^0\.6s/);
      assert.equal(await page.locator(".slide.is-on").count(), 1);
      assert.equal(await page.locator(".slide[inert]").count(), 3);
      // Every screen's images have been asked for by now, after the page loaded.
      assert.equal(await page.locator(".slides [data-srcset]").count(), 0);

      // Hover holds it; leaving lets it go on.
      await page.hover(".slides");
      await page.clock.runFor(16000);
      assert.equal(await current(page), "0", "moved under the pointer");
      await page.mouse.move(5, 795);
      await page.clock.runFor(5100);
      assert.equal(await current(page), "1");

      // A dot jumps, and keyboard focus on it holds the slider there.
      await page.focus(".hero-actions .btn-outline");
      await page.keyboard.press("Tab"); // the pause button, which holds nothing
      await page.keyboard.press("Tab"); // the first dot
      await page.keyboard.press("Tab"); // the second
      await page.keyboard.press("Tab"); // the third
      await page.keyboard.press("Enter");
      assert.equal(await current(page), "2");
      assert.equal(await page.locator('[data-go="2"]').getAttribute("aria-current"), "true");
      await page.clock.runFor(16000);
      assert.equal(await current(page), "2", "moved with keyboard focus inside");
      await page.focus(".hero-actions .btn-outline");
      await page.clock.runFor(5100);
      assert.equal(await current(page), "3");

      // A touch holds it while the finger is down and for two seconds after.
      await page.locator(".hero-actions .btn-outline").blur();
      const slides = await page.locator(".slides").boundingBox();
      await page.touchscreen.tap(slides.x + 20, slides.y + 20);
      await page.clock.runFor(6500);
      assert.equal(await current(page), "3", "moved under a finger");
      await page.clock.runFor(800);
      assert.equal(await current(page), "0");

      // The pause button stops it until it is pressed again.
      await page.click("[data-pause]");
      await page.mouse.move(5, 795);
      assert.equal(await page.locator("[data-pause]").getAttribute("aria-pressed"), "true");
      await page.clock.runFor(30000);
      assert.equal(await current(page), "0", "moved while paused");
      await page.click("[data-pause]");
      await page.mouse.move(5, 795);
      await page.clock.runFor(5100);
      assert.equal(await current(page), "1");
    } finally {
      await context.close();
    }
  });

  test("under reduced motion nothing moves: the first screen, no pause button, no animation, final figures", async () => {
    const { context, page } = await open({ reducedMotion: "reduce" });
    try {
      await at(page);
      await page.clock.runFor(30000);
      assert.equal(await current(page), "0", "moved under reduced motion");
      assert.equal(await page.locator("[data-pause]").isVisible(), false);
      assert.equal(await page.locator(".slide").first().evaluate((el) => getComputedStyle(el).transitionDuration), "0s");
      await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
      assert.equal(await page.evaluate(() => document.getAnimations().length), 0);
      const figures = await page.evaluate(() => [...document.querySelectorAll("[data-count]")].map((x) => [x.dataset.count, x.textContent]));
      for (const [want, shown] of figures) assert.equal(shown, want);
      const hidden = await page.evaluate(() =>
        [...document.querySelectorAll(".reveal, .n-dots circle")].filter((el) => getComputedStyle(el).opacity !== "1").length,
      );
      assert.equal(hidden, 0, "something is left undrawn");
      // The dots still change the screen, at once.
      await page.click('[data-go="1"]');
      assert.equal(await current(page), "1");
    } finally {
      await context.close();
    }
  });

  // The report sheet: empty when it arrives, row by row as the page scrolls,
  // complete with every total counted and every grade stamped by the end, on
  // a desk (pinned) and a phone (rising up the screen).
  for (const [width, height] of [[1280, 800], [390, 800]]) {
    test(`the report sheet fills in as the page scrolls, at ${width}px`, async () => {
      const { context, page } = await open({ viewport: { width, height } });
      try {
        await page.goto(`${SITE}/`);
        await page.waitForLoadState("networkidle");
        // The deferred screens land first, so the page below the hero has stopped moving.
        await page.waitForTimeout(2000);
        const state = () =>
          page.evaluate(() => {
            const cells = [...document.querySelectorAll(".sheet .ink, .sheet .stamp")];
            const counted = [...document.querySelectorAll(".sheet .ink-sum, .sheet .ink-total")].map((x) =>
              getComputedStyle(x).getPropertyValue("--n").trim() === x.textContent.trim(),
            );
            return { shown: cells.filter((x) => getComputedStyle(x).opacity === "1").length, all: cells.length, counted };
          });
        const scrollTo = (y) => page.evaluate((top) => window.scrollTo({ top, behavior: "instant" }), y);
        const { top, size } = await page.evaluate(() => {
          const el = document.querySelector(innerWidth >= 900 ? ".sheet-row" : ".sheet");
          return { top: el.getBoundingClientRect().top + scrollY, size: el.offsetHeight };
        });
        await scrollTo(top - height);
        await page.waitForTimeout(100);
        const before = await state();
        assert.equal(before.shown, 0, "the sheet is filled before it arrives");
        const middle = width >= 900 ? top + (size - height) * 0.45 : top - height + (size + height) * 0.45;
        await scrollTo(middle);
        await page.waitForTimeout(100);
        const during = await state();
        assert.ok(during.shown > 0 && during.shown < during.all, `${during.shown} of ${during.all} filled halfway`);
        await scrollTo(top + size);
        await page.waitForTimeout(100);
        const after = await state();
        assert.equal(after.shown, after.all, "the sheet is not complete at the end");
        assert.deepEqual(after.counted, after.counted.map(() => true), "a total stopped short");
      } finally {
        await context.close();
      }
    });
  }

  test("under reduced motion the report sheet is complete and does not move", async () => {
    const { context, page } = await open({ reducedMotion: "reduce" });
    try {
      await page.goto(`${SITE}/`);
      await page.locator(".sheet").scrollIntoViewIfNeeded();
      const still = await page.evaluate(() =>
        [...document.querySelectorAll(".sheet .ink, .sheet .stamp")].every(
          (x) => getComputedStyle(x).opacity === "1" && getComputedStyle(x).color !== "rgba(0, 0, 0, 0)",
        ),
      );
      assert.ok(still, "something on the sheet is left undrawn");
      assert.equal(await page.evaluate(() => document.querySelector(".sheet-row").offsetHeight < innerHeight * 2), true, "the sheet is pinned");
    } finally {
      await context.close();
    }
  });

  for (const width of [1280, 360]) {
    test(`only the floating cards, the network's dots and the dot grids loop, at ${width}px`, async () => {
      const { context, page } = await open({ viewport: { width, height: 800 } });
      try {
        await page.goto(`${SITE}/`);
        await page.waitForLoadState("networkidle");
        const LOOPS = new Set(["float", "breathe", "drift"]);
        const kinds = new Set();
        for (let y = 0; y < (await page.evaluate(() => document.body.scrollHeight)); y += 300) {
          await page.evaluate((top) => window.scrollTo(0, top), y);
          await page.waitForTimeout(60);
          for (const a of await page.evaluate(() =>
            document.getAnimations().map((a) => {
              const t = a.effect.getComputedTiming();
              return {
                name: a.animationName || a.transitionProperty,
                iterations: t.iterations,
                duration: t.duration,
                target: a.effect.target.closest(".nodes, .float-card, .dot-grid, .reveal, .slide, .slider-dots, .btn, .step, .sheet")
                  ? "ok" : a.effect.target.outerHTML.slice(0, 60),
              };
            }),
          )) {
            assert.equal(a.target, "ok", `something else moves: ${a.target}`);
            if (LOOPS.has(a.name)) assert.equal(a.iterations, Infinity, `${a.name} stops`);
            else assert.equal(a.iterations, 1, `${a.name} repeats`);
            if (a.name === "float") assert.ok(a.duration >= 4000 && a.duration <= 6000, `a card floats over ${a.duration}ms`);
            kinds.add(a.name);
          }
        }
        for (const name of ["draw", "breathe", "float", "drift", "rise", "write", "add-up", "stamp"]) assert.ok(kinds.has(name), `${name} never ran: ${[...kinds]}`);
        // Every figure counted up to the screens' own figure.
        await page.waitForTimeout(1500);
        const figures = await page.evaluate(() =>
          [...document.querySelectorAll("[data-count]")].filter((x) => x.getClientRects().length).map((x) => [x.dataset.count, x.textContent]),
        );
        assert.ok(figures.length >= 2);
        for (const [want, shown] of figures) assert.equal(Number(shown), Number(want), "a figure stopped short");
      } finally {
        await context.close();
      }
    });
  }
});
