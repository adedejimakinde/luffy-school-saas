/**
 * Accepting an invitation.
 *
 * What it walks is `api.py`'s two invitation routes: a preview (200, or a
 * refusal about the token), and an accept (200, a 422 about the password, or a
 * refusal about the token).
 *
 * **A refusal about the token is one state.** The server answers an unknown,
 * used, replaced and expired token alike so a guess cannot be told from a
 * spent one; the page must not undo that by reading the status or the words.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { htmlFor, mount } from "../../static/invite/app.js";
import { DEAD, tokenFrom } from "../../static/invite/api.js";
import * as states from "../../static/invite/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const TOKEN = "tok_abc-123";
const PREVIEW = {
  school: "St Mary's",
  role: "teacher",
  role_display: "Teacher",
  invitee: "Kemi Bello",
  needs_password: true,
  expires_at: "2026-10-01T00:00:00+00:00",
};

function serve(routes) {
  const asked = [];
  const impl = async (url, options = {}) => {
    asked.push([options.method || "GET", url, options.body ? JSON.parse(options.body) : null]);
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    for (const [match, answer] of routes) {
      if (url.endsWith(match)) {
        const value = typeof answer === "function" ? answer(options) : answer;
        return { status: value.status, json: async () => value.body };
      }
    }
    throw new Error(`no stub for ${url}`);
  };
  impl.asked = asked;
  return impl;
}

async function mounted(routes) {
  forgetToken();
  const root = fakeRoot({});
  const fetchImpl = serve(routes);
  await mount(root, { fetchImpl, pathname: `/invitations/${TOKEN}/` });
  return { root, fetchImpl };
}

// -- one state for every refusal about the token -----------------------------

test("an unknown, used, replaced or expired token all read the same", async () => {
  // CONTROL 5: the page telling a 404 from a 410 (or reading the refusal's
  // words) makes this red.
  const pages = [];
  for (const [status, detail] of [
    [404, "No such invitation."],
    [410, "That invitation has expired."],
    [409, "That invitation has already been accepted."],
    [400, "Revoked."],
  ]) {
    const { root } = await mounted([[`/api/invitations/${TOKEN}/`, { status, body: { detail } }]]);
    pages.push(root.innerHTML);
  }

  assert.equal(new Set(pages).size, 1, "two refusals about the token read differently");
  assert.match(pages[0], /This invitation link does not work/);
  assert.doesNotMatch(pages[0], /expired\.|already been accepted|No such/);
});

test("a server that failed is not reported as a dead link", async () => {
  const { root } = await mounted([[`/api/invitations/${TOKEN}/`, { status: 500, body: {} }]]);

  assert.match(root.innerHTML, /data-state="broken"/);
  assert.match(root.innerHTML, /has not been used/);
});

test("an address with no token asks for nothing and says the link does not work", async () => {
  forgetToken();
  const root = fakeRoot({});
  const fetchImpl = serve([]);

  await mount(root, { fetchImpl, pathname: "/invitations/" });

  assert.equal(fetchImpl.asked.length, 0);
  assert.equal(root.innerHTML, htmlFor({ step: DEAD }));
});

test("the token is read from the address, decoded", () => {
  assert.equal(tokenFrom("/invitations/abc_DEF-9/"), "abc_DEF-9");
  assert.equal(tokenFrom("/invitations/a%2Bb/"), "a+b");
  assert.equal(tokenFrom("/staff-sign-in/"), "");
});

// -- what the invitee sees --------------------------------------------------

test("the offer names the school, the role and the invitee, and asks for a password", async () => {
  const { root } = await mounted([[`/api/invitations/${TOKEN}/`, { status: 200, body: PREVIEW }]]);

  assert.match(root.innerHTML, /Kemi Bello, St Mary&#39;s has invited you to join as <strong>Teacher<\/strong>/);
  assert.match(root.innerHTML, /name="password"/);
  assert.match(root.innerHTML, /At least 10 characters/);
});

test("somebody who already has a password is not asked for another", () => {
  const html = states.offer({ preview: { ...PREVIEW, needs_password: false } });

  assert.doesNotMatch(html, /name="password"/);
  assert.match(html, /You already have a password/);
});

test("what an administrator typed is escaped", () => {
  // CONTROL 6: printing the invitee's name unescaped makes this red.
  const html = states.offer({
    preview: { ...PREVIEW, invitee: '<img src=x onerror="alert(1)">', school: "<b>School</b>" },
  });

  assert.doesNotMatch(html, /<img/);
  assert.doesNotMatch(html, /<b>School/);
  assert.match(html, /&lt;img/);
});

// -- accepting ----------------------------------------------------------------

test("accepting sends the password and ends at the staff door", async () => {
  const { root, fetchImpl } = await mounted([
    [`/api/invitations/${TOKEN}/accept/`, { status: 200, body: { school: "St Mary's", role: "teacher", status: "active" } }],
    [`/api/invitations/${TOKEN}/`, { status: 200, body: PREVIEW }],
  ]);

  await root.submit({ password: "a-long-passphrase", confirm: "a-long-passphrase" });

  const posted = fetchImpl.asked.filter(([method, url]) => method === "POST" && url.endsWith("/accept/"));
  assert.deepEqual(posted.map(([, , body]) => body), [{ password: "a-long-passphrase" }]);
  assert.match(root.innerHTML, /You are in/);
  assert.match(root.innerHTML, /<a href="\/staff-sign-in\/">Sign in<\/a>/);
});

test("two different passwords are caught before anything is sent", async () => {
  const { root, fetchImpl } = await mounted([[`/api/invitations/${TOKEN}/`, { status: 200, body: PREVIEW }]]);

  await root.submit({ password: "a-long-passphrase", confirm: "a-long-passphrasf" });

  assert.equal(fetchImpl.asked.filter(([method]) => method === "POST").length, 0);
  assert.match(root.innerHTML, /The two passwords are not the same/);
});

test("a password the server refuses is the invitee's to fix, and says why", async () => {
  const { root } = await mounted([
    [`/api/invitations/${TOKEN}/accept/`, { status: 422, body: { detail: "This password is too short." } }],
    [`/api/invitations/${TOKEN}/`, { status: 200, body: PREVIEW }],
  ]);

  await root.submit({ password: "short", confirm: "short" });

  assert.match(root.innerHTML, /data-state="offer"/);
  assert.match(root.innerHTML, /This password is too short\./);
});

test("a token spent between the preview and the accept is the same dead link", async () => {
  const { root } = await mounted([
    [`/api/invitations/${TOKEN}/accept/`, { status: 409, body: { detail: "That invitation has already been accepted." } }],
    [`/api/invitations/${TOKEN}/`, { status: 200, body: PREVIEW }],
  ]);

  await root.submit({ password: "a-long-passphrase", confirm: "a-long-passphrase" });

  assert.equal(root.innerHTML, htmlFor({ step: DEAD }));
});
