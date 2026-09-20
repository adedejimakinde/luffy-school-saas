/**
 * The sign-in flow, including the step a household sharing a handset needs.
 *
 * `advance()` is a pure (state, answer) -> state function, so the whole flow is
 * testable without a browser: the tests below walk a parent all the way in,
 * through the 202 and out the other side, and assert what is on the page at
 * each stop.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { advance, destination, htmlFor, initialState } from "../../static/signin/app.js";
import * as steps from "../../static/signin/states.js";

const CODE_SENT = { status: 200, body: { detail: "If that number is on a guardian record, a code is on its way." } };
const ONE_SCHOOL = {
  status: 200,
  body: {
    full_name: "Mama Ada",
    schools: [{ slug: "st-marys", name: "St Mary's", host: "st-marys.example.test" }],
    csrf_token: "t",
  },
};
const TWO_SCHOOLS = {
  status: 200,
  body: {
    full_name: "Mama Ada",
    schools: [
      { slug: "st-marys", name: "St Mary's", host: "st-marys.example.test" },
      { slug: "grace", name: "Grace Academy", host: "grace.example.test" },
    ],
    csrf_token: "t",
  },
};
const SHARED_HANDSET = {
  status: 202,
  body: {
    detail: "This number is shared by more than one guardian.",
    choose: [
      { guardian: "3f1c-aaa", full_name: "Mama Ada" },
      { guardian: "9b2d-bbb", full_name: "Papa Ada" },
    ],
  },
};

/** A parent who has typed a number and asked for a code. */
function atTheCodeStep() {
  return advance({ ...initialState(), value: "08031234567" }, CODE_SENT);
}

test("asking for a code moves to the code step and never promises delivery", () => {
  const state = atTheCodeStep();
  assert.equal(state.step, "code");
  const html = htmlFor(state);
  // The API answers identically for every value typed so that a stranger
  // cannot learn whose number is on a guardian record. A page that said "we
  // have sent you a code" would put that oracle back.
  assert.doesNotMatch(html, /we have sent|we've sent|check your (phone|messages)/i);
  assert.match(html, /if that number is on a guardian record/i);
});

test("one school goes straight to that school's host", () => {
  const state = advance(atTheCodeStep(), ONE_SCHOOL);
  assert.equal(state.step, "leaving");
  assert.equal(destination(state), "//st-marys.example.test/cards/");
  // Protocol-relative, so a development deployment on http is not sent to an
  // https URL it cannot serve.
  assert.doesNotMatch(destination(state), /^https?:/);
});

test("more than one school asks which, on the portal", () => {
  const state = advance(atTheCodeStep(), TWO_SCHOOLS);
  assert.equal(state.step, "schools");
  assert.equal(destination(state), null, "nobody is redirected with two options");
  const html = htmlFor(state);
  assert.match(html, /St Mary&#39;s/);
  assert.match(html, /Grace Academy/);
  assert.match(html, /\/\/st-marys\.example\.test\/cards\//);
  assert.match(html, /\/\/grace\.example\.test\/cards\//);
});

test("a shared handset asks whose card this is, and keeps the code", () => {
  // The step this flow would be broken without: the code proved the handset,
  // not the person, and the pick goes back to the same route with the same
  // code. Dropping the code here is what leaves a household stuck half-way in.
  const state = advance(atTheCodeStep(), SHARED_HANDSET);

  assert.equal(state.step, "whose");
  assert.equal(state.value, "08031234567", "the number is still held");
  assert.equal(state.code, "", "the code typed at the previous step");
  const html = htmlFor(state);
  assert.match(html, /Mama Ada/);
  assert.match(html, /Papa Ada/);
  assert.match(html, /data-guardian="3f1c-aaa"/);
  assert.match(html, /data-guardian="9b2d-bbb"/);
});

test("the code survives the 202 when it was actually typed", () => {
  const typed = { ...atTheCodeStep(), code: "123456" };
  const state = advance(typed, SHARED_HANDSET);
  assert.equal(state.code, "123456", "the pick has no code to send without this");
});

test("picking a guardian on a shared handset signs that guardian in", () => {
  const picked = advance({ ...atTheCodeStep(), code: "123456", step: "whose" }, ONE_SCHOOL);
  assert.equal(picked.step, "leaving");
  assert.equal(destination(picked), "//st-marys.example.test/cards/");
});

test("a bad code leaves the parent on the code step with the sentence", () => {
  const state = advance(
    { ...atTheCodeStep(), code: "000000" },
    { status: 401, body: { detail: "That code is wrong or has expired.", code: "bad_code", retryable: false } },
  );
  assert.equal(state.step, "code");
  assert.equal(state.code, "", "the wrong code is cleared from the field");
  assert.match(htmlFor(state), /wrong or has expired/);
  // Never the programmer's string.
  assert.doesNotMatch(htmlFor(state), /bad_code/);
});

test("too many tries says how long to wait, in a unit a person reads", () => {
  const soon = advance(atTheCodeStep(), {
    status: 429,
    body: { detail: "Too many attempts.", code: "too_many_attempts", retry_after: 45 },
  });
  assert.equal(soon.step, "throttled");
  assert.match(htmlFor(soon), /about 45 seconds/);

  const later = advance(atTheCodeStep(), {
    status: 429,
    body: { detail: "Too many attempts.", retry_after: 900 },
  });
  assert.match(htmlFor(later), /about 15 minutes/);
});

test("signed in with no school says so without offering a link it cannot honour", () => {
  const state = advance(atTheCodeStep(), {
    status: 200,
    body: { full_name: "Mama Ada", schools: [], csrf_token: "t" },
  });
  assert.equal(state.step, "nowhere");
  const html = htmlFor(state);
  assert.match(html, /no schools on this account/i);
  assert.doesNotMatch(html, /<a /, "no link, because there is nowhere to send them");
});

test("a school with no host is named but not linked", () => {
  const html = steps.schools({
    full_name: "Mama Ada",
    schools: [
      { slug: "st-marys", name: "St Mary's", host: "st-marys.example.test" },
      { slug: "grace", name: "Grace Academy", host: null },
    ],
  });
  assert.match(html, /\/\/st-marys\.example\.test\/cards\//);
  assert.match(html, /Grace Academy/);
  assert.doesNotMatch(html, /href="\/\/null/, "a null host must not become a link");
  assert.match(html, /no web address/i);
});

test("a 500 or a dead transport is the broken page, not a blank one", () => {
  assert.equal(advance(atTheCodeStep(), { status: 500, body: {} }).step, "broken");
  assert.equal(advance(atTheCodeStep(), { status: 0, body: {} }).step, "broken");
  assert.match(htmlFor({ step: "broken" }), /not working/i);
});

test("a guardian's name cannot execute in another guardian's browser", () => {
  // `full_name` is typed by whoever created the account, and on a shared
  // handset one guardian's name is rendered into the other's page.
  const html = steps.whose({
    detail: "shared",
    choose: [{ guardian: "x", full_name: '<img src=x onerror="alert(1)">' }],
  });
  assert.doesNotMatch(html, /<img src=x/);
  assert.match(html, /&lt;img/);
});

test("every step renders something a reader can act on", () => {
  for (const step of ["ask", "code", "whose", "schools", "nowhere", "throttled", "broken"]) {
    const html = htmlFor({ step, body: { choose: [], schools: [] } });
    assert.match(html, /<h1>/, `${step} has no heading`);
    assert.ok(html.length > 80, `${step} renders almost nothing`);
  }
});
