/**
 * Where families pay, on the three pages that show it, and the bursar's list of
 * payments that could not be placed.
 *
 * What is asserted above all: **the account is drawn exactly as the server gave
 * it and escaped**, a child with no account gets no line and no invented one, a
 * reader who may not write is offered no button, and an unmatched payment is
 * listed with its amount in whole kobo formatted by hand, never a float.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { makeAccount, virtualAccountUrl } from "../../static/fees/api.js";
import * as feeStates from "../../static/fees/states.js";
import { htmlFor as indexHtml } from "../../static/index/app.js";
import { naira, status, unmatchedList } from "../../static/bank/states.js";
import { forgetToken } from "../../static/web/http.js";

const LINE = { bank_name: "Wema Bank", account_number: "9000000001", account_name: "ADA OBI" };

function serve(answer) {
  return async (url, options = {}) => {
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    return { status: answer.status, json: async () => answer.body, seen: [url, options] };
  };
}

// -- the bursar's account page -------------------------------------------------

test("a child's account page says where the family pays, escaped", () => {
  const html = feeStates.account({
    account: { student: "Ada", may_write: true, pay_into: { ...LINE, account_name: "<b>ADA</b>" }, bank_connected: true },
  });

  assert.match(html, /data-pay-into/);
  assert.match(html, /Wema Bank <strong>9000000001<\/strong>/);
  assert.doesNotMatch(html, /<b>ADA<\/b>/);
  assert.match(html, /&lt;b&gt;ADA/);
  assert.doesNotMatch(html, /data-action="make-account"/);
});

test("with a bank connected and no account yet the bursar is offered one", () => {
  const html = feeStates.account({ account: { student: "Ada", may_write: true, bank_connected: true } });

  assert.match(html, /data-action="make-account"/);
  assert.doesNotMatch(html, /data-pay-into/);
});

test("with no bank connected the bursar is told to connect one, and offered no button", () => {
  const html = feeStates.account({ account: { student: "Ada", may_write: true, bank_connected: false } });

  assert.doesNotMatch(html, /data-action="make-account"/);
  assert.match(html, /Connect the school(?:'|&#39;)s bank account/);
});

test("a reader who may not write is shown the account but never a button or a hint", () => {
  const shown = feeStates.account({ account: { student: "Ada", may_write: false, pay_into: LINE, bank_connected: true } });
  const none = feeStates.account({ account: { student: "Ada", may_write: false, bank_connected: true } });

  assert.match(shown, /9000000001/);
  assert.doesNotMatch(shown, /data-action="make-account"/);
  assert.doesNotMatch(none, /make-account|Connect the school|data-pay-into/);
});

test("making an account posts to the child's own route, and a sentence comes back for 409 and 503", async () => {
  forgetToken();
  assert.equal(virtualAccountUrl(12), "/api/fees/virtual/students/12/");
  for (const [status_, ok] of [[201, true], [200, true], [409, false], [422, false], [503, false]]) {
    forgetToken();
    const answer = await makeAccount({
      studentId: 12,
      fetchImpl: serve({ status: status_, body: ok ? { created: true } : { detail: "A sentence." } }),
    });
    assert.equal(answer.ok, ok, String(status_));
    if (!ok) {
      assert.equal(answer.refusal, null, `${status_} keeps the page up`);
      assert.equal(answer.body.detail, "A sentence.");
    }
  }
});

test("a 404 on making an account is the flat not-yours refusal, not a sentence", async () => {
  forgetToken();
  const answer = await makeAccount({ studentId: 12, fetchImpl: serve({ status: 404, body: {} }) });

  assert.equal(answer.ok, false);
  assert.notEqual(answer.refusal, null);
});

// -- the parent's page ----------------------------------------------------------

const FAMILY = {
  status: 200,
  body: {
    children: [
      { student_membership_id: 1, student_name: "Ada Obi", cards: [{ term_id: 5, term_label: "First term", academic_session: "2025/2026", version: 1 }] },
      { student_membership_id: 2, student_name: "Kemi Obi", cards: [{ term_id: 5, term_label: "First term", academic_session: "2025/2026", version: 1 }] },
    ],
  },
};

test("the parent's page says where to pay for the child who has an account, and only that child", () => {
  const html = indexHtml(FAMILY, { activeChild: 1, payInto: { 1: LINE } });

  const ada = html.match(/<section class="child" data-child="1".*?<\/section>/s)[0];
  const kemi = html.match(/<section class="child" data-child="2".*?<\/section>/s)[0];
  assert.match(ada, /Pay fees into: Wema Bank <strong>9000000001<\/strong>, ADA OBI/);
  assert.doesNotMatch(kemi, /Pay fees into/);
});

test("with no accounts the parent's page is what it always was", () => {
  const html = indexHtml(FAMILY, { activeChild: 1 });

  assert.doesNotMatch(html, /Pay fees into|data-pay-into/);
  assert.match(html, /First term/);
});

test("a family with no cards yet still sees where to pay", () => {
  const html = indexHtml(
    { status: 200, body: { children: [{ student_membership_id: 1, student_name: "Ada Obi", cards: [] }] } },
    { payInto: { 1: LINE } },
  );

  assert.match(html, /data-state="pay"/);
  assert.match(html, /Ada Obi: <p class="pay-into"/);
  assert.match(html, /9000000001/);
});

test("the account is escaped on the parent's page too", () => {
  const html = indexHtml(FAMILY, { activeChild: 1, payInto: { 1: { ...LINE, bank_name: "<script>x</script>" } } });

  assert.doesNotMatch(html, /<script>x/);
});

// -- the unmatched payments -----------------------------------------------------

test("money is formatted from whole kobo by hand", () => {
  assert.equal(naira(5_000_000), "NGN 50,000");
  assert.equal(naira(15_000_050), "NGN 150,000.50");
  assert.equal(naira(100), "NGN 1");
  assert.equal(naira(1), "NGN 0.01");
  assert.equal(naira(123_456_789_00), "NGN 123,456,789");
});

test("an unmatched payment is listed with what arrived and why it was not placed", () => {
  const html = unmatchedList([
    { reference: "REF-1", amount_kobo: 5_000_000, reason_label: "Paystack says a different customer paid into it" },
  ]);

  assert.match(html, /Payments we could not match/);
  assert.match(html, /NGN 50,000/);
  assert.match(html, /REF-1/);
  assert.match(html, /a different customer/);
  assert.match(html, /Nothing has been guessed/);
});

test("with none unmatched the page says nothing about it", () => {
  assert.equal(unmatchedList([]), "");
  assert.doesNotMatch(status({ connected: null, may_write: true, unmatched: [] }), /could not match/);
});

test("the list is on the bank page whether or not a bank is connected, and escaped", () => {
  const payments = [{ reference: "<i>R</i>", amount_kobo: 100, reason_label: "x" }];

  for (const connected of [null, { bank_name: "Wema", account_number: "1", account_name: "N", connected_by: "B" }]) {
    const html = status({ connected, may_write: false, unmatched: payments });
    assert.match(html, /Payments we could not match/);
    assert.doesNotMatch(html, /<i>R<\/i>/);
  }
});
