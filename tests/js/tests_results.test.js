/**
 * A test's results page (screen 7), item analysis, release and Send to CA (screens 8a,
 * 8b): `cbt/results_api.py`, CBT step 5.
 *
 * A question and a name are a teacher's or the school's plain text, escaped wherever they
 * are drawn; a button is drawn only where the school's answer says this login may press
 * it; the office's view has no question, option or key in it; and the send carries back
 * exactly what the preview showed.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { htmlFor, mount, routeOf } from "../../static/test-results/app.js";
import { shownOf } from "../../static/test-results/api.js";
import * as states from "../../static/test-results/states.js";
import * as testsPage from "../../static/tests/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const ITEM = {
  item_id: 51, number: 2, stem: "Evaluate <b>log</b> 0.001.", options: ["-1", "-2", "-3", "3"], key: 2,
  key_corrected: false, original_key: 2, marks: 1, chose: [6, 1, 2, 0], percent: [67, 11, 22, 0], blank: 1,
  right: 2, facility: 22, most_wrong: 0, check_key: true, topic: "",
};
const EASY = { ...ITEM, item_id: 52, number: 1, stem: "1 + 1?", key: 0, chose: [9, 0, 0, 0], percent: [100, 0, 0, 0], blank: 0, right: 9, facility: 100, most_wrong: null, check_key: false };

const RESULTS = {
  test_id: 9, title: "Second CA <i>test</i>", subject: "Mathematics", state: "published", state_label: "Approved",
  closes_at: "2026-11-10T11:00:00+00:00", released_only: false, out_of: 20,
  classes: [
    { id: 3, name: "JSS 1A", released: false, release_id: null, released_at: null, released_by: "", may_release: true, why_not: "", history: [] },
    { id: 4, name: "JSS 1B", released: true, release_id: 70, released_at: "2026-11-10T12:00:00+00:00", released_by: "Kemi Bello", may_release: false, why_not: "", history: [] },
  ],
  rows: [
    { student_id: 41, name: "Ada <Obi>", admission_number: "SM/001", class_name: "JSS 1A", state: "The student submitted", number: 1, score: 18, out_of: 20, right: 18, answered: 20, started_at: "2026-11-10T08:02:00+00:00", submitted_at: "2026-11-10T08:29:00+00:00", disconnects: 0, late_refused: 0, released: false },
    { student_id: 42, name: "Tunde Cole", admission_number: "SM/004", class_name: "JSS 1A", state: "Did not sit", number: 0, score: null, out_of: null, right: null, answered: null, started_at: null, submitted_at: null, disconnects: 0, late_refused: 0, released: false },
  ],
  stats: { sat: 1, placed: 2, average: 18, percent: 90, highest: 18, highest_count: 1, lowest: 18, lowest_count: 1 },
  distribution: [{ score: 17, count: 0 }, { score: 18, count: 1 }],
  items: [EASY, ITEM],
  corrections: [],
  transfers: [],
  may_correct: true, may_send: true, may_close: true, may_restore: true, sends_to_ca: true, open_attempts: 0,
};

test("screen 7: the numbers, the hardest question first, its key shown and flagged", () => {
  const html = states.resultsView(RESULTS);
  assert.match(html, /Second CA &lt;i&gt;test&lt;\/i&gt;/);
  assert.match(html, /Ada &lt;Obi&gt;/);
  assert.match(html, /Evaluate &lt;b&gt;log&lt;\/b&gt; 0.001\./);
  assert.ok(html.indexOf("Question 2") < html.indexOf("Question 1"), "hardest first");
  assert.match(html, /22% right/);
  assert.match(html, /Check the key/);
  assert.match(html, /<li class="opt is-key"><span class="letter">C<\/span>/);
  assert.match(html, /<li class="opt is-wrong"><span class="letter">A<\/span>/);
  assert.match(html, /1 student left it blank/);
  assert.match(html, /18 out of 20/);
  assert.match(html, /href="#ca\/9"/);
  assert.match(html, /data-action="ask-release-3"/);
  assert.doesNotMatch(html, /ask-release-4/, "a released class is not released again");
  assert.match(html, /data-action="ask-restore-4"/);
  assert.match(html, /Did not sit/);
});

test("nothing is offered that the school says this login may not do", () => {
  const html = states.resultsView({
    ...RESULTS, may_correct: false, may_send: false, may_close: false, may_restore: false,
    classes: RESULTS.classes.map((c) => ({ ...c, may_release: false })),
  });
  for (const word of ["ask-key-", "ask-release-", "ask-restore-", "ask-close", "#ca/"]) assert.doesNotMatch(html, new RegExp(word));
});

test("the office's view: released scores, no question and no answer", () => {
  const html = states.resultsView({ ...RESULTS, released_only: true, items: [], may_correct: false, may_send: false, may_close: false, may_restore: false });
  assert.match(html, /once its class is released/);
  assert.doesNotMatch(html, /Question \d/);
  assert.doesNotMatch(html, /is-key/);
});

test("a key correction is a form with the options and a reason", () => {
  const html = states.resultsView(RESULTS, { confirming: "key-51" });
  assert.match(html, /<form data-form="key" data-item="51"/);
  assert.match(html, /value="2" checked/);
  assert.match(html, /Every attempt is marked again/);
});

test("half the students' scores, in words", () => {
  assert.equal(states.mostScored([{ score: 0, count: 0 }, { score: 1, count: 3 }, { score: 2, count: 3 }, { score: 3, count: 1 }]), "Half of them scored 1 to 2.");
  assert.equal(states.mostScored([{ score: 4, count: 5 }, { score: 5, count: 1 }]), "Half of them scored 4.");
  assert.equal(states.mostScored([{ score: 4, count: 1 }]), "");
});

test("correcting a key sends the option and the reason, and says how many scores moved", async () => {
  const calls = [];
  const corrected = { item_id: 51, number: 2, old: "C", new: "A", reason: "A is right", by: "Kemi", at: "x", changes: [{ name: "Ada", before: 17, after: 18 }], out_of: 20 };
  const fetchImpl = async (url, init = {}) => {
    calls.push([url, init.body ? JSON.parse(init.body) : null]);
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    if (url.endsWith("/key/")) return { status: 200, json: async () => ({ ...RESULTS, corrections: [corrected], corrected }) };
    return { status: 200, json: async () => RESULTS };
  };
  forgetToken();
  const root = fakeRoot();
  const page = await mount(root, { fetchImpl, location: { hash: "#9" } });
  assert.equal(page.state().step, "results");
  await root.submit({ new_index: "0", reason: "A is right" }, { form: "key", item: "51" });
  const sent = calls.find(([url]) => url.endsWith("/tests/9/items/51/key/"));
  assert.deepEqual(sent[1], { new_index: 0, reason: "A is right" });
  assert.match(root.innerHTML, /1 score changed/);
  assert.match(root.innerHTML, /Ada 17 to 18/);
});

test("release and restore go to their routes and redraw from the answer", async () => {
  const calls = [];
  const fetchImpl = async (url, init = {}) => {
    calls.push([url, init.body ? JSON.parse(init.body) : null]);
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    return { status: 200, json: async () => RESULTS };
  };
  forgetToken();
  const root = fakeRoot();
  await mount(root, { fetchImpl, location: { hash: "#9" } });
  await root.click({ "data-action": "release", "data-class": "3" });
  assert.ok(calls.some(([url]) => url.endsWith("/tests/9/classes/3/release/")));
  assert.match(root.innerHTML, /Released\. Each student sees their own score/);
  await root.submit({ reason: "Wrong key" }, { form: "restore", release: "70" });
  const restore = calls.find(([url]) => url.endsWith("/releases/70/restore/"));
  assert.deepEqual(restore[1], { reason: "Wrong key" });
});

const PREVIEW = {
  test_id: 9, title: "Second CA test", assessment: { id: 5, name: "Second CA", max_score: 10 },
  columns: [{ id: 4, name: "First CA", max_score: 10 }, { id: 5, name: "Second CA", max_score: 10 }],
  existing: "replace", out_of: 20,
  lines: [
    { student_id: 41, name: "Ada <Obi>", class_name: "JSS 1A", class_id: 3, test_score: 18, mark: 9, current: null, version: null, by_hand: false, will: "new", locked_state: "", sitting_now: false },
    { student_id: 43, name: "Bola Ahmed", class_name: "JSS 1A", class_id: 3, test_score: 11, mark: 6, current: 5, version: 2, by_hand: true, will: "replace", locked_state: "", sitting_now: false },
    { student_id: 42, name: "Tunde Cole", class_name: "JSS 1A", class_id: 3, test_score: null, mark: null, current: null, version: null, by_hand: false, will: "not_sat", locked_state: "", sitting_now: false },
    { student_id: 44, name: "Kunle Adeyemi", class_name: "JSS 1B", class_id: 4, test_score: 13, mark: 7, current: null, version: null, by_hand: false, will: "locked", locked_state: "submitted", sitting_now: false },
  ],
  counts: { new: 1, replace: 1, not_sat: 1, locked: 1 },
  locked_classes: [{ class_name: "JSS 1B", state: "submitted", count: 1 }],
  replaces_by_hand: 1,
};

test("screen 8a: every student, what happens to each, the locked class named", () => {
  const html = states.caView(PREVIEW);
  assert.match(html, /Ada &lt;Obi&gt;/);
  assert.match(html, /Replaces 5/);
  assert.match(html, /Typed by hand/);
  assert.match(html, /Did not sit/);
  assert.match(html, /JSS 1B cannot take marks now/);
  assert.match(html, /<option value="5" selected>Second CA, out of 10<\/option>/);
  assert.match(html, /Send 2 marks/);
  assert.match(html, /a student who did not sit gets no mark, not a zero/i);
});

test("screen 8b: the confirm asks again for a mark typed by hand", () => {
  const html = states.caView(PREVIEW, { confirming: "send" });
  assert.match(html, /<form data-form="ca-send"/);
  assert.match(html, /name="confirm_replace" required/);
  assert.doesNotMatch(states.caView({ ...PREVIEW, existing: "keep", replaces_by_hand: 0 }, { confirming: "send" }), /confirm_replace/);
});

test("no column, no form", () => {
  assert.match(states.caView({ test_id: 9, columns: [], lines: [], assessment: null }), /no CA column this term/);
});

test("the send carries back exactly what the preview showed", async () => {
  assert.deepEqual(shownOf(PREVIEW)["43"], { score: 11, mark: 6, current: 5, version: 2 });
  assert.deepEqual(shownOf(PREVIEW)["42"], { score: null, mark: null, current: null, version: null });
  const calls = [];
  const sent = { number: 1, assessment: "Second CA", max_score: 10, existing: "replace", lines: [{ name: "Bola Ahmed", outcome: "changed_meanwhile", outcome_label: "Changed since the preview, not sent", detail: "Reload" }], counts: { written: 1, kept: 0, not_sat: 1, locked: 1, changed_meanwhile: 1 } };
  const fetchImpl = async (url, init = {}) => {
    calls.push([url, init.body ? JSON.parse(init.body) : null]);
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    if (url.includes("/ca/?")) return { status: 200, json: async () => (url.includes("assessment=0") ? { test_id: 9, columns: PREVIEW.columns, assessment: null, lines: [] } : PREVIEW) };
    if (url.endsWith("/ca/")) return { status: 200, json: async () => sent };
    return { status: 200, json: async () => RESULTS };
  };
  forgetToken();
  const root = fakeRoot();
  const page = await mount(root, { fetchImpl, location: { hash: "#ca/9" } });
  assert.equal(page.state().step, "ca");
  await root.submit({ assessment: "5", existing: "replace" }, { form: "ca-preview" });
  assert.ok(calls.some(([url]) => url.endsWith("/tests/9/ca/?assessment=5&existing=replace")));
  await root.submit({ confirm_replace: { checked: true } }, { form: "ca-send" });
  const posted = calls.find(([url, body]) => url.endsWith("/tests/9/ca/") && body);
  assert.deepEqual(posted[1], { assessment_id: 5, existing: "replace", shown: shownOf(PREVIEW), confirm_replace: true });
  assert.match(root.innerHTML, /1 changed meanwhile and not sent/);
  assert.match(root.innerHTML, /Bola Ahmed: Changed since the preview, not sent/);
});

test("the Tests list links an approved test to its results page", () => {
  const row = { id: 9, title: "T", subject: "M", level_name: "", classes: [], state: "closed", state_label: "Closed", opens: "", closes: "", duration: 1, size: 1, code_set: true, set_by: "K" };
  assert.match(testsPage.testsView({ tests: [row] }), /href="results\/#9"/);
  assert.doesNotMatch(testsPage.testsView({ tests: [{ ...row, state: "draft" }] }), /results\/#/);
});

test("the routes read the hash, and a test id is a number", async () => {
  assert.deepEqual(routeOf("#9"), ["results", "9"]);
  assert.deepEqual(routeOf("#ca/9"), ["ca", "9"]);
  assert.deepEqual(routeOf(""), ["results", ""]);
  assert.match(htmlFor({ step: "not-yours", detail: "Not <yours>" }), /Not &lt;yours&gt;/);
  assert.match(htmlFor({ step: "results", results: RESULTS }), /data-state="results"/);
});

test("screen 7: while another class has still to sit, a release is said to show scores and no answers (audit G-03)", () => {
  const held = { ...RESULTS, answers_held_for: ["JSS 1C", "JSS <1D>"] };
  const asking = states.resultsView(held, { confirming: "release-3" });
  assert.match(asking, /Release JSS 1A&#39;s scores\? Each student then sees their own score, and each parent their own child&#39;s\. The answers stay hidden from every student until JSS 1C and JSS &lt;1D&gt; have finished this test\./);
  assert.doesNotMatch(asking, /own score and corrections/);
  const released = states.resultsView(held);
  assert.match(released, /Released by Kemi Bello[^<]*The answers stay hidden until JSS 1C and JSS &lt;1D&gt; have finished this test\./);
  // And once every class has finished, or for a paper one class sits, it is as before.
  assert.match(states.resultsView({ ...RESULTS, answers_held_for: [] }, { confirming: "release-3" }), /own score and corrections/);
  assert.match(states.resultsView(RESULTS), /Each student sees their own score and corrections/);
});
