/**
 * Subjects and teachers: the office's screen for what a school teaches.
 *
 * What it walks is `gradebook/teaching_api.py`'s answer set: one overview read, every write
 * answering with the whole overview, a 422 sentence to print under the form it came from, a 403
 * for anybody who is not the office, a 404 off a school's host, and a 401 that is two states.
 *
 * **Removal asks twice.** The first tap only names what will go; nothing is sent until the second.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { fromOverview, htmlFor, mount } from "../../static/teaching/app.js";
import { REFUSAL, refusalFor } from "../../static/teaching/api.js";
import * as states from "../../static/teaching/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const OVERVIEW = {
  term_id: 7,
  term: "2026/2027 First term",
  subjects: [
    {
      subject_id: 1, name: "Mathematics", code: "MTH", is_active: true, papers_ever: 2,
      papers: [
        { assessment_id: 11, name: "First CA", max_score: 20, has_marks: true },
        { assessment_id: 12, name: "Exam", max_score: 60, has_marks: false },
      ],
    },
    { subject_id: 2, name: "Civic <b>Education</b>", code: "CVC", is_active: false, papers_ever: 0, papers: [] },
  ],
  classes: [
    { class_group_id: 3, name: "JSS 1A", class_teacher_id: 21 },
    { class_group_id: 4, name: "JSS 1B", class_teacher_id: null },
  ],
  teachers: [
    { membership_id: 21, name: "Kemi Bello" },
    { membership_id: 22, name: "Tunde Ade" },
  ],
};

function serve(routes) {
  return async (url, options = {}) => {
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    for (const [match, answer] of routes) {
      if (url.includes(match)) {
        const value = typeof answer === "function" ? answer(options, url) : answer;
        return { status: value.status, json: async () => value.body };
      }
    }
    throw new Error(`no stub for ${url}`);
  };
}

const opened = async (extra = [], root = fakeRoot({ portal: "app.example.test" })) => {
  forgetToken();
  await mount(root, { fetchImpl: serve([...extra, ["/api/teaching/", { status: 200, body: OVERVIEW }]]) });
  return root;
};

test("the overview names each class's teacher and offers the others", () => {
  const html = states.overview({ ...OVERVIEW, notes: {} });

  assert.match(html, /<option value="21" selected>Kemi Bello<\/option>/);
  assert.match(html, /<option value="22">Tunde Ade<\/option>/);
  assert.match(html, /data-class="4">\s*<option value="">No class teacher<\/option>/);
  assert.match(html, /2026\/2027 First term/);
});

test("a subject's name is escaped, a retired one says so, and papers are counted for this term", () => {
  const html = states.overview({ ...OVERVIEW, notes: {} });

  assert.doesNotMatch(html, /<b>Education/);
  assert.match(html, /Civic &lt;b&gt;Education&lt;\/b&gt;/);
  assert.match(html, /No longer taught/);
  assert.match(html, /MTH &middot; 2 papers this term/);
});

test("with no term open the screen says so and where to fix it", () => {
  const html = states.overview({ ...OVERVIEW, term: null, notes: {} });

  assert.match(html, /No term is open/);
  assert.match(html, /Setup page/);
});

test("a subject with papers offers no removal; one without asks first", () => {
  const taught = states.subject(OVERVIEW.subjects[0]);
  const unused = states.subject(OVERVIEW.subjects[1]);

  assert.doesNotMatch(taught, /ask-remove-subject/);
  assert.match(taught, /cannot be removed/);
  assert.match(unused, /data-action="ask-remove-subject"/);
  assert.match(states.subject(OVERVIEW.subjects[1], { confirming: { subject: 2 } }), /data-action="remove-subject"/);
});

test("a paper with marks cannot be removed or re-totalled, but can be renamed", () => {
  const list = states.subject(OVERVIEW.subjects[0]);
  assert.doesNotMatch(list, /data-action="ask-remove-paper" data-paper="11"/);
  assert.match(list, /data-action="ask-remove-paper" data-paper="12"/);
  assert.match(list, /out of 20 &middot; has marks/);

  const editing = states.subject(OVERVIEW.subjects[0], { editing: 11 });
  assert.match(editing, /name="max_score"[^>]*value="20" readonly/);
  assert.match(editing, /It has marks, so what it is out of cannot change/);
});

test("the refusals are different answers", () => {
  assert.equal(refusalFor(403, {}), REFUSAL.NOT_THE_OFFICE);
  assert.equal(refusalFor(404, {}), REFUSAL.WRONG_HOST);
  assert.equal(refusalFor(401, { code: "session_expired" }), REFUSAL.EXPIRED);
  assert.equal(refusalFor(401, {}), REFUSAL.SIGNED_OUT);
  assert.match(htmlFor({ step: REFUSAL.NOT_THE_OFFICE, detail: "Only the office." }), /Only the office\./);
  assert.match(htmlFor({ step: REFUSAL.EXPIRED }), /Your session has ended/);
  assert.doesNotMatch(htmlFor({ step: "nonsense" }), /<form/);
});

test("a teacher is shown the office's page, not the school's setup", async () => {
  forgetToken();
  const root = fakeRoot({ portal: "app.example.test" });
  await mount(root, { fetchImpl: serve([["/api/teaching/", { status: 403, body: { detail: "Set by a principal." } }]]) });

  assert.match(root.innerHTML, /This page is the office&#39;s/);
  assert.doesNotMatch(root.innerHTML, /Mathematics/);
});

test("adding a subject posts it and redraws from the school's answer", async () => {
  const sent = [];
  const root = await opened([
    ["/api/teaching/subjects/", (options) => {
      sent.push(JSON.parse(options.body));
      return { status: 200, body: { ...OVERVIEW, subjects: [...OVERVIEW.subjects, { subject_id: 9, name: "Biology", code: "BIO", is_active: true, papers_ever: 0, papers: [] }] } };
    }],
  ]);

  await root.submit({ dataset: { form: "subject" }, name: "Biology", code: "BIO" });

  assert.deepEqual(sent, [{ name: "Biology", code: "BIO" }]);
  assert.match(root.innerHTML, /Biology/);
});

test("a refused subject keeps the form with the school's sentence under it", async () => {
  const root = await opened([
    ["/api/teaching/subjects/", { status: 422, body: { detail: "Mathematics is already a subject here." } }],
  ]);

  await root.submit({ dataset: { form: "subject" }, name: "Mathematics", code: "MTH" });

  assert.match(root.innerHTML, /Mathematics is already a subject here\./);
  assert.match(root.innerHTML, /data-form="subject"/);
});

test("choosing a class teacher saves at once, and 'No class teacher' clears", async () => {
  const calls = [];
  const root = await opened([
    ["/classes/4/teacher/", (options) => {
      calls.push([options.method, options.body]);
      return { status: 200, body: OVERVIEW };
    }],
  ]);

  await root.change({ "data-class": "4" }, "22");
  await root.change({ "data-class": "4" }, "");

  assert.deepEqual(calls, [["PUT", JSON.stringify({ membership_id: 22 })], ["DELETE", undefined]]);
});

test("removing a paper asks first, and only the second tap sends", async () => {
  const calls = [];
  const root = await opened([
    ["/papers/12/", (options) => {
      calls.push(options.method);
      return { status: 200, body: { ...OVERVIEW, subjects: [{ ...OVERVIEW.subjects[0], papers: [OVERVIEW.subjects[0].papers[0]] }, OVERVIEW.subjects[1]] } };
    }],
  ]);
  await root.click({ "data-action": "open-subject", "data-subject": "1" });
  assert.match(root.innerHTML, /Papers this term/);

  await root.click({ "data-action": "ask-remove-paper", "data-paper": "12" });
  assert.deepEqual(calls, [], "naming what will go sends nothing");
  assert.match(root.innerHTML, /Remove Exam/);
  await root.click({ "data-action": "keep" });
  assert.match(root.innerHTML, /data-action="ask-remove-paper"/);

  await root.click({ "data-action": "ask-remove-paper", "data-paper": "12" });
  await root.click({ "data-action": "remove-paper", "data-paper": "12" });

  assert.deepEqual(calls, ["DELETE"]);
  assert.doesNotMatch(root.innerHTML, /Remove Exam/);
  assert.match(root.innerHTML, /First CA/, "still on the subject");
});

test("an edited paper that the school refuses stays open with the sentence", async () => {
  const root = await opened([
    ["/papers/11/", { status: 422, body: { detail: "First CA already has marks, so what it is out of cannot change." } }],
  ]);
  await root.click({ "data-action": "open-subject", "data-subject": "1" });
  await root.click({ "data-action": "edit-paper", "data-paper": "11" });

  await root.submit({ dataset: { form: "paper-edit", paper: "11" }, name: "First CA", max_score: "10" });

  assert.match(root.innerHTML, /cannot change\./);
  assert.match(root.innerHTML, /data-form="paper-edit"/);
});

test("a session that ends under a write becomes the signed-out screen", async () => {
  const root = await opened([["/api/teaching/subjects/", { status: 401, body: { code: "session_expired" } }]]);

  await root.submit({ dataset: { form: "subject" }, name: "Art", code: "ART" });

  assert.match(root.innerHTML, /Your session has ended/);
});

test("fromOverview keeps what is open across a redraw", () => {
  const state = fromOverview({ ok: true, body: OVERVIEW }, { open: 1 });

  assert.equal(state.open, 1);
  assert.equal(state.step, "teaching");
});
