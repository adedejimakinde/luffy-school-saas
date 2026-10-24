/**
 * The picker every `<select>` opens (`static/web/picker.js`; `docs/design.md`,
 * "The picker"), in a real browser against the demo.
 *
 * - **It is photographed** open on a phone and on a desk: the staff invite's
 *   role, the roll's class, and the specimen's long grouped list with its
 *   search box, at 360 and 1280 (`<width>/picker-*.png` in the `screens`
 *   artifact), and once at 320px with the text doubled.
 * - **It behaves like a select**: its keys, focus back on the field, the
 *   roles and names a screen reader reads, a disabled field and a disabled
 *   row, an invalid field.
 * - **Every page that draws a select still sends what was chosen** through
 *   it, to the route it always sent it to, and a page whose picker fails to
 *   load still draws and sends with the system's own menu.
 * - **A school's lists are its own**: the classes and the staff each picker
 *   offers at Sunrise are Sunrise's, and at Harbour Harbour's, and the
 *   school-specific forms send from both.
 *
 * **It writes nothing.** Every request a page makes other than a GET is
 * recorded and refused in the browser (`watch()`), so this file runs beside
 * the others with no class of its own, and names none (`seed_ui`'s rule,
 * `schools/tests/test_seed_demo.py`). The few states the demo cannot reach (a
 * bank to connect, a payment to place, the end of a session) are drawn from
 * a GET answered here; what is then chosen and sent is the page's own.
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
const SCHOOLS = {
  sunrise: `http://sunrise-demo.${DOMAIN}:${PORT}`,
  harbour: `http://harbour-demo.${DOMAIN}:${PORT}`,
};
const SUNRISE = SCHOOLS.sunrise;
const SPECIMEN = `${PORTAL}/__specimen__/`;

const PHONE = { viewport: { width: 360, height: 740 }, hasTouch: true, isMobile: true };
const DESK = { viewport: { width: 1280, height: 800 } };

let browser;
const contexts = new Map();

/** A browser signed in as `as` (or nobody), on a phone or a desk; one each, reused. */
async function signedIn(as, device = DESK) {
  const key = `${as}:${JSON.stringify(device)}`;
  if (contexts.has(key)) return contexts.get(key);
  const context = await browser.newContext(device);
  // As `screens.test.js` says: the demo is plain HTTP, and the fees page needs
  // the one call an HTTPS page has.
  await context.addInitScript(() => {
    if (typeof crypto.randomUUID !== "function") {
      crypto.randomUUID = () =>
        "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) =>
          (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16),
        );
    }
  });
  await context.route(SPECIMEN, (route) =>
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
  contexts.set(key, context);
  return context;
}

/**
 * Every API request the page makes, in order. GETs go through; anything else
 * is kept (method, URL, JSON body or form text) and refused, so nothing is
 * written. Routes added after this one (`answer()`) win over it.
 */
async function watch(page) {
  const sent = [];
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const entry = { method: request.method(), url: request.url() };
    sent.push(entry);
    if (entry.method === "GET") return route.continue();
    const raw = request.postDataBuffer();
    entry.text = raw ? raw.toString("latin1") : "";
    try {
      entry.body = JSON.parse(entry.text);
    } catch {
      entry.body = null;
    }
    return route.abort();
  });
  return sent;
}

/** A GET the demo cannot give, answered here. */
async function answer(page, pattern, body) {
  await page.route(pattern, (route) =>
    route.request().method() === "GET" ? route.fulfill({ contentType: "application/json", body: JSON.stringify(body) }) : route.fallback(),
  );
}

/**
 * Counts the page's API requests in flight. `waitForLoadState("networkidle")`
 * answers at once on a page that was idle once, so a redraw after a choice
 * (the timetable reads the class's week) is waited for by this instead.
 */
function track(page) {
  if (page.inflight !== undefined) return;
  page.inflight = 0;
  page.quietSince = Date.now();
  const api = (request) => request.url().includes("/api/");
  const done = (request) => {
    if (!api(request)) return;
    page.inflight -= 1;
    page.quietSince = Date.now();
  };
  page.on("request", (request) => api(request) && (page.inflight += 1));
  page.on("requestfinished", done);
  page.on("requestfailed", done);
}

/** The page drawn: loaded, no API request in flight for 300ms, its fonts in, a frame passed. */
async function settle(page) {
  await page.waitForLoadState("networkidle");
  for (let i = 0; i < 200 && (page.inflight > 0 || Date.now() - page.quietSince < 300); i++) await page.waitForTimeout(50);
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => setTimeout(done, 50))));
}

async function open(page, url) {
  track(page);
  const response = await page.goto(url);
  assert.equal(response.status(), 200, url);
  await settle(page);
}

const picker = (page) => page.locator("dialog.picker[open]");

/**
 * Chooses a row through the picker, the way a person does: press the field,
 * press the row. `label` names the row; without it, the first row that is not
 * the field's current value nor its "nothing chosen" one. Returns the value
 * the select now holds, read before the page reacts to it.
 */
async function choose(page, field, { label } = {}) {
  await field.scrollIntoViewIfNeeded();
  await field.click();
  const sheet = picker(page);
  await sheet.waitFor();
  const rows = sheet.getByRole("option");
  let row;
  if (label !== undefined) row = sheet.getByRole("option", { name: label, exact: true });
  else {
    const values = await field.evaluate((s) => [...s.options].filter((o) => !o.hidden).map((o) => ({ value: o.value, chosen: o.selected, off: o.disabled })));
    const at = values.findIndex((v) => v.value !== "" && !v.chosen && !v.off);
    assert.ok(at >= 0, "a row to choose");
    row = rows.nth(at);
  }
  const text = (await row.textContent()).trim();
  const value = await field.evaluate((s, text) => [...s.options].find((o) => o.textContent.trim() === text).value, text);
  await page.evaluate(() => {
    window.__picked = null;
    document.addEventListener("change", (event) => (window.__picked = event.target.value), { once: true, capture: true });
  });
  await row.click();
  await sheet.waitFor({ state: "hidden" });
  // What the change event carried, read as it was sent: the page may redraw on hearing it.
  assert.equal(await page.evaluate(() => window.__picked), value, `"${text}" was chosen`);
  return value;
}

/** The rows the picker on `field` offers, read from the picker itself, then closed. */
async function rowsOf(page, field) {
  await field.scrollIntoViewIfNeeded();
  await field.click();
  const sheet = picker(page);
  await sheet.waitFor();
  const rows = (await sheet.getByRole("option").allTextContents()).map((t) => t.trim());
  await page.keyboard.press("Escape");
  await sheet.waitFor({ state: "hidden" });
  return rows;
}

const optionsOf = (field) => field.evaluate((s) => [...s.options].filter((o) => !o.hidden).map((o) => o.textContent.trim()));

/** The last request matching `method` and `url` that was sent, waiting a moment for it. */
async function sentTo(page, sent, method, url) {
  const hit = () => [...sent].reverse().find((r) => r.method === method && url.test(r.url));
  for (let i = 0; i < 50 && !hit(); i++) await page.waitForTimeout(100);
  const found = hit();
  assert.ok(found, `no ${method} to ${url}: ${sent.map((r) => `${r.method} ${r.url}`).join(", ")}`);
  return found;
}

/** A GET after `since` whose query or path carries `value`. */
async function askedFor(page, sent, since, value) {
  const carries = (r) => r.method === "GET" && new RegExp(`[=/]${value}(?:[&/]|$)`).test(r.url);
  for (let i = 0; i < 50 && !sent.slice(since).some(carries); i++) await page.waitForTimeout(100);
  assert.ok(sent.slice(since).some(carries), `no GET for ${value}: ${sent.slice(since).map((r) => r.url).join(", ")}`);
}

function shoot(page, width, name) {
  mkdirSync(join(OUT, String(width)), { recursive: true });
  return page.screenshot({ path: join(OUT, String(width), `picker-${name}.png`) });
}

before(async () => {
  browser = await chromium.launch({
    args: [
      `--host-resolver-rules=MAP *.${DOMAIN} 127.0.0.1, MAP ${DOMAIN} 127.0.0.1`,
      // The specimen, as in `screens.test.js`.
      "--disable-features=BlockInsecurePrivateNetworkRequests,PrivateNetworkAccessSendPreflights,PrivateNetworkAccessRespectPreflightResults,LocalNetworkAccessChecks",
    ],
  });
});

after(async () => {
  await browser?.close();
});

describe("the picker, open", () => {
  test("on a phone it is a sheet from the foot, titled by the field, with the chosen row checked", async () => {
    const page = await (await signedIn("sunrise.admin", PHONE)).newPage();
    try {
      await open(page, `${SUNRISE}/staff/`);
      await page.locator("#role").tap();
      const sheet = picker(page);
      await sheet.waitFor();
      await page.waitForTimeout(300); // the slide up
      await shoot(page, 360, "staff-role");

      const box = await sheet.boundingBox();
      assert.equal(Math.round(box.x), 0);
      assert.equal(Math.round(box.width), 360);
      assert.equal(Math.round(box.y + box.height), 740, "flush with the foot of the screen");
      assert.equal(await sheet.locator(".picker-title").textContent(), "Role");
      assert.ok(await sheet.locator(".picker-handle").isVisible(), "a drag handle");
      assert.equal(await page.getByRole("listbox", { name: "Role" }).count(), 1);
      const chosen = sheet.locator('[role="option"][aria-selected="true"]');
      assert.equal(await chosen.count(), 1);
      assert.ok(await chosen.locator("svg").isVisible(), "a check on the chosen row");
      for (const row of await sheet.getByRole("option").all()) {
        const r = await row.boundingBox();
        assert.ok(r.height >= 52, `a row ${r.height}px tall`);
        assert.ok(parseFloat(await row.evaluate((el) => getComputedStyle(el).fontSize)) >= 15);
      }
      // The page behind is still, under a soft backdrop.
      const backdrop = await sheet.evaluate((el) => getComputedStyle(el, "::backdrop").backgroundColor);
      assert.notEqual(backdrop, "rgba(0, 0, 0, 0)");
      assert.equal(await page.evaluate(() => getComputedStyle(document.documentElement).overflow), "hidden");

      await sheet.getByRole("option", { name: "Teacher", exact: true }).tap();
      await sheet.waitFor({ state: "hidden" });
      assert.equal(await page.locator("#role").inputValue(), "teacher");
      assert.equal(await page.evaluate(() => document.activeElement.id), "role", "focus is back on the field");
    } finally {
      await page.close();
    }
  });

  test("on a phone the backdrop and a swipe down close it and change nothing", async () => {
    const page = await (await signedIn("sunrise.admin", PHONE)).newPage();
    try {
      await open(page, `${SUNRISE}/staff/`);
      const field = page.locator("#role");
      const was = await field.inputValue();
      await field.tap();
      await picker(page).waitFor();
      await page.touchscreen.tap(180, 40); // above the sheet: the backdrop
      await picker(page).waitFor({ state: "hidden" });
      assert.equal(await field.inputValue(), was);

      await field.tap();
      const sheet = picker(page);
      await sheet.waitFor();
      await page.waitForTimeout(300);
      const handle = await sheet.locator(".picker-head").boundingBox();
      const cdp = await page.context().newCDPSession(page);
      const at = (y) => [{ x: handle.x + handle.width / 2, y }];
      const y0 = handle.y + 10;
      await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: at(y0) });
      for (let dy = 20; dy <= 200; dy += 20) await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: at(y0 + dy) });
      await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
      await sheet.waitFor({ state: "hidden" });
      assert.equal(await field.inputValue(), was);
    } finally {
      await page.close();
    }
  });

  test("on a desk it is a popover under the field, as wide as it", async () => {
    const page = await (await signedIn("sunrise.admin", DESK)).newPage();
    try {
      await open(page, `${SUNRISE}/staff/`);
      const field = page.locator("#role");
      await field.click();
      const sheet = picker(page);
      await sheet.waitFor();
      await page.waitForTimeout(200);
      await shoot(page, 1280, "staff-role");

      const f = await field.boundingBox();
      const s = await sheet.boundingBox();
      assert.ok(Math.abs(s.x - f.x) <= 1 && Math.abs(s.width - f.width) <= 1, "lined up with the field");
      assert.ok(s.y >= f.y + f.height && s.y <= f.y + f.height + 8, "just under it");
      assert.equal(await sheet.locator(".picker-head").isVisible(), false, "the field's own label is its title");
      await page.mouse.click(1200, 700); // anywhere else
      await sheet.waitFor({ state: "hidden" });
    } finally {
      await page.close();
    }
  });

  test("the roll's class, on a phone and a desk", async () => {
    for (const [device, width] of [[PHONE, 360], [DESK, 1280]]) {
      const page = await (await signedIn("sunrise.admin", device)).newPage();
      try {
        await open(page, `${SUNRISE}/roll/`);
        const field = page.locator("#class_group_id");
        await field.scrollIntoViewIfNeeded();
        if (device === PHONE) await field.tap();
        else await field.click();
        await picker(page).waitFor();
        await page.waitForTimeout(300);
        await shoot(page, width, "roll-class");
        assert.equal(await picker(page).locator(".picker-title").textContent(), "Class (optional)");
        assert.deepEqual(await picker(page).getByRole("option").allTextContents(), await optionsOf(field));
        await page.keyboard.press("Escape");
      } finally {
        await page.close();
      }
    }
  });

  test("a long list has a search box, and its groups are headings", async () => {
    for (const [device, width] of [[PHONE, 360], [DESK, 1280]]) {
      const page = await (await signedIn(null, device)).newPage();
      try {
        await open(page, SPECIMEN);
        const field = page.locator("#specimen-class");
        await field.scrollIntoViewIfNeeded();
        if (device === PHONE) await field.tap();
        else await field.click();
        const sheet = picker(page);
        await sheet.waitFor();
        await page.waitForTimeout(300);
        const search = sheet.getByRole("combobox", { name: "Search Class" });
        assert.ok(await search.isVisible(), "a search box over more than eight rows");
        const groups = sheet.getByRole("group");
        assert.deepEqual(
          await groups.evaluateAll((all) => all.map((g) => document.getElementById(g.getAttribute("aria-labelledby")).textContent)),
          ["JSS 1", "JSS 2", "JSS 3", "SS 1", "SS 2", "SS 3"],
        );
        // On a desk the search box takes the keys; on a phone it waits for a tap.
        assert.equal(await search.evaluate((el) => el === document.activeElement), device === DESK);
        await shoot(page, width, "long-list");

        if (device === PHONE) await search.tap();
        await search.pressSequentially("ss 2");
        assert.deepEqual(await sheet.getByRole("option").filter({ visible: true }).allTextContents(), ["SS 2A", "SS 2B"]);
        assert.deepEqual(
          await sheet.locator(".picker-group:not([hidden]) .picker-group-label").allTextContents(),
          ["SS 2"],
          "an emptied group goes",
        );
        assert.equal(await sheet.locator('[aria-live="polite"]').textContent(), "2 matches");
        await shoot(page, width, "long-list-search");

        await search.fill("zz");
        assert.equal(await sheet.getByRole("option").filter({ visible: true }).count(), 0);
        assert.equal(await sheet.locator(".picker-empty").textContent(), 'Nothing matches "zz".');
        await search.fill("ss 3b");
        await page.keyboard.press("Enter");
        await sheet.waitFor({ state: "hidden" });
        assert.equal(await field.inputValue(), "SS 3B");
      } finally {
        await page.close();
      }
    }
  });

  test("at 320px with the text doubled it still fits, nothing sideways", async () => {
    const page = await (await signedIn("sunrise.admin", { ...PHONE, viewport: { width: 320, height: 640 } })).newPage();
    try {
      await open(page, `${SUNRISE}/roll/`);
      await page.addStyleTag({ content: "html { font-size: 200% !important; }" });
      await settle(page);
      const field = page.locator("#class_group_id");
      await field.scrollIntoViewIfNeeded();
      await field.tap();
      const sheet = picker(page);
      await sheet.waitFor();
      await page.waitForTimeout(300);
      await shoot(page, 320, "roll-class-large-text");
      const fits = await sheet.evaluate((el) => {
        const list = el.querySelector(".picker-list");
        return {
          width: el.getBoundingClientRect().width,
          sideways: el.scrollWidth > el.clientWidth + 1 || list.scrollWidth > list.clientWidth + 1,
          top: el.getBoundingClientRect().top,
        };
      });
      assert.equal(Math.round(fits.width), 320);
      assert.equal(fits.sideways, false);
      assert.ok(fits.top >= 0, "the sheet's top is on the screen");
    } finally {
      await page.close();
    }
  });
});

describe("the picker, with a keyboard and a screen reader", () => {
  test("the keys open it, move, jump, choose and close, and focus goes back to the field", async () => {
    const page = await (await signedIn("sunrise.admin", DESK)).newPage();
    try {
      await open(page, `${SUNRISE}/staff/`);
      const field = page.locator("#role");
      await page.locator("#full_name").focus();
      await page.keyboard.press("Tab");
      assert.equal(await page.evaluate(() => document.activeElement.id), "role");
      assert.notEqual(await field.evaluate((el) => getComputedStyle(el).outlineStyle), "none", "a visible focus ring on the field");
      await field.evaluate((el) => {
        window.__changes = 0;
        el.closest("main").addEventListener("change", () => window.__changes++);
      });

      // Open, and the listbox has the keys, on the chosen row.
      await page.keyboard.press("ArrowDown");
      const sheet = picker(page);
      await sheet.waitFor();
      const list = page.getByRole("listbox", { name: "Role" });
      assert.ok(await list.evaluate((el) => el === document.activeElement));
      const active = () => list.evaluate((el) => document.getElementById(el.getAttribute("aria-activedescendant")).textContent);
      assert.equal(await active(), "Administrator");

      await page.keyboard.press("ArrowDown");
      assert.equal(await active(), "Bursar");
      assert.equal(await sheet.locator(".is-active").evaluate((el) => getComputedStyle(el).outlineStyle), "solid", "the keys' row is ringed");
      await page.keyboard.press("End");
      assert.equal(await active(), "Vice principal (academic)");
      await page.keyboard.press("Home");
      assert.equal(await active(), "Administrator");
      await page.keyboard.press("t");
      assert.equal(await active(), "Teacher", "a letter jumps");
      await page.keyboard.press("Enter");
      await sheet.waitFor({ state: "hidden" });
      assert.equal(await field.inputValue(), "teacher");
      assert.equal(await page.evaluate(() => document.activeElement.id), "role");
      assert.equal(await page.evaluate(() => window.__changes), 1, "one change event, which bubbles");

      // Escape and Tab close without choosing.
      for (const key of ["Escape", "Tab"]) {
        await page.keyboard.press("Space");
        await sheet.waitFor();
        await page.keyboard.press("ArrowUp");
        await page.keyboard.press(key);
        await sheet.waitFor({ state: "hidden" });
        assert.equal(await field.inputValue(), "teacher", key);
        assert.equal(await page.evaluate(() => document.activeElement.id), "role", key);
      }

      // A letter on the closed field opens it on the first row it starts.
      await page.keyboard.press("p");
      await sheet.waitFor();
      assert.equal(await active(), "Principal");
      await page.keyboard.press("Escape");
      assert.equal(await page.evaluate(() => window.__changes), 1);
    } finally {
      await page.close();
    }
  });

  test("each row is an option a screen reader can name, marked chosen or not", async () => {
    const page = await (await signedIn("sunrise.admin", DESK)).newPage();
    try {
      await open(page, `${SUNRISE}/staff/`);
      await page.locator("#role").click();
      await picker(page).waitFor();
      const roles = await page.getByRole("listbox", { name: "Role" }).getByRole("option").evaluateAll((all) =>
        all.map((o) => [o.textContent, o.getAttribute("aria-selected")]),
      );
      assert.deepEqual(roles, [
        ["Administrator", "true"],
        ["Bursar", "false"],
        ["Principal", "false"],
        ["Teacher", "false"],
        ["Vice principal (academic)", "false"],
      ]);
      assert.equal(await page.getByRole("dialog", { name: "Role" }).count(), 1, "a dialog named by the field");
      await page.keyboard.press("Escape");
    } finally {
      await page.close();
    }
  });

  test("a disabled field does not open, a row that cannot be chosen is passed over, an invalid field is red", async () => {
    const page = await (await signedIn(null, DESK)).newPage();
    try {
      await open(page, SPECIMEN);
      const off = page.locator("#specimen-subject");
      await off.scrollIntoViewIfNeeded();
      await off.click({ force: true });
      await page.waitForTimeout(200);
      assert.equal(await picker(page).count(), 0, "a disabled select opens nothing");
      assert.equal(await off.evaluate((el) => getComputedStyle(el).cursor), "not-allowed");

      const term = page.locator("#specimen-term");
      await term.focus();
      await page.keyboard.press("ArrowDown");
      const sheet = picker(page);
      await sheet.waitFor();
      const row = sheet.getByRole("option", { name: "Third term (not open yet)" });
      assert.equal(await row.getAttribute("aria-disabled"), "true");
      await page.keyboard.press("ArrowDown");
      await page.keyboard.press("ArrowDown");
      await page.keyboard.press("Enter");
      await sheet.waitFor({ state: "hidden" });
      assert.equal(await term.inputValue(), "Second term", "the keys stop at the last row that can be chosen");
      await term.click();
      await sheet.getByRole("option", { name: "Third term (not open yet)" }).click({ force: true });
      assert.ok(await sheet.isVisible(), "pressing it does nothing");
      await page.keyboard.press("Escape");

      const invalid = await page.locator("#specimen-method").evaluate((el) => getComputedStyle(el).borderColor);
      const fine = await term.evaluate((el) => getComputedStyle(el).borderColor);
      assert.equal(invalid, "rgb(180, 35, 24)", "the design's red");
      assert.notEqual(fine, invalid);
      await shoot(page, 1280, "fields");
    } finally {
      await page.close();
    }
  });
});

/**
 * Every page that draws a select, each select chosen through the picker, and
 * what the page then sent. `run(page, sent)` does what a person does there
 * and asserts on what reached the network.
 */
const PAGES = [
  {
    name: "staff: the role of an invitation",
    as: "admin",
    path: "/staff/",
    async run(page, sent) {
      await page.locator("#address").fill("picker.test@example.com");
      assert.equal(await choose(page, page.locator("#role"), { label: "Vice principal (academic)" }), "vp_academic");
      await page.locator('form[data-form="invite"] button[type="submit"]').click();
      assert.equal((await sentTo(page, sent, "POST", /\/invitations\/$/)).body.role, "vp_academic");
    },
  },
  {
    name: "roll: the class a child is admitted to",
    as: "admin",
    path: "/roll/",
    perSchool: true,
    async run(page, sent) {
      await page.locator("#full_name").fill("Picker Test");
      await page.locator("#username").fill("PICKER/0001");
      const value = await choose(page, page.locator("#class_group_id"));
      await page.locator('form[data-form="admit"] button[type="submit"]').click();
      assert.equal(String((await sentTo(page, sent, "POST", /\/roll\/$/)).body.class_group_id), value);
    },
  },
  {
    name: "roll: moving a child to another class",
    as: "admin",
    path: "/roll/",
    perSchool: true,
    async run(page, sent) {
      const value = await choose(page, page.locator("select[data-child]").first());
      assert.equal(String((await sentTo(page, sent, "PUT", /\/class\/$/)).body.class_group_id), value);
    },
  },
  {
    name: "roll: a guardian's relationship",
    as: "admin",
    path: "/roll/",
    async run(page, sent) {
      await page.locator('[data-action="guardians"]').first().click();
      await settle(page);
      await page.locator("#guardian_name").fill("Picker Guardian");
      await page.locator("#guardian_contact").fill("08030000001");
      const value = await choose(page, page.locator("#relationship"));
      await page.locator("#relationship").evaluate((el) => el.form.requestSubmit());
      assert.equal((await sentTo(page, sent, "POST", /guardian/)).body.relationship, value);
    },
  },
  {
    name: "roll: a child's sex, in their details",
    as: "admin",
    path: "/roll/",
    async run(page, sent) {
      await page.locator('[data-action="details"]').first().click();
      await settle(page);
      const value = await choose(page, page.locator("#sex"));
      await page.locator('form[data-form="details"]').evaluate((form) => form.requestSubmit());
      assert.equal((await sentTo(page, sent, "PUT", /details/)).body.sex, value);
    },
  },
  {
    name: "setup: which term a new term is",
    as: "admin",
    path: "/setup/",
    async run(page, sent) {
      await page.locator("#session").fill("2031/2032");
      assert.equal(await choose(page, page.locator("#name"), { label: "Third term" }), "third");
      await page.locator("#starts_on").fill("2031-09-08");
      await page.locator("#ends_on").fill("2031-12-12");
      await page.locator('form[data-form="term"] button[type="submit"]').click();
      assert.equal((await sentTo(page, sent, "POST", /\/academics\/terms\/$/)).body.name, "third");
    },
  },
  {
    name: "setup: a subject's department",
    as: "admin",
    path: "/setup/",
    async run(page, sent) {
      const value = await choose(page, page.locator("select[data-subject]").first());
      const write = await sentTo(page, sent, "PUT", /\/api\//);
      assert.ok(Object.values(write.body).map(String).includes(value), write.text);
    },
  },
  {
    name: "teaching: a class's class teacher",
    as: "admin",
    path: "/teaching/",
    perSchool: true,
    async run(page, sent) {
      const value = await choose(page, page.locator("select[data-class]").first());
      assert.equal(String((await sentTo(page, sent, "PUT", /\/teacher\/$/)).body.membership_id), value);
    },
  },
  {
    name: "who teaches what: the teacher, the subject and the class",
    as: "principal",
    path: "/subject-teachers/",
    perSchool: true,
    async run(page, sent) {
      const teacher = await choose(page, page.locator("#st_teacher"));
      const subject = await choose(page, page.locator("#st_subject"));
      const group = await choose(page, page.locator("#st_class"));
      await page.locator("#st_class").evaluate((el) => el.form.requestSubmit());
      const { body } = await sentTo(page, sent, "POST", /subject-teachers/);
      assert.deepEqual([body.membership_id, body.subject_id, body.class_group_id].map(String), [teacher, subject, group]);
    },
  },
  {
    name: "timetable: the term and the class shown",
    as: "teacher",
    path: "/timetable/",
    async run(page, sent) {
      let since = sent.length;
      await askedFor(page, sent, since, await choose(page, page.locator("#class")));
      await settle(page);
      since = sent.length;
      await askedFor(page, sent, since, await choose(page, page.locator("#term")));
    },
  },
  {
    name: "fees: the term of the books, and a payment's term and method",
    as: "bursar",
    path: "/fees/",
    async run(page, sent) {
      await page.locator('[data-action="open-class"]').first().click();
      await settle(page);
      await page.locator('[data-action="open-account"]').first().click();
      await settle(page);
      const form = page.locator("form[data-payment]");
      const term = await choose(page, form.locator('select[name="term_id"]'));
      await form.locator('input[name="amount"]').fill("1000");
      const method = await choose(page, form.locator('select[name="method"]'));
      await form.evaluate((f) => f.requestSubmit());
      const write = await sentTo(page, sent, "POST", /payments?\/$/);
      assert.equal(write.body.method, method);
      assert.equal(String(write.body.term_id), term);
      await open(page, `${SUNRISE}/fees/`);
      const since = sent.length;
      await askedFor(page, sent, since, await choose(page, page.locator("select[data-term]")));
    },
  },
  {
    name: "bank: the bank of an account to connect, found by searching",
    as: "bursar",
    path: "/bank/",
    async before(page) {
      const banks = ["Access Bank", "Citibank", "Ecobank", "Fidelity Bank", "First Bank", "FCMB", "GTBank", "Keystone Bank", "Polaris Bank", "Stanbic IBTC", "Sterling Bank", "UBA", "Union Bank", "Wema Bank", "Zenith Bank"];
      await answer(page, "**/api/fees/bank/banks/", { banks: banks.map((name, i) => ({ code: String(100 + i), name })) });
    },
    async run(page, sent) {
      await page.locator('[data-action="start"]').click();
      await settle(page);
      const field = page.locator('select[name="bank_code"]');
      await field.click();
      const sheet = picker(page);
      await sheet.waitFor();
      await page.keyboard.type("zen");
      assert.deepEqual(await sheet.getByRole("option").filter({ visible: true }).allTextContents(), ["Zenith Bank"]);
      await page.keyboard.press("Enter");
      await sheet.waitFor({ state: "hidden" });
      assert.equal(await field.inputValue(), "114");
      await page.locator('input[name="account_number"]').fill("0123456789");
      await field.evaluate((el) => el.form.requestSubmit());
      assert.equal((await sentTo(page, sent, "POST", /\/api\/fees\/bank\//)).body.bank_code, "114");
    },
  },
  {
    name: "bank: the class and the child a payment is placed on",
    as: "bursar",
    path: "/bank/",
    perSchool: true,
    async before(page) {
      await answer(page, "**/api/fees/virtual/unmatched/", {
        may_place: true,
        payments: [{ payment_id: 990001, amount_kobo: 2_500_000, reference: "PSK-PICKER-1", reason_label: "No account matched", placed: null }],
      });
    },
    async run(page, sent) {
      await page.locator('[data-action="place"]').click();
      await settle(page);
      await choose(page, page.locator('select[data-field="class"]'));
      await settle(page);
      const child = await choose(page, page.locator('select[data-field="child"]'));
      await page.locator('form[data-form="pick"]').evaluate((f) => f.requestSubmit());
      await settle(page);
      await page.locator('form[data-form="place-confirm"]').evaluate((f) => f.requestSubmit());
      const write = await sentTo(page, sent, "POST", /\/placement\/$/);
      assert.ok(Object.values(write.body).map(String).includes(child), write.text);
    },
  },
  {
    name: "broadsheets: the term",
    as: "principal",
    path: "/broadsheet/",
    async run(page, sent) {
      const since = sent.length;
      await askedFor(page, sent, since, await choose(page, page.locator("select[data-term]")));
    },
  },
  {
    name: "absences: the term",
    as: "principal",
    path: "/absences/",
    async run(page, sent) {
      const since = sent.length;
      await askedFor(page, sent, since, await choose(page, page.locator("select[data-term]")));
    },
  },
  {
    name: "remarks: a child's rating",
    as: "teacher",
    path: "/comments/",
    async run(page, sent) {
      await page.locator('[data-action="pick-class"]').first().click();
      await settle(page);
      await page.locator('[data-action="open"]').first().click();
      await settle(page);
      const value = await choose(page, page.locator("select[data-trait]").first());
      assert.equal(String((await sentTo(page, sent, "PUT", /rating/)).body.score), value);
    },
  },
  {
    name: "promotion: where each class goes, and a child who repeats",
    as: "principal",
    path: "/promotion/",
    async before(page) {
      await answer(page, "**/api/academics/promotion/", {
        term: "2025/2026 Third term",
        to_term: "2026/2027 First term",
        classes: [
          { class_group_id: 801, name: "Picker One", destination_id: null, graduate: false, children: [{ membership_id: 9001, name: "Ada Picker", action: "promote" }] },
          { class_group_id: 802, name: "Picker Two", destination_id: null, graduate: false, children: [{ membership_id: 9002, name: "Bayo Picker", action: "promote" }] },
        ],
        targets: [
          { class_group_id: 801, name: "Picker One" },
          { class_group_id: 802, name: "Picker Two" },
        ],
      });
    },
    async run(page, sent) {
      assert.equal(await choose(page, page.locator('select[name="dest_801"]'), { label: "Picker Two" }), "802");
      assert.equal(await choose(page, page.locator('select[name="dest_802"]'), { label: "Graduated" }), "graduate");
      assert.equal(await choose(page, page.locator('select[name="child_9001"]'), { label: "Repeat" }), "repeat");
      await page.locator('form[data-form="review"]').evaluate((f) => f.requestSubmit());
      await settle(page);
      await page.locator('form[data-form="confirm"]').evaluate((f) => f.requestSubmit());
      const { body } = await sentTo(page, sent, "POST", /\/academics\/promotion\/$/);
      assert.deepEqual(body.classes, [
        { class_group_id: 801, graduate: false, destination_id: 802, children: { 9001: "repeat" } },
        { class_group_id: 802, graduate: true, destination_id: null, children: { 9002: "promote" } },
      ]);
    },
  },
  {
    name: "OGSERA: the class and the subject a template is for",
    as: "admin",
    path: "/ogsera/",
    async run(page, sent) {
      const group = await choose(page, page.locator("#class_group_id"));
      const subject = await choose(page, page.locator("#subject_id"));
      await page.locator("#file").setInputFiles({ name: "picker.xlsx", mimeType: "application/octet-stream", buffer: Buffer.from("PK") });
      const form = page.locator('form[data-form="choose"]');
      // What the form submits, which is what the page reads the class and subject from.
      assert.deepEqual(await form.evaluate((f) => [new FormData(f).get("class_group_id"), new FormData(f).get("subject_id")]), [group, subject]);
      await form.evaluate((f) => f.requestSubmit());
      assert.match((await sentTo(page, sent, "POST", /\/api\//)).text, /filename="picker\.xlsx"/);
    },
  },
];

describe("every page with a select still sends what was chosen", () => {
  for (const spec of PAGES) {
    for (const school of spec.perSchool ? ["sunrise", "harbour"] : ["sunrise"]) {
      test(`${spec.name}${spec.perSchool ? `, at ${school}` : ""}`, async () => {
        const page = await (await signedIn(`${school}.${spec.as}`, DESK)).newPage();
        try {
          const sent = await watch(page);
          if (spec.before) await spec.before(page);
          await open(page, `${SCHOOLS[school]}${spec.path}`);
          await spec.run(page, sent);
        } finally {
          await page.close();
        }
      });
    }
  }

  test("a page whose picker cannot load still draws, and its select still sends", async () => {
    const page = await (await signedIn("sunrise.admin", DESK)).newPage();
    try {
      const sent = await watch(page);
      await page.route("**/web/picker.js", (route) => route.abort());
      await open(page, `${SUNRISE}/staff/`);
      const field = page.locator("#role");
      await page.locator("#address").fill("picker.test@example.com");
      await field.selectOption("vp_academic"); // the system's own menu
      assert.equal(await picker(page).count(), 0);
      await page.locator('form[data-form="invite"] button[type="submit"]').click();
      assert.equal((await sentTo(page, sent, "POST", /\/invitations\/$/)).body.role, "vp_academic");
    } finally {
      await page.close();
    }
  });
});

describe("a school's lists are its own", () => {
  /** Each school's own class names, from its own setup route. */
  async function classesAt(school) {
    const page = await (await signedIn(`${school}.admin`, DESK)).newPage();
    try {
      await open(page, `${SCHOOLS[school]}/setup/`);
      return await page.evaluate(async () => (await (await fetch("/api/academics/setup/")).json()).classes.filter((c) => c.is_active).map((c) => c.name));
    } finally {
      await page.close();
    }
  }

  test("the roll's class picker offers this school's classes and none of the other's", async () => {
    const own = { sunrise: await classesAt("sunrise"), harbour: await classesAt("harbour") };
    const onlySunrise = own.sunrise.filter((n) => !own.harbour.includes(n));
    assert.ok(onlySunrise.length, "the control: Sunrise has classes Harbour has not");
    for (const school of ["sunrise", "harbour"]) {
      const page = await (await signedIn(`${school}.admin`, DESK)).newPage();
      try {
        await open(page, `${SCHOOLS[school]}/roll/`);
        const field = page.locator("#class_group_id");
        const rows = await rowsOf(page, field);
        assert.deepEqual(rows, await optionsOf(field), "the picker lists what the select holds");
        assert.deepEqual(rows.slice(1).sort(), [...own[school]].sort(), `${school}'s classes`);
        if (school === "harbour") assert.deepEqual(rows.filter((r) => onlySunrise.includes(r)), []);
      } finally {
        await page.close();
      }
    }
  });

  for (const [what, as, path, field] of [
    ["a class teacher", "admin", "/teaching/", "select[data-class]"],
    ["who teaches a subject", "principal", "/subject-teachers/", "#st_teacher"],
  ]) {
    test(`the staff offered as ${what} are this school's own`, async () => {
      for (const [school, other] of [["sunrise", "Harbour"], ["harbour", "Sunrise"]]) {
        const page = await (await signedIn(`${school}.${as}`, DESK)).newPage();
        try {
          await open(page, `${SCHOOLS[school]}${path}`);
          const select = page.locator(field).first();
          const rows = await rowsOf(page, select);
          assert.deepEqual(rows, await optionsOf(select));
          const people = rows.filter((r) => / (Sunrise|Harbour)$/.test(r));
          assert.ok(people.length >= 2, `the control: ${school} lists its staff (${rows.join(", ")})`);
          const own = school === "sunrise" ? "Sunrise" : "Harbour";
          assert.deepEqual(people.filter((r) => !r.endsWith(` ${own}`)), [], `${school} lists nobody from ${other}`);
        } finally {
          await page.close();
        }
      }
    });
  }
});
