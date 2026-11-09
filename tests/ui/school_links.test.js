/**
 * The installed app's sign-in, in a real browser: open a school's start_url signed out, follow
 * "Sign in", sign in, and never leave the school's host. Every page on the way shows the school's
 * crest and name and never Classnode's wordmark, and every URL is inside the manifest's scope, so
 * the installed app does not hand the person to a browser tab on `app.<domain>`.
 *
 * Against the same demo as `screens.test.js` (see its header): Sunrise's teacher and Harbour's.
 * Both schools are run, so a link built from the wrong school's host fails here too.
 */

import assert from "node:assert/strict";
import { after, before, describe, test } from "./timed.js";

import { chromium } from "playwright";

const DOMAIN = process.env.SCREENS_DOMAIN || "classnode.test";
const PORT = process.env.SCREENS_PORT || "8000";
const PASSWORD = process.env.SCREENS_PASSWORD || "demo-pass-2026";
const PORTAL_HOST = `app.${DOMAIN}`;
const SCHOOLS = [
  { name: /Sunrise/, host: `sunrise-demo.${DOMAIN}`, login: "sunrise.teacher", other: `harbour-demo.${DOMAIN}` },
  { name: /Harbour/, host: `harbour-demo.${DOMAIN}`, login: "harbour.teacher", other: `sunrise-demo.${DOMAIN}` },
];

let browser;

before(async () => {
  browser = await chromium.launch({
    args: [`--host-resolver-rules=MAP *.${DOMAIN} 127.0.0.1, MAP ${DOMAIN} 127.0.0.1`],
  });
});

after(async () => {
  await browser?.close();
});

async function settle(page) {
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => setTimeout(done, 50))));
}

/** The school's crest (or initials tile) is on screen and its name is in the header; no wordmark. */
async function assertSchoolHeader(page, school, where) {
  const seen = page.locator(".logo-school .crest:visible, .door-school .crest:visible");
  assert.ok((await seen.count()) > 0, `${where}: no school crest on screen at ${page.url()}`);
  const names = (await page.locator(".logo-school, .door-school").allTextContents()).join(" ");
  assert.match(names, school.name, `${where}: the school's name is missing at ${page.url()}`);
  assert.equal(await page.locator(".logo-word:visible").count(), 0, `${where}: Classnode's wordmark at ${page.url()}`);
}

describe("the installed app, signed out then signed in", () => {
  for (const school of SCHOOLS) {
    test(`${school.host}: start_url, Sign in, sign in: one host, the crest on every page`, async () => {
      const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
      const page = await context.newPage();
      const visited = [];
      page.on("framenavigated", (frame) => {
        if (frame === page.mainFrame()) visited.push(frame.url());
      });
      try {
        const base = `http://${school.host}:${PORT}`;
        // The manifest, read by the page itself so the browser's own name resolution is used.
        await page.goto(`${base}/staff-sign-in/`);
        const manifest = await page.evaluate(() => fetch("/site.webmanifest").then((r) => r.json()));
        visited.length = 0;
        const start = new URL(manifest.start_url, base);
        assert.equal(manifest.scope, "/");

        // The app opens signed out: the school's "Please sign in", in the school's header.
        await page.goto(start.href);
        await settle(page);
        await assertSchoolHeader(page, school, "start_url");
        assert.match(await page.locator("main").textContent(), /Please sign in/);

        // "Sign in" goes to this school's own door.
        const link = page.getByRole("link", { name: "Sign in" }).first();
        assert.equal(new URL(await link.evaluate((a) => a.href)).host, `${school.host}:${PORT}`);
        await Promise.all([page.waitForURL(`${base}/staff-sign-in/`), link.click()]);
        await settle(page);
        await assertSchoolHeader(page, school, "the staff door");

        // The parent door is one tap away, on the same host, in the same header.
        const parent = page.getByRole("link", { name: "I'm a parent" });
        assert.equal(new URL(await parent.evaluate((a) => a.href)).host, `${school.host}:${PORT}`);

        await page.fill("input[name=identifier]", school.login);
        await page.fill("input[name=password]", PASSWORD);
        await Promise.all([page.waitForURL(`${base}/home/`), page.locator("button[type=submit]").click()]);
        await settle(page);
        await assertSchoolHeader(page, school, "after sign-in");

        // Signing out lands on this school's door, in its header.
        await Promise.all([page.waitForURL(`${base}/staff-sign-in/`), page.locator("#sign-out button").click()]);
        await settle(page);
        await assertSchoolHeader(page, school, "after sign-out");

        for (const url of visited) {
          const where = new URL(url);
          assert.equal(where.host, `${school.host}:${PORT}`, `left the school's host: ${url}`);
          assert.ok(where.pathname.startsWith(manifest.scope), `outside the manifest's scope: ${url}`);
          assert.notEqual(where.hostname, PORTAL_HOST);
          assert.notEqual(where.hostname, school.other);
        }
        assert.ok(visited.length >= 4, `the walk saw too few pages: ${visited}`);
      } finally {
        await page.close();
        await context.close();
      }
    });
  }

  test("a school's website offers sign-in links on its own host only", async () => {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const page = await context.newPage();
    try {
      for (const school of SCHOOLS) {
        const base = `http://${school.host}:${PORT}`;
        await page.goto(`${base}/`);
        await settle(page);
        const hrefs = await page
          .locator("a[href*='sign-in']")
          .evaluateAll((links) => links.map((a) => new URL(a.href).host));
        assert.ok(hrefs.length >= 2, `${school.host}: no sign-in links on the website`);
        for (const host of hrefs) assert.equal(host, `${school.host}:${PORT}`);
      }
    } finally {
      await page.close();
      await context.close();
    }
  });
});
