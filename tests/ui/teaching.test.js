/**
 * The office sets up what a school teaches, on a phone, and a teacher can then mark it.
 *
 * `tests/js/` walks the page against a stub and `gradebook/tests/test_teaching.py` walks the
 * routes; only a browser shows that the two meet and that a teacher's marking page sees what the
 * administrator made. Runs against the same demo as `screens.test.js` (see its header), as
 * Sunrise's administrator and teacher at 360px, and puts everything back: the other files here
 * run side by side in the same database.
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
let admin;
let teacher;

async function signedIn(identifier) {
  const context = await browser.newContext({ viewport: { width: 360, height: 740 }, hasTouch: true });
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
  }, { identifier, password: PASSWORD });
  assert.equal(status, 200, `signing in as ${identifier}`);
  return page;
}

before(async () => {
  browser = await chromium.launch({
    args: [`--host-resolver-rules=MAP *.${DOMAIN} 127.0.0.1, MAP ${DOMAIN} 127.0.0.1`],
  });
  admin = await signedIn("sunrise.admin");
  teacher = await signedIn("sunrise.teacher");
});

after(async () => {
  await browser?.close();
});

describe("the office builds a subject and a teacher marks it", () => {
  test("a teacher is told the page is the office's", async () => {
    await teacher.goto(`${SUNRISE}/teaching/`);
    await teacher.waitForSelector(".state-refused");
    assert.match(await teacher.innerText("main"), /the office/);
    assert.doesNotMatch(await teacher.innerText("main"), /Mathematics/);
  });

  test("subject, paper and class teacher are made on a phone, then marked, then put back", async () => {
    await admin.goto(`${SUNRISE}/teaching/`);
    await admin.waitForSelector("form[data-form=subject]");
    assert.equal(
      await admin.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth),
      true,
      "the page does not scroll sideways at 360px",
    );

    await admin.fill("#subject_name", "Civic Education");
    await admin.fill("#subject_code", "CVC");
    await admin.click("form[data-form=subject] button[type=submit]");
    await admin.waitForSelector("text=Civic Education");

    await admin.locator("li", { hasText: "Civic Education" }).locator('[data-action="open-subject"]').click();
    await admin.fill("#paper_name", "First CA");
    await admin.fill("#paper_out_of", "20");
    await admin.click("form[data-form=paper] button[type=submit]");
    await admin.waitForSelector("li:has-text('First CA'):has-text('out of 20')");

    // A class with no class teacher in the demo, then one chosen, as the office does it.
    await admin.click('[data-action="back"]');
    const select = admin.locator("li", { hasText: "JSS 1B" }).locator("select");
    await select.selectOption({ label: "Teacher Sunrise" });
    await admin.waitForTimeout(600);
    await admin.reload();
    await admin.waitForSelector("form[data-form=subject]");
    assert.equal(
      await admin.locator("li", { hasText: "JSS 1B" }).locator("select option:checked").innerText(),
      "Teacher Sunrise",
      "the choice was kept by the school",
    );

    // The teacher finds the new paper where papers are marked.
    await teacher.goto(`${SUNRISE}/marking/`);
    await teacher.waitForSelector('[data-action="pick-assessment"]');
    assert.ok(
      await teacher.locator('[data-action="pick-assessment"]', { hasText: "Civic Education · First CA out of 20" }).count(),
      "the administrator's paper is on the teacher's marking page",
    );

    // Put it all back: the class teacher, the paper (nobody marked it), the subject.
    await admin.locator("li", { hasText: "JSS 1B" }).locator("select").selectOption({ label: "No class teacher" });
    await admin.waitForTimeout(600);
    await admin.locator("li", { hasText: "Civic Education" }).locator('[data-action="open-subject"]').click();
    await admin.locator("li", { hasText: "First CA" }).locator('[data-action="ask-remove-paper"]').click();
    await admin.click('[data-action="remove-paper"]');
    await admin.waitForSelector("text=No papers yet");
    await admin.click('[data-action="ask-remove-subject"]');
    await admin.click('[data-action="remove-subject"]');
    await admin.waitForSelector("form[data-form=subject]");
    assert.equal(await admin.locator("text=Civic Education").count(), 0, "the subject is gone");
  });
});
