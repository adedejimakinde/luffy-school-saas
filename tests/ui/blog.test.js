/**
 * Classnode's blog, in a real browser: classnode.co/blog/ and a post, and the
 * writing side on the portal's /write/ (`docs/blog.md`).
 *
 * It starts from a blog with nothing in it, as one ships, and photographs the
 * "First posts coming soon" state. Then a writer writes a post in the editor,
 * with a cover and a picture (refused until the picture is described), and
 * sends it for review; the writer's own attempt to publish it is refused; an
 * editor publishes it from the review queue; and it is on classnode.co and in
 * the sitemap. A few more posts are made through `blog.workflow` so the lists
 * have rows to land.
 *
 * Every page is then opened at 320, 375, 414, 768 and 1280 pixels and fails
 * when it scrolls sideways, when a target is under 44px, or when text on a
 * phone is under 15px, and is photographed into `<SCREENS_OUT>/blog/<width>/`.
 * The editor's phone bar is held to never covering the post, and to sitting
 * at the bottom of what is visible when the page shrinks for a keyboard.
 *
 * The writer and the editor are made here (`manage.py blog_account`) and
 * signed in with a session written by `manage.py shell`: the code the sign-in
 * door emails goes through a worker this job does not run, and the door
 * itself is held by `blog/tests/test_signin.py`. Its two steps are still
 * opened and photographed here. This file owns the blog: no other file in
 * `tests/ui/` touches it, so the files can run side by side.
 */

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { request } from "node:http";
import { dirname, join, resolve } from "node:path";
import { after, before, describe, test } from "node:test";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright";

const DOMAIN = process.env.SCREENS_DOMAIN || "classnode.test";
const PORT = process.env.SCREENS_PORT || "8000";
const OUT = join(process.env.SCREENS_OUT || "screens", "blog");
const PYTHON = process.env.PYTHON || "python";
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../..");

const SITE = `http://${DOMAIN}:${PORT}`;
const PORTAL = `http://app.${DOMAIN}:${PORT}`;

export const WIDTHS = [320, 375, 414, 768, 1280];
const WRITER = "writer@blog-ui.classnode.test";
const EDITOR = "editor@blog-ui.classnode.test";

/** Text the design sets below body size on purpose: labels, counts, initials, the footer. */
const SMALL_ON_PURPOSE = ".label, .tag, .count, .pane-head h2, .avatar, .avatar-sm, .site-foot";

/**
 * GET `url` from this machine, naming its host: `*.classnode.test` resolves
 * nowhere but in the browser (`--host-resolver-rules` below).
 */
function get(url) {
  const { hostname, port, pathname, search } = new URL(url);
  return new Promise((done, fail) => {
    const req = request(
      { host: "127.0.0.1", port, path: pathname + search, headers: { host: `${hostname}:${port}` } },
      (res) => {
        let body = "";
        res.setEncoding("utf8");
        res.on("data", (chunk) => (body += chunk));
        res.on("end", () => done({ status: res.statusCode, text: async () => body }));
      },
    );
    req.on("error", fail);
    req.end();
  });
}

function manage(...args) {
  return execFileSync(PYTHON, ["manage.py", ...args], { cwd: ROOT, encoding: "utf8" }).trim();
}

function shell(code) {
  return manage("shell", "-c", code);
}

/** A session for `email`, written straight into the session store; its key. */
function sessionFor(email) {
  return shell(`
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
from django.contrib.sessions.backends.db import SessionStore
from accounts.models import User
user = User.objects.get(email="${email}")
store = SessionStore()
store[SESSION_KEY] = str(user.pk)
store[BACKEND_SESSION_KEY] = "accounts.backends.IdentifierBackend"
store[HASH_SESSION_KEY] = user.get_session_auth_hash()
store.create()
print(store.session_key)
`).split("\n").pop();
}

/** Posts in each state, with real pictures, made through `blog.workflow` as the editor and writer would. */
function morePosts() {
  shell(`
from pathlib import Path
from accounts.models import User
from blog import images, workflow
from blog.models import Post
writer = User.objects.get(email="${WRITER}")
editor = User.objects.get(email="${EDITOR}")
pictures = ["static/website/photos/teacher-880.webp", "static/website/shots/slide-report-desk-1280.webp",
            "static/website/shots/slide-home-desk-1280.webp", "static/website/shots/slide-fees-desk-1280.webp"]
posts = [
  ("Taking the register on a shared phone", "register-on-a-shared-phone", "Attendance",
   "When three teachers share one handset, the register still has to be right. How to set it up so each class is marked once."),
  ("What the Ogun State report sheet asks for", "ogun-report-sheet", "Results",
   "The columns, the weighting of continuous assessment and exam, and what the Ministry expects to see printed at the bottom."),
  ("A principal's first ten minutes each morning", "principals-morning", "Leadership",
   "Who is in, what was collected yesterday and which classes are still waiting on marks. Read in one screen before assembly."),
  ("Fee reminders parents actually read", "fee-reminders-parents-read", "Fees",
   "Short, specific and sent once. What to put in a reminder so a parent knows what is owed and how to pay it."),
]
for (title, slug, tag, summary), picture in zip(posts, pictures):
    post = workflow.new_post(editor)
    workflow.save(editor, post, {"title": title, "slug": slug, "summary": summary, "tags": [tag],
        "body": "## Why it matters\\n\\n" + summary + "\\n\\nA second paragraph with a very long address in it: https://classnode.co/blog/a-very-long-address-that-has-to-wrap-on-a-small-phone-screen/ and a table:\\n\\n| Term | Students | Collected | Outstanding | Last payment |\\n|---|---|---|---|---|\\n| First term | 45 | 1,200,000 | 300,000 | 14 Oct 2026 |\\n| Second term | 44 | 1,150,000 | 350,000 | 13 Oct 2026 |\\n",
        "seo_title": title[:60], "seo_description": summary[:155], "cover_alt": "A picture for " + title})
    cover = images.store(post, Path(picture).read_bytes(), cover=True, by=editor)
    workflow.set_cover(editor, post, cover)
    workflow.publish(editor, Post.objects.get(pk=post.pk))
draft = workflow.new_post(writer)
workflow.save(writer, draft, {"title": "What a class teacher's remark should say", "slug": "class-teacher-remarks", "summary": "One sentence, about this child."})
review = workflow.new_post(writer)
workflow.save(writer, review, {"title": "Marking a late exam fairly", "slug": "marking-a-late-exam", "summary": "A student who missed the exam.", "body": "Words.",
    "seo_title": "Marking a late exam fairly", "seo_description": "A student who missed the exam.", "cover_alt": "A teacher at a desk"})
workflow.set_cover(writer, review, images.store(review, Path(pictures[0]).read_bytes(), cover=True, by=writer))
workflow.submit(writer, Post.objects.get(pk=review.pk))
back = workflow.new_post(writer)
workflow.save(writer, back, {"title": "Promoting a student who missed a term", "slug": "promoting-after-a-missed-term", "summary": "When to hold back.", "body": "Words.",
    "seo_title": "Promoting a student who missed a term", "seo_description": "When to hold back.", "cover_alt": "A classroom"})
workflow.set_cover(writer, back, images.store(back, Path(pictures[1]).read_bytes(), cover=True, by=writer))
workflow.submit(writer, Post.objects.get(pk=back.pk))
workflow.send_back(editor, Post.objects.get(pk=back.pk), "Shorten the opening, and add one example of a decision.")
`);
}

let browser;
const contexts = {};

async function contextFor(who) {
  if (contexts[who]) return contexts[who];
  const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  if (who !== "anyone") {
    const key = sessionFor(who === "writer" ? WRITER : EDITOR);
    await context.addCookies([{ name: "sessionid", value: key, domain: `.${DOMAIN}`, path: "/" }]);
  }
  contexts[who] = context;
  return context;
}

/** What a page must hold to at every width. */
function measure({ phone, smallOnPurpose }) {
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
  const describe = (el) => `<${el.tagName.toLowerCase()} class="${el.className}"> "${(el.textContent || el.value || el.getAttribute("aria-label") || "").trim().slice(0, 30)}"`;
  const targets = 'button, select, textarea, input:not([type="checkbox"]):not([type="radio"]):not([type="hidden"]), .btn, .tabs a, .topbar-nav a, .write-menu a, .crumb, .pager a, .row-actions a';
  for (const el of document.querySelectorAll(targets)) {
    if (!visible(el) || el.closest("dialog:not([open])")) continue;
    const height = el.getBoundingClientRect().height;
    if (height < 43.5) problems.push(`target ${Math.round(height)}px tall: ${describe(el)}`);
  }
  for (const el of document.querySelectorAll(".prose, .post-table, .tabs")) {
    if (visible(el) && el.getBoundingClientRect().right > root.clientWidth + 1) problems.push(`runs past the screen: ${describe(el)}`);
  }
  if (phone) {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const seen = new Set();
    while (walker.nextNode()) {
      const el = walker.currentNode.parentElement;
      if (!el || seen.has(el) || !walker.currentNode.textContent.trim()) continue;
      seen.add(el);
      if (!visible(el) || el.closest(smallOnPurpose) || el.closest("script, style, noscript, dialog:not([open])")) continue;
      const size = parseFloat(getComputedStyle(el).fontSize);
      if (size < 14.95) problems.push(`text ${size}px on a phone: ${describe(el)}`);
    }
  }
  return problems;
}

async function settle(page) {
  await page.waitForLoadState("networkidle");
  await page.evaluate(() => new Promise((done) => requestAnimationFrame(() => setTimeout(done, 50))));
}

async function shoot(page, width, name) {
  mkdirSync(join(OUT, String(width)), { recursive: true });
  const problems = await page.evaluate(measure, { phone: width < 640, smallOnPurpose: SMALL_ON_PURPOSE });
  await page.screenshot({ path: join(OUT, String(width), `${name}.png`), fullPage: true });
  assert.deepEqual(problems, [], `${name} at ${width}px`);
}

/** Open `url` as `who` at each width, photograph it, and hold it to `measure`. */
async function everyWidth(who, name, url, steps = async () => {}) {
  const context = await contextFor(who);
  const page = await context.newPage();
  try {
    for (const width of WIDTHS) {
      await page.setViewportSize({ width, height: width < 640 ? 800 : 900 });
      const response = await page.goto(url);
      assert.ok(response.ok(), `${name}: ${url} answered ${response.status()}`);
      await settle(page);
      await steps(page, width);
      await shoot(page, width, name);
    }
  } finally {
    await page.close();
  }
}

let postUrl;
let editorUrl;

describe("the blog", () => {
  before(async () => {
    shell(`
from blog.models import Post, SignInCode
Post.objects.all().delete()
SignInCode.objects.all().delete()
`);
    manage("blog_account", WRITER, "--name", "Kemi Oladipo", "--role", "writer");
    manage("blog_account", EDITOR, "--name", "Tunde Bello", "--role", "editor");
    browser = await chromium.launch({
      args: [`--host-resolver-rules=MAP *.${DOMAIN} 127.0.0.1, MAP ${DOMAIN} 127.0.0.1`],
    });
  });

  after(async () => {
    await browser?.close();
  });

  test("with nothing published, /blog/ says the first posts are coming", async () => {
    await everyWidth("anyone", "blog-empty", `${SITE}/blog/`, async (page) => {
      assert.match(await page.locator("main").innerText(), /First posts coming soon/);
    });
    const sitemap = await (await get(`${SITE}/sitemap.xml`)).text();
    assert.doesNotMatch(sitemap, /\/blog\/[a-z0-9-]+\//, "no post in the sitemap");
  });

  test("the sign-in door: the email, then the code", async () => {
    await everyWidth("anyone", "sign-in", `${PORTAL}/write/sign-in/`);
    await everyWidth("anyone", "sign-in-code", `${PORTAL}/write/sign-in/`, async (page) => {
      await page.fill("#email", "somebody@example.com");
      await Promise.all([page.waitForLoadState("load"), page.click("button.btn-primary")]);
      await settle(page);
      assert.match(await page.locator("main").innerText(), /If that address belongs to a blog account/);
    });
  });

  test("a writer writes a post, the writer cannot publish it, an editor does", async () => {
    const writer = await (await contextFor("writer")).newPage();
    await writer.setViewportSize({ width: 1280, height: 900 });
    await writer.goto(`${PORTAL}/write/`);
    await Promise.all([writer.waitForURL(/\/write\/posts\/\d+\/\?done=created/), writer.click("text=New post")]);
    editorUrl = writer.url().split("?")[0];

    await writer.fill("#id_title", "Five checks before you release first term report cards");
    await writer.fill("#id_body", "Report cards go home once a term, and every parent reads them closely.\n\n## 1. Every subject has a mark\n\nOpen each class's broadsheet and look for blanks.\n\n<script>alert('not on this page')</script>\n\n- One sentence from the class teacher.\n- One sentence from the principal.\n\n> Checking three cards by hand catches more than reading thirty on screen.\n");
    await writer.waitForFunction(() => document.querySelector("#preview h2")?.textContent.includes("Every subject"));
    assert.equal(await writer.locator("#preview script").count(), 0, "the preview has no script");

    // The picture box refuses a picture with no description.
    await writer.click('[data-md="image"]');
    await writer.setInputFiles("#img-file", join(ROOT, "static/website/shots/slide-home-desk-640.webp"));
    await writer.click("#img-insert");
    assert.match(await writer.locator("#img-error").innerText(), /Describe the picture/);
    await writer.fill("#img-alt", "The principal's home screen with classes still waiting on marks");
    await writer.click("#img-insert");
    await writer.waitForFunction(() => /image:[0-9a-f]{32}/.test(document.querySelector("#id_body").value));
    await writer.waitForFunction(() => document.querySelector("#preview img")?.complete);

    await writer.fill("#id_slug", "five-checks-before-report-cards");
    await writer.fill("#id_summary", "A short list a principal can run on the Friday before cards go home, so no parent finds a missing mark first.");
    await writer.fill("#id_tags", "Results, Principals");
    await writer.fill("#id_seo_title", "Five checks before releasing report cards");
    await writer.fill("#id_seo_description", "Five checks a principal can run before first term report cards go home: marks, totals, attendance, remarks and names.");
    await writer.setInputFiles("#id_cover", join(ROOT, "static/website/photos/bursar-880.webp"));
    await writer.fill("#id_cover_alt", "A bursar at her desk checking payments on a laptop");
    await Promise.all([writer.waitForURL(/done=saved/), writer.click('.ed-actions-desk button[value="save"]')]);
    assert.match(await writer.locator("main").innerText(), /Saved\./);

    // The writer's own attempt to publish, sent past the page: refused, and still a draft.
    const status = await writer.evaluate(async () => {
      const form = new FormData(document.getElementById("post-form"));
      form.set("action", "publish");
      return (await fetch(location.pathname, { method: "POST", body: form })).status;
    });
    assert.equal(status, 403, "a writer cannot publish");

    await Promise.all([writer.waitForURL(/done=submitted/), writer.click('.ed-actions-desk button[value="submit"]')]);
    assert.match(await writer.locator(".ed-status").innerText(), /In review/);
    const slug = "five-checks-before-report-cards";
    postUrl = `${SITE}/blog/${slug}/`;
    assert.equal((await get(postUrl)).status, 404, "in review is not public");
    await writer.close();

    const editor = await (await contextFor("editor")).newPage();
    await editor.setViewportSize({ width: 1280, height: 900 });
    await editor.goto(`${PORTAL}/write/review/`);
    await Promise.all([editor.waitForURL(/\/write\/posts\/\d+\/$/), editor.click(`a.btn-primary:has-text("Review")`)]);
    await Promise.all([editor.waitForURL(/done=published/), editor.click('.ed-actions-desk button[value="publish"]')]);
    await editor.close();

    const page = await get(postUrl);
    assert.equal(page.status, 200, "published is public");
    const html = await page.text();
    assert.doesNotMatch(html, /not on this page/, "the script tag was stripped");
    assert.doesNotMatch(html, /write\/app\.js|write\/tools\.js/, "no editor script on a public page");
    assert.match(await (await get(`${SITE}/sitemap.xml`)).text(), new RegExp(`/blog/${slug}/`));

    morePosts();
  });

  test("every page, at every width", async () => {
    await everyWidth("anyone", "blog", `${SITE}/blog/`);
    await everyWidth("anyone", "post", postUrl);
    await everyWidth("anyone", "post-with-table", `${SITE}/blog/ogun-report-sheet/`, async (page) => {
      const table = await page.evaluate(() => {
        const box = document.querySelector(".post-table");
        return { scrolls: box.scrollWidth >= box.clientWidth, right: box.getBoundingClientRect().right, room: document.documentElement.clientWidth };
      });
      assert.ok(table.right <= table.room + 1, "the table stays inside the screen");
    });
    await everyWidth("writer", "write-posts", `${PORTAL}/write/`);
    await everyWidth("writer", "write-menu", `${PORTAL}/write/`, async (page, width) => {
      if (width < 768) {
        await page.click(".menu-toggle");
        await page.waitForSelector("#write-menu:popover-open");
      }
    });
    await everyWidth("writer", "editor-writer", `${PORTAL}/write/`, async (page) => {
      await page.click('a:has-text("What a class teacher")');
      await settle(page);
    });
    await everyWidth("writer", "editor-preview", editorUrl.replace(/\/$/, "/view/"));
    await everyWidth("editor", "review", `${PORTAL}/write/review/`);
    await everyWidth("editor", "review-published", `${PORTAL}/write/review/?state=published`);
    await everyWidth("editor", "editor-review", `${PORTAL}/write/review/`, async (page) => {
      await page.click('a.btn-primary:has-text("Review")');
      await settle(page);
    });
    await everyWidth("editor", "editor-published", editorUrl);
    for (const tab of ["preview", "details"]) {
      await everyWidth("editor", `editor-${tab}-tab`, editorUrl, async (page, width) => {
        if (width < 1100) {
          await page.click(`.ed-tabs [data-tab="${tab}"]`);
          await settle(page);
        }
      });
    }
  });

  test("on a phone the editor's bar never covers the post, and sits above a keyboard", async () => {
    const page = await (await contextFor("writer")).newPage();
    await page.setViewportSize({ width: 375, height: 800 });
    await page.goto(`${PORTAL}/write/`);
    await page.click('a:has-text("What a class teacher")');
    // `click` returns before the navigation commits, and "networkidle" on the page being left
    // can already be true, so `settle` alone let the next line run on the post list, which has
    // no `.ed-bottom` (main run #618). Wait for the editor itself.
    await page.waitForSelector(".ed-bottom");
    await settle(page);
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    const atBottom = await page.evaluate(() => {
      const bar = document.querySelector(".ed-bottom").getBoundingClientRect();
      const fields = [...document.querySelectorAll(".ed-main textarea, .ed-main .md-help")].map((el) => el.getBoundingClientRect().bottom);
      return { barTop: bar.top, barBottom: bar.bottom, lastWords: Math.max(...fields), height: innerHeight };
    });
    assert.ok(atBottom.lastWords <= atBottom.barTop, `the bar covers the post: ${JSON.stringify(atBottom)}`);
    assert.ok(Math.abs(atBottom.barBottom - atBottom.height) <= 1, "the bar is at the bottom of the screen");

    // A keyboard that shrinks the page (Chrome on Android, `interactive-widget`): the bar rides on top of it.
    await page.focus("#id_body");
    await page.setViewportSize({ width: 375, height: 420 });
    await settle(page);
    const typing = await page.evaluate(() => {
      const bar = document.querySelector(".ed-bottom").getBoundingClientRect();
      const field = document.querySelector("#id_body").getBoundingClientRect();
      return { barBottom: bar.bottom, height: innerHeight, usable: bar.height >= 60 };
    });
    assert.ok(Math.abs(typing.barBottom - typing.height) <= 1, `the bar is above the keyboard: ${JSON.stringify(typing)}`);
    mkdirSync(join(OUT, "375"), { recursive: true });
    await page.screenshot({ path: join(OUT, "375", "editor-typing.png") });
    await page.close();
  });

  test("the public pages run no script but the phone menu's", async () => {
    for (const url of [`${SITE}/blog/`, postUrl]) {
      const html = await (await get(url)).text();
      const scripts = [...html.matchAll(/<script\b([^>]*)>/g)].map((m) => m[1].trim());
      assert.deepEqual(scripts.filter((attrs) => attrs !== 'type="module"' && attrs !== 'type="application/ld+json"'), [], url);
      assert.doesNotMatch(html, /src="[^"]*\/write\//, url);
    }
  });
});
