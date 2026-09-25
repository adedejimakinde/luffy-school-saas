/**
 * A child's guardians, in a panel on the roll.
 *
 * What the panel walks is `accounts/enrolment_api.py`'s guardians routes: a
 * 200 for the panel, a 201 for a link, a 200 for a removal, a 422 with a
 * sentence, a 403 for a principal who tried to write, a 404 for a child who
 * is not on this school's roll.
 *
 * **The status is the server's.** A link starts "pending verification" and
 * goes live only when the guardian answers this school (#135); the renderer
 * says what it is told. Control 4 turns the server's answer to "live", and the
 * Python tests catch that — these catch a renderer that stopped listening.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { applyPanel, mount } from "../../static/roll/app.js";
import { SAVE } from "../../static/roll/api.js";
import * as states from "../../static/roll/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const ROLL = {
  term_id: 7,
  term: "2025/2026 First term",
  children: [
    { student_membership_id: 1, student: "Ada Obi", username: "STM/1", reference: "", class_group_id: 11, class_group: "JSS 1A" },
  ],
  classes: [{ class_group_id: 11, name: "JSS 1A" }],
  may_admit: true,
  may_place: true,
};

const PENDING = {
  link_id: 40,
  name: "Mama Obi",
  contact: "+2348031234567",
  relationship: "mother",
  status: "pending verification",
  channel: "not verified here",
};

const PANEL = {
  student_membership_id: 1,
  student: "Ada Obi",
  guardians: [PENDING],
  may_link: true,
  relationships: ["mother", "father", "guardian", "other"],
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

// -- what the panel says ------------------------------------------------------

test("a pending link says plainly that it is not live, and what finishes the job", () => {
  const html = states.guardiansPanel({ body: PANEL });

  assert.match(html, /Pending verification — not live yet/);
  assert.match(html, /cannot see Ada Obi until they confirm with this school/);
  assert.match(html, /send them a code, and they type it on the sign-in page/);
  assert.doesNotMatch(html, /not connected yet/);
  assert.doesNotMatch(html, /Live:/);
});

test("a live link says live, because the server said so", () => {
  // The control for the one above: a renderer printing "pending" whatever it
  // was told would pass it.
  const html = states.guardiansPanel({
    body: { ...PANEL, guardians: [{ ...PENDING, status: "live", channel: "verified" }] },
  });

  assert.match(html, /Live: they can see Ada Obi/);
  assert.doesNotMatch(html, /not live yet/);
});

test("a dormant channel on a live link says what the school has to do", () => {
  const html = states.guardiansPanel({
    body: { ...PANEL, guardians: [{ ...PENDING, status: "live", channel: "dormant" }] },
  });

  assert.match(html, /quiet for 180 days/);
});

test("a guardian with nothing typed shows a dash, not a blank that reads as unfinished", () => {
  const html = states.guardiansPanel({
    body: { ...PANEL, guardians: [{ ...PENDING, name: "", contact: "" }] },
  });

  assert.match(html, /<span class="name">—<\/span>/);
  assert.match(html, /<span class="contact">—<\/span>/);
});

test("no guardian yet says so", () => {
  assert.match(states.guardiansPanel({ body: { ...PANEL, guardians: [] } }), /No guardian is linked/);
});

test("what a school typed is escaped", () => {
  const html = states.guardiansPanel({
    body: { ...PANEL, guardians: [{ ...PENDING, name: "<img src=x onerror=alert(1)>" }] },
  });

  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
});

// -- per role -------------------------------------------------------------------

test("an administrator is offered the link form and a remove button", () => {
  const html = states.guardiansPanel({ body: PANEL });

  assert.match(html, /data-form="guardian"/);
  assert.match(html, /data-action="ask-remove" data-link="40"/);
});

test("a principal reads the panel and is told who links, with no form and no remove", () => {
  // CONTROL 6: the renderer drawing the write controls regardless of
  // `may_link` makes this red.
  const html = states.guardiansPanel({ body: { ...PANEL, may_link: false } });

  assert.doesNotMatch(html, /data-form="guardian"/);
  assert.doesNotMatch(html, /data-action="ask-remove"/);
  assert.doesNotMatch(html, /data-action="remove-guardian"/);
  assert.match(html, /Guardians are linked by an administrator of the school/);
  assert.match(html, /Mama Obi/);
});

test("removing asks first, naming who and from whom", () => {
  const html = states.guardiansPanel({ body: PANEL, confirming: 40 });

  assert.match(html, /Remove Mama Obi from Ada Obi\?/);
  assert.match(html, /data-action="remove-guardian" data-link="40"/);
  assert.match(html, /data-action="cancel-remove"/);
});

test("a refused link keeps what was typed", () => {
  const state = applyPanel(
    { step: "roll", panel: { childId: 1, body: PANEL } },
    1,
    { ok: false, outcome: SAVE.REJECTED, body: { detail: "'0803' is neither a phone number nor an email address." } },
    { full_name: "Papa Obi", contact: "0803", relationship: "father" },
  );

  const html = states.guardiansPanel(state.panel);

  assert.match(html, /value="Papa Obi"/);
  assert.match(html, /value="0803"/);
  assert.match(html, /<option value="father" selected>/);
  assert.match(html, /neither a phone number nor an email/);
});

// -- the flow -----------------------------------------------------------------

test("opening a child's guardians fetches that child's panel", async () => {
  forgetToken();
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/1/guardians/", { status: 200, body: PANEL }],
      ["/api/enrolment/roll/", { status: 200, body: ROLL }],
    ]),
  });

  await root.click({ "data-action": "guardians", "data-child": "1" });

  assert.match(root.innerHTML, /Guardians of Ada Obi/);
  assert.match(root.innerHTML, /Pending verification/);
});

test("linking sends the name, the contact and the relationship, and shows the server's panel", async () => {
  forgetToken();
  const sent = [];
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/1/guardians/", (o) => {
        if (o.method === "POST") {
          sent.push(JSON.parse(o.body));
          return { status: 201, body: { ...PANEL, guardians: [PENDING, { ...PENDING, link_id: 41, name: "Papa Obi" }] } };
        }
        return { status: 200, body: PANEL };
      }],
      ["/api/enrolment/roll/", { status: 200, body: ROLL }],
    ]),
  });
  await root.click({ "data-action": "guardians", "data-child": "1" });

  await root.submit({ guardian_name: "Papa Obi", guardian_contact: "0803 999 9999", relationship: "father" });

  assert.deepEqual(sent, [{ full_name: "Papa Obi", contact: "0803 999 9999", relationship: "father" }]);
  assert.match(root.innerHTML, /Papa Obi/);
});

test("removing takes two clicks, and a stray second click removes nothing", async () => {
  forgetToken();
  const removed = [];
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/remove/", (o, url) => {
        removed.push(url);
        return { status: 200, body: { ...PANEL, guardians: [] } };
      }],
      ["/1/guardians/", { status: 200, body: PANEL }],
      ["/api/enrolment/roll/", { status: 200, body: ROLL }],
    ]),
  });
  await root.click({ "data-action": "guardians", "data-child": "1" });

  await root.click({ "data-action": "remove-guardian", "data-link": "40" });
  assert.deepEqual(removed, [], "removed without being asked");

  await root.click({ "data-action": "ask-remove", "data-link": "40" });
  assert.match(root.innerHTML, /Remove Mama Obi from Ada Obi\?/);
  await root.click({ "data-action": "remove-guardian", "data-link": "40" });

  assert.deepEqual(removed, ["/api/enrolment/roll/1/guardians/40/remove/"]);
  assert.match(root.innerHTML, /No guardian is linked/);
});

test("a principal who tries to write is told, in the panel, and the roll stays", async () => {
  const state = applyPanel(
    { step: "roll", panel: { childId: 1, body: { ...PANEL, may_link: false } } },
    1,
    { ok: false, outcome: SAVE.NOT_ALLOWED, body: { detail: "Guardians are linked by an administrator of the school." } },
  );

  assert.equal(state.step, "roll");
  assert.match(states.guardiansPanel(state.panel), /role="alert">Guardians are linked by an administrator/);
});

// -- sending a code (docs/messaging.md D8) -------------------------------------

const TYPED = {
  channel_type: "phone",
  value: "+2348031234567",
  state: "not verified here",
  last_message: "",
  may_send: true,
};

const LIVE = {
  link_id: 41,
  name: "Papa Obi",
  contact: "+2348039999999",
  relationship: "father",
  status: "live",
  channel: "dormant",
  channels: [
    { channel_type: "phone", value: "+2348039999999", state: "dormant", last_message: "", may_send: true },
  ],
};

test("a pending link offers to send a code to what this school typed", () => {
  const html = states.guardiansPanel({ body: { ...PANEL, guardians: [{ ...PENDING, channels: [TYPED] }] } });

  assert.match(html, /data-action="send-code" data-link="40" data-channel="phone">Send a code</);
  assert.match(html, /not verified here/);
});

test("a dormant phone is reopened, in those words", () => {
  const html = states.guardiansPanel({ body: { ...PANEL, guardians: [LIVE] } });

  assert.match(html, />Send a code to reopen it</);
  assert.match(html, /until the school sends a code to reopen it/);
});

test("the last code's outcome is said on its channel", () => {
  const told = { ...TYPED, last_message: "could not be delivered to this contact" };
  const html = states.guardiansPanel({ body: { ...PANEL, guardians: [{ ...PENDING, channels: [told] }] } });

  assert.match(html, /Last code from this school: could not be delivered to this contact\./);
});

test("nothing is offered to a principal, who only reads the panel", () => {
  const html = states.guardiansPanel({
    body: { ...PANEL, may_link: false, guardians: [{ ...PENDING, channels: [TYPED] }, LIVE] },
  });

  assert.doesNotMatch(html, /data-action="send-code"/);
  assert.doesNotMatch(html, /data-form="contact"/);
});

test("a live guardian with one channel can be given the other; one with both cannot", () => {
  const one = states.guardiansPanel({ body: { ...PANEL, guardians: [LIVE] } });
  assert.match(one, /data-form="contact"/);
  assert.match(one, /name="link_id" value="41"/);

  const both = {
    ...LIVE,
    channels: [...LIVE.channels, { channel_type: "email", value: "papa@example.com", state: "verified", last_message: "", may_send: false }],
  };
  const two = states.guardiansPanel({ body: { ...PANEL, guardians: [both] } });
  assert.doesNotMatch(two, /data-form="contact"/);
  // A verified, current channel needs nothing from the school.
  assert.doesNotMatch(two, /data-channel="email"/);
});

test("pressing send posts to that link and channel, and the panel comes back", async () => {
  forgetToken();
  const posted = [];
  const root = fakeRoot({});
  const after = { ...PANEL, guardians: [{ ...PENDING, channels: [{ ...TYPED, last_message: "waiting to be sent" }] }] };
  await mount(root, {
    fetchImpl: serve([
      ["/guardians/40/send-code/", (options, url) => {
        posted.push([url, JSON.parse(options.body)]);
        return { status: 200, body: after };
      }],
      ["/guardians/", { status: 200, body: { ...PANEL, guardians: [{ ...PENDING, channels: [TYPED] }] } }],
      ["/api/enrolment/roll/", { status: 200, body: ROLL }],
    ]),
  });
  await root.click({ "data-action": "guardians", "data-child": "1" });
  await root.click({ "data-action": "send-code", "data-link": "40", "data-channel": "phone" });

  assert.equal(posted.length, 1);
  assert.match(posted[0][0], /\/roll\/1\/guardians\/40\/send-code\/$/);
  assert.deepEqual(posted[0][1], { channel_type: "phone" });
  assert.match(root.innerHTML, /Last code from this school: waiting to be sent\./);
});

test("too many codes is a sentence on the panel, not a broken page", async () => {
  forgetToken();
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/send-code/", { status: 429, body: { detail: "Too many codes have gone out to this contact or from this school just now. Try again in 12 minutes." } }],
      ["/guardians/", { status: 200, body: { ...PANEL, guardians: [{ ...PENDING, channels: [TYPED] }] } }],
      ["/api/enrolment/roll/", { status: 200, body: ROLL }],
    ]),
  });
  await root.click({ "data-action": "guardians", "data-child": "1" });
  await root.click({ "data-action": "send-code", "data-link": "40", "data-channel": "phone" });

  assert.match(root.innerHTML, /Try again in 12 minutes/);
  assert.match(root.innerHTML, /data-panel="guardians"/);
});

test("adding a contact posts what was typed to that link", async () => {
  forgetToken();
  const posted = [];
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/guardians/41/contacts/", (options) => {
        posted.push(JSON.parse(options.body));
        return { status: 201, body: { ...PANEL, guardians: [LIVE] } };
      }],
      ["/guardians/", { status: 200, body: { ...PANEL, guardians: [LIVE] } }],
      ["/api/enrolment/roll/", { status: 200, body: ROLL }],
    ]),
  });
  await root.click({ "data-action": "guardians", "data-child": "1" });
  await root.submit({ link_id: "41", new_contact: "papa@example.com" });

  assert.deepEqual(posted, [{ contact: "papa@example.com" }]);
});
