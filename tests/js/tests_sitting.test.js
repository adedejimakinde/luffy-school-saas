/**
 * A test's sitting (`cbt/sitting_api.py`, `/tests/sitting/`): its code, its classes, the log,
 * extra time and retakes, and exam slips for the staff who may print them.
 *
 * A button is drawn only where the school's answer says this login may press it (`may_run`,
 * `may_extend`, `may_retake`, `may_print`), and the server asks again on every route.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { mount } from "../../static/test-sitting/app.js";
import * as states from "../../static/test-sitting/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

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

// -- the staff attempt log: a sign-in that did not get through, and why --

const REFUSALS = [
  ["wrong_code", "Wrong test code"],
  ["wrong_pin", "Wrong exam PIN"],
  ["other_term_slip", "PIN is from another term's slip"],
  ["not_in_class", "Not in a class sitting this test"],
  ["not_open", "Test not open to their class"],
  ["already_sat", "Has sat it already"],
  ["locked", "Locked out for too many wrong tries"],
];

function tried(reason, what, extra = {}) {
  return { at: "2026-11-09T07:58:00Z", reason, what, until: null, device: "a1b2c3", ...extra };
}

test("a student's failed sign-ins are listed with the real reason, each of the seven", () => {
  const row = { ...LOG.rows[1], sign_ins: REFUSALS.map(([reason, what]) => tried(reason, what, reason === "locked" ? { until: "2026-11-09T08:05:00Z" } : {})) };
  const html = states.sittingView({ ...LOG, rows: [row] });
  assert.match(html, /<summary>Failed sign-ins \(7\)<\/summary>/);
  assert.match(html, /data-failed-sign-ins>7 failed sign-ins</);
  for (const [reason, what] of REFUSALS) {
    assert.match(html, new RegExp(`<li data-reason="${reason}">[^<]*: ${what.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace("'", "(?:'|&#39;)")}`), reason);
  }
  assert.match(html, /Only staff see this/);
});

test("a lockout says until when, in HH:MM", () => {
  const row = { ...LOG.rows[1], sign_ins: [tried("locked", "Locked out for too many wrong tries", { until: "2026-11-09T08:05:00Z" })] };
  const html = states.sittingView({ ...LOG, rows: [row] });
  const hhmm = states.clockTime("2026-11-09T08:05:00Z");
  assert.match(hhmm, /^\d\d:\d\d$/);
  assert.ok(html.includes(`Locked out for too many wrong tries, until ${hhmm}`), html);
  assert.equal(states.clockTime(null), "");
  assert.equal(states.clockTime("not a time"), "");
});

test("a student with none shows no list, and one is spoken of in the singular", () => {
  assert.doesNotMatch(states.sittingView(LOG), /Failed sign-ins|failed sign-in/);
  const one = states.sittingView({ ...LOG, rows: [{ ...LOG.rows[1], sign_ins: [tried("wrong_pin", "Wrong exam PIN")] }] });
  assert.match(one, /1 failed sign-in</);
  assert.match(one, /Failed sign-ins \(1\)/);
});

test("a name, a reason and a computer tag are text, never markup", () => {
  const row = { ...LOG.rows[1], name: "<img src=x onerror=alert(1)>", sign_ins: [tried("wrong_pin", "<b>Wrong</b>", { device: '"><i>' })] };
  const html = states.sittingView({ ...LOG, rows: [row] });
  assert.doesNotMatch(html, /<img|<b>Wrong|<i>/);
});

test("a student outside the test's classes has a line of their own", () => {
  const outsider = {
    ...LOG.rows[1], student_id: 77, name: "Bimpe Ojo", admission_number: "SM/005", class_name: "JSS 1B",
    state: "Not in this test's classes", number: 0, started_at: null, deadline: null, submitted_at: null, computers: 0,
    sign_ins: [tried("not_in_class", "Not in a class sitting this test")],
  };
  const html = states.sittingView({ ...LOG, rows: [outsider] });
  assert.match(html, /Bimpe Ojo/);
  assert.match(html, /Not in this test(?:'|&#39;)s classes/);
  assert.match(html, /data-reason="not_in_class"/);
  assert.doesNotMatch(html, /data-count=/, "no attempt, no counts");
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

test("extra time is sent with its minutes and its reason, and the log is drawn again", async () => {
  const calls = [];
  const fetchImpl = async (url, init = {}) => {
    calls.push([url, init.body ? JSON.parse(init.body) : null]);
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    return { status: 200, json: async () => ({ ...LOG, rows: [{ ...LOG.rows[0], extra_minutes: 25 }] }) };
  };
  forgetToken();
  const root = fakeRoot();
  const page = await mount(root, { fetchImpl, location: { hash: "#9" } });
  assert.equal(page.state().step, "sitting");
  await root.submit({ minutes: "15", reason: "Power cut" }, { form: "extra", student: "41" });
  const sent = calls.find(([url]) => url.endsWith("/students/41/extra-time/"));
  assert.deepEqual(sent[1], { minutes: 15, reason: "Power cut" });
  assert.match(root.innerHTML, /25 extra minutes/);
  assert.match(root.innerHTML, /Extra time given/);
});

test("the sitting says, for each class, when its PINs were last issued and by whom", () => {
  const issued = { at: "24 Oct 2026, 10:04", by: "Ngozi <b>Eze</b>" };
  const html = states.sittingView({
    ...LOG,
    classes: [
      { ...LOG.classes[0], pins_issued: issued },
      { id: 4, name: "JSS 1B", open: false, by_hand: false, said: "As planned", pins_issued: null },
    ],
  });

  assert.match(html, /data-class="3">.*PINs last issued: 24 Oct 2026, 10:04 by Ngozi &lt;b&gt;Eze&lt;\/b&gt;/s);
  assert.match(html, /data-class="4">.*PINs not issued yet this term/s);
  assert.doesNotMatch(html, /<b>Eze/);
});

// -- action buttons and exam slips on the test and sitting pages ------------------------------

const PRINTING = {
  ...LOG,
  may_print: true,
  classes: [{ ...LOG.classes[0], printable: 4, with_a_pin: 3, pins_issued: null }],
  rows: LOG.rows.map((r) => ({ ...r, class_id: 3 })),
};

test("the sitting page's action buttons are outline buttons, navy only for the one main action", () => {
  const html = states.sittingView({ ...PRINTING, code_set: false });
  assert.match(html, /class="submit" data-action="set-code">Set the test code/);
  assert.match(html, /<button type="button" data-action="ask-close-3">Close it now/);
  assert.match(html, /<button type="button" data-action="ask-extra-41">Extra time/);
  assert.doesNotMatch(html, /class="again"/);
});

test("a login that may print slips sees Print exam PIN slips for the class and Reissue slip for each student", () => {
  const html = states.sittingView(PRINTING);
  assert.match(html, /data-action="ask-print-class-3">Print exam PIN slips<\/button>/);
  assert.match(html, /data-action="ask-print-student-41" aria-label="Reissue slip for Ada &lt;b&gt;Obi&lt;\/b&gt;">Reissue slip</);
  assert.match(html, /data-action="ask-print-student-42"/);
});

test("a login that may not print slips is drawn no slip button at all", () => {
  for (const log of [LOG, { ...PRINTING, may_print: false }]) {
    const html = states.sittingView(log);
    assert.doesNotMatch(html, /Print exam PIN slips|Reissue slip|print-class|print-student/);
  }
});

test("a student with no admission number, or in none of the test's classes, has no Reissue button", () => {
  const rows = [
    { ...PRINTING.rows[0], admission_number: "" },
    { ...PRINTING.rows[1], class_id: null },
  ];
  assert.doesNotMatch(states.sittingView({ ...PRINTING, rows }), /Reissue slip/);
});

test("printing a class that holds PINs asks first, with Cancel the default", () => {
  const html = states.sittingView(PRINTING, { confirming: "print-class-3" });
  assert.match(html, /This gives all 4 students new PINs\. Slips already handed out will stop working\./);
  assert.match(html, /data-action="keep" data-default>Cancel/);
  assert.match(html, /data-action="print-class" data-class="3">Give JSS 1A new PINs and print/);
  assert.doesNotMatch(html, /Print exam PIN slips/);
});

test("a first print for a class says what it will print and still needs the second tap", () => {
  const log = { ...PRINTING, classes: [{ ...PRINTING.classes[0], with_a_pin: 0 }] };
  const html = states.sittingView(log, { confirming: "print-class-3" });
  assert.match(html, /JSS 1A gets 4 slips\./);
  assert.match(html, /data-action="print-class" data-class="3">Print JSS 1A</);
});

test("reissuing one student's slip asks, naming them, and says the old slip stops working", () => {
  const html = states.sittingView(PRINTING, { confirming: "print-student-42" });
  assert.match(html, /This gives Emeka Nwosu a new exam PIN\. Their old slip will stop working\./);
  assert.match(html, /data-action="keep" data-default>Cancel/);
  assert.match(html, /data-action="print-student" data-class="3" data-student="42">/);
});

function slipPage({ answers = {}, saved = [], sent = [] } = {}) {
  const fetchImpl = async (url, init = {}) => {
    const method = init.method || "GET";
    sent.push(`${method} ${url}`);
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    const answer = answers[`${method} ${url}`];
    if (answer) return { status: answer.status, json: async () => answer.body, blob: async () => "the-pdf", headers: { get: () => answer.disposition || null } };
    return { status: 200, json: async () => PRINTING, blob: async () => "the-pdf", headers: { get: () => null } };
  };
  forgetToken();
  const root = fakeRoot();
  return { root, sent, saved, start: () => mount(root, { fetchImpl, location: { hash: "#9" }, save: (blob, name) => saved.push([blob, name]) }) };
}

test("the second tap prints the class with a yes, saves the PDF and draws the log again", async () => {
  const sent = [];
  const saved = [];
  const { root, start } = slipPage({
    sent,
    saved,
    answers: { "POST /api/cbt/slips/classes/3/print/": { status: 200, body: null, disposition: 'attachment; filename="exam-slips-jss-1a.pdf"' } },
  });
  await start();
  await root.click({ "data-action": "ask-print-class-3" });
  assert.match(root.innerHTML, /Slips already handed out will stop working/);
  assert.ok(!sent.includes("POST /api/cbt/slips/classes/3/print/"), "asking prints nothing");
  await root.click({ "data-action": "print-class", "data-class": "3" });
  assert.ok(sent.includes("POST /api/cbt/slips/classes/3/print/"));
  assert.deepEqual(saved, [["the-pdf", "exam-slips-jss-1a.pdf"]]);
  assert.match(root.innerHTML, /Printed\. Saved as exam-slips-jss-1a\.pdf/);
  assert.doesNotMatch(root.innerHTML, /Slips already handed out will stop working\./);
});

test("Not now, or Cancel, prints nothing", async () => {
  const sent = [];
  const { root, start } = slipPage({ sent });
  await start();
  await root.click({ "data-action": "ask-print-student-42" });
  await root.click({ "data-action": "keep" });
  assert.ok(!sent.some((s) => s.includes("/print/")));
  assert.doesNotMatch(root.innerHTML, /This gives/);
});

test("reissuing one student's slip posts to that student's print route and saves the PDF", async () => {
  const sent = [];
  const saved = [];
  const { root, start } = slipPage({
    sent,
    saved,
    answers: { "POST /api/cbt/slips/classes/3/students/42/print/": { status: 200, body: null, disposition: 'attachment; filename="exam-slip-emeka.pdf"' } },
  });
  await start();
  await root.click({ "data-action": "ask-print-student-42" });
  await root.click({ "data-action": "print-student", "data-class": "3", "data-student": "42" });
  assert.ok(sent.includes("POST /api/cbt/slips/classes/3/students/42/print/"));
  assert.deepEqual(saved, [["the-pdf", "exam-slip-emeka.pdf"]]);
  assert.match(root.innerHTML, /Their earlier slip no longer works/);
});

test("a refused print says the school's sentence and saves nothing", async () => {
  const saved = [];
  const { root, start } = slipPage({
    saved,
    answers: { "POST /api/cbt/slips/classes/3/print/": { status: 422, body: { detail: "No term is open." } } },
  });
  await start();
  await root.click({ "data-action": "ask-print-class-3" });
  await root.click({ "data-action": "print-class", "data-class": "3" });
  assert.deepEqual(saved, []);
  assert.match(root.innerHTML, /No term is open\./);
});
