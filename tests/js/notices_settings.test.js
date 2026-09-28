/**
 * Notices settings: the three switches, and who gets the daily money summary.
 *
 * What it walks is `notices/api.py`'s one route: a 200 read, a 200 save, a
 * 403 with a sentence for somebody who may not change these, and a 401 that
 * is two states, the same shape `staff.test.js` and `home.test.js` walk.
 *
 * **Nobody is chosen by default.** The empty-recipients note is asserted
 * directly, since it is the one thing this page exists to say that a plain
 * settings toggle would not.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { fromSettings, htmlFor, mount, payloadFrom } from "../../static/notices/app.js";
import { REFUSAL, refusalFor } from "../../static/notices/api.js";
import * as states from "../../static/notices/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const STAFF = [
  { membership_id: 1, name: "Ade Admin", email: "ade@example.com", role: "admin", role_display: "Administrator" },
  { membership_id: 2, name: "Bola Bursar", email: "bola@example.com", role: "bursar", role_display: "Bursar" },
];

const SETTINGS = {
  payment_receipts: true,
  absence_alerts: false,
  daily_money_summary: true,
  money_summary_recipient_ids: [1],
  staff: STAFF,
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

test("nobody chosen says so, and names what to do about it", () => {
  const html = states.settings({ ...SETTINGS, money_summary_recipient_ids: [] });

  assert.match(html, /Nobody is chosen yet/);
});

test("a chosen recipient's box is ticked; an unchosen one's is not", () => {
  const html = states.settings(SETTINGS);

  assert.match(html, /name="recipient_1" checked/);
  assert.doesNotMatch(html, /name="recipient_2" checked/);
});

test("each switch reflects its own setting, independently of the others", () => {
  const html = states.settings(SETTINGS);

  assert.match(html, /name="payment_receipts" checked/);
  assert.doesNotMatch(html, /name="absence_alerts" checked/);
  assert.match(html, /name="daily_money_summary" checked/);
});

test("an empty staff list says so, not just an empty box", () => {
  const html = states.settings({ ...SETTINGS, staff: [], money_summary_recipient_ids: [] });

  assert.match(html, /Nobody is on the live staff list yet/);
});

test("payloadFrom reads the switches and the ticked staff, named by id", () => {
  const form = {
    payment_receipts: { checked: true },
    absence_alerts: { checked: false },
    daily_money_summary: { checked: true },
    recipient_1: { checked: true },
    recipient_2: { checked: false },
  };

  assert.deepEqual(payloadFrom(form, STAFF), {
    payment_receipts: true,
    absence_alerts: false,
    daily_money_summary: true,
    money_summary_recipient_ids: [1],
  });
});

test("403 is not allowed, 404 is the wrong host, 401 is two states", () => {
  assert.equal(refusalFor(403), REFUSAL.NOT_ALLOWED);
  assert.equal(refusalFor(404), REFUSAL.WRONG_HOST);
  assert.equal(refusalFor(401, { code: "session_expired" }), REFUSAL.EXPIRED);
  assert.equal(refusalFor(401, {}), REFUSAL.SIGNED_OUT);
  assert.equal(refusalFor(500), REFUSAL.BROKEN);
});

test("fromSettings carries the body through on success and keeps no stale note", () => {
  assert.deepEqual(fromSettings({ ok: true, body: SETTINGS }), {
    step: "settings", ...SETTINGS, note: null,
  });
});

test("mount loads the settings and draws the switches", async () => {
  forgetToken();
  const root = fakeRoot({ portal: "app.example.com", onSchool: "yes" });
  const fetchImpl = serve([["/api/notices/settings/", { status: 200, body: SETTINGS }]]);

  const state = await mount(root, { fetchImpl });

  assert.equal(state.step, "settings");
  assert.match(root.innerHTML, /Ade Admin/);
});

test("the wrong host draws before any fetch, when the page was served off a school", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "" });
  const fetchImpl = async () => {
    throw new Error("should not have fetched");
  };

  const state = await mount(root, { fetchImpl });

  assert.equal(state.step, REFUSAL.WRONG_HOST);
});

test("saving reposts the whole state and redraws from the answer", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  let posted = null;
  const fetchImpl = serve([
    ["/api/notices/settings/", (options, url) => {
      if (options.method === "POST") {
        posted = JSON.parse(options.body);
        return { status: 200, body: { ...SETTINGS, daily_money_summary: false, money_summary_recipient_ids: [] } };
      }
      return { status: 200, body: SETTINGS };
    }],
  ]);

  await mount(root, { fetchImpl });
  await root.submit({
    payment_receipts: { checked: true },
    absence_alerts: { checked: false },
    daily_money_summary: { checked: false },
  });

  assert.deepEqual(posted, {
    payment_receipts: true,
    absence_alerts: false,
    daily_money_summary: false,
    money_summary_recipient_ids: [],
  });
  assert.match(root.innerHTML, /Nobody is chosen yet/);
});

test("a refusal with a sentence keeps the form up and shows the note", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  const fetchImpl = serve([
    ["/api/notices/settings/", (options) => {
      if (options.method === "POST") {
        return { status: 403, body: { detail: "Only the principal or an administrator decides what the school sends." } };
      }
      return { status: 200, body: SETTINGS };
    }],
  ]);

  await mount(root, { fetchImpl });
  await root.submit({
    payment_receipts: { checked: true },
    absence_alerts: { checked: false },
    daily_money_summary: { checked: true },
  });

  assert.match(root.innerHTML, /Only the principal or an administrator/);
  assert.match(root.innerHTML, /data-state="settings"/);
});

test("htmlFor draws each refusal state and the settings state", () => {
  assert.match(htmlFor({ step: "settings", ...SETTINGS }), /data-state="settings"/);
  assert.match(htmlFor({ step: REFUSAL.NOT_ALLOWED }), /data-state="not-allowed"/);
  assert.match(htmlFor({ step: REFUSAL.WRONG_HOST }), /data-state="wrong-host"/);
  assert.match(htmlFor({ step: REFUSAL.EXPIRED }, { portal: "app.example.com" }), /Your session has ended/);
  assert.match(htmlFor({ step: REFUSAL.SIGNED_OUT }, { portal: "app.example.com" }), /Please sign in/);
  assert.match(htmlFor({ step: REFUSAL.BROKEN }), /data-state="broken"/);
});
