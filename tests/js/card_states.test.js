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
