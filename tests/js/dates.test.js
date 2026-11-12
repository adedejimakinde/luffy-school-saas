/**
 * `web/dates.js`'s pure parts: what a date field says and what its calendar
 * draws. The sheet in a browser (opening, picking, closing, disabled days) is
 * `tests/ui/dates.test.js`.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { cells, iso, parse, say, shift, todayIn, within } from "../../static/web/dates.js";
import { choose } from "../../static/register/states.js";

test("a stored day is read whole, and a day not on the calendar is not read", () => {
  assert.deepEqual(parse("2026-11-12"), { y: 2026, m: 11, d: 12 });
  assert.deepEqual(parse("2026-11-12T09:00"), { y: 2026, m: 11, d: 12 });
  assert.equal(parse("2026-02-30"), null);
  assert.equal(parse(""), null);
  assert.equal(iso({ y: 2026, m: 3, d: 4 }), "2026-03-04");
  assert.deepEqual(shift({ y: 2026, m: 12, d: 31 }, 1), { y: 2027, m: 1, d: 1 });
});

test("the field says Today, Yesterday and Tomorrow near today, and a day-first date otherwise", () => {
  assert.equal(say("2026-11-12", "2026-11-12"), "Today, Thu 12 Nov");
  assert.equal(say("2026-11-11", "2026-11-12"), "Yesterday, Wed 11 Nov");
  assert.equal(say("2026-11-13", "2026-11-12"), "Tomorrow, Fri 13 Nov");
  assert.equal(say("2026-11-04", "2026-11-12"), "Wed 4 Nov 2026");
  assert.equal(say("2027-01-02", "2026-11-12"), "Sat 2 Jan 2027");
  assert.equal(say("2012-11-12", "2026-11-12", { weekdays: false }), "12 Nov 2012");
  assert.equal(say("", "2026-11-12"), "");
  assert.doesNotMatch(say("2026-11-04", "2026-11-12"), /\d\/\d/);
});

test("today is the school's day, not Greenwich's", () => {
  assert.equal(todayIn("Africa/Lagos", new Date("2026-11-11T23:30:00Z")), "2026-11-12");
  assert.equal(todayIn("UTC", new Date("2026-11-11T23:30:00Z")), "2026-11-11");
});

test("a month is Monday-first weeks, blank where the week spills over", () => {
  const nov = cells(2026, 11);
  assert.equal(nov.length % 7, 0);
  // 1 Nov 2026 is a Sunday: six blanks, then the 1st.
  assert.deepEqual(nov.slice(0, 7).map((c) => c && c.d), [null, null, null, null, null, null, 1]);
  assert.equal(nov.filter(Boolean).length, 30);
  assert.equal(cells(2028, 2).filter(Boolean).length, 29);
});

test("a day outside the range is not within it", () => {
  const [min, max] = ["2026-09-07", "2026-12-18"];
  assert.ok(within({ y: 2026, m: 9, d: 7 }, min, max));
  assert.ok(within({ y: 2026, m: 12, d: 18 }, min, max));
  assert.ok(!within({ y: 2026, m: 9, d: 6 }, min, max));
  assert.ok(!within({ y: 2026, m: 12, d: 19 }, min, max));
  assert.ok(within({ y: 1999, m: 1, d: 1 }, "", ""));
});

test("the register's day is bound to its term, and its classes are list rows in one card", () => {
  const html = choose({ term: "T", starts_on: "2026-09-07", ends_on: "2026-12-18", classes: [{ id: 1, name: "JSS 1A" }, { id: 2, name: "JSS 1B" }], on: "2026-11-12" });
  assert.match(html, /data-dates="recent" value="2026-11-12" min="2026-09-07" max="2026-12-18"/);
  assert.equal((html.match(/class="card class-card"/g) || []).length, 1);
  assert.equal((html.match(/<li><button type="button" class="list-row class-row" data-action="open"/g) || []).length, 2);
  assert.doesNotMatch(html, /<select/);
});
