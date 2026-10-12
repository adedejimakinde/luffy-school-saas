/**
 * The list pages' empty states: drawn from a successful answer with no rows,
 * and never from a fetch that failed, was refused, or came back from the
 * phone's own copy.
 *
 * Each page decides in its own `from…()` and `states.…()`; this file holds the
 * rule across all six at once, so a seventh that forgot it reads as one more
 * row here rather than a new test somebody has to think of.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { emptyState } from "../../static/web/html.js";
import { fromRoll, htmlFor as rollHtml } from "../../static/roll/app.js";
import { REFUSAL as ROLL } from "../../static/roll/api.js";
import { fromList, htmlFor as staffHtml } from "../../static/staff/app.js";
import { fromSetup, htmlFor as setupHtml } from "../../static/setup/app.js";
import { htmlFor as feesHtml } from "../../static/fees/app.js";
import { fromWhere as registerWhere, htmlFor as registerHtml } from "../../static/register/app.js";
import { REFUSAL as REGISTER } from "../../static/register/api.js";
import { fromWhere as markingWhere, htmlFor as markingHtml } from "../../static/marking/app.js";
import { REFUSAL as MARKING } from "../../static/marking/api.js";

const EMPTY = /data-empty="/;
const CLOCK = { timeZone: "Africa/Lagos", now: new Date("2026-10-12T09:00:00Z") };

/** What every page's fetch hands back when the network is gone. */
const offline = (refusal) => ({ ok: false, refusal, offline: true, body: { detail: "TypeError: Failed to fetch" } });

test("the empty state escapes what it is handed and draws one button", () => {
  const html = emptyState({
    key: "x",
    title: "<b>No</b>",
    text: "a & b",
    action: { href: "/start/classes/", label: "Go" },
  });

  assert.match(html, /&lt;b&gt;No&lt;\/b&gt;/);
  assert.match(html, /a &amp; b/);
  assert.equal(html.match(/class="btn/g).length, 1);
});

test("without a way to act, it says who does this and offers no button", () => {
  const html = emptyState({ key: "x", title: "No fees yet", who: "The bursar sets up fees." });

  assert.doesNotMatch(html, /<a |<button/);
  assert.match(html, /The bursar sets up fees\./);
});

// -- the roll ------------------------------------------------------------------

test("roll: no classes yet sends an administrator to the classes step", () => {
  const html = rollHtml(fromRoll({ ok: true, body: { children: [], classes: [], may_admit: true, may_place: true } }));

  assert.match(html, /data-empty="students-need-classes"/);
  assert.match(html, /Add your classes first/);
  assert.match(html, /href="\/start\/classes\/"/);
});

test("roll: a principal is sent to the setup page, not to a step page she cannot open", () => {
  const html = rollHtml(fromRoll({ ok: true, body: { children: [], classes: [], may_admit: false, may_place: true } }));

  assert.match(html, /href="\/setup\/#classes"/);
  assert.doesNotMatch(html, /\/start\//);
});

test("roll: classes and no students is the import button", () => {
  const html = rollHtml(fromRoll({
    ok: true,
    body: { children: [], classes: [{ id: 1, name: "JSS 1A" }], may_admit: true, may_place: true },
  }));

  assert.match(html, /data-empty="students"/);
  assert.match(html, /href="\/roll\/import\/"/);
  // One clear button: the import link at the top is left off an empty roll.
  assert.equal(html.match(/href="\/roll\/import\/"/g).length, 1);
});

test("roll: a roll with a child in it has no empty state", () => {
  const html = rollHtml(fromRoll({
    ok: true,
    body: {
      children: [{ student_membership_id: 9, name: "Ada", class_group_id: 1 }],
      classes: [{ id: 1, name: "JSS 1A" }],
      may_admit: true,
    },
  }));

  assert.doesNotMatch(html, EMPTY);
});

test("roll: a failed or offline fetch is never an empty roll", () => {
  for (const refusal of [ROLL.BROKEN, ROLL.SIGNED_OUT, ROLL.EXPIRED, ROLL.NOT_THE_OFFICE]) {
    assert.doesNotMatch(rollHtml(fromRoll(offline(refusal))), EMPTY, refusal);
  }
});

// -- staff ---------------------------------------------------------------------

test("staff: no teacher and nobody invited is the empty state, pointing at the form", () => {
  const html = staffHtml(fromList({ ok: true, body: { invitations: [], roles: ["teacher"], has_teachers: false } }));

  assert.match(html, /data-empty="teachers"/);
  assert.match(html, /href="#address"/);
  assert.match(html, /id="address"/);
});

test("staff: teachers already in, or an invitation waiting, is not empty", () => {
  const teachers = staffHtml(fromList({ ok: true, body: { invitations: [], roles: [], has_teachers: true } }));
  const waiting = staffHtml(fromList({
    ok: true,
    body: { invitations: [{ id: 1, status: "pending", role_display: "Teacher" }], roles: [], has_teachers: false },
  }));

  assert.doesNotMatch(teachers, EMPTY);
  assert.doesNotMatch(waiting, EMPTY);
});

test("staff: a failed fetch is never an empty staff list", () => {
  assert.doesNotMatch(staffHtml(fromList(offline("broken"))), EMPTY);
});

// -- classes, on the setup page --------------------------------------------------

test("setup: no classes is the empty state, and its button goes to the class form", () => {
  const html = setupHtml(fromSetup({ ok: true, body: { terms: [], classes: [] } }));

  assert.match(html, /data-empty="classes"/);
  assert.match(html, /href="#class_name"/);
  assert.match(html, /id="class_name"/);
});

test("setup: a failed fetch is never an empty list of classes", () => {
  assert.doesNotMatch(setupHtml(fromSetup(offline("broken"))), EMPTY);
});

// -- fees ----------------------------------------------------------------------

const books = (extra) => ({
  step: "books",
  books: { terms: [{ term_id: 1, term: "First term", is_current: true }], term_id: 1, term: "First term", classes: [], ...extra },
  notSent: [],
});

test("fees: no fee items this term is the empty state, and a writer gets the button", () => {
  const html = feesHtml(books({ may_write: true, has_fee_items: false }));

  assert.match(html, /data-empty="fees"/);
  assert.match(html, /data-action="open-bills"/);
  assert.equal(html.match(/data-action="open-bills"/g).length, 1);
});

test("fees: a reader who may not write is told who sets fees up", () => {
  const html = feesHtml(books({ may_write: false, has_fee_items: false }));

  assert.match(html, /The bursar sets up fees/);
  assert.doesNotMatch(html, /data-action="open-bills"/);
});

test("fees: a term with fee items has no empty state", () => {
  assert.doesNotMatch(feesHtml(books({ may_write: true, has_fee_items: true })), EMPTY);
});

test("fees: a failed fetch is never an empty fee book", () => {
  assert.doesNotMatch(feesHtml({ step: "broken" }), EMPTY);
});

// -- the register and marks, the two pages kept offline ----------------------------

const where = (extra) => ({ ok: true, body: { term_id: 3, term: "First term", classes: [], user_id: 7, ...extra } });

test("register: a live answer with no classes is the empty state", () => {
  const html = registerHtml(registerWhere(where({ may_set_up: true })), CLOCK);

  assert.match(html, /data-empty="register"/);
  assert.match(html, /href="\/setup\/#classes"/);
});

test("register: a teacher is told who adds classes, with no button to a page she cannot open", () => {
  const html = registerHtml(registerWhere(where({ may_set_up: false })), CLOCK);

  assert.match(html, /The school office adds the classes/);
  assert.doesNotMatch(html, /\/setup\//);
});

test("register: offline, or from the phone's own copy, is never an empty register", () => {
  const failed = registerHtml(registerWhere(offline(REGISTER.BROKEN)), CLOCK);
  const copy = registerHtml(
    registerWhere({ ...where({ may_set_up: true }), asOf: "2026-10-11T08:00:00Z" }),
    CLOCK,
  );

  assert.doesNotMatch(failed, EMPTY);
  assert.doesNotMatch(copy, EMPTY);
});

test("marks: no papers this term is the empty state, and the office is sent to papers", () => {
  const html = markingHtml(
    markingWhere(where({ classes: [{ id: 1, name: "JSS 1A" }], assessments: [], may_set_up: true })),
    CLOCK,
  );

  assert.match(html, /data-empty="marks"/);
  assert.match(html, /No papers to mark yet/);
  assert.match(html, /href="\/teaching\/#papers"/);
});

test("marks: offline, or from the phone's own copy, is never an empty sheet list", () => {
  const failed = markingHtml(markingWhere(offline(MARKING.BROKEN)), CLOCK);
  const copy = markingHtml(
    markingWhere({ ...where({ assessments: [], may_set_up: true }), asOf: "2026-10-11T08:00:00Z" }),
    CLOCK,
  );

  assert.doesNotMatch(failed, EMPTY);
  assert.doesNotMatch(copy, EMPTY);
});

test("marks: papers and classes both there is no empty state", () => {
  const html = markingHtml(
    markingWhere(where({
      classes: [{ id: 1, name: "JSS 1A" }],
      assessments: [{ id: 2, subject: "Mathematics", name: "First CA", max_score: 20 }],
    })),
    CLOCK,
  );

  assert.doesNotMatch(html, EMPTY);
});
