/**
 * The marking screen: save on blur, one mark per request.
 *
 * Every state is a pure function of an API body, so the flow is walked here
 * without a browser. What it walks is `gradebook/api.py`'s actual answer set:
 * a 200 carrying the new version and total, a 409 carrying somebody else's
 * value, a 423, a 422, and a 401 that is two states.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { applySave, fromSheet, fromWhere, htmlFor, mount } from "../../static/marking/app.js";
import { REFUSAL, SAVE, refusalFor, provesASession } from "../../static/marking/api.js";
import * as states from "../../static/marking/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const WHERE = {
  term_id: 7,
  term: "2025/2026 First term",
  assessments: [{ id: 3, name: "First CA", subject: "Mathematics", max_score: 20 }],
  classes: [{ id: 11, name: "JSS 1A", level: 1 }],
};

const SHEET = {
  assessment_id: 3,
  assessment: "First CA",
  subject: "Mathematics",
  term: "2025/2026 First term",
  class_group_id: 11,
  class_group: "JSS 1A",
  max_score: 20,
  locked: false,
  locked_reason: null,
  rows: [
    { student_membership_id: 1, student: "Ada Obi", value: null, version: null, max_score: 20, total: { scored: 0, available: 0, marked: 0 } },
    { student_membership_id: 2, student: "Emeka Nwosu", value: 12, version: 4, max_score: 20, total: { scored: 12, available: 20, marked: 1 } },
  ],
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

const state = () => fromSheet({ ok: true, body: SHEET });

// -- the refusals are not one refusal ---------------------------------------

test("403 and 404 are different answers with different remedies", () => {
  assert.equal(refusalFor(403, {}), REFUSAL.NOT_A_MARKER);
  assert.equal(refusalFor(404, {}), REFUSAL.WRONG_HOST);
});

test("only answers that prove a session carry a sign-out button", () => {
  // The 403 is reached only after `session_auth` identified the caller. The
  // 404 is raised by `_school_of()` before any authority question, so it says
  // nothing about the cookie.
  assert.ok(provesASession({ ok: false, refusal: REFUSAL.NOT_A_MARKER }));
  assert.ok(!provesASession({ ok: false, refusal: REFUSAL.WRONG_HOST }));
});

test("the refusal a bursar reads does not offer her the staff door", () => {
  const html = states.notAMarker({ detail: "Marking is done by a teacher." });

  assert.doesNotMatch(html, /staff-sign-in/);
  assert.match(html, /school office/i);
});

// -- nought is a mark --------------------------------------------------------

test("a mark of 0 is drawn, and an unmarked cell is not", () => {
  // Truthiness cannot tell these apart, and a cell rendered `value || ""`
  // would print nothing for a child who scored nought.
  const html = states.sheet({
    ...SHEET,
    rows: [
      { student_membership_id: 1, student: "Ada Obi", value: 0, version: 2, max_score: 20, total: { scored: 0, available: 20, marked: 1 } },
      { student_membership_id: 2, student: "Emeka Nwosu", value: null, version: null, max_score: 20, total: { scored: 0, available: 0, marked: 0 } },
    ],
  });

  assert.match(html, /id="mark-1"[^>]*value="0"/);
  assert.match(html, /id="mark-2"[^>]*value=""/);
});

test("an unmarked cell carries no version, so the next save is an insert", () => {
  // Empty, not `0`: null is what tells `set_score()` this must be an insert,
  // and `0` would be a version claim about a row that does not exist.
  const html = states.sheet(SHEET);

  assert.match(html, /id="mark-1"[^>]*data-version=""/);
  assert.match(html, /id="mark-2"[^>]*data-version="4"/);
});

// -- the locked sheet --------------------------------------------------------

test("a locked sheet disables every cell before anybody types", () => {
  // The whole reason the flag is on the payload. Without it a teacher types a
  // mark into a cell that cannot accept it and learns from the 423 after.
  const html = states.sheet({
    ...SHEET,
    locked: true,
    locked_reason: "JSS 1A — 2025/2026 First term is submitted by teacher.",
  });

  assert.match(html, /id="mark-1"[^>]*disabled/);
  assert.match(html, /id="mark-2"[^>]*disabled/);
  assert.match(html, /submitted by teacher/);
});

test("a 423 from a save locks the whole sheet, not the one cell", () => {
  // Nothing the page can reload reopens a term, so retrying one cell is a loop
  // that never terminates.
  const after = applySave(state(), 1, {
    ok: false,
    outcome: SAVE.LOCKED,
    body: { detail: "JSS 1A — First term has been released to parents." },
  });

  assert.equal(after.locked, true);
  assert.match(htmlFor(after), /released to parents/);
});

// -- the conflict ------------------------------------------------------------

test("a conflict names the other person's value, not merely that it moved", () => {
  // "Somebody changed this" is not useful to a teacher; "saved as 17" is.
  const after = applySave(state(), 2, {
    ok: false,
    outcome: SAVE.CONFLICT,
    body: {
      detail: "That mark changed while you were typing.",
      current: { student_membership_id: 2, value: 17, version: 5, max_score: 20, total: { scored: 17, available: 20, marked: 1 } },
    },
  });

  const html = htmlFor(after);
  assert.match(html, /Saved as 17 by somebody else/);
  // Redrawn to *their* version, so the teacher's next save is a deliberate
  // overwrite rather than a second conflict.
  assert.match(html, /id="mark-2"[^>]*value="17"/);
  assert.match(html, /id="mark-2"[^>]*data-version="5"/);
});

test("a conflict whose current is null says cleared, not a new number", () => {
  // A real outcome and a different one: the mark was taken back while this one
  // was being typed.
  const after = applySave(state(), 2, {
    ok: false,
    outcome: SAVE.CONFLICT,
    body: { detail: "That mark changed.", current: null },
  });

  const html = htmlFor(after);
  assert.match(html, /cleared this mark/i);
  assert.match(html, /id="mark-2"[^>]*value=""/);
  assert.match(html, /id="mark-2"[^>]*data-version=""/);
});

test("a rejected number is kept so it can be corrected", () => {
  // Clearing it would throw away the only copy of what the teacher typed.
  const after = applySave(state(), 1, {
    ok: false,
    outcome: SAVE.INVALID,
    body: { detail: "A mark cannot be more than 20." },
  });

  assert.match(htmlFor(after), /cannot be more than 20/);
  assert.equal(after.locked, false, "an invalid number closed the sheet");
});

test("a save that worked clears the note it is replacing", () => {
  const conflicted = applySave(state(), 2, {
    ok: false,
    outcome: SAVE.CONFLICT,
    body: { detail: "moved", current: { student_membership_id: 2, value: 17, version: 5, max_score: 20, total: { scored: 17, available: 20, marked: 1 } } },
  });

  const fixed = applySave(conflicted, 2, {
    ok: true,
    cell: { student_membership_id: 2, value: 19, version: 6, max_score: 20, total: { scored: 19, available: 20, marked: 1 } },
  });

  assert.doesNotMatch(htmlFor(fixed), /somebody else/);
  assert.match(htmlFor(fixed), /id="mark-2"[^>]*value="19"/);
});

// -- the blur is the save ----------------------------------------------------

test("blurring a cell saves it, with the version it was drawn with", async () => {
  forgetToken();
  const sent = [];
  const root = fakeRoot({ portal: "portal.example.test" });
  await mount(root, {
    fetchImpl: serve([
      ["/api/gradebook/where/", { status: 200, body: WHERE }],
      ["/sheet/", { status: 200, body: SHEET }],
      [
        "/scores/",
        (options) => {
          sent.push(JSON.parse(options.body));
          return {
            status: 200,
            body: { student_membership_id: 2, value: 15, version: 5, max_score: 20, total: { scored: 15, available: 20, marked: 1 } },
          };
        },
      ],
    ]),
  });

  await root.click({ "data-action": "pick-assessment", "data-assessment": "3" });
  await root.click({ "data-action": "pick-class", "data-class": "11" });
  await root.blur({ "data-child": "2", "data-version": "4" }, "15");

  assert.deepEqual(sent, [{ value: 15, expected_version: 4 }]);
  // Redrawn from the response, not from a local guess: the total is the
  // server's sum and a page that recomputed it would be a second implementation
  // free to disagree.
  assert.match(root.innerHTML, /id="mark-2"[^>]*value="15"/);
  assert.match(root.innerHTML, /id="mark-2"[^>]*data-version="5"/);
});

test("an unmarked cell sends a null version, which the server reads as an insert", async () => {
  forgetToken();
  const sent = [];
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/api/gradebook/where/", { status: 200, body: WHERE }],
      ["/sheet/", { status: 200, body: SHEET }],
      ["/scores/", (options) => {
        sent.push(JSON.parse(options.body));
        return { status: 200, body: { student_membership_id: 1, value: 8, version: 1, max_score: 20, total: { scored: 8, available: 20, marked: 1 } } };
      }],
    ]),
  });

  await root.click({ "data-action": "pick-assessment", "data-assessment": "3" });
  await root.click({ "data-action": "pick-class", "data-class": "11" });
  await root.blur({ "data-child": "1", "data-version": "" }, "8");

  assert.deepEqual(sent, [{ value: 8, expected_version: null }]);
});

test("blurring an emptied cell saves nothing", async () => {
  // An emptied cell is not a mark of nought, and unmarking is a different
  // route. Sending 0 here would record a score nobody gave.
  forgetToken();
  const sent = [];
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/api/gradebook/where/", { status: 200, body: WHERE }],
      ["/sheet/", { status: 200, body: SHEET }],
      ["/scores/", (options) => { sent.push(JSON.parse(options.body)); return { status: 200, body: {} }; }],
    ]),
  });

  await root.click({ "data-action": "pick-assessment", "data-assessment": "3" });
  await root.click({ "data-action": "pick-class", "data-class": "11" });
  await root.blur({ "data-child": "1", "data-version": "" }, "   ");

  assert.deepEqual(sent, [], "an empty cell was sent as a mark");
});

test("blurring a cell on a locked sheet sends nothing", async () => {
  forgetToken();
  const sent = [];
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/api/gradebook/where/", { status: 200, body: WHERE }],
      ["/sheet/", { status: 200, body: { ...SHEET, locked: true, locked_reason: "submitted" } }],
      ["/scores/", (options) => { sent.push(JSON.parse(options.body)); return { status: 200, body: {} }; }],
    ]),
  });

  await root.click({ "data-action": "pick-assessment", "data-assessment": "3" });
  await root.click({ "data-action": "pick-class", "data-class": "11" });
  await root.blur({ "data-child": "1", "data-version": "" }, "8");

  assert.deepEqual(sent, [], "a locked sheet accepted a write");
});

// -- no current term, and the hosts -----------------------------------------

test("no current term is its own screen, not a refusal and not a guess", () => {
  const s = fromWhere({ ok: true, body: { term_id: null, term: null, assessments: [], classes: [] } });

  assert.equal(s.step, "no-term");
  assert.match(htmlFor(s), /No term is open/);
});

test("on the portal the page says where the work is", async () => {
  const root = fakeRoot({ portal: "portal.example.test" });
  await mount(root, {
    fetchImpl: serve([["/api/gradebook/where/", { status: 404, body: { detail: "No gradebook on this host." } }]]),
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

test("a school name typed into the admin cannot execute in a teacher's browser", () => {
  const html = states.sheet({ ...SHEET, class_group: '<img src=x onerror="alert(1)">' });

  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
});
