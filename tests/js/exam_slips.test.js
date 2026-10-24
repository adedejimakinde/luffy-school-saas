/**
 * Exam slips: the principal's, the administrator's and an exam officer's screen.
 *
 * What it walks is `cbt/api.py`'s answer set: one overview read, one class's students,
 * a print that answers with a PDF, officer writes that answer with the whole overview,
 * a 422 sentence to print in the row, a 403 for anybody the page is not for, a 404 off
 * a school's host, and a 401 that is two states.
 *
 * **Printing asks twice**, because it cancels the slips already given out: the first tap
 * says how many, and nothing is sent until the second. So does ending an exam officer.
 * The PDF is handed to the browser to save and never kept in a state.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { htmlFor, mount, printedNote } from "../../static/exam-slips/app.js";
import { REFUSAL, filenameOf, printUrl, refusalFor } from "../../static/exam-slips/api.js";
import * as states from "../../static/exam-slips/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const OVERVIEW = {
  term_id: 7,
  term: "First term, 2026/2027",
  may_name: true,
  classes: [
    { id: 3, name: "JSS 1A", students: 4, with_a_pin: 3, last_print: { at: "24 Oct 2026, 10:04", by: "Ngozi Eze" } },
    { id: 4, name: "JSS 1B <b>Gold</b>", students: 1, with_a_pin: 0, last_print: null },
    { id: 5, name: "JSS 2A", students: 0, with_a_pin: 0, last_print: null },
  ],
  officers: [
    { membership_id: 21, name: "Kemi Bello", role: "Teacher", named_by: "Ngozi Eze", named_at: "23 Oct 2026, 09:00", can_act: true },
  ],
  candidates: [
    { membership_id: 22, name: "Tayo Ojo", role: "Teacher" },
    { membership_id: 30, name: "Ade Admin", role: "Administrator" },
  ],
  prints: [
    { kind: "class", class_group: "JSS 1A", student: "", count: 3, cancelled: 3, without_a_number: 1, by: "Ngozi Eze", at: "24 Oct 2026, 10:04" },
    { kind: "student", class_group: "JSS 1A", student: "Ada Obi", count: 1, cancelled: 1, without_a_number: 0, by: "Ade Admin", at: "24 Oct 2026, 11:00" },
  ],
  officer_changes: [
    { kind: "named", name: "Kemi Bello", role: "Teacher", by: "Ngozi Eze", note: "Runs the lab", at: "23 Oct 2026, 09:00" },
    { kind: "ended", name: "Sade Ola", role: "Vice principal (academic)", by: "Ngozi Eze", note: "", at: "22 Oct 2026, 09:00" },
  ],
};

const ROSTER = {
  id: 3,
  name: "JSS 1A",
  term: "First term, 2026/2027",
  students: [
    { id: 101, name: "Ada Obi", admission_number: "SM/001", has_pin: true },
    { id: 104, name: "Tunde Cole", admission_number: "", has_pin: false },
  ],
};

function serve(routes, sent = []) {
  return async (url, options = {}) => {
    const method = options.method || "GET";
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    for (const [match, answer] of routes) {
      if (url.endsWith(match) && (answer.method || "GET") === method) {
        sent.push(`${method} ${url}`);
        const value = typeof answer.reply === "function" ? answer.reply(options, url) : answer.reply;
        return {
          status: value.status,
          json: async () => value.body,
          blob: async () => value.blob,
          headers: { get: (name) => (value.headers || {})[name] || null },
        };
      }
    }
    throw new Error(`no stub for ${method} ${url}`);
  };
}

const PDF = { status: 200, blob: "the-pdf", headers: { "Content-Disposition": 'attachment; filename="exam-slips-jss-1a.pdf"' } };

async function opened(extra = [], { overview = OVERVIEW, sent = [], saved = [] } = {}) {
  forgetToken();
  const root = fakeRoot({ portal: "app.example.test" });
  await mount(root, {
    fetchImpl: serve([...extra, ["/api/cbt/slips/", { reply: { status: 200, body: overview } }]], sent),
    save: (blob, filename) => saved.push([blob, filename]),
  });
  return root;
}

test("each class says how many students and slips it has, and when it was last printed", () => {
  const html = states.overview({ ...OVERVIEW });

  assert.match(html, /data-class="3">.*4 students, 3 with a slip\. Last printed 24 Oct 2026, 10:04 by Ngozi Eze\./s);
  assert.match(html, /data-class="4">.*1 student, 0 with a slip\. Not printed yet this term\./s);
  assert.match(html, /data-class="5">.*Nobody placed this term/s);
  assert.match(html, /First term, 2026\/2027/);
});

test("a class with nobody has no Print button; one with slips offers a lost slip", () => {
  const html = states.overview({ ...OVERVIEW });

  assert.match(html, /data-action="ask-print-class" data-class="3">Print again</);
  assert.match(html, /data-action="ask-print-class" data-class="4">Print slips</);
  assert.doesNotMatch(html, /data-class="5">Print/);
  assert.match(html, /data-action="open-class" data-class="3"/);
  assert.doesNotMatch(html, /data-action="open-class" data-class="4"/);
});

test("names are escaped", () => {
  const html = states.overview({ ...OVERVIEW });

  assert.doesNotMatch(html, /<b>Gold/);
  assert.match(html, /JSS 1B &lt;b&gt;Gold&lt;\/b&gt;/);
});

test("printing a class asks first, says what stops working, and only the second tap prints", async () => {
  const sent = [];
  const saved = [];
  const root = await opened([["/api/cbt/slips/classes/3/print/", { method: "POST", reply: PDF }]], { sent, saved });

  await root.click({ "data-action": "ask-print-class", "data-class": "3" });
  assert.deepEqual(sent.filter((s) => s.startsWith("POST")), [], "asking sends nothing");
  assert.match(root.innerHTML, /JSS 1A gets 4 new slips\. The 3 slips already given out will stop working\./);
  await root.click({ "data-action": "keep" });
  assert.doesNotMatch(root.innerHTML, /data-confirm=/);

  await root.click({ "data-action": "ask-print-class", "data-class": "3" });
  await root.click({ "data-action": "print-class", "data-class": "3" });

  assert.deepEqual(sent.filter((s) => s.startsWith("POST")), ["POST /api/cbt/slips/classes/3/print/"]);
  assert.deepEqual(saved, [["the-pdf", "exam-slips-jss-1a.pdf"]]);
  assert.equal(sent.filter((s) => s === "GET /api/cbt/slips/").length, 2, "the overview is read again after printing");
  assert.match(root.innerHTML, /Printed\. Saved as exam-slips-jss-1a\.pdf\./);
  assert.doesNotMatch(root.innerHTML, /the-pdf/, "the file is not kept on the page");
});

test("a class never printed says only how many slips it gets", () => {
  const html = states.overview({ ...OVERVIEW, confirming: "class4" });

  assert.match(html, /data-confirm="class4"><p>JSS 1B &lt;b&gt;Gold&lt;\/b&gt; gets 1 slip\.<\/p>/);
});

test("a lost slip: the class opens to its students, and one with no number cannot be printed", async () => {
  const sent = [];
  const saved = [];
  const root = await opened(
    [
      ["/api/cbt/slips/classes/3/", { reply: { status: 200, body: ROSTER } }],
      ["/api/cbt/slips/classes/3/students/101/print/", { method: "POST", reply: PDF }],
    ],
    { sent, saved },
  );

  await root.click({ "data-action": "open-class", "data-class": "3" });
  assert.match(root.innerHTML, /Ada Obi<\/strong> <span class="who">SM\/001<\/span>/);
  assert.match(root.innerHTML, /data-student="104">.*No admission number on the Roll/s);
  assert.doesNotMatch(root.innerHTML, /ask-print-student" data-student="104"/);

  await root.click({ "data-action": "ask-print-student", "data-student": "101" });
  assert.match(root.innerHTML, /Ada Obi gets a new slip, and the old one stops working\./);
  await root.click({ "data-action": "print-student", "data-class": "3", "data-student": "101" });

  assert.ok(sent.includes("POST /api/cbt/slips/classes/3/students/101/print/"));
  assert.equal(saved.length, 1);
  assert.match(root.innerHTML, /data-student="101">.*Printed\. Saved as/s);
});

test("a refused print says the school's sentence in the row and saves nothing", async () => {
  const saved = [];
  const root = await opened(
    [["/api/cbt/slips/classes/4/print/", { method: "POST", reply: { status: 422, body: { detail: "No term is open." } } }]],
    { saved },
  );

  await root.click({ "data-action": "print-class", "data-class": "4" });

  assert.deepEqual(saved, []);
  assert.match(root.innerHTML, /data-class="4">.*No term is open\./s);
});

test("the principal names and ends exam officers; anybody else sees who they are and no controls", () => {
  const principal = states.overview({ ...OVERVIEW });
  const office = states.overview({ ...OVERVIEW, may_name: false, candidates: [] });

  assert.match(principal, /data-form="name-officer"/);
  assert.match(principal, /<option value="30">Ade Admin \(Administrator\)<\/option>/);
  assert.match(principal, /data-action="ask-end" data-member="21"/);
  assert.doesNotMatch(office, /data-form="name-officer"/);
  assert.doesNotMatch(office, /ask-end/);
  assert.match(office, /Kemi Bello<\/strong> <span class="who">Teacher, named by Ngozi Eze 23 Oct 2026, 09:00/);
  assert.match(office, /The principal names them\./);
});

test("naming an officer posts the choice and the note, and redraws from the answer", async () => {
  const bodies = [];
  const root = await opened([
    ["/api/cbt/officers/", {
      method: "POST",
      reply: (options) => {
        bodies.push(JSON.parse(options.body));
        return { status: 200, body: { ...OVERVIEW, officers: [...OVERVIEW.officers, { membership_id: 22, name: "Tayo Ojo", role: "Teacher", named_by: "Ngozi Eze", named_at: "24 Oct 2026, 12:00", can_act: true }] } };
      },
    }],
  ]);

  await root.submit({ dataset: { form: "name-officer" }, member: "22", note: "Lab two" });

  assert.deepEqual(bodies, [{ membership_id: 22, note: "Lab two" }]);
  assert.match(root.innerHTML, /data-officer="22"/);
});

test("ending an officer asks first, and only the second tap sends", async () => {
  const sent = [];
  const root = await opened(
    [["/api/cbt/officers/21/end/", { method: "POST", reply: { status: 200, body: { ...OVERVIEW, officers: [] } } }]],
    { sent },
  );

  await root.click({ "data-action": "ask-end", "data-member": "21" });
  assert.match(root.innerHTML, /Kemi Bello will no longer print exam slips\./);
  assert.deepEqual(sent.filter((s) => s.startsWith("POST")), []);
  await root.click({ "data-action": "end", "data-member": "21" });

  assert.deepEqual(sent.filter((s) => s.startsWith("POST")), ["POST /api/cbt/officers/21/end/"]);
  assert.match(root.innerHTML, /No exam officers yet\./);
});

test("a refused naming keeps the form with the school's sentence under it", async () => {
  const root = await opened([
    ["/api/cbt/officers/", { method: "POST", reply: { status: 422, body: { detail: "Tayo Ojo is already an exam officer." } } }],
  ]);

  await root.submit({ dataset: { form: "name-officer" }, member: "22", note: "" });

  assert.match(root.innerHTML, /data-form="name-officer".*Tayo Ojo is already an exam officer\./s);
});

test("the logs say who printed what and who named whom, and when", () => {
  const html = states.overview({ ...OVERVIEW });

  assert.match(html, /Ngozi Eze printed 3 slips for JSS 1A, 3 old PINs stopped, 1 student with no admission number <span class="when">24 Oct 2026, 10:04/);
  assert.match(html, /Ade Admin printed a new slip for Ada Obi in JSS 1A, 1 old PIN stopped/);
  assert.match(html, /Ngozi Eze named Kemi Bello \(Teacher\) exam officer: Runs the lab/);
  assert.match(html, /Ngozi Eze ended Sade Ola as exam officer/);
  const empty = states.overview({ ...OVERVIEW, prints: [], officer_changes: [] });
  assert.doesNotMatch(empty, /change-log/);
});

test("with no term open there are no classes to print, and the page says where the term is set", () => {
  const html = states.overview({ ...OVERVIEW, term: null, classes: [] });

  assert.match(html, /No term is open/);
  assert.doesNotMatch(html, /ask-print-class/);
});

test("nothing on the page is a PIN, a question or a bank", () => {
  const html = states.overview({ ...OVERVIEW, open: 3, roster: ROSTER, printed: { class3: printedNote("x.pdf") } });

  assert.doesNotMatch(html, /\b\d{4} \d{4}\b/);
  assert.doesNotMatch(html.toLowerCase(), /question|bank/);
});

test("the refusals are different answers", () => {
  assert.equal(refusalFor(403, {}), REFUSAL.NOT_YOURS);
  assert.equal(refusalFor(404, {}), REFUSAL.WRONG_HOST);
  assert.equal(refusalFor(401, { code: "session_expired" }), REFUSAL.EXPIRED);
  assert.equal(refusalFor(401, {}), REFUSAL.SIGNED_OUT);
  assert.match(htmlFor({ step: REFUSAL.NOT_YOURS }), /printed by the principal, the administrator or an exam officer/);
  assert.match(htmlFor({ step: REFUSAL.EXPIRED }, { portal: "app.example.test" }), /Your session has ended/);
  assert.doesNotMatch(htmlFor({ step: "nonsense" }), /<form/);
});

test("a teacher who is not an exam officer is told it is not theirs, and sees no class", async () => {
  forgetToken();
  const root = fakeRoot({ portal: "app.example.test" });
  await mount(root, {
    fetchImpl: serve([["/api/cbt/slips/", { reply: { status: 403, body: { detail: "Exam slips are printed by the principal, the administrator or an exam officer." } } }]]),
  });

  assert.match(root.innerHTML, /This page is not yours/);
  assert.doesNotMatch(root.innerHTML, /JSS 1A/);
});

test("the print routes and the file's name", () => {
  assert.equal(printUrl(3), "/api/cbt/slips/classes/3/print/");
  assert.equal(printUrl(3, 101), "/api/cbt/slips/classes/3/students/101/print/");
  assert.equal(filenameOf('attachment; filename="a.pdf"'), "a.pdf");
  assert.equal(filenameOf(null), "exam-slips.pdf");
});
