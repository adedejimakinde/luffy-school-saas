/**
 * Who teaches what: the principal's screen, read by the vice principal and the administrator.
 *
 * What it walks is `gradebook/assignments_api.py`'s answer set: one overview read, every write
 * answering with the whole overview, a 422 sentence to print under the form, a 403 for anybody
 * the page is not for, a 404 off a school's host, and a 401 that is two states.
 *
 * **Taking one away asks twice.** The first tap names what will go; nothing is sent until the second.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { htmlFor, mount } from "../../static/subject-teachers/app.js";
import { REFUSAL, refusalFor } from "../../static/subject-teachers/api.js";
import * as states from "../../static/subject-teachers/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const OVERVIEW = {
  term_id: 7,
  term: "2026/2027 First term",
  may_change: true,
  in_force: true,
  classes: [
    { id: 3, name: "JSS 1A" },
    { id: 4, name: "JSS 1B" },
  ],
  subjects: [
    { id: 1, name: "Mathematics" },
    { id: 2, name: "English <b>Language</b>" },
  ],
  teachers: [
    { id: 21, name: "Kemi Bello" },
    { id: 22, name: "Tayo Ojo" },
  ],
  assignments: [
    { id: 51, class_group_id: 3, class_group: "JSS 1A", subject_id: 1, subject: "Mathematics", teacher_membership_id: 21, teacher: "Kemi Bello" },
    { id: 52, class_group_id: 3, class_group: "JSS 1A", subject_id: 1, subject: "Mathematics", teacher_membership_id: 22, teacher: "Tayo Ojo" },
  ],
  changes: [
    { kind: "added", teacher: "Tayo Ojo", subject: "Mathematics", class_group: "JSS 1A", by: "Ngozi Eze", at: "23 Oct 2026, 10:04" },
    { kind: "removed", teacher: "Kemi Bello", subject: "English", class_group: "JSS 1B", by: "Ngozi Eze", at: "23 Oct 2026, 09:58" },
  ],
};

function serve(routes) {
  return async (url, options = {}) => {
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    for (const [match, answer] of routes) {
      if (url.includes(match) && (!answer.method || answer.method === (options.method || "GET"))) {
        const value = typeof answer.reply === "function" ? answer.reply(options, url) : answer.reply;
        return { status: value.status, json: async () => value.body };
      }
    }
    throw new Error(`no stub for ${options.method || "GET"} ${url}`);
  };
}

const opened = async (extra = [], overview = OVERVIEW) => {
  forgetToken();
  const root = fakeRoot({ portal: "app.example.test" });
  await mount(root, {
    fetchImpl: serve([...extra, ["/api/subject-teachers/", { method: "GET", reply: { status: 200, body: overview } }]]),
  });
  return root;
};

test("each class lists who teaches what in it, and one with nobody says so", () => {
  const html = states.overview({ ...OVERVIEW, notes: {} });

  assert.match(html, /data-class="3">.*Mathematics<\/strong> <span class="who">Kemi Bello<\/span>.*Tayo Ojo/s);
  assert.match(html, /data-class="4"><span class="name">JSS 1B<\/span><span class="level">Nobody yet<\/span>/);
  assert.match(html, /2026\/2027 First term/);
});

test("names are escaped", () => {
  const html = states.overview({ ...OVERVIEW, notes: {} });

  assert.doesNotMatch(html, /<b>Language/);
  assert.match(html, /English &lt;b&gt;Language&lt;\/b&gt;/);
});

test("the principal gets the form and the Remove buttons; anybody else neither", () => {
  const principal = states.overview({ ...OVERVIEW, notes: {} });
  const reader = states.overview({ ...OVERVIEW, may_change: false, notes: {} });

  assert.match(principal, /data-form="assign"/);
  assert.match(principal, /data-action="ask-unassign"/);
  assert.doesNotMatch(reader, /<form/);
  assert.doesNotMatch(reader, /data-action=/);
  assert.match(reader, /Only the principal changes these\./);
});

test("the page says whether marking is narrowed yet", () => {
  assert.match(states.overview({ ...OVERVIEW, notes: {} }), /data-standing="in-force".*marks only the subjects and classes given to them/s);
  const none = states.overview({ ...OVERVIEW, in_force: false, assignments: [], notes: {} });
  assert.match(none, /data-standing="not-yet".*any teacher can mark any subject\. Once you give the first one/s);
  const read = states.overview({ ...OVERVIEW, in_force: false, may_change: false, assignments: [], notes: {} });
  assert.match(read, /Once the principal gives the first one/);
});

test("with no term open there is no form, and the page says where the term is set", () => {
  const html = states.overview({ ...OVERVIEW, term: null, notes: {} });

  assert.match(html, /No term is open/);
  assert.doesNotMatch(html, /data-form="assign"/);
});

test("recent changes say who did what, and when", () => {
  const html = states.overview({ ...OVERVIEW, notes: {} });

  assert.match(html, /Ngozi Eze gave Tayo Ojo Mathematics in JSS 1A <span class="when">23 Oct 2026, 10:04<\/span>/);
  assert.match(html, /Ngozi Eze took English in JSS 1B from Kemi Bello/);
  assert.doesNotMatch(states.overview({ ...OVERVIEW, changes: [], notes: {} }), /Recent changes/);
});

test("the refusals are different answers", () => {
  assert.equal(refusalFor(403, {}), REFUSAL.NOT_YOURS);
  assert.equal(refusalFor(404, {}), REFUSAL.WRONG_HOST);
  assert.equal(refusalFor(401, { code: "session_expired" }), REFUSAL.EXPIRED);
  assert.equal(refusalFor(401, {}), REFUSAL.SIGNED_OUT);
  assert.match(htmlFor({ step: REFUSAL.NOT_YOURS, detail: "Not for you." }), /Not for you\./);
  assert.match(htmlFor({ step: REFUSAL.EXPIRED }), /Your session has ended/);
  assert.doesNotMatch(htmlFor({ step: "nonsense" }), /<form/);
});

test("a teacher opening it is told it is not theirs, and sees nobody's subjects", async () => {
  forgetToken();
  const root = fakeRoot({ portal: "app.example.test" });
  await mount(root, {
    fetchImpl: serve([["/api/subject-teachers/", { reply: { status: 403, body: { detail: "Shown to the principal." } } }]]),
  });

  assert.match(root.innerHTML, /This page is not yours/);
  assert.doesNotMatch(root.innerHTML, /Mathematics/);
});

test("giving a subject posts the three choices and redraws from the school's answer", async () => {
  const sent = [];
  const root = await opened([
    ["/api/subject-teachers/", {
      method: "POST",
      reply: (options) => {
        sent.push(JSON.parse(options.body));
        return { status: 200, body: { ...OVERVIEW, assignments: [...OVERVIEW.assignments, { id: 53, class_group_id: 4, class_group: "JSS 1B", subject_id: 2, subject: "English", teacher_membership_id: 21, teacher: "Kemi Bello" }] } };
      },
    }],
  ]);

  await root.submit({ dataset: { form: "assign" }, teacher: "21", subject: "2", class_group: "4" });

  assert.deepEqual(sent, [{ class_group_id: 4, subject_id: 2, membership_id: 21 }]);
  assert.match(root.innerHTML, /data-class="4">.*English<\/strong> <span class="who">Kemi Bello/s);
});

test("a refused assignment keeps the form with the school's sentence under it", async () => {
  const root = await opened([
    ["/api/subject-teachers/", { method: "POST", reply: { status: 422, body: { detail: "Kemi Bello already teaches Mathematics to JSS 1A." } } }],
  ]);

  await root.submit({ dataset: { form: "assign" }, teacher: "21", subject: "1", class_group: "3" });

  assert.match(root.innerHTML, /Kemi Bello already teaches Mathematics to JSS 1A\./);
  assert.match(root.innerHTML, /data-form="assign"/);
});

test("taking one away asks first, and only the second tap sends", async () => {
  const calls = [];
  const root = await opened([
    ["/api/subject-teachers/52/", {
      method: "DELETE",
      reply: () => {
        calls.push("DELETE");
        return { status: 200, body: { ...OVERVIEW, assignments: [OVERVIEW.assignments[0]] } };
      },
    }],
  ]);

  await root.click({ "data-action": "ask-unassign", "data-assignment": "52" });
  assert.deepEqual(calls, [], "naming what will go sends nothing");
  assert.match(root.innerHTML, /Take Mathematics from Tayo Ojo/);
  await root.click({ "data-action": "keep" });
  assert.doesNotMatch(root.innerHTML, /Take Mathematics from Tayo Ojo/);

  await root.click({ "data-action": "ask-unassign", "data-assignment": "52" });
  await root.click({ "data-action": "unassign", "data-assignment": "52" });

  assert.deepEqual(calls, ["DELETE"]);
  assert.doesNotMatch(root.innerHTML, /Tayo Ojo<\/span>/);
});
