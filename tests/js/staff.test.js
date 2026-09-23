/**
 * Staff invitations: this school's, sent, resent and cancelled.
 *
 * What it walks is `api.py`'s invitation routes: a 200 list, a 201 invite or
 * resend, a 200 revoke, refusals with a sentence (400, 409, 502, 503), a 403
 * page for somebody who may not invite, and a 401 that is two states.
 *
 * **"Who" is only what the office typed.** An invitation from before that was
 * recorded shows "-", never a name borrowed from the account.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { fromList, htmlFor, mount } from "../../static/staff/app.js";
import { REFUSAL, inviteePayload, refusalFor } from "../../static/staff/api.js";
import * as states from "../../static/staff/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const LIST = {
  invitations: [
    { id: 9, sent_to: "new.teacher@example.com", role: "teacher", role_display: "Teacher", status: "pending", expires_at: "2026-10-01T00:00:00+00:00" },
    { id: 8, sent_to: null, role: "bursar", role_display: "Bursar", status: "expired", expires_at: "2026-09-01T00:00:00+00:00" },
  ],
  roles: ["admin", "bursar", "principal", "teacher"],
};

function serve(routes) {
  return async (url, options = {}) => {
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    for (const [match, answer] of routes) {
      if (url.includes(match)) {
        const value = typeof answer === "function" ? answer(options, url) : answer;
        return { status: value.status, json: async () => value.body };
      }
    }
    throw new Error(`no stub for ${url}`);
  };
}

test("each row says who was typed, the role, and what the invitation is waiting on", () => {
  const html = states.list(LIST);

  assert.match(html, /new\.teacher@example\.com/);
  assert.match(html, /Waiting for them to accept/);
  assert.match(html, /The link ran out before they used it/);
});

test("an invitation from before the address was kept shows a dash", () => {
  const html = states.list(LIST);

  assert.match(html, /<span class="who">-<\/span>/);
});

test("cancelling is offered only on a live invitation; sending again on every row", () => {
  const html = states.list(LIST);

  assert.match(html, /data-action="revoke" data-invitation="9"/);
  assert.doesNotMatch(html, /data-action="revoke" data-invitation="8"/);
  assert.match(html, /data-action="resend" data-invitation="8"/);
});

test("an empty list says so", () => {
  assert.match(states.list({ ...LIST, invitations: [] }), /Nobody is waiting on an invitation/);
});

test("the address box decides email or phone by the @", () => {
  assert.deepEqual(inviteePayload({ address: " a@b.co ", role: "teacher", full_name: "" }), {
    role: "teacher", full_name: "", email: "a@b.co",
  });
  assert.deepEqual(inviteePayload({ address: "0803 123 4567", role: "bursar", full_name: "Bola" }), {
    role: "bursar", full_name: "Bola", phone: "0803 123 4567",
  });
});

test("403 is not the office, 404 is the wrong host, 401 is two states", () => {
  assert.equal(refusalFor(403), REFUSAL.NOT_THE_OFFICE);
  assert.equal(refusalFor(404), REFUSAL.WRONG_HOST);
  assert.equal(refusalFor(401, { code: "session_expired" }), REFUSAL.EXPIRED);
  assert.equal(refusalFor(401, {}), REFUSAL.SIGNED_OUT);
  assert.match(htmlFor(fromList({ ok: false, refusal: REFUSAL.NOT_THE_OFFICE, body: {} })), /invited by an administrator/);
});

test("a frame on a host that is not a school's asks for nothing", async () => {
  forgetToken();
  const root = fakeRoot({ school: "" });
  await mount(root, { fetchImpl: serve([]) });

  assert.match(root.innerHTML, /your school's own web address/);
});

test("inviting sends the address as typed and re-reads the list", async () => {
  forgetToken();
  const sent = [];
  let reads = 0;
  const root = fakeRoot({ school: "st-marys" });
  await mount(root, {
    fetchImpl: serve([
      ["/api/schools/st-marys/invitations/", (o) => {
        if (o.method === "POST") {
          sent.push(JSON.parse(o.body));
          return { status: 201, body: { id: 10, status: "pending" } };
        }
        reads += 1;
        return { status: 200, body: LIST };
      }],
    ]),
  });

  await root.submit({ address: "bola@example.com", role: "bursar", full_name: "Bola" });

  assert.deepEqual(sent, [{ role: "bursar", full_name: "Bola", email: "bola@example.com" }]);
  assert.equal(reads, 2);
});

test("a refused invitation is a note in the form, which keeps what was typed", async () => {
  forgetToken();
  const root = fakeRoot({ school: "st-marys" });
  await mount(root, {
    fetchImpl: serve([
      ["/api/schools/st-marys/invitations/", (o) =>
        o.method === "POST"
          ? { status: 409, body: { detail: "They are already teacher at St Mary's." } }
          : { status: 200, body: LIST }],
    ]),
  });

  await root.submit({ address: "bola@example.com", role: "teacher", full_name: "Bola" });

  assert.match(root.innerHTML, /already teacher/);
  assert.match(root.innerHTML, /value="bola@example.com"/);
  assert.match(root.innerHTML, /data-state="list"/);
});

test("resend and cancel post to their own row", async () => {
  forgetToken();
  const posted = [];
  const root = fakeRoot({ school: "st-marys" });
  await mount(root, {
    fetchImpl: serve([
      ["/resend/", (o, url) => { posted.push(url); return { status: 201, body: {} }; }],
      ["/revoke/", (o, url) => { posted.push(url); return { status: 200, body: {} }; }],
      ["/api/schools/st-marys/invitations/", { status: 200, body: LIST }],
    ]),
  });

  await root.click({ "data-action": "resend", "data-invitation": "8" });
  await root.click({ "data-action": "revoke", "data-invitation": "9" });

  assert.deepEqual(posted, [
    "/api/schools/st-marys/invitations/8/resend/",
    "/api/schools/st-marys/invitations/9/revoke/",
  ]);
});
