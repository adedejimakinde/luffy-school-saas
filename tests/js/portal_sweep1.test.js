/**
 * Portal polish, sweep PR 1: the fees list as list rows in one card, setup as
 * stacked cards, and every date day-first. Pure functions of an API body, so
 * no browser; `tests/ui/sweep1.test.js` holds how they land on a screen.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import * as fees from "../../static/fees/states.js";
import * as setup from "../../static/setup/states.js";
import { dayFirst } from "../../static/web/html.js";

const BOOKS = {
  terms: [{ term_id: 7, term: "2025/2026 First term", is_current: true }],
  term_id: 7,
  term: "2025/2026 First term",
  has_fee_items: true,
  classes: [
    { class_group_id: 1, class_group: "JSS 1A", children: 25, collected_kobo: 5_000_000, billed_kobo: 20_000_000 },
    { class_group_id: 2, class_group: "JSS 1B", children: 1, collected_kobo: 0, billed_kobo: 0 },
    { class_group_id: 3, class_group: "JSS 2A", children: 30, collected_kobo: 30_000_000, billed_kobo: 20_000_000 },
  ],
};

test("the classes are list rows inside one card, not floating buttons", () => {
  const html = fees.books({ books: BOOKS });
  assert.equal((html.match(/class="card class-card"/g) || []).length, 1);
  assert.equal((html.match(/<li><button type="button" class="list-row class-row"/g) || []).length, 3);
  // Every row is inside that card.
  const card = html.slice(html.indexOf('class="card class-card"'));
  assert.ok(card.indexOf("</ul></div>") > card.lastIndexOf('data-action="open-class"'));
});

test("a row has the class in bold, the children muted, the amount, the share and a chevron", () => {
  const html = fees.books({ books: BOOKS });
  assert.match(html, /<span class="list-row-title">JSS 1A<\/span><span class="list-row-sub">25 children<\/span>/);
  assert.match(html, /<span class="list-row-sub">1 child<\/span>/);
  assert.match(html, /<span class="class-collected">₦50,000\.00<\/span><span class="class-share">25% collected<\/span>/);
  assert.match(html, /<span class="bar" role="img" aria-label="25% collected"><span style="width: 25%">/);
  assert.match(html, /<path d="M9 6l6 6-6 6"\/>/);
});

test("a row still opens its class through the page's own action", () => {
  const html = fees.books({ books: BOOKS });
  assert.match(html, /data-action="open-class" data-class="1"/);
});

test("a class nobody was billed for says so, and an overpaid one stops at 100%", () => {
  const html = fees.books({ books: BOOKS });
  assert.match(html, /JSS 1B[\s\S]*?<span class="class-share">Not billed<\/span>/);
  assert.match(html, /<span class="class-share">100% collected<\/span>/);
  assert.equal(fees.collectedShare(5, 0), null);
  assert.equal(fees.collectedShare(199, 200), 99);
});

test("setup's sections are each their own card under a heading", () => {
  const html = setup.shape({
    terms: [], classes: [], card: { template: "ogun", colour: "#143D8C", default_colour: "#143D8C" },
    subjects: [{ subject_id: 1, name: "Maths", department: "" }], departments: [{ value: "sci", label: "Science" }],
    conduct: { sections: [], scale: [], changes: [] },
  });
  const cards = html.split('<section class="card setup-card">').slice(1);
  for (const id of ["terms", "classes", "report-card", "conduct", "lga", "departments", "contact-email", "public-page"]) {
    const mine = cards.filter((c) => c.includes(`<h2 id="${id}">`));
    assert.equal(mine.length, 1, `${id} is in exactly one card`);
    assert.ok(mine[0].startsWith(`<h2 id="${id}">`), `${id}'s heading opens its card`);
  }
  // No heading sits on the bare page.
  assert.equal((html.match(/<h2 /g) || []).length, cards.length);
});

test("a section with nothing to show draws no empty card", () => {
  const html = setup.shape({ terms: [], classes: [] });
  assert.ok(!html.includes('<section class="card setup-card"></section>'));
  assert.ok(!html.includes('id="departments"'));
});

test("the office can set the short name beside the web page, with the default as its hint", () => {
  const html = setup.shape({ short_name: "", short_name_default: "Crestfield College" });
  assert.match(html, /<input id="short_name" name="short_name" value="" maxlength="60" autocomplete="off" placeholder="Crestfield College">/);
});

test("a stored day is said day first, never month first", () => {
  assert.equal(dayFirst("2026-11-08"), "8 Nov 2026");
  assert.equal(dayFirst("2026-01-31"), "31 Jan 2026");
  assert.equal(dayFirst("2026-11-08T09:30"), "8 Nov 2026");
  assert.equal(dayFirst(null), "");
  assert.equal(dayFirst("not a day"), "not a day");
  for (let m = 1; m <= 12; m++) assert.doesNotMatch(dayFirst(`2026-${String(m).padStart(2, "0")}-08`), /\d\/\d/);
});

test("the term's dates in setup are day first", () => {
  const html = setup.shape({
    terms: [{ term_id: 1, session: "2025/2026", name: "first", name_label: "First term", starts_on: "2025-09-15", ends_on: "2025-12-12", school_days: 62, is_current: true }],
  });
  assert.match(html, /15 Sep 2025 to 12 Dec 2025/);
  assert.doesNotMatch(html, /2025-09-15 to/);
});
