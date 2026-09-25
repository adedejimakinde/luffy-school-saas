/**
 * Fee reminders on the bursar's page: docs/messaging.md D10, as decided on
 * 2026-09-25.
 *
 * The button asks before it sends: which children, who will be sent it, and how
 * many messages. Nothing is posted until "Send them". Reminders that went
 * nowhere because the account moved are listed under the classes, with the
 * account as it stands and "Remind again". Every test that clicks a button
 * first asserts it was drawn, because the fake DOM's click needs only the
 * attributes.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { mount } from "../../static/fees/app.js";
import * as states from "../../static/fees/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const TERMS = [{ term_id: 7, term: "2025/2026 First term", is_current: true }];
const BOOKS = {
  terms: TERMS,
  term_id: 7,
  term: "2025/2026 First term",
  may_write: true,
  may_remind: true,
  classes: [{ class_group_id: 11, class_group: "JSS 1A", children: 4 }],
};
const CLASS = {
  class_group_id: 11,
  class_group: "JSS 1A",
  term_id: 7,
  term: "2025/2026 First term",
  may_remind: true,
  children: [{ student_membership_id: 3, student: "Ada Obi", reference: "SM/001", balance_kobo: 12_000_000 }],
};
const PREVIEW = {
  detail: "This will send 2 messages about 2 children.",
  messages: 2,
  segments: 2,
  held_until: null,
  unreachable: 0,
  children: [
    { student_membership_id: 3, student: "Ada Obi", reference: "SM/001", amount_kobo: 12_000_000, guardians: ["Ngozi Obi"], unreachable: 0 },
    { student_membership_id: 4, student: "Bisi Ade", reference: "SM/004", amount_kobo: 8_000_000, guardians: ["Funke Ade"], unreachable: 0 },
  ],
  recently_reminded: [],
};
const NOT_SENT = {
  may_remind: true,
  children: [
    {
      student_membership_id: 3, student: "Ada Obi", reference: "SM/001", term_id: 7,
      stated_kobo: 12_000_000, asked_for: "2026-09-25T07:00:00+01:00", balance_kobo: 11_000_000,
    },
  ],
};

/** Records every call's method and URL, so a GET and a POST to one URL differ. */
function serve(routes, calls = []) {
  return async (url, options = {}) => {
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    for (const [match, answer] of routes) {
      if (url.includes(match)) {
        calls.push([options.method || "GET", url, options.body ? JSON.parse(options.body) : undefined]);
        const value = typeof answer === "function" ? answer(options, url) : answer;
        return { status: value.status, json: async () => value.body };
      }
    }
    throw new Error(`no stub for ${url}`);
  };
}

const posts = (calls) => calls.filter(([method, url]) => method === "POST" && url.includes("/reminders/"));

test("the button is offered only to somebody who may send them", () => {
  assert.match(states.books({ books: BOOKS }), /data-action="ask-reminders">Remind families who owe, in every class</);
  assert.doesNotMatch(states.books({ books: { ...BOOKS, may_remind: false } }), /ask-reminders/);
  assert.match(states.classBalances({ classBalances: CLASS }), /data-action="ask-reminders" data-class="11"/);
  assert.doesNotMatch(states.classBalances({ classBalances: { ...CLASS, may_remind: false } }), /ask-reminders/);
});

test("pressing it asks first: which children, who, how many, and nothing is sent", async () => {
  forgetToken();
  const calls = [];
  const root = fakeRoot({ onSchool: "yes" });
  await mount(root, {
    fetchImpl: serve([
      ["/api/fees/reminders/not-sent/", { status: 200, body: { may_remind: true, children: [] } }],
      ["/api/fees/reminders/", { status: 200, body: PREVIEW }],
      ["/api/fees/classes/11/", { status: 200, body: CLASS }],
      ["/api/fees/classes/", { status: 200, body: BOOKS }],
    ], calls),
  });
  await root.click({ "data-action": "open-class", "data-class": "11" });
  assert.match(root.innerHTML, /data-action="ask-reminders" data-class="11"/);

  await root.click({ "data-action": "ask-reminders", "data-class": "11" });

  const asked = calls.filter(([, url]) => url.startsWith("/api/fees/reminders/?"));
  assert.deepEqual(asked.map(([method, url]) => [method, url]), [["GET", "/api/fees/reminders/?term_id=7&class_group_id=11"]]);
  assert.deepEqual(posts(calls), [], "a reminder went before anybody said send");
  assert.match(root.innerHTML, /This will send 2 messages about 2 children\./);
  assert.match(root.innerHTML, /Ada Obi: ₦120,000\.00 owing\. To Ngozi Obi\./);
  assert.match(root.innerHTML, /data-action="send-reminders">Send them</);
});

test("send posts the same scope once, and the page says what it did", async () => {
  forgetToken();
  const calls = [];
  const root = fakeRoot({ onSchool: "yes" });
  await mount(root, {
    fetchImpl: serve([
      ["/api/fees/reminders/not-sent/", { status: 200, body: { may_remind: true, children: [] } }],
      ["/api/fees/reminders/", (options) =>
        options.method === "POST"
          ? { status: 200, body: { ...PREVIEW, detail: "2 messages about 2 children are being sent." } }
          : { status: 200, body: PREVIEW }],
      ["/api/fees/classes/", { status: 200, body: BOOKS }],
    ], calls),
  });
  assert.match(root.innerHTML, /data-action="ask-reminders">/);
  await root.click({ "data-action": "ask-reminders" });
  assert.match(root.innerHTML, /data-action="send-reminders"/);
  await root.click({ "data-action": "send-reminders" });

  assert.deepEqual(posts(calls).map(([, , body]) => body), [{ term_id: 7, class_group_id: null, children: null }]);
  assert.match(root.innerHTML, /2 messages about 2 children are being sent\./);
  assert.doesNotMatch(root.innerHTML, /data-action="send-reminders"/, "the question outlived the send");
});

test("cancel sends nothing and closes the question", async () => {
  forgetToken();
  const calls = [];
  const root = fakeRoot({ onSchool: "yes" });
  await mount(root, {
    fetchImpl: serve([
      ["/api/fees/reminders/not-sent/", { status: 200, body: { may_remind: true, children: [] } }],
      ["/api/fees/reminders/", { status: 200, body: PREVIEW }],
      ["/api/fees/classes/", { status: 200, body: BOOKS }],
    ], calls),
  });
  await root.click({ "data-action": "ask-reminders" });
  assert.match(root.innerHTML, /data-action="cancel-reminders">Cancel</);
  await root.click({ "data-action": "cancel-reminders" });

  assert.deepEqual(posts(calls), []);
  assert.doesNotMatch(root.innerHTML, /This will send/);
});

test("nothing to send is a box to close, not a button to press", () => {
  const html = states.books({
    books: BOOKS,
    reminding: {
      detail: "Nobody here owes anything, so there is nobody to remind.",
      messages: 0, children: [], scope: { termId: 7, classId: null, children: null },
    },
  });
  assert.match(html, /Nobody here owes anything/);
  assert.doesNotMatch(html, /send-reminders/);
  assert.match(html, /data-action="cancel-reminders">Close</);
});

test("a refusal is a sentence on the page, not a broken page", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  await mount(root, {
    fetchImpl: serve([
      ["/api/fees/reminders/not-sent/", { status: 200, body: { may_remind: true, children: [] } }],
      ["/api/fees/reminders/", { status: 422, body: { detail: "This school does not send fee reminders." } }],
      ["/api/fees/classes/", { status: 200, body: BOOKS }],
    ]),
  });
  await root.click({ "data-action": "ask-reminders" });

  assert.match(root.innerHTML, /data-state="books"/);
  assert.match(root.innerHTML, /This school does not send fee reminders\./);
  assert.doesNotMatch(root.innerHTML, /send-reminders/);
});

test("a reminder the account moved under is listed, with the account now, and can go again", async () => {
  forgetToken();
  const calls = [];
  const root = fakeRoot({ onSchool: "yes" });
  const again = { ...PREVIEW, detail: "This will send 1 message about 1 child.", messages: 1, segments: 1,
    children: [{ ...PREVIEW.children[0], amount_kobo: 11_000_000 }] };
  await mount(root, {
    fetchImpl: serve([
      ["/api/fees/reminders/not-sent/", { status: 200, body: NOT_SENT }],
      ["/api/fees/reminders/", { status: 200, body: again }],
      ["/api/fees/classes/", { status: 200, body: BOOKS }],
    ], calls),
  });

  assert.match(root.innerHTML, /Reminders that did not go/);
  assert.match(root.innerHTML, /Ada Obi \(SM\/001\): it would have said ₦120,000\.00; the account now shows/);
  assert.match(root.innerHTML, /data-action="ask-reminders" data-term="7" data-children="3">Remind again</);

  await root.click({ "data-action": "ask-reminders", "data-term": "7", "data-children": "3" });

  const asked = calls.filter(([, url]) => url.startsWith("/api/fees/reminders/?"));
  assert.deepEqual(asked.map(([, url]) => url), ["/api/fees/reminders/?term_id=7&children=3"]);
  assert.match(root.innerHTML, /This will send 1 message about 1 child\./);
  assert.match(root.innerHTML, /Ada Obi: ₦110,000\.00 owing/);
});

test("a reader who may not send sees the list and is offered nothing", () => {
  const html = states.books({ books: { ...BOOKS, may_remind: false }, notSent: NOT_SENT.children });
  assert.match(html, /Reminders that did not go/);
  assert.doesNotMatch(html, /Remind again/);
});

test("nothing owed now, nothing to remind again", () => {
  const html = states.books({ books: BOOKS, notSent: [{ ...NOT_SENT.children[0], balance_kobo: 0 }] });
  assert.match(html, /Ada Obi/);
  assert.doesNotMatch(html, /Remind again/);
});
