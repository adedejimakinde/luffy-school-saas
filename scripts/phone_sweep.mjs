/**
 * The phone-width sweep (`docs/phone-width-sweep.md`): every staff, parent,
 * student, CBT and public page of the demo, at 320, 360, 390 and 412px, with
 * text at 100% and at 130%, photographed and measured for the faults a budget
 * Android with a large system font shows:
 *
 * - the page scrolls sideways;
 * - an element runs past the screen's edge (and is not inside a scroller);
 * - a button or field is wider than the screen;
 * - text is cut off (clipped by its box, not scrolled);
 * - two lines of text overlap;
 * - a table runs out of its card;
 * - a wide table scrolls with no visible edge to say there is more;
 * - an amount, a date, a class name, an admission number or a PIN is broken
 *   across two lines.
 *
 * 130% text is the browser's default font size raised from 16px to 20.8px
 * (`Page.setFontSizes`), which scales every `rem` the design uses, as a
 * system font of 130% does in Chrome on Android. Not run by CI: the 320px
 * guard is `tests/ui/phone_width.test.js`.
 *
 * Against the demo served as the `screens` job serves it, plus Crestfield
 * (`manage.py crestfield create`) with every role given SWEEP_PASSWORD:
 *
 *   node scripts/phone_sweep.mjs <out-dir>            # writes <out-dir>/report.json and PNGs
 *
 * SWEEP_ONLY=<substring> limits it to pages whose name contains it.
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { chromium } from "playwright";

const DOMAIN = process.env.SCREENS_DOMAIN || "classnode.test";
const PORT = process.env.SCREENS_PORT || "8000";
const PASSWORD = process.env.SWEEP_PASSWORD || "demo-pass-2026";
const OUT = process.argv[2] || "sweep";
const ONLY = process.env.SWEEP_ONLY || "";
const WIDTHS = (process.env.SWEEP_WIDTHS || "320,360,390,412").split(",").map(Number);
const ZOOMS = (process.env.SWEEP_ZOOMS || "100,130").split(",").map(Number);
const JOBS = Number(process.env.SWEEP_JOBS || 3);

const SITE = `http://${DOMAIN}:${PORT}`;
const PORTAL = `http://app.${DOMAIN}:${PORT}`;
const CF = `http://crestfield.${DOMAIN}:${PORT}`;
const SUNRISE = `http://sunrise-demo.${DOMAIN}:${PORT}`;
const HARBOUR = `http://harbour-demo.${DOMAIN}:${PORT}`;

// The CBT test `crestfield create` opened, and one JSS 2A student's slip.
const SIT = {
  code: process.env.SWEEP_SIT_CODE || "",
  number: process.env.SWEEP_SIT_NUMBER || "",
  pin: process.env.SWEEP_SIT_PIN || "",
};

const click = (selector) => async (page) => {
  await page.locator(selector).first().click();
};

/** [name, who, url, steps]. A step is [name, (page) => …]. */
const PAGES = [
  // Classnode's public site.
  ...["", "pricing/", "about/", "privacy/", "terms/", "faq/", "blog/",
    "result-computation-software/", "cbt-software-for-schools/", "school-result-checker/",
    "school-fees-management-software/", "school-website-design/", "school-management-software-lagos/",
    "excel-vs-school-software/"].map((p) => [`site-${p.replace(/\/$/, "") || "home"}`, null, `${SITE}/${p}`]),
  ["portal-sign-in", null, `${PORTAL}/sign-in/`],
  ["portal-staff-sign-in", null, `${PORTAL}/staff-sign-in/`],

  // Crestfield's public pages and doors: families, students, the CBT door.
  ["cf-website", null, `${CF}/`],
  ["cf-website-about", null, `${CF}/about/`],
  ["cf-website-admissions", null, `${CF}/admissions/`],
  ["cf-website-contact", null, `${CF}/contact/`],
  ["cf-website-gallery", null, `${CF}/gallery/`, [["cf-website-album", click(".album-card a, main a[href^='/gallery/']")]]],
  ["cf-website-menu", null, `${CF}/`, [["cf-website-menu-open", click(".menu summary")]]],
  ["cf-sign-in", null, `${CF}/sign-in/`],
  ["cf-staff-sign-in", null, `${CF}/staff-sign-in/`],
  ["cf-forgot-password", null, `${CF}/forgot-password/`],
  ["cf-checker", null, `${CF}/check/`],
  ["cf-test-scores-door", null, `${CF}/test-scores/`],
  ["cf-sit-door", null, `${CF}/sit/`, SIT.code ? [
    ["cf-sit-confirm", async (page) => {
      await page.fill("#code", SIT.code);
      await page.fill("#number", SIT.number);
      await page.fill("#pin", SIT.pin);
      await page.click('button[type="submit"]');
      await page.waitForSelector('[data-state="confirm"]');
    }],
    ["cf-sit-exam", async (page) => {
      await page.click('[data-action="start"]');
      await page.waitForSelector('[data-state="exam"]');
    }],
    ["cf-sit-calculator", click('[data-action="calculator"]:visible')],
  ] : []],

  // The principal.
  ["cf-home-principal", "cfc.principal", `${CF}/home/`],
  ["cf-results", "cfc.principal", `${CF}/results/`],
  ["cf-broadsheet", "cfc.principal", `${CF}/broadsheet/`, [["cf-broadsheet-class", click('[data-action="open-class"]')]]],
  ["cf-absences", "cfc.principal", `${CF}/absences/`],
  ["cf-promotion", "cfc.principal", `${CF}/promotion/`],
  ["cf-tests-principal", "cfc.principal", `${CF}/tests/`, [
    ["cf-tests-sitting", click('a[href^="#sitting/"]')],
  ]],
  ["cf-tests-banks", "cfc.principal", `${CF}/tests/#banks`],
  ["cf-exam-slips", "cfc.principal", `${CF}/exam-slips/`, [["cf-exam-slips-confirm", click('[data-action="ask-print-class"]')]]],
  ["cf-id-cards", "cfc.principal", `${CF}/id-cards/`, [["cf-id-cards-choose", click('[data-action="ask-print"]')]]],
  ["cf-subject-teachers", "cfc.principal", `${CF}/subject-teachers/`],
  ["cf-start-principal", "cfc.principal", `${CF}/start/`],
  ["cf-website-editor", "cfc.principal", `${CF}/website/`, [
    ["cf-website-editor-page", click('[data-action="open-page"][data-ref="home"]')],
    ["cf-website-editor-section", click('[data-action="edit-section"]')],
  ]],
  ["cf-website-photos", "cfc.principal", `${CF}/website/photos/`, [["cf-website-photos-album", click('[data-action="open-album"]')]]],
  ["cf-website-look", "cfc.principal", `${CF}/website/look/`],
  ["cf-notices", "cfc.principal", `${CF}/notices/settings/`],
  ["cf-ogsera", "cfc.principal", `${CF}/ogsera/`],

  // The vice principal (exam officer).
  ["cf-home-vp", "cfc.vp", `${CF}/home/`],
  ["cf-results-vp", "cfc.vp", `${CF}/results/`],
  ["cf-tests-vp", "cfc.vp", `${CF}/tests/`],

  // The administrator.
  ["cf-home-admin", "cfc.admin", `${CF}/home/`],
  ["cf-setup", "cfc.admin", `${CF}/setup/`],
  ["cf-roll", "cfc.admin", `${CF}/roll/`, [
    ["cf-roll-guardians", click('[data-action="guardians"]')],
    ["cf-roll-details", click('[data-action="details"]')],
  ]],
  ["cf-roll-import", "cfc.admin", `${CF}/roll/import/`],
  ["cf-staff", "cfc.admin", `${CF}/staff/`],
  ["cf-teaching", "cfc.admin", `${CF}/teaching/`, [["cf-teaching-subject", click('[data-action="open-subject"]')]]],
  ["cf-exam-slips-office", "cfc.admin", `${CF}/exam-slips/`],
  ["cf-help", "cfc.admin", `${CF}/help/`],
  ["cf-start-admin", "cfc.admin", `${CF}/start/`],
  ["cf-start-step", "cfc.admin", `${CF}/start/school-details/`],

  // The bursar.
  ["cf-home-bursar", "cfc.bursar", `${CF}/home/`],
  ["cf-fees", "cfc.bursar", `${CF}/fees/`, [
    ["cf-fees-class", click('[data-action="open-class"]')],
    ["cf-fees-account", click('[data-action="open-account"]')],
  ]],
  ["cf-bank", "cfc.bursar", `${CF}/bank/`],

  // A teacher (mathematics, class teacher of JSS 2B).
  ["cf-home-teacher", "cfc.teacher", `${CF}/home/`],
  ["cf-register", "cfc.teacher", `${CF}/register/`, [["cf-register-class", click('[data-action="open"]')]]],
  ["cf-marking", "cfc.teacher", `${CF}/marking/`, [
    ["cf-marking-sheet", click('[data-action="pick-assessment"]')],
  ]],
  ["cf-comments", "cfc.teacher", `${CF}/comments/`],
  ["cf-timetable", "cfc.teacher", `${CF}/timetable/`],
  ["cf-tests-teacher", "cfc.teacher", `${CF}/tests/`],
  ["cf-help-teacher", "cfc.teacher", `${CF}/help/`],

  // A parent of two released children.
  ["cf-cards", "cfc.parent", `${CF}/cards/`, [
    ["cf-cards-second-child", click(".child-switcher button:nth-of-type(2)")],
    ["cf-card", click(".cards a:visible")],
  ]],
  ["cf-test-scores-parent", "cfc.parent", `${CF}/test-scores/`],

  // What only the Sunrise and Harbour demo have: CBT results, ID card checks, the Ogun-free card.
  ["sun-test-results", "sunrise.principal", `${SUNRISE}/tests/`, [
    ["sun-test-results-page", click('.test-row:has-text("UI Results") a[href^="results/#"]')],
  ]],
  ["sun-test-scores-parent", "sunrise.uiresparent", `${SUNRISE}/test-scores/`],
  ["sun-id-card-valid", null, `${SUNRISE}/verify/UIidcardvalid001/`],
  ["sun-id-card-expired", null, `${SUNRISE}/verify/UIidcardexpire01/`],
  ["sun-cards", "sunrise.parent", `${SUNRISE}/cards/`, [["sun-cards-second-child", click(".child-switcher button:nth-of-type(2)")], ["sun-card", click(".cards a:visible")]]],
  ["harbour-website", null, `${HARBOUR}/`],
  ["harbour-website-boarding", null, `${HARBOUR}/pages/boarding/`],
];

/**
 * Everything wrong with the page as drawn, measured in it. Pure: it runs in
 * the page. Each problem is { kind, what, text }.
 */
function measure() {
  const problems = [];
  const root = document.documentElement;
  const vw = root.clientWidth;
  const push = (kind, el, text = "") => problems.push({ kind, what: el ? describe(el) : "", text: text.slice(0, 80) });

  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return false;
    const s = getComputedStyle(el);
    if (s.visibility === "hidden" || s.display === "none" || el.closest("[hidden], .sr, .visually-hidden")) return false;
    // Clipped to a pixel for a screen reader (`.sr`'s pattern under another name).
    for (let e = el; e && e !== document.body; e = e.parentElement) {
      const t = getComputedStyle(e);
      if (t.position === "absolute" && (t.clip !== "auto" || t.clipPath !== "none") && e.getBoundingClientRect().width <= 1) return false;
    }
    return true;
  };
  // A menu or popup laid over the page on purpose: what it covers is meant to be covered.
  const overlay = (el) => {
    for (let e = el; e && e !== document.body; e = e.parentElement) {
      const t = getComputedStyle(e).position;
      if ((t === "absolute" || t === "fixed") && e.closest("details[open], [popover]:popover-open, dialog[open]")) return true;
    }
    return false;
  };
  const ownText = (el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
  function describe(el) {
    const name = (e) => e.tagName.toLowerCase() + (e.id ? `#${e.id}` : "") + [...e.classList].slice(0, 2).map((c) => `.${c}`).join("");
    const parts = [name(el)];
    for (let up = el.parentElement, n = 0; up && up !== document.body && n < 2; up = up.parentElement) {
      if (up.classList.length || up.id) { parts.unshift(name(up)); n++; }
    }
    return parts.join(" > ");
  }
  // An ancestor that scrolls or clips sideways: what runs past it is that box's to show.
  const clipper = (el) => {
    for (let up = el.parentElement; up && up !== document.body && up !== root; up = up.parentElement) {
      const o = getComputedStyle(up).overflowX;
      if (o !== "visible") return up;
    }
    return null;
  };
  const fixedish = (el) => {
    for (let e = el; e && e !== document.body; e = e.parentElement) {
      const p = getComputedStyle(e).position;
      if (p === "fixed") return true;
    }
    return false;
  };
  const drawing = ".mini, .float-card, .browser, .browser-bar, .sheet, .hero-screen, .tour-slides, .n-lines, svg, [popover]:not(:popover-open)";

  if (root.scrollWidth > vw) push("page-scrolls-sideways", null, `${root.scrollWidth}px of content in ${vw}px`);

  // Elements past the edge: the outermost that is not inside a scroller.
  const all = [...document.body.querySelectorAll("*")];
  const past = new Set();
  for (const el of all) {
    if (el.closest(drawing) || !visible(el) || fixedish(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.right <= vw + 1 && r.left >= -1) continue;
    const c = clipper(el);
    if (c) continue;
    past.add(el);
  }
  for (const el of past) {
    if (el.parentElement && past.has(el.parentElement)) continue;
    const r = el.getBoundingClientRect();
    push("past-the-edge", el, `${Math.round(r.left)}..${Math.round(r.right)} in ${vw}`);
  }

  // Buttons and fields wider than the screen, or than the box they sit in.
  for (const el of document.querySelectorAll("button, .btn, input:not([type=checkbox]):not([type=radio]):not([type=hidden]), select, textarea")) {
    if (!visible(el) || el.closest(drawing) || clipper(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width > vw + 0.5 || r.right > vw + 1) push("button-wider-than-screen", el, `${Math.round(r.width)}px, right edge ${Math.round(r.right)} in ${vw}`);
    else if (el.scrollWidth > el.clientWidth + 1 && el.tagName !== "SELECT" && el.tagName !== "INPUT" && el.tagName !== "TEXTAREA") push("text-cut-off", el, el.textContent.trim());
  }

  // Text cut off: a box that hides overflow and has more text than room, and does not scroll.
  for (const el of all) {
    if (!visible(el) || el.closest(drawing)) continue;
    const s = getComputedStyle(el);
    if (s.overflowX === "auto" || s.overflowX === "scroll") continue;
    const clipsX = s.overflowX === "hidden" || s.overflowX === "clip" || s.textOverflow === "ellipsis";
    const clipsY = s.overflowY === "hidden" || s.overflowY === "clip" || s.webkitLineClamp !== "none" && s.webkitLineClamp;
    if (!ownText(el) || el.matches(".sr, .visually-hidden")) continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 2 && r.height <= 2) continue;
    if ((clipsX && el.scrollWidth > el.clientWidth + 1) || (clipsY && el.scrollHeight > el.clientHeight + 2 && el.clientHeight > 0)) {
      if (el.querySelector("img, picture") && !el.textContent.trim()) continue;
      push("text-cut-off", el, el.textContent.trim().replace(/\s+/g, " "));
    }
  }

  // Tables out of their card, and wide tables with no visible edge.
  for (const table of document.querySelectorAll("table")) {
    if (!visible(table)) continue;
    const t = table.getBoundingClientRect();
    const card = table.closest(".card, .class-card, section, main, .content");
    const c = clipper(table);
    if (card && !c) {
      const b = card.getBoundingClientRect();
      if (t.right > b.right + 1 || t.right > vw + 1) push("table-out-of-card", table, `${Math.round(t.width)}px table in ${Math.round(b.width)}px ${card.className || card.tagName}`);
    }
    if (c && (getComputedStyle(c).overflowX === "auto" || getComputedStyle(c).overflowX === "scroll") && c.scrollWidth > c.clientWidth + 1) {
      const cue = c.previousElementSibling && c.previousElementSibling.matches(".swipe-cue") && visible(c.previousElementSibling);
      const cs = getComputedStyle(c);
      const edge = cs.boxShadow !== "none" || cs.maskImage !== "none" || parseFloat(cs.borderRightWidth) > 0;
      if (!edge) push("wide-table-no-visible-edge", table, `${Math.round(c.scrollWidth)}px in a ${Math.round(c.clientWidth)}px scroller${cue ? " (cue above, no edge)" : ""}`);
    }
  }

  // Overlapping lines of text, between two different elements.
  const lines = [];
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walk.nextNode()) {
    const node = walk.currentNode;
    const el = node.parentElement;
    if (!el || !node.textContent.trim() || el.closest(drawing) || el.closest("script, style, noscript, option, .sr, .visually-hidden") || !visible(el) || fixedish(el) || overlay(el)) continue;
    const s = getComputedStyle(el);
    if (s.position === "sticky" || el.closest(".topbar, .site-head, .tabbar, [popover], dialog, details:not([open]) > :not(summary)")) continue;
    const range = document.createRange();
    range.selectNodeContents(node);
    // Only what shows: a line scrolled out of its own box is not on the screen.
    let box = null;
    for (let up = el.parentElement; up && up !== document.body; up = up.parentElement) {
      const t = getComputedStyle(up);
      if (t.overflowX !== "visible" || t.overflowY !== "visible") { box = up.getBoundingClientRect(); break; }
    }
    for (const r of range.getClientRects()) {
      if (r.width <= 2 || r.height <= 2) continue;
      if (box && (r.bottom <= box.top + 1 || r.top >= box.bottom - 1 || r.right <= box.left + 1 || r.left >= box.right - 1)) continue;
      lines.push({ el, r });
    }
  }
  const seenPairs = new Set();
  for (let i = 0; i < lines.length && problems.length < 400; i++) {
    for (let j = i + 1; j < lines.length; j++) {
      const a = lines[i], b = lines[j];
      if (a.el === b.el || a.el.contains(b.el) || b.el.contains(a.el)) continue;
      const x = Math.min(a.r.right, b.r.right) - Math.max(a.r.left, b.r.left);
      const y = Math.min(a.r.bottom, b.r.bottom) - Math.max(a.r.top, b.r.top);
      if (x > 3 && y > Math.min(a.r.height, b.r.height) * 0.35) {
        const key = describe(a.el) + "|" + describe(b.el);
        if (seenPairs.has(key)) continue;
        seenPairs.add(key);
        push("text-overlaps", a.el, `"${a.el.textContent.trim().slice(0, 30)}" over "${b.el.textContent.trim().slice(0, 30)}" (${describe(b.el)})`);
      }
    }
  }

  // Values that must stay on one line.
  const MONTH = "(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*";
  const TOKENS = [
    ["amount", /₦\s?-?[\d,]+(?:\.\d+)?(?:[km]\b)?/g],
    ["date", new RegExp(`\\b(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\\s)?\\d{1,2}\\s${MONTH}(?:\\s\\d{4})?\\b|\\b${MONTH}\\s\\d{4}\\b`, "g")],
    ["class name", /\b(?:JSS|SSS|SS|Primary|Basic|Nursery|KG|Year|Grade|Pry)\s?\d+(?:\s?[A-Z]\b)?/g],
    ["admission number", /\b[A-Z]{2,5}\/[A-Z0-9-]+(?:\/[A-Z0-9-]+)*\b/g],
    ["PIN", /\b\d{4}\s\d{4}\b/g],
    ["time", /\b\d{1,2}:\d{2}(?:\s?[ap]\.?m\b\.?)?/gi],
  ];
  const walk2 = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walk2.nextNode()) {
    const node = walk2.currentNode;
    const el = node.parentElement;
    if (!el || el.closest("script, style, noscript, option, textarea, .sr, .visually-hidden") || !visible(el) || el.closest(drawing)) continue;
    for (const [kind, re] of TOKENS) {
      for (const m of node.textContent.matchAll(re)) {
        const range = document.createRange();
        range.setStart(node, m.index);
        range.setEnd(node, m.index + m[0].length);
        const tops = new Set([...range.getClientRects()].filter((r) => r.width > 0).map((r) => Math.round(r.top / 4)));
        if (tops.size > 1) push(`${kind} broken across lines`, el, m[0]);
      }
    }
  }
  return problems;
}

async function settle(page) {
  try { await page.waitForLoadState("networkidle", { timeout: 8000 }); } catch {}
  await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => setTimeout(done, 120))));
}

async function main() {
  const browser = await chromium.launch({
    args: ["--font-render-hinting=full", `--host-resolver-rules=MAP *.${DOMAIN} 127.0.0.1, MAP ${DOMAIN} 127.0.0.1`],
  });
  const sessions = new Map();
  async function contextFor(as) {
    if (sessions.has(as)) return sessions.get(as);
    const made = (async () => {
      const context = await browser.newContext({ viewport: { width: 360, height: 800 }, reducedMotion: "reduce" });
      await context.addInitScript(() => {
        if (typeof crypto.randomUUID !== "function") crypto.randomUUID = () => "10000000-1000-4000-8000-" + String(Math.random()).slice(2, 14).padEnd(12, "0");
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
        }, { identifier: as, password: as.startsWith("cfc.") ? PASSWORD : "demo-pass-2026" });
        if (status !== 200) throw new Error(`signing in as ${as}: ${status}`);
        await page.close();
      }
      return context;
    })();
    sessions.set(as, made);
    return made;
  }

  const jobs = [];
  for (const [name, as, url, steps = []] of PAGES) {
    if (ONLY && !name.includes(ONLY)) continue;
    // Sitting a test changes what the door shows next: one sitting, every width and size measured on it.
    if (name === "cf-sit-door") jobs.push({ name, as, url, steps, once: true });
    else for (const zoom of ZOOMS) for (const width of WIDTHS) jobs.push({ name, as, url, steps, zoom, width });
  }
  const results = [];
  let done = 0;
  async function sitOnce({ name, url, steps }) {
    const context = await browser.newContext({ viewport: { width: 360, height: 800 }, reducedMotion: "reduce" });
    const page = await context.newPage();
    const cdp = await context.newCDPSession(page);
    try {
      await page.goto(url);
      await settle(page);
      for (const [shot, step] of [[name, null], ...steps]) {
        if (step) {
          try { await step(page); await settle(page); } catch (error) {
            results.push({ page: shot, width: 360, zoom: 100, problems: [{ kind: "step-failed", what: "", text: String(error.message).split("\n")[0].slice(0, 120) }] });
            break;
          }
        }
        for (const zoom of ZOOMS) for (const width of WIDTHS) {
          await cdp.send("Page.setFontSizes", { fontSizes: { standard: Math.round(16 * zoom / 100), fixed: Math.round(13 * zoom / 100) } });
          await page.setViewportSize({ width, height: 800 });
          await settle(page);
          const dir = join(OUT, `${width}-${zoom}`);
          mkdirSync(dir, { recursive: true });
          await page.screenshot({ path: join(dir, `${shot}.png`), fullPage: true });
          results.push({ page: shot, as: null, url, width, zoom, status: 200, problems: await page.evaluate(measure) });
        }
      }
    } finally {
      await context.close();
      done++;
    }
  }
  async function run(job) {
    if (job.once) return sitOnce(job);
    const { name, as, url, steps, zoom, width } = job;
    const context = await contextFor(as);
    const page = await context.newPage();
    const cdp = await context.newCDPSession(page);
    await cdp.send("Page.enable");
    await cdp.send("Page.setFontSizes", { fontSizes: { standard: Math.round(16 * zoom / 100), fixed: Math.round(13 * zoom / 100) } });
    await page.setViewportSize({ width, height: 800 });
    const shots = [[name, null], ...steps];
    try {
      const response = await page.goto(url);
      const status = response ? response.status() : 0;
      await settle(page);
      for (const [shot, step] of shots) {
        if (step) {
          try {
            await step(page);
            await settle(page);
          } catch (error) {
            results.push({ page: shot, width, zoom, status, problems: [{ kind: "step-failed", what: "", text: String(error.message).split("\n")[0].slice(0, 120) }] });
            break;
          }
        }
        const dir = join(OUT, `${width}-${zoom}`);
        mkdirSync(dir, { recursive: true });
        await page.screenshot({ path: join(dir, `${shot}.png`), fullPage: true });
        const problems = await page.evaluate(measure);
        results.push({ page: shot, as, url, width, zoom, status, problems });
      }
    } catch (error) {
      results.push({ page: name, width, zoom, problems: [{ kind: "load-failed", what: "", text: String(error.message).split("\n")[0].slice(0, 120) }] });
    } finally {
      await page.close();
      done++;
      if (done % 20 === 0) console.error(`${done}/${jobs.length}`);
    }
  }
  // Sitting the CBT test changes state: run its job alone, first.
  const queue = jobs.slice();
  const workers = Array.from({ length: JOBS }, async () => {
    while (queue.length) await run(queue.shift());
  });
  await Promise.all(workers);
  await browser.close();
  mkdirSync(OUT, { recursive: true });
  writeFileSync(join(OUT, "report.json"), JSON.stringify(results, null, 1));
  const count = results.reduce((n, r) => n + r.problems.length, 0);
  console.log(`${results.length} screens, ${count} problems; ${join(OUT, "report.json")}`);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
