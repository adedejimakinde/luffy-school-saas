/**
 * "Forgot password", in a real browser: asking for a link, and choosing a new
 * password (`accounts/password_views.py`, `docs/sign-in-page.md`).
 *
 * Every state of the two pages is opened at 320, 390 and 1280 pixels, on a
 * school's own host (Sunrise's, in Sunrise's look) and on the portal (in
 * Classnode's), and fails when it has no doctype or language, scrolls
 * sideways, has a target under 44px, or sets text under 15px on a phone. Each
 * is photographed into `<SCREENS_OUT>/password/<width>/`.
 *
 * Then the flow, as a person meets it: "Forgot password?" on both of a
 * school's doors goes to that school's own page and back, never to another
 * host; and a link asked for on Sunrise's host is dead on Harbour's and on the
 * portal, sets a new password on Sunrise's, signs the person's other session
 * out, lands on Sunrise's own door, opens that door with the new password, and
 * is dead the second time.
 *
 * Against the same demo as `screens.test.js` (see its header). The email a
 * request sends goes through a worker this job does not run, so the link is
 * made here with the rule that makes every link (`accounts.password_reset`,
 * through `manage.py shell`, as `blog.test.js` writes its sessions), for a
 * person of this file's own: a parent with no children, whom no other file in
 * `tests/ui/` signs in as and no page of the school's lists. The request page
 * itself is still posted to in the browser. Who is sent a link, and every rule
 * about it, is `accounts/tests/test_password_reset.py`'s.
 */

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { after, before, describe, test } from "./timed.js";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const DOMAIN = process.env.SCREENS_DOMAIN || "classnode.test";
const PORT = process.env.SCREENS_PORT || "8000";
const OUT = join(process.env.SCREENS_OUT || "screens", "password");
const PYTHON = process.env.PYTHON || "python";
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

const PORTAL = `http://app.${DOMAIN}:${PORT}`;
const SUNRISE = `http://sunrise-demo.${DOMAIN}:${PORT}`;
const HARBOUR = `http://harbour-demo.${DOMAIN}:${PORT}`;

export const WIDTHS = [320, 390, 1280];

// This file's own person: a parent at Sunrise and at nowhere else.
const PERSON = "ui.reset@password-ui.classnode.test";
const OLD = "the-old-password-1";

function shell(code) {
  return execFileSync(PYTHON, ["manage.py", "shell", "-c", code], { cwd: ROOT, encoding: "utf8" }).trim();
}

/** The person, with the old password again, whatever an earlier run left. */
function person() {
  shell(`
from accounts.models import Role, User
from accounts.services import grant_membership
from schools.models import School
user = User.objects.filter(username="${PERSON}").first() or User.objects.create_user("${PERSON}", None, full_name="Reset Parent", email="${PERSON}")
user.set_password("${OLD}")
user.save(update_fields=["password"])
grant_membership(user, School.objects.get(slug="sunrise-demo"), Role.PARENT)
`);
}

/** A reset link for the person, asked for on `slug`'s host (null: the portal's). Its path. */
function linkPath(slug) {
  const token = shell(`
from django.db import transaction
from accounts.models import User
from accounts.password_reset import _mint
from schools.models import School
with transaction.atomic():
    reset, raw = _mint(User.objects.get(username="${PERSON}"), ${slug ? `School.objects.get(slug="${slug}")` : "None"})
print(raw)
`).split("\n").pop();
  return `/reset-password/${token}/`;
}

/** What a page must hold to at every width (`screens.test.js`'s rules, for a door). */
function measure({ phone }) {
  const problems = [];
  const root = document.documentElement;
  if (document.compatMode !== "CSS1Compat") problems.push(`quirks mode: no doctype (${document.compatMode})`);
  if (!root.lang) problems.push("no lang on <html>");
  if (root.scrollWidth > root.clientWidth) {
    problems.push(`scrolls sideways: ${root.scrollWidth}px of content in ${root.clientWidth}px`);
  }
  const visible = (el) => {
    const box = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return box.width > 0 && box.height > 0 && style.visibility !== "hidden" && style.display !== "none";
  };
  const describe = (el) => `<${el.tagName.toLowerCase()} class="${el.className}"> "${(el.textContent || el.value || "").trim().slice(0, 30)}"`;
  // Every link in the card too: on these pages each one is a way on, tapped with a thumb.
  for (const el of document.querySelectorAll('button, input:not([type="hidden"]), .btn, main a')) {
    if (!visible(el)) continue;
    const height = el.getBoundingClientRect().height;
    if (height < 43.5) problems.push(`target ${Math.round(height)}px tall: ${describe(el)}`);
  }
  const card = document.querySelector("main").getBoundingClientRect();
  if (card.left < 15.5 && root.clientWidth < 640) problems.push(`the card is ${Math.round(card.left)}px from the edge, under 16`);
  if (phone) {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const seen = new Set();
    while (walker.nextNode()) {
      const el = walker.currentNode.parentElement;
      if (!el || seen.has(el) || !walker.currentNode.textContent.trim()) continue;
      seen.add(el);
      if (!visible(el) || el.closest("script, style, noscript")) continue;
      const size = parseFloat(getComputedStyle(el).fontSize);
      if (size < 14.95) problems.push(`text ${size}px on a phone: ${describe(el)}`);
    }
  }
  return problems;
}

/** Whose look the page wears: the school's name over the card, or Classnode's mark. */
function look() {
  const name = document.querySelector(".door-name");
  return {
    school: name ? name.textContent.trim() : null,
    classnode: Boolean(document.querySelector(".door-logo .logo-mark")),
    foot: document.querySelector(".door-foot").textContent.trim(),
    robots: document.querySelector('meta[name="robots"]')?.content || "",
  };
}

async function settle(page) {
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => setTimeout(done, 50))));
}

async function check(page, width, name) {
  mkdirSync(join(OUT, String(width)), { recursive: true });
  await page.screenshot({ path: join(OUT, String(width), `${name}.png`), fullPage: true });
  return (await page.evaluate(measure, { phone: width < 640 })).map((problem) => `${width}px ${name}: ${problem}`);
}

let browser;

before(async () => {
  browser = await chromium.launch({
    args: ["--font-render-hinting=full", `--host-resolver-rules=MAP *.${DOMAIN} 127.0.0.1, MAP ${DOMAIN} 127.0.0.1`],
  });
  person();
});

after(async () => {
  await browser?.close();
});

describe("forgot password, at every width", () => {
  const HOSTS = [
    { key: "school", base: SUNRISE, slug: "sunrise-demo", school: /Sunrise/ },
    { key: "portal", base: PORTAL, slug: null, school: null },
  ];

  for (const host of HOSTS) {
    test(`every state on the ${host.key}'s host, in its look`, async () => {
      const context = await browser.newContext({ viewport: { width: WIDTHS[0], height: 800 } });
      const page = await context.newPage();
      const problems = [];
      // Asked for once: every width opens the same link, and none of them spends it.
      const link = host.base + linkPath(host.slug);

      const wears = async (state) => {
        const seen = await page.evaluate(look);
        assert.equal(new URL(page.url()).origin, host.base, `${state} left the host`);
        assert.match(seen.robots, /noindex/, `${state} may be indexed`);
        if (host.school) {
          assert.match(seen.school || "", host.school, `${state} does not name the school`);
          assert.equal(seen.classnode, false, `${state} shows Classnode's mark on a school's host`);
          assert.equal(seen.foot, "Powered by Classnode");
        } else {
          assert.equal(seen.school, null, `${state} names a school on the portal`);
          assert.equal(seen.classnode, true);
          assert.equal(seen.foot, "Classnode");
        }
      };

      try {
        for (const width of WIDTHS) {
          await page.setViewportSize({ width, height: 800 });

          // Asking: the form, the empty box said under it, and the one answer.
          assert.equal((await page.goto(`${host.base}/forgot-password/`)).status(), 200);
          await settle(page);
          await wears("ask");
          problems.push(...(await check(page, width, `${host.key}-ask`)));

          await page.locator("button[type=submit]").click();
          await settle(page);
          assert.match(await page.locator("#forgot-error").textContent(), /Type the email address or phone number/);
          await wears("ask, nothing typed");
          problems.push(...(await check(page, width, `${host.key}-ask-empty`)));

          await page.fill("#identifier", "nobody-at-all@password-ui.classnode.test");
          await page.locator("button[type=submit]").click();
          await settle(page);
          assert.match(await page.locator("main").textContent(), /If an account matches, we've sent a link/);
          assert.equal(await page.locator("form").count(), 0);
          await wears("sent");
          problems.push(...(await check(page, width, `${host.key}-sent`)));

          // Choosing: the form, a password that is too short, and a dead link.
          assert.equal((await page.goto(link)).status(), 200);
          await settle(page);
          assert.equal(await page.locator("h1").textContent(), "Choose a new password");
          await wears("choose");
          problems.push(...(await check(page, width, `${host.key}-choose`)));

          await page.fill("#password", "short");
          await page.fill("#password_again", "short");
          await page.locator("button[type=submit]").click();
          await settle(page);
          assert.match(await page.locator("#reset-error").textContent(), /at least 10 characters/);
          await wears("choose, too short");
          problems.push(...(await check(page, width, `${host.key}-choose-refused`)));

          assert.equal((await page.goto(`${host.base}/reset-password/not-a-link-anybody-was-sent/`)).status(), 404);
          await settle(page);
          assert.equal(await page.locator("h1").textContent(), "This link no longer works.");
          await wears("dead");
          problems.push(...(await check(page, width, `${host.key}-dead`)));
        }
      } finally {
        await page.close();
        await context.close();
      }
      assert.deepEqual(problems, []);
    });
  }

  test("a school with no crest shows its initials, and both doors carry the link", async () => {
    const context = await browser.newContext({ viewport: { width: 390, height: 800 } });
    const page = await context.newPage();
    const problems = [];
    try {
      for (const width of WIDTHS) {
        await page.setViewportSize({ width, height: 800 });
        await page.goto(`${HARBOUR}/forgot-password/`);
        await settle(page);
        assert.match((await page.evaluate(look)).school, /Harbour/);
        assert.equal(await page.locator(".door-school .crest img").count(), 0);
        problems.push(...(await check(page, width, "school-initials-ask")));

        // The two doors with their new link, for the photograph and the thumb.
        for (const [name, path] of [["staff-door", "/staff-sign-in/"], ["parent-door", "/sign-in/"]]) {
          await page.goto(SUNRISE + path);
          await settle(page);
          const link = page.getByRole("link", { name: "Forgot password?" });
          assert.equal(await link.count(), 1, `${path} has no "Forgot password?"`);
          if (name === "staff-door") {
            const height = (await link.boundingBox()).height;
            assert.ok(height >= 43.5, `"Forgot password?" is ${Math.round(height)}px tall at ${width}px`);
          }
          mkdirSync(join(OUT, String(width)), { recursive: true });
          await page.screenshot({ path: join(OUT, String(width), `${name}.png`), fullPage: true });
          assert.equal(
            await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth),
            true,
            `${path} scrolls sideways at ${width}px`,
          );
        }
      }
    } finally {
      await page.close();
      await context.close();
    }
    assert.deepEqual(problems, []);
  });
});

describe("forgot password stays on the school's host", () => {
  test("from each door to the page and back, never leaving the host", async () => {
    for (const base of [SUNRISE, HARBOUR]) {
      const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
      const page = await context.newPage();
      const visited = [];
      page.on("framenavigated", (frame) => {
        if (frame === page.mainFrame() && frame.url().startsWith("http")) visited.push(frame.url());
      });
      try {
        for (const [door, there] of [["/staff-sign-in/", "/forgot-password/"], ["/sign-in/", "/forgot-password/?from=sign-in"]]) {
          await page.goto(base + door);
          await settle(page);
          await Promise.all([page.waitForURL(base + there), page.getByRole("link", { name: "Forgot password?" }).click()]);
          await settle(page);
          assert.equal(await page.locator("h1").textContent(), "Forgot your password?");

          // Asked, answered, and the way back is the door they came from.
          await page.fill("#identifier", "08030000000");
          await Promise.all([page.waitForLoadState("load"), page.locator("button[type=submit]").click()]);
          await settle(page);
          assert.equal(await page.locator("h1").textContent(), "Check your email");
          await Promise.all([page.waitForURL(base + door), page.getByRole("link", { name: "Back to sign in" }).click()]);
          await settle(page);
        }
        assert.ok(visited.length >= 6, `the walk saw too few pages: ${visited}`);
        for (const url of visited) assert.equal(new URL(url).origin, base, `left the school's host: ${url}`);
      } finally {
        await page.close();
        await context.close();
      }
    }
  });

  test("a link works once, on the host it was asked for from, and signs every session out", async () => {
    person();
    const fresh = `a-new-password-${Date.now()}`;
    const path = linkPath("sunrise-demo");

    /** POST the staff door's own route from the page that is open. */
    const signIn = (page, password) =>
      page.evaluate(
        async ({ identifier, password }) => {
          const { csrf_token: token } = await (await fetch("/api/csrf/")).json();
          const response = await fetch("/api/login/", {
            method: "POST",
            headers: { "content-type": "application/json", "X-CSRFToken": token },
            body: JSON.stringify({ identifier, password }),
          });
          return response.status;
        },
        { identifier: PERSON, password },
      );
    const cards = (page) => page.evaluate(async () => (await fetch("/api/results/cards/")).status);

    // Another browser, already signed in on Sunrise's door with the old password.
    const elsewhere = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const other = await elsewhere.newPage();
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const page = await context.newPage();
    try {
      await other.goto(`${SUNRISE}/staff-sign-in/`);
      assert.equal(await signIn(other, OLD), 200, "the old password opens the door before the reset");
      assert.equal(await cards(other), 200);

      // Sunrise's link, on Harbour's host and on the portal: a dead link, and nothing to type into.
      for (const elsewhereHost of [HARBOUR, PORTAL]) {
        assert.equal((await page.goto(elsewhereHost + path)).status(), 404, `${elsewhereHost} opened Sunrise's link`);
        assert.equal(await page.locator("h1").textContent(), "This link no longer works.");
        assert.equal(await page.locator("input[type=password]").count(), 0);
      }

      // On its own host: choose a password, and land on this host's own door.
      assert.equal((await page.goto(SUNRISE + path)).status(), 200);
      await settle(page);
      await page.fill("#password", fresh);
      await page.fill("#password_again", fresh);
      await Promise.all([page.waitForURL(`${SUNRISE}/staff-sign-in/`), page.locator("button[type=submit]").click()]);
      await settle(page);
      assert.match((await page.locator(".door-name").textContent()) || "", /Sunrise/);

      // The new password opens that door, the old one does not, and the other browser is out.
      assert.equal(await signIn(page, OLD), 401);
      assert.equal(await signIn(page, fresh), 200);
      assert.equal(await cards(other), 401, "the session signed in before the reset is still good");

      // Once: the same link again is a dead link.
      assert.equal((await page.goto(SUNRISE + path)).status(), 404);
      assert.equal(await page.locator("h1").textContent(), "This link no longer works.");
    } finally {
      await page.close();
      await other.close();
      await context.close();
      await elsewhere.close();
    }
  });
});
