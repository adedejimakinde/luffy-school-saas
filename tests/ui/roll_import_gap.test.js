/**
 * After an import, the office is told which children will get no email, and can take the list away.
 *
 * Absence alerts and payment receipts go by email only (`docs/messaging.md` D13), and an imported
 * guardian usually has a phone and nothing else. `tests/js/` proves the list and the file; only a
 * browser shows the list on a phone and the download arriving. Runs against the same demo as
 * `screens.test.js` (see its header), as Sunrise's administrator, at 360px. The three children are
 * added to JSS 1A under admission numbers made from the clock, so a second run does not collide.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
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
  const context = await browser.newContext({
    viewport: { width: 360, height: 740 },
    hasTouch: true,
    acceptDownloads: true,
  });
  page = await context.newPage();
  await page.goto(`${PORTAL}/staff-sign-in/`);
  const status = await page.evaluate(async (password) => {
    const { csrf_token: token } = await (await fetch("/api/csrf/")).json();
    const response = await fetch("/api/login/", {
      method: "POST",
      headers: { "content-type": "application/json", "X-CSRFToken": token },
      body: JSON.stringify({ identifier: "sunrise.admin", password }),
    });
    return response.status;
  }, PASSWORD);
  assert.equal(status, 200, "signing in as sunrise.admin");
});

after(async () => {
  await browser?.close();
});

describe("the import's gap report", () => {
  test("lists the phone-only and the guardian-less, not the emailed, and downloads as a CSV", async () => {
    const stamp = String(Date.now());
    const phone = `0803${stamp.slice(-7)}`;
    const csv = [
      "Full name,Class group,Reference,Guardian name,Guardian contact",
      `Gap One,JSS 1A,G${stamp}1,Mrs One,${phone}`,
      `Gap Two,JSS 1A,G${stamp}2,Mr Two,two${stamp}@example.test`,
      `Gap Three,JSS 1A,G${stamp}3,,`,
    ].join("\n");

    await page.goto(`${SUNRISE}/roll/import/`);
    await page.setInputFiles("input[type=file]", { name: "gap.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
    await page.click("text=Check the file");
    await page.click("button:has-text('Admit 3 children')");
    await page.waitForSelector("table.no-email");

    const listed = await page.locator("table.no-email tbody tr").allInnerTexts();
    assert.equal(listed.length, 2);
    assert.match(listed[0], /Gap One/);
    assert.match(listed[0], /A phone number only\./);
    assert.match(listed[1], /Gap Three/);
    assert.match(listed[1], /No guardian was given\./);
    assert.doesNotMatch(await page.locator("table.no-email").innerText(), /Gap Two/);
    assert.equal(
      await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth),
      true,
      "the report does not scroll the page sideways at 360px",
    );

    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.click('[data-action="download-no-email"]'),
    ]);
    assert.equal(download.suggestedFilename(), "students-without-guardian-email.csv");
    const text = readFileSync(await download.path(), "utf8");
    assert.equal(text.charCodeAt(0), 0xfeff, "a byte-order mark, so Excel reads the names as UTF-8");
    const lines = text.slice(1).trim().split("\r\n");
    assert.equal(lines.length, 3);
    assert.match(lines[1], new RegExp(`^"\\d+","Gap One","JSS 1A","G${stamp}1","Mrs One","\\+234803\\d{7}","A phone number only\\."$`));
    assert.match(lines[2], new RegExp(`"Gap Three","JSS 1A","G${stamp}3","","","No guardian was given\\."$`));
    assert.doesNotMatch(text, /Gap Two/);
  });
});
