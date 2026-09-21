/**
 * Remarks: a class list, then one child, two signatories and a conduct grid.
 *
 * Every state is a pure function of an API body, so the flow is walked without
 * a browser. What it walks is `results/comments_api.py`'s answer set: a 200, a
 * 423 for a term that left draft, a 422 for text the column refuses, a 403 for
 * a remark that is not yours, and a 401 that is two states.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { applySave, fromChild, fromClass, htmlFor, mount } from "../../static/comments/app.js";
import { REFUSAL, SAVE, refusalFor, provesASession } from "../../static/comments/api.js";
import * as states from "../../static/comments/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const TEACHER = "class_teacher";
const PRINCIPAL = "principal";

const CLASS = {
  class_group_id: 11,
  class_group: "JSS 1A",
  term_id: 7,
  term: "2025/2026 First term",
  rows: [
    { student_membership_id: 1, student: "Ada Obi", outstanding: [TEACHER, PRINCIPAL] },
    { student_membership_id: 2, student: "Emeka Nwosu", outstanding: [] },
  ],
};

const asTeacher = (over = {}) => ({
  student_membership_id: 1,
  student: "Ada Obi",
  class_group_id: 11,
  class_group: "JSS 1A",
  term_id: 7,
  term: "2025/2026 First term",
  locked: false,
  locked_reason: null,
  remarks: [
    { author: TEACHER, author_label: "Class teacher", body: "", may_edit: true },
    { author: PRINCIPAL, author_label: "Principal", body: "Well done.", may_edit: false },
  ],
  phrases: { [TEACHER]: ["A steady term."] },
  may_rate: true,
  sections: [
    { group: "affective", group_label: "Affective", traits: [{ trait_id: 9, name: "Punctuality", score: null }] },
  ],
  scale: [{ value: 5, label: "Excellent" }, { value: 4, label: "Good" }],
  ...over,
});

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

// -- both remarks, one editable ---------------------------------------------

test("both remarks are shown and only the signable one is editable", () => {
  // Hiding the other would make a half-written card look finished, and the
  // principal has to read the teacher's line before adding hers.
  const html = states.child(asTeacher());

  assert.match(html, /Class teacher/);
  assert.match(html, /Principal/);
  assert.match(html, /<textarea[^>]*data-author="class_teacher"/);
  assert.doesNotMatch(html, /<textarea[^>]*data-author="principal"/);
  // The other signatory's words are readable, not a greyed-out box.
  assert.match(html, /Well done\./);
});

test("a remark nobody has written yet says so rather than showing an empty box", () => {
  const html = states.child(
    asTeacher({
      remarks: [
        { author: TEACHER, author_label: "Class teacher", body: "", may_edit: false },
        { author: PRINCIPAL, author_label: "Principal", body: "", may_edit: true },
      ],
      phrases: {},
    }),
  );

  assert.match(html, /Not written yet/);
});

test("each signatory is offered only their own phrase bank", () => {
  // A teacher picking a remark must never be shown one written for a principal
  // to sign — which is why the payload carries one bank, keyed by author.
  const html = states.child(asTeacher());

  assert.match(html, /data-action="phrase"[^>]*data-author="class_teacher"/);
  assert.doesNotMatch(html, /data-author="principal"[^>]*data-action="phrase"/);
});

// -- the conduct grid --------------------------------------------------------

test("no switched-on group means no conduct section at all", () => {
  const html = states.child(asTeacher({ sections: [] }));

  assert.doesNotMatch(html, /Conduct/);
});

test("a principal sees the grid read-only, and is told why", () => {
  // Two different reasons for an absent grid: the school does not print
  // conduct, or this login is not the class teacher. They are not one sentence.
  const html = states.child(asTeacher({ may_rate: false }));

  assert.match(html, /Conduct/);
  assert.doesNotMatch(html, /<select/);
  assert.match(html, /rated by the teacher answerable for the class/);
});

test("a rated trait shows its score and an unrated one does not invent zero", () => {
  const rated = states.child(asTeacher({
    sections: [{ group: "affective", group_label: "Affective", traits: [{ trait_id: 9, name: "Punctuality", score: 4 }] }],
  }));

  assert.match(rated, /<option value="4" selected>/);
  assert.doesNotMatch(states.child(asTeacher()), /<option value="[45]" selected>/);
});

// -- locked ------------------------------------------------------------------

test("a locked card is read-only before anybody types", () => {
  // The marking sheet's lesson: a screen that learns from the refusal after
  // the paragraph is written tells her at the worst possible moment.
  const html = states.child(asTeacher({ locked: true, locked_reason: "JSS 1A — First term is submitted by teacher." }));

  assert.doesNotMatch(html, /<textarea/);
  assert.doesNotMatch(html, /<select/);
  assert.match(html, /submitted by teacher/);
});

test("a 423 from a save takes the whole screen read-only", () => {
  // Nothing the page can reload reopens a term that has left draft, so
  // retrying one box is a loop that never terminates.
  const after = applySave(fromChild({ ok: true, body: asTeacher() }), TEACHER, {
    ok: false,
    outcome: SAVE.LOCKED,
    body: { detail: "JSS 1A — First term has been released to parents." },
  });

  assert.equal(after.locked, true);
  assert.match(htmlFor(after), /released to parents/);
});

test("a rejected remark keeps what was typed", () => {
  // Clearing it would throw away the only copy of the sentence just written.
  const after = applySave(fromChild({ ok: true, body: asTeacher() }), TEACHER, {
    ok: false,
    outcome: SAVE.REJECTED,
    body: { detail: "A remark cannot be blank." },
  });

  assert.equal(after.locked, false);
  assert.match(htmlFor(after), /cannot be blank/);
  assert.match(htmlFor(after), /<textarea/);
});

// -- the round trips ---------------------------------------------------------

test("saving sends what is in the box", async () => {
  forgetToken();
  const sent = [];
  const root = fakeRoot({ class: "11" });
  await mount(root, {
    classGroupId: 11,
    fetchImpl: serve([
      ["/api/results/comments/1/class_teacher/", (o) => {
        sent.push(JSON.parse(o.body));
        return { status: 200, body: { detail: "Saved." } };
      }],
      ["/api/results/comments/1/", { status: 200, body: asTeacher() }],
      ["/api/results/comments/?", { status: 200, body: CLASS }],
    ]),
  });

  await root.click({ "data-action": "open", "data-child": "1" });
  root.type('[data-author="class_teacher"]', "A steady term, well handled.");
  await root.click({ "data-action": "save", "data-author": "class_teacher" });

  assert.deepEqual(sent, [{ body: "A steady term, well handled." }]);
});

test("a phrase fills the box and leaves it editable", async () => {
  forgetToken();
  const root = fakeRoot({ class: "11" });
  await mount(root, {
    classGroupId: 11,
    fetchImpl: serve([
      ["/api/results/comments/1/", { status: 200, body: asTeacher() }],
      ["/api/results/comments/?", { status: 200, body: CLASS }],
    ]),
  });

  await root.click({ "data-action": "open", "data-child": "1" });
  await root.click({ "data-action": "phrase", "data-author": "class_teacher", "data-text": "A steady term." });

  assert.match(root.innerHTML, /<textarea[^>]*data-author="class_teacher"/);
  assert.match(root.innerHTML, /A steady term\./);
});

test("choosing a score saves it, and an empty choice saves nothing", async () => {
  // An emptied select is "no score yet"; clearing a rating is a different
  // route, and sending 0 would record a score nobody gave.
  forgetToken();
  const sent = [];
  const root = fakeRoot({ class: "11" });
  await mount(root, {
    classGroupId: 11,
    fetchImpl: serve([
      ["/api/results/ratings/", (o) => {
        sent.push(JSON.parse(o.body));
        return { status: 200, body: { detail: "Saved." } };
      }],
      ["/api/results/comments/1/", { status: 200, body: asTeacher() }],
      ["/api/results/comments/?", { status: 200, body: CLASS }],
    ]),
  });

  await root.click({ "data-action": "open", "data-child": "1" });
  await root.change({ "data-trait": "9" }, "4");
  await root.change({ "data-trait": "9" }, "   ");

  assert.deepEqual(sent, [{ score: 4 }]);
});

test("the class list says who is still outstanding", () => {
  const html = states.classList(CLASS);

  assert.match(html, /Ada Obi/);
  assert.match(html, /2 still to write/);
  assert.match(html, /Both written/);
});

// -- refusals and hosts ------------------------------------------------------

test("403 and 404 are different page-level refusals", () => {
  assert.equal(refusalFor(403, {}), REFUSAL.NOT_A_SIGNATORY);
  assert.equal(refusalFor(404, {}), REFUSAL.WRONG_HOST);
});

test("only answers that prove a session carry a sign-out button", () => {
  assert.ok(provesASession({ ok: false, refusal: REFUSAL.NOT_A_SIGNATORY }));
  assert.ok(!provesASession({ ok: false, refusal: REFUSAL.WRONG_HOST }));
});

test("the refusal a bursar reads does not offer her the staff door", () => {
  const html = states.notASignatory({ detail: "A card is signed by…" });

  assert.doesNotMatch(html, /staff-sign-in/);
  assert.match(html, /school office/i);
});

test("on the portal the page says where the work is", async () => {
  const root = fakeRoot({ portal: "portal.example.test", class: "11" });
  await mount(root, {
    classGroupId: 11,
    fetchImpl: serve([["/api/results/comments/?", { status: 404, body: { detail: "No results on this host." } }]]),
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

test("with no portal domain there is a sentence and no link", () => {
  const html = htmlFor({ step: REFUSAL.SIGNED_OUT }, { portal: "" });

  assert.doesNotMatch(html, /<a /);
  assert.match(html, /go back to the sign-in page/i);
});

test("a remark typed by a teacher cannot execute in a principal's browser", () => {
  const html = states.child(
    asTeacher({
      remarks: [
        { author: TEACHER, author_label: "Class teacher", body: '<img src=x onerror="alert(1)">', may_edit: false },
      ],
    }),
  );

  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
});
