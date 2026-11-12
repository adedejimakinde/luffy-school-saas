/**
 * `/test-scores/`: a student's own released score and corrections (screen 09a), and a
 * parent's children's scores (09b). `cbt/score_views.py`, `cbt/release.py`.
 *
 * A parent is never shown the student's door; a student's door says one sentence for
 * every failure; a parent's screen has no question and no answer; and every value is
 * escaped.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { first, htmlFor, mount, opened } from "../../static/test-scores/app.js";
import * as states from "../../static/test-scores/states.js";
import { fakeRoot } from "./fake_dom.js";

const SCORE = { test_title: "Second CA <test>", subject: "Mathematics", score: 18, out_of: 20, percent: 90, released_at: "2026-10-23T10:00:00+00:00", released_by: "Mr Okonkwo" };
const MINE = {
  name: "Amaka Obi", class_name: "SS 2A",
  this: {
    ...SCORE, right: 1, questions: 2,
    corrections: [
      { number: 1, stem: "1 + 1?", image_alt: "", options: [], chosen: "A", chosen_text: "2", right_letter: "A", right_text: "2", right: true, marks: 1, explanation: "" },
      { number: 2, stem: "Evaluate <b>log</b>", image_alt: "", options: [], chosen: "D", chosen_text: "-1", right_letter: "B", right_text: "-3", right: false, marks: 1, explanation: "0.001 = 10^-3" },
    ],
  },
  earlier: [{ ...SCORE, test_title: "First CA test: number bases", score: 15 }],
};

test("09a: the score, only the ones not right, with the letters the student saw", () => {
  const html = states.student(MINE);
  assert.match(html, /<strong>18<\/strong> out of 20/);
  assert.match(html, /Evaluate &lt;b&gt;log&lt;\/b&gt;/);
  assert.match(html, /<span class="letter">D<\/span> Your answer: -1/);
  assert.match(html, /<span class="letter">B<\/span> Right answer: -3/);
  assert.doesNotMatch(html, /1 \+ 1\?/, "a right one is not listed until asked");
  assert.match(states.student(MINE, { all: true }), /1 \+ 1\?/);
  assert.match(html, /Earlier tests/);
  assert.match(html, /First CA test: number bases/);
  assert.match(html, /Second CA &lt;test&gt;/);
});

test("09b: a parent's children, one at a time, no question and no answer", () => {
  const children = [
    { student_id: 1, name: "Amaka Obi", class_name: "SS 2A", scores: [SCORE], waiting: 1 },
    { student_id: 2, name: "Ike Obi", class_name: "JSS 1A", scores: [], waiting: 0 },
  ];
  const html = states.family(children);
  assert.match(html, /18\/20/);
  assert.match(html, /90%/);
  assert.match(html, /Amaka has 1 test waiting for release/);
  assert.doesNotMatch(html, /Right answer|Your answer|stem/);
  assert.match(html, /data-action="child" data-index="1"/);
  assert.match(states.family(children, { current: 1 }), /No test score for Ike Obi has been released yet/);
});

test("a parent is shown their children, never the student's door", async () => {
  const fetchImpl = async () => ({ status: 200, json: async () => ({ children: [{ student_id: 1, name: "Amaka", class_name: "", scores: [], waiting: 0 }] }) });
  assert.equal((await first({ guardian: true, fetchImpl })).step, "family");
  const none = async () => ({ status: 200, json: async () => ({ children: [] }) });
  assert.equal((await first({ guardian: true, fetchImpl: none })).step, "blank");
  assert.equal((await first({ guardian: false, fetchImpl: none })).step, "door");
  const signedOut = async () => ({ status: 401, json: async () => ({}) });
  assert.equal((await first({ fetchImpl: signedOut })).step, "door");
});

test("the door's answers: the score, the one sentence, a wait, no school", () => {
  assert.equal(opened({ status: 200, body: MINE }, "SM/1").step, "student");
  const refused = opened({ status: 404, body: { detail: "Those three do not open anything." } }, "SM/1");
  assert.deepEqual([refused.step, refused.note, refused.number], ["door", "Those three do not open anything.", "SM/1"]);
  assert.match(htmlFor(opened({ status: 429, body: { retry_after: 120 } }, "SM/1")), /Too many wrong tries/);
  assert.match(htmlFor(opened({ status: 0, body: {} }, "SM/1")), /could not be reached/);
  assert.match(htmlFor(opened({ status: 409, body: { detail: "Your score for this test has not been released yet." } }, "")), /not been released yet/);
});

test("the door posts the three and keeps no PIN in the form it draws again", async () => {
  const calls = [];
  const fetchImpl = async (url, init = {}) => {
    calls.push([url, init.body ? JSON.parse(init.body) : null]);
    if (url === "/api/cbt/scores/") return { status: 401, json: async () => ({}) };
    return { status: 404, json: async () => ({ detail: "No." }) };
  };
  const root = fakeRoot();
  await mount(root, { fetchImpl });
  assert.match(root.innerHTML, /data-form="door"/);
  await root.submit({ code: "KMTRWX", number: "SM/001", pin: "12345678" }, { form: "door" });
  assert.deepEqual(calls.at(-1), ["/test-scores/api/open/", { code: "KMTRWX", admission_number: "SM/001", pin: "12345678" }]);
  assert.match(root.innerHTML, /value="SM\/001"/);
  assert.doesNotMatch(root.innerHTML, /12345678/);
});

test("09a: while another class has still to sit, the score shows and no answer does (audit G-03)", () => {
  const held = {
    ...MINE,
    this: { ...MINE.this, corrections: [], answers_held: true, answers_held_why: "Your answers and the right ones will show here once every class has finished this test." },
  };
  const html = states.student(held);
  assert.match(html, /<strong>18<\/strong> out of 20/);
  assert.match(html, /once every class has finished this test/);
  assert.doesNotMatch(html, /Right answer/);
  assert.doesNotMatch(html, /class="corrections"/);
  // One wrong of two, and nothing to list yet: never "you got every question right".
  assert.doesNotMatch(html, /You got every question right/);
  assert.doesNotMatch(html, /data-action="show-all"/);
});
