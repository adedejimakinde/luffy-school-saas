/**
 * The result checker page: docs/messaging.md D11.
 *
 * A form, one POST, and five answers. The card and the withheld refusal are
 * drawn by the card page's own modules, so what is asserted about them here is
 * that they are reached, not how they look — `card_render.test.js` and
 * `card_states.test.js` own that.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { ANSWER, answerFor, check, checkUrl } from "../../static/checker/api.js";
import { EMPTY, afterAnswer, htmlFor, mount } from "../../static/checker/app.js";
import * as states from "../../static/checker/states.js";
import { fakeRoot } from "./fake_dom.js";

const NOT_OPENED =
  "That admission number and PIN do not open a report card here. Check both against the slip and try again.";
const WAIT = "Too many wrong tries. Wait a few minutes and try again. Nothing has been locked.";

/** The smallest payload `card/render.js` draws without complaint. */
const CARD = {
  school_name: "St Mary's",
  student_name: "Ada Obi",
  class_group_name: "JSS 1A",
  academic_session: "2025/2026",
  term_name: "first",
  term_label: "First term",
  term_id: 3,
  version: 1,
  is_revised: false,
  total_scored: 0,
  total_available: 0,
  own_average: null,
  days_present: null,
  days_absent: null,
  days_open: null,
  attendance: { state: "not_kept" },
  subjects: [],
  columns: [],
  sections: [],
  comments: [],
};

const HELD = {
  school_name: "St Mary's",
  contact: "The bursar, 0803 000 0000",
  detail: "St Mary's is holding this report card.",
};

/** A fetch that answers once with `status`/`body`, and records what it was asked. */
function answering(status, body, calls = []) {
  return async (url, options = {}) => {
    calls.push({ url, ...options });
    return { status, json: async () => body };
  };
}

// -- the request -------------------------------------------------------------

test("each status is its own answer", () => {
  assert.equal(answerFor(200, CARD), ANSWER.CARD);
  assert.equal(answerFor(403, HELD), ANSWER.WITHHELD);
  assert.equal(answerFor(404, { detail: NOT_OPENED }), ANSWER.NOT_OPENED);
  assert.equal(answerFor(429, { detail: WAIT, retry_after: 180 }), ANSWER.WAIT);
  assert.equal(answerFor(500, null), ANSWER.BROKEN);
  assert.equal(answerFor(401, {}), ANSWER.BROKEN, "the route has no session to lapse");
  assert.equal(answerFor(200, null), ANSWER.BROKEN, "a 200 with no card is not a card");
});

test("the number and the PIN go in a POST body, and the PIN is never in the URL", async () => {
  const calls = [];
  await check({ admissionNumber: "SM/001", pin: "1234 5678 9012", fetchImpl: answering(200, CARD, calls) });

  assert.equal(calls.length, 1);
  const [call] = calls;
  assert.equal(call.url, checkUrl());
  assert.equal(call.url, "/api/results/check/");
  assert.equal(call.method, "POST");
  assert.deepEqual(JSON.parse(call.body), { admission_number: "SM/001", pin: "1234 5678 9012" });
  assert.doesNotMatch(call.url, /1234|5678|9012|SM/);
});

test("no cookie goes with it, so no session and no CSRF token are part of the check", async () => {
  const calls = [];
  await check({ admissionNumber: "SM/001", pin: "123456789012", fetchImpl: answering(404, { detail: NOT_OPENED }, calls) });

  assert.equal(calls[0].credentials, "omit");
  assert.equal(calls.length, 1, "nothing was fetched first, such as /api/csrf/");
  assert.equal(calls[0].headers["X-CSRFToken"], undefined);
});

test("a dead transport or an unreadable body is broken, not a refusal", async () => {
  const dead = async () => {
    throw new TypeError("Failed to fetch");
  };
  assert.deepEqual(await check({ pin: "1", fetchImpl: dead }), { kind: ANSWER.BROKEN, body: {} });

  const garbled = async () => ({ status: 502, json: async () => JSON.parse("<html>") });
  assert.equal((await check({ pin: "1", fetchImpl: garbled })).kind, ANSWER.BROKEN);
});

// -- what the page says --------------------------------------------------------

test("the form asks for the admission number and a PIN typed on a number pad", () => {
  const html = htmlFor(EMPTY);

  assert.match(html, /name="admission_number"/);
  assert.match(html, /<input id="pin" name="pin" inputmode="numeric" autocomplete="off"/);
  assert.doesNotMatch(html, /type="number"/, "a number input would drop the spaces the slip prints");
  assert.match(html, /<button type="submit">Open the report card<\/button>/);
  assert.doesNotMatch(html, /role="alert"/, "an empty form has nothing to report");
});

test("the one refusal is the server's sentence, and the number is kept while the PIN box is empty", () => {
  const state = afterAnswer("SM/001", { kind: ANSWER.NOT_OPENED, body: { detail: NOT_OPENED } });
  const html = htmlFor(state);

  assert.equal(state.step, "form");
  assert.match(html, /role="alert">That admission number and PIN do not open a report card here\./);
  assert.match(html, /name="admission_number"[^>]*value="SM\/001"/);
  assert.doesNotMatch(html, /<input id="pin"[^>]*value=/, "a PIN was left in the box");
});

test("the refusal adds no guess about which half was wrong", () => {
  const html = htmlFor(afterAnswer("SM/001", { kind: ANSWER.NOT_OPENED, body: { detail: NOT_OPENED } }));

  assert.doesNotMatch(html, /admission number is wrong|PIN is wrong|no such|not found/i);
});

test("a wait says how long, and that nothing is locked", () => {
  const html = htmlFor(afterAnswer("SM/001", { kind: ANSWER.WAIT, body: { detail: WAIT, retry_after: 180 } }));

  assert.match(html, /Too many wrong tries\./);
  assert.match(html, /Nothing has been locked\./);
  assert.match(html, /Try again in about 3 minutes\./);
});

test("a wait with no retry_after invents no number", () => {
  const html = htmlFor(afterAnswer("SM/001", { kind: ANSWER.WAIT, body: { detail: WAIT } }));

  assert.match(html, /Nothing has been locked\./);
  assert.doesNotMatch(html, /Try again in/);
});

test("broken says nothing was checked, and the form is still there to try again", () => {
  const html = htmlFor(afterAnswer("SM/001", { kind: ANSWER.BROKEN, body: {} }));

  assert.match(html, /nothing was checked/);
  assert.match(html, /name="pin"/);
});

test("the card is the card page's renderer, with a way back to the form", () => {
  const html = htmlFor(afterAnswer("SM/001", { kind: ANSWER.CARD, body: CARD }));

  assert.match(html, /Ada Obi/);
  assert.match(html, /data-action="check-another"/);
  assert.doesNotMatch(html, /name="pin"/, "the form stayed up under the card");
});

test("a withheld card names who to contact, as the card page does", () => {
  const html = htmlFor(afterAnswer("SM/001", { kind: ANSWER.WITHHELD, body: HELD }));

  assert.match(html, /This card is being held/);
  assert.match(html, /The bursar, 0803 000 0000/);
  assert.match(html, /data-action="check-another"/);
});

test("the admission number is escaped back into the form", () => {
  const html = states.form({ admissionNumber: '"><script>x</script>' });

  assert.doesNotMatch(html, /<script>x/);
  assert.match(html, /value="&quot;&gt;&lt;script&gt;/);
});

test("a family with an account is pointed at sign-in, and only where there is a portal to point at", () => {
  assert.match(states.form({ portal: "classnode.test" }), /<a href="\/\/classnode\.test\/sign-in\/">Sign in<\/a>/);
  assert.doesNotMatch(states.form({ portal: "" }), /sign-in/);
});

// -- the page, driven ----------------------------------------------------------

test("a wrong answer redraws the form with the refusal; a right one draws the card; another clears it", async () => {
  const calls = [];
  let right = false;
  const root = fakeRoot({ portal: "" });
  mount(root, {
    fetchImpl: async (url, options) => {
      calls.push({ url, ...options });
      return right
        ? { status: 200, json: async () => CARD }
        : { status: 404, json: async () => ({ detail: NOT_OPENED }) };
    },
  });
  assert.equal(root.dataset.state, "form");

  await root.submit({ admission_number: "SM/001", pin: "0000 0000 0000" });
  assert.equal(root.dataset.state, "form");
  assert.match(root.innerHTML, /do not open a report card here/);
  assert.match(root.innerHTML, /value="SM\/001"/);

  right = true;
  await root.submit({ admission_number: "SM/001", pin: "1234 5678 9012" });
  assert.equal(root.dataset.state, "card");
  assert.match(root.innerHTML, /Ada Obi/);
  assert.equal(calls.length, 2);
  assert.ok(calls.every((call) => call.url === "/api/results/check/"));

  await root.click({ "data-action": "check-another" });
  assert.equal(root.dataset.state, "form");
  assert.doesNotMatch(root.innerHTML, /Ada Obi/, "the card outlived Check another");
  assert.doesNotMatch(root.innerHTML, /value="SM\/001"/, "the last family's number is still in the box");
});

test("the submit is the page's, not the browser's: it does not navigate", async () => {
  const root = fakeRoot({});
  mount(root, { fetchImpl: answering(404, { detail: NOT_OPENED }) });

  const prevented = await root.submit({ admission_number: "SM/001", pin: "1" });

  assert.equal(prevented, true);
});
