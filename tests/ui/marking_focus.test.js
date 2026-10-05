/**
 * Marks typed down a column on a phone: tap a box, type, tap the next box, type.
 *
 * Found running the first-school pilot flow. Saving a mark redraws the sheet from the blur, and
 * the blur of one box is the tap on the next, so the redraw replaced the box the teacher had just
 * tapped: the keyboard dropped and the digits went nowhere, every second mark was lost, and fast
 * typing could save the first digit alone ("1" for "11"). `tests/js/` cannot see it (its stub has
 * no focus) and `offline.test.js` fills each box directly, so only a real browser typing in turn
 * would. Runs against the same demo as `screens.test.js` (see its header), as Sunrise's teacher,
 * on a sheet nobody has marked: JSS 1A's exams, which `seed_demo` leaves empty.
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
let page;

before(async () => {
  browser = await chromium.launch({
    args: [`--host-resolver-rules=MAP *.${DOMAIN} 127.0.0.1, MAP ${DOMAIN} 127.0.0.1`],
  });
  const context = await browser.newContext({ viewport: { width: 360, height: 740 }, hasTouch: true });
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

describe("typing marks down a column", () => {
  test("each box keeps what is typed in it, and the school ends up with every one", async () => {
    await page.goto(`${SUNRISE}/marking/`);
    await page.waitForSelector('[data-action="pick-assessment"]');
    const exam = page.locator('[data-action="pick-assessment"]', { hasText: "English Language · Exam" });
    const assessment = await exam.getAttribute("data-assessment");
    await exam.click();
    const group = page.locator('[data-action="pick-class"]', { hasText: "JSS 1A" });
    const classGroup = await group.getAttribute("data-class");
    await group.click();
    await page.waitForSelector("ul.roster");

    const boxes = page.locator("ul.roster input");
    const free = (await boxes.evaluateAll((all) => all.map((box) => box.value))).flatMap((value, at) =>
      value === "" ? [at] : [],
    );
    assert.ok(free.length >= 4, `a sheet with room for four marks, found ${free.length}`);
    const chosen = free.slice(0, 4);
    const typed = [31, 42, 53, 14];

    for (const [turn, at] of chosen.entries()) {
      await boxes.nth(at).click();
      // A person types a beat after the tap, and a digit at a time.
      await page.waitForTimeout(300);
      await page.keyboard.type(String(typed[turn]), { delay: 100 });
    }
    await page.locator("h1").click(); // leave the last box, as a teacher puts the phone down

    const children = [];
    for (const at of chosen) children.push(await boxes.nth(at).getAttribute("data-child"));
    const shown = await boxes.evaluateAll((all, at) => at.map((i) => all[i].value), chosen);
    assert.deepEqual(shown.map(Number), typed, "every box shows what was typed in it");

    // The school holds each mark as typed. Asked until it does, because saving is the outbox's, a beat
    // behind the blur.
    const heldAtSchool = () =>
      page.evaluate(async ([assessment, classGroup]) => {
        const response = await fetch(`/api/gradebook/assessments/${assessment}/sheet/?class_group_id=${classGroup}`);
        const sheet = await response.json();
        return Object.fromEntries(sheet.rows.map((row) => [String(row.student_membership_id), row.value]));
      }, [assessment, classGroup]);
    let held = await heldAtSchool();
    for (let tries = 0; tries < 50 && children.some((child) => held[child] == null); tries++) {
      await page.waitForTimeout(200);
      held = await heldAtSchool();
    }
    assert.deepEqual(
      children.map((child) => held[child]),
      typed,
      "the school holds each mark as typed, not its first digit",
    );
  });
});
