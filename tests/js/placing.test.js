/**
 * Placing an unmatched payment on a child, and the platform's list of payments no
 * school owns.
 *
 * What is asserted above all: **nothing is written until the last button.** Picking
 * a class, picking a child and reviewing post nothing; the one write sends the child
 * and the amount and reference exactly as they were read back, and a refusal keeps the
 * page up with the server's sentence. A login that may not place is offered no button.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { mount } from "../../static/bank/app.js";
import { placePayment } from "../../static/bank/api.js";
import * as bankStates from "../../static/bank/states.js";
import { mount as mountPlatform } from "../../static/platform/app.js";
import { fetchUnrouted } from "../../static/platform/api.js";
import { unroutedList } from "../../static/platform/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const OPEN = {
  payment_id: 7,
  reference: "REF-A",
  amount_kobo: 5_000_000,
  account_number: "9000000001",
  reason: "wrong_customer",
  reason_label: "Paystack says a different customer paid into it",
  placed: null,
};
const PLACED = {
  ...OPEN,
  payment_id: 8,
  reference: "REF-B",
  amount_kobo: 250_050,
  placed: { student: "Ada Obi", placed_by: "Bola Bursar", student_membership_id: 1, entry_id: 3 },
};
const STATE = { connected: null, may_write: true };
const CLASSES = { term_id: 4, terms: [], classes: [{ class_group_id: 2, class_group: "JSS 1A", children: 2 }] };
const CHILDREN = {
  children: [
    { student_membership_id: 11, student: "Ada Obi", reference: "A1", balance_kobo: 0 },
    { student_membership_id: 12, student: "Chidi Okafor", reference: "", balance_kobo: 0 },
  ],
};

function serve(routes) {
  const seen = [];
  const fetchImpl = async (url, options = {}) => {
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    seen.push([options.method || "GET", url, options.body ? JSON.parse(options.body) : null]);
    for (const [match, answer] of routes) {
      if (url === match || (match.endsWith("*") && url.startsWith(match.slice(0, -1)))) {
        const value = typeof answer === "function" ? answer(options, url) : answer;
        return { status: value.status, json: async () => value.body };
      }
    }
    throw new Error(`no stub for ${url}`);
  };
  return { fetchImpl, seen, writes: () => seen.filter(([m]) => m !== "GET") };
}

const routes = ({ mayPlace = true, unmatched = [OPEN, PLACED], placement } = {}) => [
  ["/api/fees/bank/", { status: 200, body: STATE }],
  ["/api/fees/virtual/unmatched/7/placement/", placement || { status: 201, body: { created: true, balance_kobo: -5_000_000, placed: { student: "Ada Obi", placed_by: "Bola Bursar" } } }],
  ["/api/fees/virtual/unmatched/", { status: 200, body: { payments: unmatched, may_place: mayPlace } }],
  ["/api/fees/classes/2/?term_id=4", { status: 200, body: CHILDREN }],
  ["/api/fees/classes/", { status: 200, body: CLASSES }],
];

// -- the list -------------------------------------------------------------------

test("a payment still waiting is offered a button, and one already placed says where it went", () => {
  const html = bankStates.unmatchedList([OPEN, PLACED], { mayPlace: true });

  assert.match(html, /data-action="place" data-payment="7"/);
  assert.doesNotMatch(html, /data-payment="8"/);
  assert.match(html, /Placed on Ada Obi by Bola Bursar/);
  assert.match(html, /NGN 2,500\.50/);
});

test("a login that may not place is offered no button", () => {
  assert.doesNotMatch(bankStates.unmatchedList([OPEN], { mayPlace: false }), /data-action="place"/);
  assert.doesNotMatch(bankStates.unmatchedList([OPEN]), /data-action="place"/);
});

test("the names and the reference in the list are escaped", () => {
  const html = bankStates.unmatchedList(
    [{ ...OPEN, reference: "<b>R</b>" }, { ...PLACED, placed: { ...PLACED.placed, student: "<i>x</i>" } }],
    { mayPlace: true },
  );

  assert.doesNotMatch(html, /<b>R<\/b>|<i>x<\/i>/);
  assert.match(html, /&lt;b&gt;R/);
});

// -- the api ---------------------------------------------------------------------

test("placing posts the child and the confirmed amount and reference to the payment's own route", async () => {
  forgetToken();
  const { fetchImpl, writes } = serve(routes());

  const answer = await placePayment({ paymentId: 7, studentId: 11, amountKobo: 5_000_000, reference: "REF-A", fetchImpl });

  assert.equal(answer.ok, true);
  assert.deepEqual(writes(), [
    ["POST", "/api/fees/virtual/unmatched/7/placement/", { student_membership_id: 11, amount_kobo: 5_000_000, reference: "REF-A" }],
  ]);
});

test("409 and 422 carry a sentence, 200 is success, and 403 and 404 are page-wide refusals", async () => {
  for (const [status, ok, note] of [[201, true], [200, true], [409, false, true], [422, false, true], [403, false, false], [404, false, false]]) {
    forgetToken();
    const { fetchImpl } = serve([["/api/fees/virtual/unmatched/7/placement/", { status, body: { detail: "A sentence." } }]]);
    const answer = await placePayment({ paymentId: 7, studentId: 11, amountKobo: 1, reference: "R", fetchImpl });
    assert.equal(answer.ok, ok, String(status));
    if (!ok) assert.equal(Boolean(answer.note), note, String(status));
  }
});

// -- the flow -----------------------------------------------------------------------

async function toConfirm(root, fetchImpl) {
  await mount(root, { fetchImpl });
  await root.click({ "data-action": "place", "data-payment": "7" });
  await root.change({ "data-field": "class" }, "2");
  await root.change({ "data-field": "child" }, "11");
  await root.submit({ class_group: "2", child: "11" });
}

test("nothing is written until the last button: picking, and reviewing, post nothing", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  const { fetchImpl, writes } = serve(routes());

  await toConfirm(root, fetchImpl);

  assert.deepEqual(writes(), []);
  assert.match(root.innerHTML, /data-state="place-confirm"/);
  assert.match(root.innerHTML, /NGN 50,000/);
  assert.match(root.innerHTML, /REF-A/);
  assert.match(root.innerHTML, /Ada Obi/);
});

test("choosing a class reads its children for the chosen term, and the child list follows it", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  const { fetchImpl, seen } = serve(routes());
  await mount(root, { fetchImpl });
  await root.click({ "data-action": "place", "data-payment": "7" });
  assert.match(root.innerHTML, /<select name="child" data-field="child" disabled>/);

  await root.change({ "data-field": "class" }, "2");

  assert.ok(seen.some(([, url]) => url === "/api/fees/classes/2/?term_id=4"));
  assert.match(root.innerHTML, /Chidi Okafor/);
  assert.doesNotMatch(root.innerHTML, /<select name="child" data-field="child" disabled>/);
});

test("reviewing with no child chosen says so and posts nothing", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  const { fetchImpl, writes } = serve(routes());
  await mount(root, { fetchImpl });
  await root.click({ "data-action": "place", "data-payment": "7" });

  await root.submit({ class_group: "", child: "" });

  assert.match(root.innerHTML, /Choose the class and then the child/);
  assert.match(root.innerHTML, /data-state="place"/);
  assert.deepEqual(writes(), []);
});

test("confirming posts once, with the amount and reference exactly as they were read back", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  const { fetchImpl, writes } = serve(routes());
  await toConfirm(root, fetchImpl);

  await root.submit({ confirm: "yes" });

  assert.deepEqual(writes(), [
    ["POST", "/api/fees/virtual/unmatched/7/placement/", { student_membership_id: 11, amount_kobo: 5_000_000, reference: "REF-A" }],
  ]);
  assert.match(root.innerHTML, /data-state="status"/);
  assert.match(root.innerHTML, /Placed on Ada Obi/);
});

test("going back from the review keeps the class and child that were chosen", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  const { fetchImpl } = serve(routes());
  await toConfirm(root, fetchImpl);

  await root.click({ "data-action": "back-to-pick" });

  assert.match(root.innerHTML, /data-state="place"/);
  assert.match(root.innerHTML, /<option value="2" selected>JSS 1A/);
  assert.match(root.innerHTML, /<option value="11" selected>Ada Obi/);
});

test("a refusal keeps the review up with the server's sentence", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  const { fetchImpl } = serve(
    routes({ placement: { status: 409, body: { detail: "This payment was already placed on Chidi Okafor by Ade Admin." } } }),
  );
  await toConfirm(root, fetchImpl);

  await root.submit({ confirm: "yes" });

  assert.match(root.innerHTML, /data-state="place-confirm"/);
  assert.match(root.innerHTML, /already placed on Chidi Okafor by Ade Admin/);
});

test("cancelling returns to the list and posts nothing", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  const { fetchImpl, writes } = serve(routes());
  await mount(root, { fetchImpl });
  await root.click({ "data-action": "place", "data-payment": "7" });

  await root.click({ "data-action": "cancel-place" });

  assert.match(root.innerHTML, /data-state="status"/);
  assert.match(root.innerHTML, /Payments we could not match/);
  assert.deepEqual(writes(), []);
});

test("a reader sees the list and no button", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  const { fetchImpl } = serve(routes({ mayPlace: false }));

  await mount(root, { fetchImpl });

  assert.match(root.innerHTML, /Payments we could not match/);
  assert.doesNotMatch(root.innerHTML, /data-action="place"/);
});

test("the classes not being readable keeps the list, with a sentence", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  const { fetchImpl } = serve([
    ...routes().filter(([url]) => url !== "/api/fees/classes/"),
    ["/api/fees/classes/", { status: 500, body: {} }],
  ]);
  await mount(root, { fetchImpl });

  await root.click({ "data-action": "place", "data-payment": "7" });

  assert.match(root.innerHTML, /data-state="status"/);
  assert.match(root.innerHTML, /classes could not be read/);
});

// -- the platform's list ----------------------------------------------------------------

test("the platform lists payments no school owns, in whole kobo, escaped, and offers nothing to do with them", () => {
  const html = unroutedList([
    { reference: "REF-1", amount_kobo: 15_000_050, account_number: "0000000000" },
    { reference: "<b>R</b>", amount_kobo: 100, account_number: "" },
  ]);

  assert.match(html, /2 payments no school owns/);
  assert.match(html, /NGN 150,000\.50/);
  assert.match(html, /account unknown/);
  assert.doesNotMatch(html, /<b>R<\/b>/);
  assert.doesNotMatch(html, /<button|data-action/);
  assert.equal(unroutedList([]), "");
});

test("the platform page shows them beside the schools, and says nothing when they cannot be read", async () => {
  forgetToken();
  const schools = { status: 200, body: { schools: [{ name: "St Mary's", subdomain: "st-marys", host: "st-marys.example", students: 5 }] } };
  const withThem = fakeRoot({});
  await mountPlatform(withThem, {
    fetchImpl: serve([
      ["/api/platform/schools/", schools],
      ["/api/platform/unrouted/", { status: 200, body: { payments: [{ reference: "REF-1", amount_kobo: 5_000_000, account_number: "1" }] } }],
    ]).fetchImpl,
  });
  const without = fakeRoot({});
  await mountPlatform(without, { fetchImpl: serve([["/api/platform/schools/", schools]]).fetchImpl });

  assert.match(withThem.innerHTML, /1 payment no school owns/);
  assert.match(withThem.innerHTML, /St Mary/);
  assert.doesNotMatch(without.innerHTML, /no school owns/);
  assert.match(without.innerHTML, /St Mary/);
  assert.deepEqual(await fetchUnrouted({ fetchImpl: async () => { throw new Error("down"); } }), []);
});
