/**
 * "Create accounts for this class": the button, the words after a press, and the flow.
 *
 * What is asserted above all: **the words tell the truth about a press**: how many were
 * made, how many already had one, each failure by name with its sentence, and how many
 * are left; they read "done" only when nothing failed and nothing stopped it. The button
 * is offered only to a login that may press it, at a school with a bank, while some child
 * still has none.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { classAccountsNote, mount } from "../../static/fees/app.js";
import { makeClassAccounts } from "../../static/fees/api.js";
import * as states from "../../static/fees/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const CLASS_BODY = (extra = {}) => ({
  class_group_id: 5,
  class_group: "JSS 1A",
  term_id: 3,
  term: "First term 2025/2026",
  children: [
    { student_membership_id: 11, student: "Ada Obi", reference: "A1", balance_kobo: 0 },
    { student_membership_id: 12, student: "Chidi Okafor", reference: "", balance_kobo: 0 },
  ],
  may_remind: false,
  may_make_accounts: true,
  accounts_missing: 2,
  ...extra,
});

// -- the words -----------------------------------------------------------------------

test("a clean press says how many were made, and reads done", () => {
  const { note, tone } = classAccountsNote({ made: 3, skipped: 0, failed: [], remaining: 0, stopped: null });

  assert.equal(note, "Made 3 accounts.");
  assert.equal(tone, "done");
});

test("skipped, failed and remaining are all said, and a failure reads stop", () => {
  const { note, tone } = classAccountsNote({
    made: 12,
    skipped: 3,
    failed: [{ student: "Chidi Okafor", detail: "Paystack would not make that account: Customer is not eligible" }],
    remaining: 8,
    stopped: null,
  });

  assert.match(note, /Made 12 accounts\./);
  assert.match(note, /3 children already had one\./);
  assert.match(note, /1 account could not be made: Chidi Okafor \(Paystack would not make that account: Customer is not eligible\)\./);
  assert.match(note, /8 more to do: press the button again\./);
  assert.equal(tone, "stop");
});

test("singulars read as singulars", () => {
  const { note } = classAccountsNote({ made: 1, skipped: 1, failed: [], remaining: 0, stopped: null });

  assert.equal(note, "Made 1 account. 1 child already had one.");
});

test("Paystack stopping the batch is said, and reads stop", () => {
  const { note, tone } = classAccountsNote({ made: 0, skipped: 0, failed: [], remaining: 3, stopped: "Paystack is not available right now, so the rest were not tried." });

  assert.match(note, /Paystack is not available right now/);
  assert.match(note, /3 more to do/);
  assert.equal(tone, "stop");
});

test("a class where everyone already has one says so, plainly", () => {
  const { note, tone } = classAccountsNote({ made: 0, skipped: 3, failed: [], remaining: 0, stopped: null });

  assert.match(note, /3 children already had one\./);
  assert.match(classAccountsNote({ made: 0, skipped: 0, failed: [], remaining: 0, stopped: null }).note, /Every child in this class already has an account/);
  assert.equal(tone, "done");
});

// -- the button ---------------------------------------------------------------------------

test("the button is offered while some child has none, and says how many", () => {
  const html = states.classBalances({ classBalances: CLASS_BODY() });

  assert.match(html, /data-action="make-class-accounts" data-class="5"/);
  assert.match(html, /Create accounts for this class \(2 children have none\)/);
  assert.match(states.classBalances({ classBalances: CLASS_BODY({ accounts_missing: 1 }) }), /1 child has none/);
});

test("with none missing it says so and offers no button", () => {
  const html = states.classBalances({ classBalances: CLASS_BODY({ accounts_missing: 0 }) });

  assert.doesNotMatch(html, /make-class-accounts/);
  assert.match(html, /Every child in this class has an account to pay into/);
});

test("a login that may not press it, or a school with no bank, is offered nothing", () => {
  const html = states.classBalances({ classBalances: CLASS_BODY({ may_make_accounts: false, accounts_missing: 0 }) });

  assert.doesNotMatch(html, /make-class-accounts|has an account to pay into/);
});

// -- the api ----------------------------------------------------------------------------------

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

test("pressing posts to the class's own route with the term the page is on", async () => {
  forgetToken();
  const { fetchImpl, writes } = serve([["/api/fees/virtual/classes/5/", { status: 200, body: { made: 2 } }]]);

  const answer = await makeClassAccounts({ classId: 5, termId: 3, fetchImpl });

  assert.equal(answer.ok, true);
  assert.deepEqual(writes(), [["POST", "/api/fees/virtual/classes/5/", { term_id: 3 }]]);
});

test("409 and 422 carry a sentence and 404 is a page-wide refusal", async () => {
  for (const [status, note] of [[409, true], [422, true], [403, true], [404, false]]) {
    forgetToken();
    const { fetchImpl } = serve([["/api/fees/virtual/classes/5/", { status, body: { detail: "A sentence." } }]]);
    const answer = await makeClassAccounts({ classId: 5, fetchImpl });
    assert.equal(answer.ok, false, String(status));
    assert.equal(answer.refusal === null, note, String(status));
  }
});

// -- the flow ------------------------------------------------------------------------------------

const BOOKS = { terms: [{ term_id: 3, term: "First term 2025/2026", is_current: true }], term_id: 3, term: "First term 2025/2026", may_write: true, classes: [{ class_group_id: 5, class_group: "JSS 1A", children: 2 }], may_remind: false };

async function openClass(root, fetchImpl) {
  await mount(root, { fetchImpl, search: "" });
  await root.click({ "data-action": "open-class", "data-class": "5" });
}

test("pressing it shows what was made, refreshes the class, and the button goes when none are missing", async () => {
  forgetToken();
  let class_calls = 0;
  const { fetchImpl, writes } = serve([
    ["/api/fees/virtual/classes/5/", { status: 200, body: { made: 2, skipped: 0, failed: [], remaining: 0, stopped: null } }],
    ["/api/fees/classes/5/?term_id=3", () => ({ status: 200, body: CLASS_BODY(++class_calls > 1 ? { accounts_missing: 0 } : {}) })],
    ["/api/fees/classes/", { status: 200, body: BOOKS }],
  ]);
  const root = fakeRoot({ onSchool: "yes" });
  await openClass(root, fetchImpl);
  assert.match(root.innerHTML, /make-class-accounts/);
  assert.deepEqual(writes(), []);

  await root.click({ "data-action": "make-class-accounts", "data-class": "5" });

  assert.deepEqual(writes(), [["POST", "/api/fees/virtual/classes/5/", { term_id: 3 }]]);
  assert.match(root.innerHTML, /Made 2 accounts\./);
  assert.doesNotMatch(root.innerHTML, /data-action="make-class-accounts"/);
});

test("a failure is shown by name and the button stays for another go", async () => {
  forgetToken();
  const { fetchImpl } = serve([
    ["/api/fees/virtual/classes/5/", { status: 200, body: { made: 1, skipped: 0, failed: [{ student_membership_id: 12, student: "Chidi Okafor", detail: "Customer is not eligible" }], remaining: 0, stopped: null } }],
    ["/api/fees/classes/5/?term_id=3", { status: 200, body: CLASS_BODY({ accounts_missing: 1 }) }],
    ["/api/fees/classes/", { status: 200, body: BOOKS }],
  ]);
  const root = fakeRoot({ onSchool: "yes" });
  await openClass(root, fetchImpl);

  await root.click({ "data-action": "make-class-accounts", "data-class": "5" });

  assert.match(root.innerHTML, /1 account could not be made: Chidi Okafor \(Customer is not eligible\)/);
  assert.match(root.innerHTML, /data-action="make-class-accounts"/);
});

test("no bank yet: the sentence is shown and the class page stays", async () => {
  forgetToken();
  const { fetchImpl } = serve([
    ["/api/fees/virtual/classes/5/", { status: 409, body: { detail: "Connect the school's bank account before making accounts for children." } }],
    ["/api/fees/classes/5/?term_id=3", { status: 200, body: CLASS_BODY() }],
    ["/api/fees/classes/", { status: 200, body: BOOKS }],
  ]);
  const root = fakeRoot({ onSchool: "yes" });
  await openClass(root, fetchImpl);

  await root.click({ "data-action": "make-class-accounts", "data-class": "5" });

  assert.match(root.innerHTML, /data-state="class"/);
  assert.match(root.innerHTML, /Connect the school(?:'|&#39;)s bank account/);
});
