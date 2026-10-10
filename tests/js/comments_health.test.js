/**
 * Physical development and health on the remarks page: fetched from its own
 * route when a child is opened (`results/health_api.py`), drawn only where it
 * came back, edited by the class teacher alone.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { applyHealth, mount } from "../../static/comments/app.js";
import { SAVE } from "../../static/comments/api.js";
import * as states from "../../static/comments/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const CLASS = {
  class_group_id: 11, class_group: "JSS 1A", term_id: 7, term: "2025/2026 First term",
  rows: [{ student_membership_id: 1, student: "Ada Obi", outstanding: [] }],
};

const CHILD = {
  student_membership_id: 1, student: "Ada Obi", class_group_id: 11, class_group: "JSS 1A",
  term_id: 7, term: "2025/2026 First term", locked: false, locked_reason: null,
  remarks: [], phrases: {}, may_rate: true, sections: [], scale: [],
};

const HEALTH = {
  student_membership_id: 1, term_id: 7, height_start_m: "1.42", height_end_m: null,
  weight_start_kg: "38.5", weight_end_kg: null, days_absent_ill: 3, illness: "Malaria",
  may_edit: true, locked: false, printed: true,
};

function serve(routes) {
  return async (url, options = {}) => {
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    for (const [match, answer] of routes) {
      if (url.includes(match)) {
        const value = typeof answer === "function" ? answer(options) : answer;
        return { status: value.status, json: async () => value.body };
      }
    }
    throw new Error(`no stub for ${url}`);
  };
}

test("the class teacher gets the form, filled in", () => {
  const html = states.child({ ...CHILD, health: HEALTH });

  assert.match(html, /Physical development and health/);
  assert.match(html, /data-form="health"/);
  assert.match(html, /name="height_start_m" value="1.42"/);
  assert.match(html, /name="illness" value="Malaria"/);
  assert.match(html, /Seen only by the class teacher, the principal/);
});

test("the office reads it as text", () => {
  const html = states.child({ ...CHILD, health: { ...HEALTH, may_edit: false } });

  assert.doesNotMatch(html, /data-form="health"/);
  assert.match(html, /<dd>1.42 m<\/dd>/);
  assert.match(html, /<dd>-<\/dd>/);
});

test("a school not on the Ogun card shows no section", () => {
  assert.doesNotMatch(states.child({ ...CHILD, health: { ...HEALTH, printed: false } }), /Physical development/);
});

test("a teacher the route refused sees the child and no section", async () => {
  forgetToken();
  const root = fakeRoot({});
  await mount(root, {
    classGroupId: 11,
    fetchImpl: serve([
      ["/api/results/health/1/", { status: 404, body: { detail: "No such health record." } }],
      ["/api/results/comments/1/", { status: 200, body: CHILD }],
      ["/api/results/comments/", { status: 200, body: CLASS }],
    ]),
  });

  await root.click({ "data-action": "open", "data-child": "1" });

  assert.match(root.innerHTML, /data-state="child"/);
  assert.doesNotMatch(root.innerHTML, /Physical development/);
});

test("saving sends the six boxes, blanks as null, and draws the answer", async () => {
  forgetToken();
  const sent = [];
  const root = fakeRoot({});
  await mount(root, {
    classGroupId: 11,
    fetchImpl: serve([
      ["/api/results/health/1/", (o) => {
        if (o.method === "PUT") {
          sent.push(JSON.parse(o.body));
          return { status: 200, body: { ...HEALTH, height_end_m: "1.45" } };
        }
        return { status: 200, body: HEALTH };
      }],
      ["/api/results/comments/1/", { status: 200, body: CHILD }],
      ["/api/results/comments/", { status: 200, body: CLASS }],
    ]),
  });
  await root.click({ "data-action": "open", "data-child": "1" });

  await root.submit({
    dataset: { form: "health" },
    height_start_m: "1.42", height_end_m: "1.45", weight_start_kg: "38.5",
    weight_end_kg: "", days_absent_ill: "3", illness: "Malaria",
  });

  assert.deepEqual(sent, [{
    height_start_m: "1.42", height_end_m: "1.45", weight_start_kg: "38.5",
    weight_end_kg: null, days_absent_ill: "3", illness: "Malaria",
  }]);
  assert.match(root.innerHTML, /name="height_end_m" value="1.45"/);
});

test("a refused save keeps what was typed; a locked one turns to text", () => {
  const typed = { height_start_m: "142", illness: "Malaria" };
  const refused = applyHealth({ step: "child", ...CHILD, health: HEALTH }, {
    ok: false, outcome: SAVE.REJECTED, body: { detail: "Height at the beginning of term is in metres, between 0.50 and 2.50." },
  }, typed);
  const html = states.child(refused);
  assert.match(html, /value="142"/);
  assert.match(html, /is in metres/);

  const locked = applyHealth({ step: "child", ...CHILD, health: HEALTH }, {
    ok: false, outcome: SAVE.LOCKED, body: { detail: "This child's card for the term has been released." },
  });
  assert.doesNotMatch(states.child(locked), /data-form="health"/);
  assert.match(states.child(locked), /has been released/);
});
