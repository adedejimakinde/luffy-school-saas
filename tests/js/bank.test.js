/**
 * The school's bank account: choose the bank, see the name the bank holds,
 * confirm it, and only then write.
 *
 * What is asserted above all is that **nothing is written until the confirm**:
 * the lookup posts to `resolve/` only, the write posts once with the name the
 * person was shown, and a refusal (the bank changed the name; Paystack is down)
 * leaves the page up with the server's sentence.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { htmlFor, mount } from "../../static/bank/app.js";
import { REFUSAL, refusalFor } from "../../static/bank/api.js";
import * as states from "../../static/bank/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const NONE = { connected: null, may_write: true };
const CONNECTED = {
  connected: {
    bank_name: "Wema Bank",
    account_number: "0123456789",
    account_name: "ST MARYS COLLEGE",
    connected_by: "Bola Bursar",
    connected_at: "2026-09-29T10:00:00Z",
  },
  may_write: true,
};
const BANKS = { banks: [{ name: "Access Bank", code: "044" }, { name: "Wema Bank", code: "035" }] };
const ACCOUNT = { bank_code: "035", account_number: "0123456789" };

function serve(routes) {
  return async (url, options = {}) => {
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    for (const [match, answer] of routes) {
      if (url === match || (match.endsWith("*") && url.startsWith(match.slice(0, -1)))) {
        const value = typeof answer === "function" ? answer(options, url) : answer;
        return { status: value.status, json: async () => value.body };
      }
    }
    throw new Error(`no stub for ${url}`);
  };
}

test("with no bank connected it says so, and only a writer is offered the button", () => {
  assert.match(states.status(NONE), /No bank account is connected/);
  assert.match(states.status(NONE), /data-action="start"/);
  const reader = states.status({ connected: null, may_write: false });
  assert.doesNotMatch(reader, /data-action="start"/);
  assert.match(reader, /bursar or an administrator/);
});

test("it always says the money goes straight to the school and Classnode never holds it", () => {
  for (const html of [states.status(NONE), states.status(CONNECTED), states.confirm({ accountName: "X", account: ACCOUNT })]) {
    assert.match(html, /Classnode never holds the money/);
    assert.match(html, /the school pays Paystack(?:'|&#39;)s fees/);
  }
});

test("a connected account shows the name, the bank and the number as given", () => {
  const html = states.status({ ...CONNECTED, connected: { ...CONNECTED.connected, account_number: "******6789" } });

  assert.match(html, /ST MARYS COLLEGE/);
  assert.match(html, /Wema Bank/);
  assert.match(html, /\*\*\*\*\*\*6789/);
  assert.match(html, /Connected by Bola Bursar/);
});

test("text the server sends cannot run as markup", () => {
  const html = states.status({ connected: { ...CONNECTED.connected, account_name: "<img src=x onerror=alert(1)>" }, may_write: false });

  assert.doesNotMatch(html, /<img src=x/);
  assert.match(html, /&lt;img/);
});

test("the states a whole page can be in", () => {
  assert.equal(refusalFor(403, {}), REFUSAL.NOT_ALLOWED);
  assert.equal(refusalFor(404, {}), REFUSAL.WRONG_HOST);
  assert.equal(refusalFor(401, { code: "session_expired" }), REFUSAL.EXPIRED);
  assert.equal(refusalFor(401, {}), REFUSAL.SIGNED_OUT);
  assert.equal(refusalFor(500), REFUSAL.BROKEN);
  assert.match(htmlFor({ step: REFUSAL.WRONG_HOST }), /own web address/);
  assert.match(htmlFor({ step: REFUSAL.BROKEN }), /not working/);
  assert.match(htmlFor({ step: REFUSAL.EXPIRED }), /session has ended/);
});

test("on the portal it never asks the API anything", async () => {
  forgetToken();
  const root = fakeRoot({});
  await mount(root, { fetchImpl: async () => { throw new Error("asked"); } });

  assert.match(root.innerHTML, /state-wrong-host/);
});

test("looking up the name writes nothing: the first submit posts only to resolve", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  const seen = [];
  const fetchImpl = serve([
    ["/api/fees/bank/banks/", () => ({ status: 200, body: BANKS })],
    ["/api/fees/bank/resolve/", (o) => { seen.push(["resolve", JSON.parse(o.body)]); return { status: 200, body: { account_name: "ST MARYS COLLEGE" } }; }],
    ["/api/fees/bank/", (o) => { seen.push([o.method || "GET"]); return { status: 200, body: NONE }; }],
  ]);
  await mount(root, { fetchImpl });
  await root.click({ "data-action": "start" });
  assert.match(root.innerHTML, /data-state="form"/);
  assert.match(root.innerHTML, /Access Bank/);

  await root.submit(ACCOUNT);

  assert.deepEqual(seen, [["GET"], ["resolve", ACCOUNT]]);
  assert.match(root.innerHTML, /data-state="confirm"/);
  assert.match(root.innerHTML, /ST MARYS COLLEGE/);
  assert.match(root.innerHTML, /Wema Bank/);
});

test("confirming posts the name that was shown, once, and then shows the connection", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  const writes = [];
  const fetchImpl = serve([
    ["/api/fees/bank/banks/", () => ({ status: 200, body: BANKS })],
    ["/api/fees/bank/resolve/", () => ({ status: 200, body: { account_name: "ST MARYS COLLEGE" } })],
    ["/api/fees/bank/", (o) => {
      if (o.method === "POST") { writes.push(JSON.parse(o.body)); return { status: 201, body: CONNECTED }; }
      return { status: 200, body: NONE };
    }],
  ]);
  await mount(root, { fetchImpl });
  await root.click({ "data-action": "start" });
  await root.submit(ACCOUNT);

  await root.submit({ confirm: "yes" });

  assert.deepEqual(writes, [{ ...ACCOUNT, account_name: "ST MARYS COLLEGE" }]);
  assert.match(root.innerHTML, /data-state="status"/);
  assert.match(root.innerHTML, /Connected by Bola Bursar/);
});

test("going back from the name returns to the form with what was typed", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  const fetchImpl = serve([
    ["/api/fees/bank/banks/", () => ({ status: 200, body: BANKS })],
    ["/api/fees/bank/resolve/", () => ({ status: 200, body: { account_name: "SOMEONE" } })],
    ["/api/fees/bank/", () => ({ status: 200, body: NONE })],
  ]);
  await mount(root, { fetchImpl });
  await root.click({ "data-action": "start" });
  await root.submit(ACCOUNT);

  await root.click({ "data-action": "back" });

  assert.match(root.innerHTML, /data-state="form"/);
  assert.match(root.innerHTML, /value="0123456789"/);
  assert.match(root.innerHTML, /<option value="035" selected>/);
});

test("the bank changing the name keeps the confirm step up with the server's sentence", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  const fetchImpl = serve([
    ["/api/fees/bank/banks/", () => ({ status: 200, body: BANKS })],
    ["/api/fees/bank/resolve/", () => ({ status: 200, body: { account_name: "ST MARYS COLLEGE" } })],
    ["/api/fees/bank/", (o) =>
      o.method === "POST"
        ? { status: 409, body: { detail: "The bank now gives a different name for that account." } }
        : { status: 200, body: NONE }],
  ]);
  await mount(root, { fetchImpl });
  await root.click({ "data-action": "start" });
  await root.submit(ACCOUNT);

  await root.submit({ confirm: "yes" });

  assert.match(root.innerHTML, /data-state="confirm"/);
  assert.match(root.innerHTML, /different name/);
});

test("an account the bank does not have returns to the form with the sentence", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  const fetchImpl = serve([
    ["/api/fees/bank/banks/", () => ({ status: 200, body: BANKS })],
    ["/api/fees/bank/resolve/", () => ({ status: 422, body: { detail: "The bank has no account with that number." } })],
    ["/api/fees/bank/", () => ({ status: 200, body: NONE })],
  ]);
  await mount(root, { fetchImpl });
  await root.click({ "data-action": "start" });

  await root.submit(ACCOUNT);

  assert.match(root.innerHTML, /data-state="form"/);
  assert.match(root.innerHTML, /no account with that number/);
  assert.match(root.innerHTML, /value="0123456789"/);
});

test("Paystack being down when the bank list is asked for keeps the status page with a sentence", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  const fetchImpl = serve([
    ["/api/fees/bank/banks/", () => ({ status: 503, body: { detail: "Paystack is not available right now." } })],
    ["/api/fees/bank/", () => ({ status: 200, body: NONE })],
  ]);
  await mount(root, { fetchImpl });

  await root.click({ "data-action": "start" });

  assert.match(root.innerHTML, /data-state="status"/);
  assert.match(root.innerHTML, /Paystack is not available/);
});

test("a principal reading the page is refused the writes, not shown a broken page", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  const fetchImpl = serve([
    ["/api/fees/bank/", () => ({ status: 200, body: { ...CONNECTED, may_write: false } })],
  ]);

  await mount(root, { fetchImpl });

  assert.doesNotMatch(root.innerHTML, /data-action="start"/);
  assert.match(root.innerHTML, /ST MARYS COLLEGE/);
});
