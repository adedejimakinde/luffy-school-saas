/**
 * Emptying a mark box takes the mark back, online and with no connection.
 *
 * Found running the first-school pilot: a teacher emptied a box and the page drew it empty while
 * the school kept the old mark, which came back at the next redraw. `tests/js/` proves the
 * requests; only a browser shows what the box, the school and the phone's queue each end up
 * holding. Runs against the same demo as `screens.test.js` (see its header), as Sunrise's
 * teacher, on JSS 1A's Mathematics exam, which `seed_demo` leaves unmarked and which no other
 * file in `tests/ui/` uses (they run side by side, in separate processes).
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
let context;
let page;
let assessment;
let classGroup;

before(async () => {
  browser = await chromium.launch({
    args: [`--host-resolver-rules=MAP *.${DOMAIN} 127.0.0.1, MAP ${DOMAIN} 127.0.0.1`],
  });
  context = await browser.newContext({ viewport: { width: 360, height: 740 }, hasTouch: true });
  page = await context.newPage();
  await page.goto(`${PORTAL}/staff-sign-in/`);
  const status = await page.evaluate(async (password) => {
    const { csrf_token: token } = await (await fetch("/api/csrf/")).json();
    const response = await fetch("/api/login/", {
      method: "POST",
      headers: { "content-type": "application/json", "X-CSRFToken": token },
      body: JSON.stringify({ identifier: "sunrise.teacher", password }),
    });
    return response.status;
  }, PASSWORD);
  assert.equal(status, 200, "signing in as sunrise.teacher");
});

after(async () => {
  await browser?.close();
});

/** What the school holds for this sheet: each child's mark, or null. */
const heldAtSchool = () =>
  page.evaluate(async ([assessment, classGroup]) => {
    const response = await fetch(`/api/gradebook/assessments/${assessment}/sheet/?class_group_id=${classGroup}`);
    const sheet = await response.json();
    return Object.fromEntries(sheet.rows.map((row) => [String(row.student_membership_id), row.value]));
  }, [assessment, classGroup]);

/** Asked until `ready(held)`, because saving is the outbox's, a beat behind the blur. */
async function schoolHolds(ready, said) {
  let held = await heldAtSchool();
  for (let tries = 0; tries < 60 && !ready(held); tries++) {
    await page.waitForTimeout(200);
    held = await heldAtSchool();
  }
  assert.ok(ready(held), `${said}: ${JSON.stringify(held)}`);
  return held;
}

async function openSheet() {
  await page.goto(`${SUNRISE}/marking/`);
  await page.waitForSelector('[data-action="pick-assessment"]');
  const exam = page.locator('[data-action="pick-assessment"]', { hasText: "Mathematics · Exam" });
  assessment = await exam.getAttribute("data-assessment");
  await exam.click();
  const group = page.locator('[data-action="pick-class"]', { hasText: "JSS 1A" });
  classGroup = await group.getAttribute("data-class");
  await group.click();
  await page.waitForSelector("ul.roster");
}

const boxFor = (child) => page.locator(`ul.roster input[data-child="${child}"]`);

describe("emptying a box", () => {
  let first;
  let second;
  let third;

  test("online, the school gives the mark back and the box stays empty after a reload", async () => {
    await openSheet();
    const boxes = page.locator("ul.roster input");
    const free = (await boxes.evaluateAll((all) => all.map((box) => box.value))).flatMap((value, at) =>
      value === "" ? [at] : [],
    );
    assert.ok(free.length >= 3, `a sheet with room for three marks, found ${free.length}`);
    [first, second, third] = await Promise.all(free.slice(0, 3).map((at) => boxes.nth(at).getAttribute("data-child")));

    for (const [child, mark] of [[first, "31"], [second, "42"], [third, "53"]]) {
      await boxFor(child).click();
      await page.waitForTimeout(200);
      await page.keyboard.type(mark, { delay: 60 });
    }
    await page.locator("h1").click();
    await schoolHolds((held) => held[first] === 31 && held[second] === 42 && held[third] === 53, "the three marks landed");

    await boxFor(first).fill("");
    await page.locator("h1").click();
    await schoolHolds((held) => held[first] === null, "the school gave the cleared mark back");

    const held = await heldAtSchool();
    assert.deepEqual([held[second], held[third]], [42, 53], "the other marks stand");
    await openSheet();
    assert.equal(await boxFor(first).inputValue(), "", "empty after a reload, not the old mark");
    assert.equal(await boxFor(second).inputValue(), "42");
  });

  test("with no connection, the clear waits on the phone and is sent when the connection is back", async () => {
    await context.setOffline(true);
    await boxFor(second).fill("");
    await page.locator("h1").click();
    await page.waitForTimeout(800);
    assert.equal(await waiting(), 1, "one write is kept on the phone");
    assert.equal(await boxFor(second).inputValue(), "", "and the box shows it");

    await context.setOffline(false);
    await schoolHolds((held) => held[second] === null, "the queued clear went when the connection came back");
    const held = await heldAtSchool();
    assert.equal(held[third], 53, "the mark nobody touched stands");
    assert.equal(await waiting(), 0, "nothing is left on the phone");
  });

  /** Entries in this phone's marks outbox. */
  const waiting = () =>
    page.evaluate(
      () =>
        new Promise((resolve) => {
          const open = indexedDB.open("luffy-marks-outbox");
          open.onsuccess = () => {
            const all = open.result.transaction("outboxes").objectStore("outboxes").getAll();
            all.onsuccess = () => resolve(all.result.filter((r) => !r.name.endsWith(" who")).flatMap((r) => r.entries).length);
          };
        }),
    );
});
