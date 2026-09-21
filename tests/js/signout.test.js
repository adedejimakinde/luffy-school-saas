/**
 * Sign-out: the POST every page shares, and the judgement about its answer.
 *
 * The module is small and the thing worth testing is not the fetch — it is
 * `sessionEnded()`, which decides whether a page is allowed to tell a reader
 * their session is over. The two wrong answers are not symmetrical: claiming a
 * session is still open when it is not costs a tap, and claiming it is closed
 * when it is live hands the next person to pick up the handset a child's marks.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  COULD_NOT_END,
  SIGN_OUT_URL,
  button,
  failureNote,
  sessionEnded,
  signOut,
} from "../../static/web/signout.js";
import { forgetToken } from "../../static/web/http.js";

test("a session is only reported ended when the answer proves it", () => {
  assert.equal(sessionEnded({ status: 200 }), true);
  // A caller whose session had already gone asks to be signed out and is told
  // nobody is signed in. That is a true answer to the question — `sign_out()`
  // says so — and treating it as a failure leaves a reader staring at "could
  // not sign you out" on a browser holding nothing.
  assert.equal(sessionEnded({ status: 401 }), true);

  for (const status of [0, 403, 500, 502, 504]) {
    assert.equal(sessionEnded({ status }), false, `${status} is not proof of anything`);
  }
});

test("what an unproved sign-out tells the reader to do is something they can do", () => {
  // Not "try again": the failures that reach here are a server that is not
  // answering, and a reader cannot fix that by tapping. Closing the browser is
  // the one action that ends the session from their side.
  assert.match(COULD_NOT_END, /close this browser/i);
  assert.doesNotMatch(COULD_NOT_END, /try again/i);
  assert.match(failureNote(), /role="alert"/, "a refusal a screen reader never says");
});

test("the control is a button, not a link", () => {
  // It performs a POST. A link that did would be a link a prefetcher, a crawler
  // or a browser's own "open in new tab" could follow, signing somebody out by
  // looking at the page.
  const html = button();
  assert.match(html, /^<button type="button"/);
  assert.doesNotMatch(html, /<a /);
  assert.match(html, /data-action="sign-out"/);
});

test("it posts to this host's own logout route and carries the CSRF token", async () => {
  forgetToken();
  const seen = [];
  const answer = await signOut({
    fetchImpl: async (url, options = {}) => {
      seen.push({ url, method: options.method, token: (options.headers || {})["X-CSRFToken"] });
      if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "tok" }) };
      return { status: 200, json: async () => ({ detail: "Signed out." }) };
    },
  });

  assert.equal(answer.status, 200);
  // Relative, so it lands on whichever host the page is on: the portal's own
  // route from the staff page, the school's own from the family pages. No POST
  // on this platform crosses hosts, which is what keeps
  // `CSRF_TRUSTED_ORIGINS` untouched.
  assert.equal(SIGN_OUT_URL, "/api/logout/");
  assert.doesNotMatch(SIGN_OUT_URL, /^https?:|^\/\//);
  assert.deepEqual(seen[1], { url: "/api/logout/", method: "POST", token: "tok" });
});

test("a transport that never lands is an answer, not a throw", async () => {
  // `mount()` calls this inside a click handler; an unhandled rejection there
  // is a button that does nothing and says nothing.
  forgetToken();
  const answer = await signOut({
    fetchImpl: async () => {
      throw new TypeError("Failed to fetch");
    },
  });

  assert.deepEqual(answer, { status: 0, body: {} });
  assert.equal(sessionEnded(answer), false);
});
