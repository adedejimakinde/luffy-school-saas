/**
 * The four states, asserted on the text a parent would actually read.
 *
 * These are the paths nobody demos: a card is withheld, a session lapses, a
 * link is wrong. They are pure functions of the API's own bodies, so they can
 * be tested here with no browser, no DOM and no dependency — which is the whole
 * reason `states.js` holds strings rather than DOM nodes.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import * as states from "../../static/card/states.js";
import { htmlFor } from "../../static/card/app.js";
import { refusalFor, REFUSAL } from "../../static/card/api.js";

const WITHHELD_BODY = {
  school_name: "St Mary's",
  contact: "the bursar, 0803 000 0001",
  detail: "St Mary's is holding this report card. Please get in touch with the school: the bursar, 0803 000 0001",
};

test("a withheld card names the school and how to reach it", () => {
  const html = states.withheld(WITHHELD_BODY);
  assert.match(html, /St Mary&#39;s/, "the school is named");
  assert.match(html, /the bursar, 0803 000 0001/, "the contact is on the page");
  assert.match(html, /state-withheld/);
});

test("the contact survives even when the sentence does not", () => {
  // `detail` is the server's prose and `contact` is the actionable part. A body
  // that arrives without the sentence must still tell a parent where to ring.
  const html = states.withheld({ school_name: "St Mary's", contact: "0803 000 0001" });
  assert.match(html, /0803 000 0001/);
  assert.match(html, /holding this report card/, "there is still a sentence");
});

test("a withheld card carries no balance, no reason and no marks", () => {
  // The API does not send them. This is the assertion that would catch a
  // well-meaning edit that started showing whatever else the body happened to
  // carry — the same structural argument `WithheldOut` makes server-side.
  const html = states.withheld({
    ...WITHHELD_BODY,
    balance_kobo: 4500000,
    reason: "Fees outstanding since last term; father unreachable.",
  });
  assert.doesNotMatch(html, /4500000|45,000|Fees outstanding|unreachable/);
});

test("a missing card does not guess which of the three reasons it was", () => {
  // The API answers one flat 404 for "no such child", "not released" and "not
  // yours", precisely so the page cannot be used to tell them apart.
  const html = states.missing();
  assert.match(html, /No report card here/);
  assert.match(html, /school office/, "it points at somebody who can tell");
  assert.doesNotMatch(html, /permission|not allowed|does not exist|no such/i);
});

test("an expired session is not the same page as never having signed in", () => {
  const expired = states.expired({
    detail: "Your session has ended. Sign in again — anything you were part-way through can be sent again once you have.",
  });
  const out = states.signedOut();
  assert.match(expired, /session has ended/i);
  assert.match(out, /sign in/i);
  assert.notEqual(expired, out, "the two 401s render the same page");
});

test("a broken load says nothing about the underlying error", () => {
  // A parent reading `SyntaxError: Unexpected token <` learns nothing they can
  // act on, and the text of a server failure is written for whoever debugs it.
  const html = states.broken();
  assert.doesNotMatch(html, /error|exception|stack|SyntaxError/i);
  assert.match(html, /try again/i);
});

test("every status the API can answer maps to a state", () => {
  assert.equal(refusalFor(403, {}), REFUSAL.WITHHELD);
  assert.equal(refusalFor(404, {}), REFUSAL.MISSING);
  assert.equal(refusalFor(401, { code: "session_expired" }), REFUSAL.EXPIRED);
  assert.equal(refusalFor(401, { code: "not_authenticated" }), REFUSAL.SIGNED_OUT);
  assert.equal(refusalFor(401, null), REFUSAL.SIGNED_OUT, "no body claims least");
  assert.equal(refusalFor(500, {}), REFUSAL.BROKEN);
});

test("an unknown refusal renders the broken page rather than nothing", () => {
  // A blank page is the one outcome that tells a parent neither what happened
  // nor what to do next.
  const html = htmlFor({ ok: false, refusal: "something-new", body: {} });
  assert.match(html, /could not load/i);
});

test("the way back to sign-in is a link to the portal, not to a route that is not there", () => {
  // **Both these states used to emit `<a href="/">`**, and `urls.py` routes no
  // root: `api/`, `cards/` and `cards/<child>/<term>/` and nothing else. So a
  // parent whose session lapsed on a card was handed a 404 by the one screen
  // whose entire job is telling her how to get back in.
  //
  // CONTROL: putting `href="/"` back reddens both halves of this test and
  // nothing else in the suite, which is what says nothing else was covering it.
  for (const state of [states.expired({}, { portal: "portal.example.test" }),
                       states.signedOut({}, { portal: "portal.example.test" })]) {
    assert.match(state, /href="\/\/portal\.example\.test\/sign-in\/"/);
    assert.doesNotMatch(state, /href="\/"/, "a link to a route this host does not serve");
    // Protocol-relative, so a development deployment on plain HTTP is not sent
    // to an https URL it cannot serve.
    assert.doesNotMatch(state, /href="https?:/);
  }
});

test("a deployment with no portal domain gets a sentence and no dead link", () => {
  // The same rule the index page is already on, and the same rule the staff
  // landing is on: no link is better than a link that goes nowhere.
  for (const state of [states.expired({}), states.signedOut({})]) {
    assert.doesNotMatch(state, /<a /);
    assert.match(state, /go back to the sign-in page you came from/i);
  }
});

test("a portal hostname cannot smuggle markup into the page", () => {
  // It comes from a `Domain` row, which an admin typed.
  const html = states.signedOut({}, { portal: '"><img src=x onerror="alert(1)">' });

  assert.doesNotMatch(html, /<img src=x/);
  assert.match(html, /&quot;&gt;&lt;img/);
});

test("the sign-out button is drawn only on answers that prove a session", () => {
  // A control that posts a logout for a browser holding no cookie is a control
  // that does nothing while looking like it did.
  const shown = (answer) => htmlFor(answer, { portal: "p.test" }).includes('data-action="sign-out"');

  assert.equal(shown({ ok: true, card: {} }), true);
  // 403 is the fee gate, reached only after `_require_may_read()` answered.
  assert.equal(shown({ ok: false, refusal: REFUSAL.WITHHELD, body: WITHHELD_BODY }), true);
  // 404 is the flat refusal to an authenticated caller with no claim on this
  // card — an anonymous one gets 401, never 404.
  assert.equal(shown({ ok: false, refusal: REFUSAL.MISSING, body: {} }), true);

  assert.equal(shown({ ok: false, refusal: REFUSAL.SIGNED_OUT, body: {} }), false);
  assert.equal(shown({ ok: false, refusal: REFUSAL.EXPIRED, body: {} }), false);
  // A 500 or a dead transport proves nothing in either direction.
  assert.equal(shown({ ok: false, refusal: REFUSAL.BROKEN, body: {} }), false);
});
