/**
 * The approval chain page: one row per class, one step at a time.
 *
 * Every state is a pure function of an API body, so the flow is walked without
 * a browser. What it walks is `results/chain_api.py`'s answer set: a 200
 * carrying the row as it now stands, a 409 with the step somebody already
 * took, a 409 without one, a 422, a 403, and a 401 that is two states.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { applyStep, fromChain, htmlFor, mount } from "../../static/results/app.js";
import { REFUSAL, STEP, refusalFor, provesASession } from "../../static/results/api.js";
import * as states from "../../static/results/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const row = (over = {}) => ({
  class_group_id: 11,
  class_group: "JSS 1A",
  sheet_id: 5,
  state: "draft",
  state_label: "Draft",
  may_submit: false,
  may_check: false,
  may_approve: false,
  may_release: false,
  may_send_back: false,
  ...over,
});

const CHAIN = {
  term_id: 7,
  term: "2025/2026 First term",
  rows: [row({ may_submit: true }), row({ class_group_id: 12, class_group: "JSS 1B" })],
};

const state = () => fromChain({ ok: true, body: CHAIN });

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

// -- the buttons come from the payload, never from a role --------------------

test("each role sees only the step it may take", () => {
  // The booleans come from `chain_api._actions()`, computed from the same sets
  // `services` enforces. A page that worked out for itself who may approve
  // would be a third opinion on one rule.
  const teacher = states.chain({ rows: [row({ may_submit: true })] });
  assert.match(teacher, /data-step="submit"/);
  assert.doesNotMatch(teacher, /data-step="approve"/);

  const vp = states.chain({ rows: [row({ state: "submitted", may_check: true, may_send_back: true })] });
  assert.match(vp, /data-step="check"/);
  assert.match(vp, /data-action="ask-send-back"/);
  assert.doesNotMatch(vp, /data-step="approve"/);

  const head = states.chain({ rows: [row({ state: "checked", may_approve: true })] });
  assert.match(head, /data-step="approve"/);
  assert.doesNotMatch(head, /data-step="check"/);
});

test("a row this login cannot act on is still listed, and says so", () => {
  // Her own school's progress, not somebody's results — the row carries no
  // mark, no name and no number. Hiding it makes an empty list ambiguous.
  const html = states.chain({ rows: [row({ class_group: "JSS 3B", state: "submitted", state_label: "Submitted by teacher" })] });

  assert.match(html, /JSS 3B/);
  assert.match(html, /Submitted by teacher/);
  assert.match(html, /Nothing for you here/);
  assert.doesNotMatch(html, /<button[^>]*data-step=/);
});

test("a released row offers nothing and says why", () => {
  // Release is final: a wrong card is corrected by reissuing it, not by moving
  // the sheet back. An empty row would read as a page that failed to draw.
  const html = states.chain({ rows: [row({ state: "released", state_label: "Released to parents" })] });

  assert.match(html, /Released — nothing further/);
  assert.doesNotMatch(html, /<button[^>]*data-step=/);
});

// -- the four refusals are four sentences ------------------------------------

test("already-signed names the step this person took", () => {
  // "You may not check this" is not a sentence somebody can act on.
  const { state: after, reload } = applyStep(state(), 11, {
    ok: false,
    outcome: STEP.ALREADY_SIGNED,
    body: {
      detail: "Kemi Bello already moved this sheet from draft to submitted on this pass.",
      existing: { from_state: "draft", to_state: "submitted", actor_id: 3, at: "2025-11-01T09:00:00" },
    },
  });

  assert.equal(reload, false);
  assert.match(htmlFor(after), /already moved this sheet from draft to submitted/);
});

test("a sheet that moved under you reloads the list", () => {
  // Leaving the old buttons up offers a step that will fail for the same
  // reason a second time.
  const { reload } = applyStep(state(), 11, {
    ok: false,
    outcome: STEP.MOVED,
    body: { detail: "This sheet is submitted, not draft." },
  });

  assert.equal(reload, true);
});

test("a send-back with nothing in it keeps the box open", () => {
  // What is missing is the sentence. Closing the form would make them find the
  // class again to type it.
  const { state: after } = applyStep(state(), 11, {
    ok: false,
    outcome: STEP.NEEDS_A_REASON,
    body: { detail: "A send-back has to say what is wrong." },
  });

  assert.equal(after.asking, 11);
  assert.match(htmlFor(after), /has to say what is wrong/);
  assert.match(htmlFor(after), /<textarea/);
});

test("not-allowed is its own sentence, and no retry helps", () => {
  const { state: after, reload } = applyStep(state(), 11, {
    ok: false,
    outcome: STEP.NOT_ALLOWED,
    body: { detail: "Results are moved along by the class teacher…" },
  });

  assert.equal(reload, false);
  assert.match(htmlFor(after), /moved along by the class teacher/);
});

test("403 and 404 are different page-level refusals", () => {
  assert.equal(refusalFor(403, {}), REFUSAL.NOT_ON_THE_CHAIN);
  assert.equal(refusalFor(404, {}), REFUSAL.WRONG_HOST);
});

test("only answers that prove a session carry a sign-out button", () => {
  assert.ok(provesASession({ ok: false, refusal: REFUSAL.NOT_ON_THE_CHAIN }));
  assert.ok(!provesASession({ ok: false, refusal: REFUSAL.WRONG_HOST }));
});

test("the refusal a bursar reads does not offer her the staff door", () => {
  const html = states.notOnTheChain({ detail: "Results are moved along by…" });

  assert.doesNotMatch(html, /staff-sign-in/);
  assert.match(html, /school office/i);
});

// -- the step round trip -----------------------------------------------------

test("taking a step redraws that row from the answer, not from a guess", async () => {
  forgetToken();
  const root = fakeRoot({ portal: "portal.example.test" });
  await mount(root, {
    fetchImpl: serve([
      ["/api/results/chain/11/submit/", {
        status: 200,
        body: row({ state: "submitted", state_label: "Submitted by teacher", may_submit: false }),
      }],
      ["/api/results/chain/", { status: 200, body: CHAIN }],
    ]),
  });
  assert.match(root.innerHTML, /data-step="submit"/);

  await root.click({ "data-action": "step", "data-step": "submit", "data-class": "11" });

  assert.match(root.innerHTML, /Submitted by teacher/);
  assert.doesNotMatch(root.innerHTML, /data-step="submit"/, "the button outlived the step");
  // The other row is untouched.
  assert.match(root.innerHTML, /JSS 1B/);
});

test("the send-back box sends what was typed", async () => {
  forgetToken();
  const sent = [];
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/send-back/", (options) => {
        sent.push(JSON.parse(options.body));
        return { status: 200, body: row({ state: "draft", state_label: "Draft", may_submit: true }) };
      }],
      ["/api/results/chain/", {
        status: 200,
        body: { ...CHAIN, rows: [row({ state: "submitted", may_send_back: true })] },
      }],
    ]),
  });

  await root.click({ "data-action": "ask-send-back", "data-class": "11" });
  assert.match(root.innerHTML, /<textarea/);
  await root.submit({ reason: "Ada's maths is transposed." });

  assert.deepEqual(sent, [{ reason: "Ada's maths is transposed." }]);
});

test("an empty send-back is still sent, so the server's sentence is the one shown", async () => {
  // A page that refused first would be a second rule to keep in step with
  // `services.send_back()` and its check constraint.
  forgetToken();
  const sent = [];
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/send-back/", (options) => {
        sent.push(JSON.parse(options.body));
        return { status: 422, body: { detail: "A send-back has to say what is wrong." } };
      }],
      ["/api/results/chain/", {
        status: 200,
        body: { ...CHAIN, rows: [row({ state: "submitted", may_send_back: true })] },
      }],
    ]),
  });

  await root.click({ "data-action": "ask-send-back", "data-class": "11" });
  await root.submit({ reason: "" });

  assert.deepEqual(sent, [{ reason: "" }]);
  assert.match(root.innerHTML, /has to say what is wrong/);
});

// -- no term, the hosts, the session ----------------------------------------

test("no current term is its own screen, not a refusal", () => {
  const s = fromChain({ ok: true, body: { term_id: null, term: null, rows: [] } });

  assert.equal(s.step, "no-term");
  assert.match(htmlFor(s), /No term is open/);
});

test("on the portal the page says where the work is", async () => {
  const root = fakeRoot({ portal: "portal.example.test" });
  await mount(root, {
    fetchImpl: serve([["/api/results/chain/", { status: 404, body: { detail: "No results on this host." } }]]),
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

test("a class name typed into the admin cannot execute in a principal's browser", () => {
  const html = states.chain({ rows: [row({ class_group: '<img src=x onerror="alert(1)">' })] });

  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
});

test("every row links to its class's broadsheet", () => {
  // Whoever is about to approve or release reads the numbers first. The
  // broadsheet route decides who may, as it always did.
  const html = states.chain({
    term: "2025/2026 First term",
    rows: [{ class_group_id: 11, class_group: "JSS 1A", state: "approved", state_label: "Approved" }],
  });

  assert.match(html, /<a class="broadsheet" href="\/broadsheet\/\?class=11">Broadsheet<\/a>/);
});
