/**
 * The roll: who is enrolled, and which class each child is in.
 *
 * Every state is a pure function of an API body. What it walks is
 * `accounts/enrolment_api.py`'s answer set: a 201, a 200 for a move, a 409 for
 * a handle somebody already holds, a 422, a 403, and a 401 that is two states.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { applyWrite, fromRoll, htmlFor, mount } from "../../static/roll/app.js";
import { REFUSAL, SAVE, refusalFor, provesASession } from "../../static/roll/api.js";
import * as states from "../../static/roll/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const ROLL = {
  term_id: 7,
  term: "2025/2026 First term",
  children: [
    { student_membership_id: 1, student: "Ada Obi", username: "STM/2026/0001", reference: "0001", class_group_id: 11, class_group: "JSS 1A" },
    { student_membership_id: 2, student: "Chike Obi", username: "STM/2026/0042", reference: "", class_group_id: null, class_group: null },
  ],
  classes: [
    { class_group_id: 11, name: "JSS 1A" },
    { class_group_id: 12, name: "JSS 1B" },
  ],
  may_admit: true,
  may_place: true,
};

const state = () => fromRoll({ ok: true, body: ROLL });

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

// -- the two authorities are two booleans -----------------------------------

test("an administrator is offered the admission form", () => {
  const html = states.roll(ROLL);

  assert.match(html, /data-form="admit"/);
  assert.match(html, /STM\/2026\/0042/);
});

test("a principal is told she may move but not admit, rather than shown nothing", () => {
  // ADMIN alone hands out memberships. An absent form reads as a page that did
  // not finish loading, so it is said out loud.
  const html = states.roll({ ...ROLL, may_admit: false, may_place: true });

  assert.doesNotMatch(html, /data-form="admit"/);
  assert.match(html, /admitted by an administrator/);
  assert.match(html, /<select[^>]*data-child="1"/);
});

test("somebody who may neither admit nor place gets no controls at all", () => {
  const html = states.roll({ ...ROLL, may_admit: false, may_place: false });

  assert.doesNotMatch(html, /data-form="admit"/);
  assert.doesNotMatch(html, /<select[^>]*data-child=/);
  assert.match(html, /JSS 1A/);
});

// -- a child with no class ---------------------------------------------------

test("a child not yet in a class says so rather than showing a blank", () => {
  // Admitted in August, placed in September. A blank reads as a page that
  // failed to draw.
  const html = states.roll({ ...ROLL, may_place: false });

  assert.match(html, /Not in a class yet/);
});

test("the chooser preselects the class a child is already in", () => {
  const html = states.roll(ROLL);

  assert.match(html, /<option value="11" selected>JSS 1A<\/option>/);
  // And the unplaced child has the empty option selected instead.
  assert.match(html, /<option value="" selected>Not in a class yet<\/option>/);
});

test("the handle is typed, never generated", () => {
  // `User.username` is school-issued; a scheme this page invented is one the
  // school lives with on every register and every card.
  const html = states.roll(ROLL);

  assert.match(html, /name="username"/);
  assert.match(html, /placeholder="STM\/2026\/0042"/);
});

// -- the writes --------------------------------------------------------------

test("a taken handle and a rejected request are different notes", () => {
  // One is a name to change; the other is the school's state disagreeing with
  // what was asked. Collapsing them leaves an administrator guessing.
  const taken = applyWrite(state(), "admit", {
    ok: false, outcome: SAVE.HANDLE_TAKEN,
    body: { detail: "'STM/2026/0042' is already in use by another account." },
  });
  const rejected = applyWrite(state(), "admit", {
    ok: false, outcome: SAVE.REJECTED,
    body: { detail: "No term is open, so there is no class to place a child in." },
  });

  assert.match(htmlFor(taken.state), /already in use/);
  assert.match(htmlFor(taken.state), /handle-taken/);
  assert.match(htmlFor(rejected.state), /No term is open/);
  assert.match(htmlFor(rejected.state), /rejected/);
});

test("a refused admission keeps the form open", () => {
  // Retyping a name and a handle to fix one field is the failure the refusal
  // exists to prevent.
  const { state: after } = applyWrite(state(), "admit", {
    ok: false, outcome: SAVE.HANDLE_TAKEN, body: { detail: "already in use" },
  });

  assert.match(htmlFor(after), /data-form="admit"/);
});

test("admitting sends what was typed, and omits the class when none was chosen", async () => {
  // "Not yet" is a real answer, not an empty one, so the field is absent
  // rather than null.
  forgetToken();
  const sent = [];
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/api/enrolment/roll/", (o) => {
        if (o.method === "POST") {
          sent.push(JSON.parse(o.body));
          return { status: 201, body: ROLL.children[1] };
        }
        return { status: 200, body: ROLL };
      }],
    ]),
  });

  await root.submit({ full_name: "Chike Obi", username: "STM/2026/0042", reference: "", class_group_id: "" });

  assert.deepEqual(sent, [{ full_name: "Chike Obi", username: "STM/2026/0042", reference: "" }]);
});

test("admitting with a class chosen sends it", async () => {
  forgetToken();
  const sent = [];
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/api/enrolment/roll/", (o) => {
        if (o.method === "POST") {
          sent.push(JSON.parse(o.body));
          return { status: 201, body: ROLL.children[0] };
        }
        return { status: 200, body: ROLL };
      }],
    ]),
  });

  await root.submit({ full_name: "Chike Obi", username: "STM/2026/0042", reference: "0042", class_group_id: "12" });

  assert.deepEqual(sent, [{ full_name: "Chike Obi", username: "STM/2026/0042", reference: "0042", class_group_id: 12 }]);
});

test("choosing a class moves the child, and choosing 'not yet' does nothing", async () => {
  // Taking a child *out* of a class is `remove_placement()`, a different act.
  // Doing it silently from a dropdown would be a removal nobody asked for.
  forgetToken();
  const sent = [];
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/class/", (o) => {
        sent.push(JSON.parse(o.body));
        return { status: 200, body: { ...ROLL.children[0], class_group_id: 12, class_group: "JSS 1B" } };
      }],
      ["/api/enrolment/roll/", { status: 200, body: ROLL }],
    ]),
  });

  await root.change({ "data-child": "1" }, "12");
  await root.change({ "data-child": "1" }, "");

  assert.deepEqual(sent, [{ class_group_id: 12 }]);
});

test("a successful write re-reads the roll rather than patching a row", async () => {
  // Admitting adds a row; moving changes one and can change what the chooser
  // beside it should say.
  forgetToken();
  let reads = 0;
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/class/", { status: 200, body: ROLL.children[0] }],
      ["/api/enrolment/roll/", () => {
        reads += 1;
        return { status: 200, body: ROLL };
      }],
    ]),
  });
  assert.equal(reads, 1);

  await root.change({ "data-child": "1" }, "12");

  assert.equal(reads, 2, "the roll was not re-read after a write");
});

// -- refusals and hosts ------------------------------------------------------

test("403 and 404 are different page-level refusals", () => {
  assert.equal(refusalFor(403, {}), REFUSAL.NOT_THE_OFFICE);
  assert.equal(refusalFor(404, {}), REFUSAL.WRONG_HOST);
});

test("only answers that prove a session carry a sign-out button", () => {
  assert.ok(provesASession({ ok: false, refusal: REFUSAL.NOT_THE_OFFICE }));
  assert.ok(!provesASession({ ok: false, refusal: REFUSAL.WRONG_HOST }));
});

test("the refusal a teacher reads does not offer her the staff door", () => {
  const html = states.notTheOffice({ detail: "Children are put in classes by…" });

  assert.doesNotMatch(html, /staff-sign-in/);
  assert.match(html, /can arrange it/);
});

test("on the portal the page says where the work is", async () => {
  const root = fakeRoot({ portal: "portal.example.test" });
  await mount(root, {
    fetchImpl: serve([["/api/enrolment/roll/", { status: 404, body: { detail: "No roll on this host." } }]]),
  });

  assert.match(root.innerHTML, /school's own web address/i);
  assert.doesNotMatch(root.innerHTML, /data-action="sign-out"/, "a 404 proved a session it cannot prove");
});

test("an expired session and no session are different sentences", () => {
  const expired = htmlFor({ step: REFUSAL.EXPIRED }, { portal: "portal.example.test" });
  const never = htmlFor({ step: REFUSAL.SIGNED_OUT }, { portal: "portal.example.test" });

  assert.match(expired, /session has ended/i);
  assert.match(never, /Please sign in/i);
  for (const html of [expired, never]) {
    assert.match(html, /\/\/portal\.example\.test\/staff-sign-in\//);
  }
});

test("a child's name typed into the office cannot execute in the next reader's browser", () => {
  const html = states.roll({
    ...ROLL,
    children: [{ student_membership_id: 1, student: '<img src=x onerror="alert(1)">', username: "x", reference: "", class_group_id: null, class_group: null }],
  });

  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
});
