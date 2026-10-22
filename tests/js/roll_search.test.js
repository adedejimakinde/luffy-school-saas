/**
 * The roll's search, class filter and pages. A school of 600 children is one
 * list nobody can scan, so a long roll gets a search box, a class filter and 25
 * children to a page; a short one is untouched.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { htmlFor, fromRoll } from "../../static/roll/app.js";
import { PAGE_SIZE, matching, rollList } from "../../static/roll/states.js";

const CLASSES = [
  { class_group_id: 11, name: "JSS 1A" },
  { class_group_id: 12, name: "JSS 1B" },
];

function children(n) {
  return Array.from({ length: n }, (_, i) => ({
    student_membership_id: i + 1,
    student: `Child ${String(i + 1).padStart(3, "0")} ${i % 2 ? "Bello" : "Adeyemi"}`,
    username: `STM/2026/${String(i + 1).padStart(4, "0")}`,
    reference: `R${i + 1}`,
    class_group_id: i % 3 === 0 ? 11 : i % 3 === 1 ? 12 : null,
    class_group: i % 3 === 0 ? "JSS 1A" : i % 3 === 1 ? "JSS 1B" : null,
  }));
}

const roll = (n, view) => ({ ...fromRoll({ ok: true, body: { term: "First term", children: children(n), classes: CLASSES, may_admit: true, may_place: true } }), view });
const rows = (html) => (html.match(/<li class="child/g) || []).length;

test("a short roll is exactly what it was: no search, no filter, no pages", () => {
  const html = htmlFor(roll(8));
  assert.equal(rows(html), 8);
  assert.doesNotMatch(html, /role="search"/);
  assert.doesNotMatch(html, /class="pager"/);
  assert.doesNotMatch(html, /roll-count/);
});

test("a long roll shows 25 to a page, says how many there are, and has a way to the next", () => {
  const html = htmlFor(roll(62));
  assert.equal(rows(html), PAGE_SIZE);
  assert.match(html, /role="search"/);
  assert.match(html, /Showing 1 to 25 of 62/);
  assert.match(html, /<button type="button" data-action="page" data-to="0" disabled>Previous<\/button>/);
  assert.match(html, /data-action="page" data-to="2">Next<\/button>/);
  assert.match(html, /Page 1 of 3/);
});

test("the last page is the remainder, and Next is off", () => {
  const html = rollList({ children: children(62), classes: CLASSES, may_place: true, view: { page: 3 } });
  assert.equal(rows(html), 12);
  assert.match(html, /Showing 51 to 62 of 62/);
  assert.match(html, /data-to="4" disabled>Next/);
});

test("a page past the end is the last page, not an empty one", () => {
  assert.equal(rows(rollList({ children: children(62), view: { page: 99 } })), 12);
  assert.equal(rows(rollList({ children: children(62), view: { page: -4 } })), PAGE_SIZE);
});

test("a search keeps the children every word of it is in, in roll order", () => {
  const all = children(62);
  assert.deepEqual(matching(all, { query: "adeyemi 0" }).map((c) => c.student_membership_id).slice(0, 3), [1, 3, 5]);
  assert.equal(matching(all, { query: "STM/2026/0042" }).length, 1);
  assert.equal(matching(all, { query: "r7" })[0].student_membership_id, 7);
  assert.equal(matching(all, { query: "jss 1b" }).length, 21);
  assert.equal(matching(all, { query: "nobody" }).length, 0);
  assert.equal(matching(all, { query: "  " }).length, 62);
});

test("the class filter takes a class, or the children who are not in one yet", () => {
  const all = children(62);
  assert.equal(matching(all, { cls: "11" }).length, 21);
  assert.equal(matching(all, { cls: "none" }).length, 20);
  assert.equal(matching(all, { cls: "11", query: "Bello" }).length, matching(all, { cls: "11" }).filter((c) => /Bello/.test(c.student)).length);
});

test("a filtered list says how many, drops the pages it no longer needs, and can be cleared", () => {
  const html = htmlFor(roll(62, { query: "STM/2026/0042" }));
  assert.equal(rows(html), 1);
  assert.match(html, /1 of 62 children/);
  assert.doesNotMatch(html, /class="pager"/);
  assert.match(html, /id="roll-search"[^>]*value="STM\/2026\/0042"/);

  const none = htmlFor(roll(62, { query: "zzz" }));
  assert.equal(rows(none), 0);
  assert.match(none, /No child matches/);
  assert.match(none, /data-action="clear-search">Show everyone/);
});

test("the controls are not forms and carry no data-child, so a row's class change is still the only change", () => {
  const html = htmlFor(roll(62));
  const tools = html.slice(html.indexOf('role="search"'), html.indexOf("data-list"));
  assert.doesNotMatch(tools, /<form|data-child/);
  assert.match(tools, /<label for="roll-search">Find a child<\/label>/);
  assert.match(tools, /<label for="roll-class">Class<\/label>/);
  assert.match(tools, /<option value="none">Not in a class yet<\/option>/);
});

test("what a search shows is escaped", () => {
  const html = rollList({ children: [{ ...children(1)[0], student: '<img src=x onerror=1>' }, ...children(11)], view: { query: "img" } });
  assert.doesNotMatch(html, /<img src=x/);
  assert.match(html, /&lt;img src=x/);
});
