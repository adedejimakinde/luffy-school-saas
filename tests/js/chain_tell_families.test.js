/**
 * "Tell families" on the chain page: docs/messaging.md D9 and D7.
 *
 * The button asks before it sends — how many messages, and in quiet hours that
 * they go at 07:00 — and nothing is posted until "Send them". Every test that
 * clicks a button first asserts the button was drawn, because the fake DOM's
 * click needs only the attributes, not the markup.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { mount } from "../../static/results/app.js";
import * as states from "../../static/results/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const released = (over = {}) => ({
  class_group_id: 11,
  class_group: "JSS 1A",
  sheet_id: 5,
  state: "released",
  state_label: "Released",
  may_submit: false,
  may_check: false,
  may_approve: false,
  may_release: false,
  may_send_back: false,
  may_tell_families: true,
  families_told: 0,
  ...over,
});

const CHAIN = { term_id: 7, term: "2025/2026 First term", rows: [released()] };

const PREVIEW = {
  detail: "This will send 3 messages to families. 1 guardian here has no verified phone or email, and will not be sent anything.",
  messages: 3,
  segments: 3,
  held_until: null,
  unreachable: 1,
};

/** Routes by URL fragment, and records every call's method, so a GET and a POST to one URL differ. */
function serve(routes, calls = []) {
  return async (url, options = {}) => {
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    for (const [match, answer] of routes) {
      if (url.includes(match)) {
        calls.push([options.method || "GET", url]);
        const value = typeof answer === "function" ? answer(options) : answer;
        return { status: value.status, json: async () => value.body };
      }
    }
    throw new Error(`no stub for ${url}`);
  };
}

const TELL = "/api/results/chain/11/tell-families/";
const posts = (calls) => calls.filter(([method, url]) => method === "POST" && url === TELL);

test("a released row the principal may tell offers the button, and counts what was asked for", () => {
  const html = states.chain({ ...CHAIN, rows: [released({ families_told: 3 })] });
  assert.match(html, /data-action="tell-families" data-class="11"/);
  assert.match(html, /3 messages to families so far\./);
});

test("nobody else is offered it", () => {
  const html = states.chain({ ...CHAIN, rows: [released({ may_tell_families: false, families_told: null })] });
  assert.doesNotMatch(html, /tell-families/);
  assert.doesNotMatch(html, /to families so far/);
});

test("pressing it asks first: how many, and nothing is sent until they say so", async () => {
  forgetToken();
  const calls = [];
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      [TELL, { status: 200, body: PREVIEW }],
      ["/api/results/chain/", { status: 200, body: CHAIN }],
    ], calls),
  });
  assert.match(root.innerHTML, /data-action="tell-families"/);

  await root.click({ "data-action": "tell-families", "data-class": "11" });

  assert.deepEqual(calls.filter(([, url]) => url === TELL), [["GET", TELL]]);
  assert.deepEqual(posts(calls), [], "a message went before anybody said send");
  assert.match(root.innerHTML, /This will send 3 messages to families\./);
  assert.match(root.innerHTML, /1 guardian here has no verified phone or email/);
  assert.match(root.innerHTML, /data-action="send-to-families" data-class="11">Send them</);
});

test("asked in quiet hours, the question says 07:00 before anything is pressed", async () => {
  forgetToken();
  const root = fakeRoot({});
  const held = {
    ...PREVIEW,
    detail: "This will send 3 messages to families. These will be sent at 07:00 on Saturday 26 September: messages are not sent between 20:00 and 07:00.",
    held_until: "2026-09-26T07:00:00+01:00",
  };
  await mount(root, {
    fetchImpl: serve([
      [TELL, { status: 200, body: held }],
      ["/api/results/chain/", { status: 200, body: CHAIN }],
    ]),
  });

  await root.click({ "data-action": "tell-families", "data-class": "11" });

  assert.match(root.innerHTML, /These will be sent at 07:00 on Saturday 26 September/);
});

test("send posts once, and the row comes back with the count and what happened", async () => {
  forgetToken();
  const calls = [];
  let sent = false;
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      [TELL, (options) => {
        if (options.method !== "POST") return { status: 200, body: PREVIEW };
        sent = true;
        return { status: 200, body: { ...PREVIEW, detail: "3 messages are being sent." } };
      }],
      ["/api/results/chain/", () => ({
        status: 200,
        body: { ...CHAIN, rows: [released({ families_told: sent ? 3 : 0 })] },
      })],
    ], calls),
  });

  await root.click({ "data-action": "tell-families", "data-class": "11" });
  assert.match(root.innerHTML, /data-action="send-to-families"/);
  await root.click({ "data-action": "send-to-families", "data-class": "11" });

  assert.equal(posts(calls).length, 1);
  assert.match(root.innerHTML, /3 messages are being sent\./);
  assert.match(root.innerHTML, /3 messages to families so far\./);
  assert.doesNotMatch(root.innerHTML, /data-action="send-to-families"/, "the question outlived the send");
});

test("cancel sends nothing and closes the question", async () => {
  forgetToken();
  const calls = [];
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      [TELL, { status: 200, body: PREVIEW }],
      ["/api/results/chain/", { status: 200, body: CHAIN }],
    ], calls),
  });

  await root.click({ "data-action": "tell-families", "data-class": "11" });
  assert.match(root.innerHTML, /data-action="cancel-telling" data-class="11">Cancel</);
  await root.click({ "data-action": "cancel-telling", "data-class": "11" });

  assert.deepEqual(posts(calls), []);
  assert.doesNotMatch(root.innerHTML, /This will send/);
  assert.match(root.innerHTML, /data-action="tell-families"/);
});

test("with every family told already there is nothing to send, only a box to close", async () => {
  forgetToken();
  const root = fakeRoot({});
  const none = { ...PREVIEW, detail: "Every family this class can reach has been told already.", messages: 0, segments: 0, unreachable: 0 };
  await mount(root, {
    fetchImpl: serve([
      [TELL, { status: 200, body: none }],
      ["/api/results/chain/", { status: 200, body: { ...CHAIN, rows: [released({ families_told: 3 })] } }],
    ]),
  });

  await root.click({ "data-action": "tell-families", "data-class": "11" });

  assert.match(root.innerHTML, /told already/);
  assert.doesNotMatch(root.innerHTML, /send-to-families/);
  assert.match(root.innerHTML, /data-action="cancel-telling" data-class="11">Close</);
});

test("a refusal is a sentence on the row, not a broken page, and offers no send", async () => {
  forgetToken();
  const root = fakeRoot({});
  const over = "This would send 3 message segments, and this school has 2 left for Friday 25 September. Nothing has been sent.";
  await mount(root, {
    fetchImpl: serve([
      [TELL, { status: 422, body: { detail: over } }],
      ["/api/results/chain/", { status: 200, body: CHAIN }],
    ]),
  });

  await root.click({ "data-action": "tell-families", "data-class": "11" });

  assert.match(root.innerHTML, /data-state="chain"/);
  assert.match(root.innerHTML, /has 2 left for Friday 25 September\. Nothing has been sent\./);
  assert.doesNotMatch(root.innerHTML, /send-to-families/);
});
