/**
 * The broadsheet table on a phone and a desk, in a real browser, at 320, 390
 * and 1280. Read only, against the demo (`tests/ui/screens.test.js` says how it
 * is served). Pos. is 40px and centred, Name 120-130px, each subject 72-80px;
 * Pos. and Name are pinned while only the table scrolls, never the page; at
 * 390 two whole subjects show beside them and at 320 one and a half.
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
const PORTAL = `http://app.${DOMAIN}:${PORT}`;
const SUNRISE = `http://sunrise-demo.${DOMAIN}:${PORT}`;

let browser;

before(async () => {
  browser = await chromium.launch({
    args: [`--host-resolver-rules=MAP *.${DOMAIN} 127.0.0.1, MAP ${DOMAIN} 127.0.0.1`],
  });
});
after(async () => {
  await browser?.close();
});

async function sheet(width) {
  const context = await browser.newContext({ viewport: { width, height: 800 } });
  const page = await context.newPage();
  await page.goto(`${PORTAL}/staff-sign-in/`);
  const status = await page.evaluate(async ({ identifier, password }) => {
    const { csrf_token: token } = await (await fetch("/api/csrf/")).json();
    return (await fetch("/api/login/", {
      method: "POST",
      headers: { "content-type": "application/json", "X-CSRFToken": token },
      body: JSON.stringify({ identifier, password }),
    })).status;
  }, { identifier: "sunrise.principal", password: PASSWORD });
  assert.equal(status, 200);
  await page.goto(`${SUNRISE}/broadsheet/`);
  await page.click('[data-action="open-class"]');
  await page.waitForSelector("table.broadsheet tbody tr");
  return { context, page };
}

for (const width of [320, 390, 1280]) {
  describe(`the broadsheet table at ${width}px`, () => {
    test("has pinned Pos. and Name, narrow subjects, and only the table scrolls", async () => {
      const { context, page } = await sheet(width);
      try {
        assert.ok(
          (await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)) <= 0,
          "the page scrolls sideways",
        );
        const m = await page.evaluate(() => {
          const box = document.querySelector(".scroll.wide");
          const b = box.getBoundingClientRect();
          const w = (el) => el.getBoundingClientRect().width;
          const head = [...document.querySelectorAll("table.broadsheet thead th")];
          const subj = head.filter((h) => h.classList.contains("subj"));
          const pinned = w(head[0]) + w(head[1]);
          const row = document.querySelector("table.broadsheet tbody tr");
          return {
            pos: w(head[0]),
            name: w(head[1]),
            subjects: subj.map(w),
            room: b.width - pinned,
            rowH: row.getBoundingClientRect().height,
            scrolls: box.scrollWidth > box.clientWidth,
            posAlign: getComputedStyle(row.children[0]).textAlign,
            nameSticky: getComputedStyle(row.children[1]).position,
            posSticky: getComputedStyle(row.children[0]).position,
            tabular: getComputedStyle(row.children[2]).fontVariantNumeric,
            titles: subj.map((h) => h.title),
            labels: subj.map((h) => h.textContent),
          };
        });
        assert.equal(m.posAlign, "center");
        assert.equal(m.posSticky, "sticky");
        assert.equal(m.nameSticky, "sticky");
        assert.match(m.tabular, /tabular-nums/);
        if (width < 640) {
          assert.equal(m.pos, 40);
          assert.ok(m.name >= 120 && m.name <= 130, `name is ${m.name}px`);
          for (const s of m.subjects) assert.ok(s >= 72 && s <= 80, `a subject is ${s}px`);
          assert.ok(m.rowH >= 50 && m.rowH <= 56, `a row is ${m.rowH}px`);
          assert.ok(m.scrolls, "the table scrolls inside its box");
          const whole = m.room / m.subjects[0];
          if (width >= 390) assert.ok(Math.floor(whole) >= 2, `only ${whole} subjects show`);
          else assert.ok(whole >= 1.5, `only ${whole} subjects show`);
          // The full name is in a title; the short one is in the header.
          assert.ok(m.titles.every((t) => t.length > 0));
          assert.ok(m.labels.some((l) => l !== m.titles[m.labels.indexOf(l)]), "no header is short");
          // Scrolling the table pins Pos. and Name and puts the shadow on.
          await page.evaluate(() => { document.querySelector(".scroll.wide").scrollLeft = 120; });
          await page.waitForSelector(".scroll[data-scrolled]");
          const left = await page.evaluate(() => {
            const r = document.querySelector("table.broadsheet tbody tr").children;
            const box = document.querySelector(".scroll.wide").getBoundingClientRect();
            return [r[0].getBoundingClientRect().left - box.left, r[1].getBoundingClientRect().left - box.left];
          });
          assert.ok(Math.abs(left[0]) < 1 && Math.abs(left[1] - 40) < 1, `not pinned: ${left}`);
          await page.waitForTimeout(250);
          assert.match(
            await page.evaluate(() => getComputedStyle(document.querySelector("table.broadsheet tbody td.name")).boxShadow),
            /6px 0px 8px -4px/,
            "no soft edge on the pinned column",
          );
          assert.ok(
            (await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)) <= 0,
            "scrolling the table scrolled the page",
          );
        }
        mkdirSync(join(OUT, String(width)), { recursive: true });
        await page.screenshot({ path: join(OUT, String(width), "broadsheet-table.png"), fullPage: true });
      } finally {
        await context.close();
      }
    });
  });
}
