/**
 * Tests: question banks, setting a test, and the principal's approval (`cbt/bank_api.py`).
 *
 * What it walks is the API's answer set: the list (with its administrator's form, no
 * question in it), a bank, a test and its chain, a 422 sentence the form says beside
 * itself, a 403 for a login the page is not for, a 404 off a school's host, and a 401.
 *
 * Every question is a teacher's plain text, so it is escaped wherever it is drawn; and
 * a button is drawn only where the school's answer says this login may press it.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { htmlFor, load, mount, routeOf, testFrom, questionFrom } from "../../static/tests/app.js";
import { REFUSAL, classify, refusalFor } from "../../static/tests/api.js";
import * as states from "../../static/tests/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const ROW = {
  id: 9,
  title: "First CA <i>test</i>",
  subject: "Mathematics",
  level_name: "JSS 1",
  classes: [{ id: 3, name: "JSS 1A" }],
  state: "submitted",
  state_label: "Waiting for approval",
  opens_at: "2026-11-10T08:00:00+00:00",
  closes_at: "2026-11-10T11:00:00+00:00",
  opens: "10 Nov 2026, 09:00",
  closes: "10 Nov 2026, 12:00",
  duration: 30,
  size: 4,
  code_set: false,
  set_by: "Kemi Bello",
};

const LIST = {
  term: "First term, 2026/2027",
  summaries_only: false,
  may_set: true,
  approves: true,
  tests: [ROW],
  choices: [{ subject_id: 1, subject: "Mathematics", level: 1, level_name: "JSS 1", in_use: 6, classes: [{ id: 3, name: "JSS 1A" }] }],
};

const ITEM = {
  number: 1,
  stem: "What is <b>2</b> + 2?",
  options: ["4", "5", "6", "7"],
  correct_index: 0,
  marks: 1,
  explanation: "Two and two make four.",
  topic: "Number",
  picture_url: null,
  image_alt: "",
  origin_question_id: 11,
  origin_version: 1,
};

const TEST = {
  ...ROW,
  subject_id: 1,
  level: 1,
  class_group_ids: [3],
  question_count: 4,
  late_window: 2,
  shuffle_questions: true,
  shuffle_options: true,
  can_go_back: true,
  grid: true,
  calculator: false,
  require_pin: true,
  may_send_to_ca: true,
  total_marks: 4,
  items: [ITEM],
  history: [{ what: "Draft to Waiting for approval", by: "Kemi Bello", note: "", at: "7 Nov 2026, 10:00" }],
  may_edit: false,
  may_submit: false,
  may_withdraw: false,
  may_approve: true,
  may_change_classes: false,
  may_delete: false,
  class_choices: [],
};

const BANK = {
  subject_id: 1,
  subject: "Mathematics",
  level: 1,
  level_name: "JSS 1",
  may_write: true,
  readers: "Only teachers of Mathematics in JSS 1, the vice principal and the principal see this bank.",
  questions: [
    { id: 11, stem: "What is <b>2</b> + 2?", options: ["4", "5", "6", "7"], correct_index: 0, marks: 1, topic: "Number", explanation: "", picture: null, image_alt: "", version: 1, retired: false, used_in: 1, updated_by: "Kemi Bello", updated_at: "7 Nov 2026, 10:00" },
  ],
};

function serve(routes, sent = []) {
  return async (url, options = {}) => {
    const method = options.method || "GET";
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    for (const [match, answer] of routes) {
      if (url.endsWith(match) && (answer.method || "GET") === method) {
        sent.push(`${method} ${url}${options.body ? ` ${options.body}` : ""}`);
        const value = typeof answer.reply === "function" ? answer.reply(options, url) : answer.reply;
        return { status: value.status, json: async () => value.body };
      }
    }
    throw new Error(`no stub for ${method} ${url}`);
  };
}

const at = (hash) => ({ hash });

test("the routes read the hash", () => {
  assert.deepEqual(routeOf(""), ["tests"]);
  assert.deepEqual(routeOf("#bank/3/2"), ["bank", "3", "2"]);
  assert.deepEqual(routeOf("#/test/9"), ["test", "9"]);
});

test("the refusals are the page's, and a write's 403 is a sentence", () => {
  assert.equal(refusalFor(403, {}), REFUSAL.NOT_YOURS);
  assert.equal(refusalFor(404, {}), REFUSAL.WRONG_HOST);
  assert.equal(refusalFor(401, { code: "session_expired" }), REFUSAL.EXPIRED);
  assert.equal(refusalFor(401, {}), REFUSAL.SIGNED_OUT);
  assert.deepEqual(classify({ status: 403, body: { detail: "No" } }, { write: true }), { ok: false, rejected: true, detail: "No" });
  assert.equal(classify({ status: 403, body: {} }).refusal, REFUSAL.NOT_YOURS);
});

test("the list escapes what a teacher typed and offers what the school says", () => {
  const html = states.testsView(LIST);

  assert.match(html, /First CA &lt;i&gt;test&lt;\/i&gt;/);
  assert.doesNotMatch(html, /<i>test/);
  assert.match(html, /href="#new-test"/);
  assert.match(html, /1 test is waiting for your approval/);
  assert.match(html, /href="#banks"/);
  assert.match(html, /4 questions\. No test code yet\./);
});

test("the administrator's list has no Open, no bank tab and no Set a test", () => {
  const html = states.testsView({ ...LIST, summaries_only: true, may_set: false, approves: false, choices: [] });

  assert.doesNotMatch(html, /href="#test\//);
  assert.doesNotMatch(html, /href="#banks"/);
  assert.doesNotMatch(html, /#new-test/);
  assert.match(html, /Its questions are its teachers&#39; and the principal&#39;s/);
  assert.match(html, /JSS 1A/);
});

test("a bank shows each answer to its readers, escaped, with Edit only for a writer", () => {
  const html = states.bankView(BANK);
  assert.match(html, /What is &lt;b&gt;2&lt;\/b&gt; \+ 2\?/);
  assert.match(html, /Answer A\./);
  assert.match(html, /href="#question\/1\/1\/11"/);
  assert.match(html, /href="#question\/1\/1\/new"/);
  const read = states.bankView({ ...BANK, may_write: false });
  assert.doesNotMatch(read, /#question\//);
});

test("a test waiting for the principal shows the paper with its answers, and Approve asks first", () => {
  const html = states.testView(TEST);
  assert.match(html, /<li class="correct">4 <span class="badge">Correct<\/span>/);
  assert.match(html, /data-action="ask-approve"/);
  assert.match(html, /data-action="ask-send-back"/);
  assert.doesNotMatch(html, /data-action="submit"/);
  const asking = states.testView(TEST, { confirming: "approve" });
  assert.match(asking, /Approve First CA &lt;i&gt;test&lt;\/i&gt;\? It opens to JSS 1A at 10 Nov 2026, 09:00/);
  assert.match(asking, /data-action="approve"/);
});

test("nothing to press for a reader who may press nothing", () => {
  const html = states.testView({ ...TEST, may_approve: false });
  assert.doesNotMatch(html, /data-action="(ask-approve|ask-send-back|submit|withdraw)"/);
  assert.match(html, /Try it as a student/);
});

test("the preview has no answer in it", () => {
  const html = states.previewView(9, {
    title: "First CA",
    duration: 30,
    items: [{ id: 1, number: 1, stem: "Q", image: null, image_alt: "", marks: 1, options: [{ index: 2, text: "six" }, { index: 0, text: "four" }] }],
  });
  assert.doesNotMatch(html, /Correct|correct/);
  assert.match(html, /<li>six<\/li><li>four<\/li>/);
});

test("the question form keeps what was typed when it is drawn again", () => {
  const html = states.questionForm(BANK, null, {
    values: { stem: "Typed <x>", options: ["a", "b", "c", "d", "e"], correct_index: 4, marks: 2, topic: "", explanation: "", image_alt: "" },
  });
  assert.match(html, /Typed &lt;x&gt;<\/textarea>/);
  assert.match(html, /id="option-4"[^>]*value="e"/);
  assert.match(html, /name="correct" value="4" checked/);
  assert.match(html, /value="5" data-action="count" checked/);
});

test("what the forms send", () => {
  const q = questionFrom({
    stem: { value: "S" }, option0: { value: "a" }, option1: { value: "b" }, option2: { value: "c" }, option3: { value: "d" },
    correct: { value: "2" }, marks: { value: "3" }, topic: { value: "T" }, explanation: { value: "" },
    image_key: { value: "" }, image_alt: { value: "" }, version: { value: "4" },
  });
  assert.deepEqual(q, { stem: "S", options: ["a", "b", "c", "d"], correct_index: 2, marks: 3, topic: "T", explanation: "", image_key: "", image_alt: "", version: 4 });
  const t = testFrom({
    title: { value: "T" }, bank: { value: "1-2" }, class: { value: "3,4" }, question_count: { value: "10" },
    opens_at: { value: "2026-11-10T09:00" }, closes_at: { value: "2026-11-10T12:00" }, duration: { value: "30" },
    late_window: { value: "2" }, shuffle_questions: { checked: true }, shuffle_options: { checked: false },
    can_go_back: { checked: true }, grid: { checked: true }, calculator: { checked: false }, require_pin: { checked: true },
  });
  assert.equal(t.subject_id, 1);
  assert.equal(t.level, 2);
  assert.deepEqual(t.class_group_ids, [3, 4]);
  assert.equal(t.shuffle_options, false);
  assert.equal(new Date(t.opens_at).getTime(), new Date("2026-11-10T09:00").getTime());
});

test("load: a refusal is the page's, and a missing test is not here", async () => {
  const refused = await load(["tests"], { fetchImpl: serve([["/api/cbt/tests/", { reply: { status: 403, body: { detail: "Not yours" } } }]]) });
  assert.equal(refused.step, REFUSAL.NOT_YOURS);
  assert.match(htmlFor(refused), /Not yours/);
  const missing = await load(["test", "9"], { fetchImpl: serve([["/api/cbt/tests/9/", { reply: { status: 404, body: { detail: "No" } } }]]) });
  assert.equal(missing.step, REFUSAL.WRONG_HOST);
  const out = await load(["tests"], { fetchImpl: serve([["/api/cbt/tests/", { reply: { status: 401, body: { code: "session_expired" } } }]]) });
  assert.match(htmlFor(out, { portal: "app.example" }), /Your session has ended/);
});

test("approving asks first, sends one POST on the second tap, and redraws from the answer", async () => {
  forgetToken();
  const sent = [];
  const approved = { ...TEST, state: "published", state_label: "Approved", may_approve: false };
  const fetchImpl = serve(
    [
      ["/api/cbt/tests/9/approve/", { method: "POST", reply: { status: 200, body: approved } }],
      ["/api/cbt/tests/9/", { reply: { status: 200, body: TEST } }],
    ],
    sent,
  );
  const root = fakeRoot();
  await mount(root, { fetchImpl, location: at("#test/9") });
  await root.click({ "data-action": "ask-approve" });
  assert.deepEqual(sent.filter((s) => s.startsWith("POST")), []);
  await root.click({ "data-action": "approve" });
  assert.equal(sent.filter((s) => s.startsWith("POST")).length, 1);
  assert.match(root.innerHTML, /Approved\. It opens as set\./);
  assert.doesNotMatch(root.innerHTML, /data-action="ask-approve"/);
});

test("a refused send-back says why beside the form", async () => {
  forgetToken();
  const fetchImpl = serve([
    ["/api/cbt/tests/9/send-back/", { method: "POST", reply: { status: 422, body: { detail: "The reason cannot be empty." } } }],
    ["/api/cbt/tests/9/", { reply: { status: 200, body: TEST } }],
  ]);
  const root = fakeRoot();
  await mount(root, { fetchImpl, location: at("#test/9") });
  await root.click({ "data-action": "ask-send-back" });
  await root.submit({ note: "" }, { form: "send-back" });
  assert.match(root.innerHTML, /The reason cannot be empty\./);
});

// -- the sitting (CBT step 4) ----------------------------------------------------------------

const LOG = {
  test_id: 9,
  title: "First CA <i>test</i>",
  state: "published",
  opens_at: "2026-11-09T08:00:00Z",
  closes_at: "2026-11-09T11:00:00Z",
  duration: 30,
  late_window: 2,
  code_set: true,
  code: null,
  may_run: true,
  may_extend: true,
  may_retake: true,
  classes: [{ id: 3, name: "JSS 1A", open: true, by_hand: false, said: "As planned" }],
  rows: [
    {
      student_id: 41, name: "Ada <b>Obi</b>", admission_number: "SM/001", class_name: "JSS 1A", state: "Sitting", number: 1,
      started_at: "2026-11-09T08:05:00Z", deadline: "2026-11-09T08:45:00Z", submitted_at: null, ended_by: "",
      extra_minutes: 10, computers: 2, replaced: 1, disconnects: 1, left_page: 3, late_refused: 0, answers_received: 7,
      may_retake: false,
      events: [{ kind: "left_page", what: "Left the test's tab or window", said_by: "device", at: "2026-11-09T08:10:00Z", seat: "Seat 4", detail: { seconds: 14 } }],
    },
    {
      student_id: 42, name: "Emeka Nwosu", admission_number: "SM/002", class_name: "JSS 1A", state: "The student submitted", number: 1,
      started_at: "2026-11-09T08:05:00Z", deadline: "2026-11-09T08:35:00Z", submitted_at: "2026-11-09T08:30:00Z", ended_by: "student",
      extra_minutes: 0, computers: 1, replaced: 0, disconnects: 0, left_page: 0, late_refused: 0, answers_received: 20,
      may_retake: true, events: [],
    },
  ],
  code_changes: [],
  controls: [],
};

test("the sitting: classes, the log's counts, and no answer in it", () => {
  const html = states.sittingView(LOG);
  assert.match(html, /First CA &lt;i&gt;test&lt;\/i&gt;: the sitting/);
  assert.match(html, /Ada &lt;b&gt;Obi&lt;\/b&gt;/, "a name is text");
  assert.match(html, /data-count="Left the page"><dt>Left the page<\/dt><dd>3</);
  assert.match(html, /data-count="Computers"><dt>Computers<\/dt><dd>2</);
  assert.match(html, /10 extra minutes/);
  assert.match(html, /Close it now/);
  assert.match(html, /Change the code/);
  assert.match(html, /data-action="ask-extra-41"/);
  assert.doesNotMatch(html, /data-action="ask-extra-42"/, "no extra time once an attempt is closed");
  assert.match(html, /data-action="ask-retake-42"/);
  assert.match(html, /No answer or score is shown here/);
  assert.doesNotMatch(html, /correct|chosen|score:/i);
});

test("the code is shown once, in the answer that set it", () => {
  assert.match(states.sittingView({ ...LOG, code_set: true }, { code: "KMTRWX" }), /<strong class="code">KMTRWX<\/strong>/);
  assert.doesNotMatch(states.sittingView(LOG), /KMTRWX/);
  assert.match(states.sittingView({ ...LOG, code_set: false }), /Set the test code/);
});

test("a login that may not run the sitting sees it and no button", () => {
  const html = states.sittingView({ ...LOG, may_run: false, may_extend: false, rows: LOG.rows.map((r) => ({ ...r, may_retake: false })) });
  assert.doesNotMatch(html, /Close it now|Change the code|Extra time|Allow a retake/);
});

test("closing by hand asks why, and offers to end the attempts in progress", () => {
  const html = states.sittingView(LOG, { confirming: "close-3" });
  assert.match(html, /data-form="control" data-kind="close" data-class="3"/);
  assert.match(html, /name="end_attempts"/);
  assert.match(html, /students already sitting carry on to their own time/);
});

test("the published test's row and page link to its sitting", () => {
  assert.match(states.testsView({ tests: [{ ...ROW, state: "published" }], summaries_only: true }), /href="#sitting\/9"/);
  assert.doesNotMatch(states.testsView({ tests: [{ ...ROW, state: "draft" }] }), /#sitting\//);
});

test("extra time is sent with its minutes and its reason, and the log is drawn again", async () => {
  const calls = [];
  const fetchImpl = async (url, init = {}) => {
    calls.push([url, init.body ? JSON.parse(init.body) : null]);
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    return { status: 200, json: async () => ({ ...LOG, rows: [{ ...LOG.rows[0], extra_minutes: 25 }] }) };
  };
  forgetToken();
  const root = fakeRoot();
  const page = await mount(root, { fetchImpl, location: { hash: "#sitting/9" } });
  assert.equal(page.state().step, "sitting");
  await root.submit({ minutes: "15", reason: "Power cut" }, { form: "extra", student: "41" });
  const sent = calls.find(([url]) => url.endsWith("/students/41/extra-time/"));
  assert.deepEqual(sent[1], { minutes: 15, reason: "Power cut" });
  assert.match(root.innerHTML, /25 extra minutes/);
  assert.match(root.innerHTML, /Extra time given/);
});
