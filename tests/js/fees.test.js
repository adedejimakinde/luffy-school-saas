/**
 * The fees page: balances in words, one child's account, a payment, a
 * discount, an undo and a receipt. What it walks is `fees/api.py`.
 *
 * **A balance is said in words.** A family in credit being chased for money is
 * the mistake this page must not make, and a minus sign on a phone screen is
 * the character most easily missed — so the sign becomes "Owes" or "In
 * credit", and the test that pins it is the control for claim 6 in
 * `fees/tests/test_fees_api.py`.
 *
 * **Every form carries a key**, and a lost answer keeps it: sending again
 * cannot record a payment or a discount twice.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { htmlFor, mount } from "../../static/fees/app.js";
import { REFUSAL, refusalFor } from "../../static/fees/api.js";
import { balanceWords, naira, signed } from "../../static/fees/money.js";
import * as states from "../../static/fees/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const TERMS = [
  { term_id: 7, term: "2025/2026 First term", is_current: true },
  { term_id: 6, term: "2024/2025 Third term", is_current: false },
];

const PAYMENT = {
  entry_id: 41,
  kind: "payment",
  kind_label: "Payment",
  amount_kobo: -5_000_000,
  narration: "Payment received",
  reference: "TRF-2231",
  method: "bank_transfer",
  method_label: "Bank transfer",
  effective_on: "2025-10-01",
  term: "2025/2026 First term",
  reverses_id: null,
  reversed_by_id: null,
  receipt_number: "ST-MARYS-000041",
  may_reverse: true,
};

const CHARGE = {
  ...PAYMENT,
  entry_id: 40,
  kind: "charge",
  kind_label: "Charge",
  amount_kobo: 15_000_000,
  narration: "First term tuition",
  reference: "",
  method: "",
  method_label: "",
  receipt_number: null,
};

const account = (overrides = {}) => ({
  student_membership_id: 3,
  student: "Ada Obi",
  reference: "SM/001",
  balance_kobo: 10_000_000,
  may_write: true,
  terms: TERMS,
  methods: [
    { value: "cash", label: "Cash" },
    { value: "bank_transfer", label: "Bank transfer" },
  ],
  entries: [PAYMENT, CHARGE],
  ...overrides,
});

function serve(routes) {
  const posted = [];
  //: PUT and DELETE, apart from `posted` so the POST tests read as before.
  const others = [];
  const impl = async (url, options = {}) => {
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    if (options.method === "POST") posted.push({ url, body: JSON.parse(options.body) });
    if (options.method === "PUT" || options.method === "DELETE") {
      others.push({ method: options.method, url, body: options.body === undefined ? undefined : JSON.parse(options.body) });
    }
    for (const [match, answer] of routes) {
      if (url.includes(match)) {
        const value = typeof answer === "function" ? answer(options) : answer;
        if (value instanceof Error) throw value;
        return { status: value.status, json: async () => value.body };
      }
    }
    throw new Error(`no stub for ${url}`);
  };
  impl.posted = posted;
  impl.others = others;
  return impl;
}

function keys() {
  let n = 0;
  return () => `key-${++n}`;
}

// -- money in words -------------------------------------------------------------

test("kobo become naira by cutting digits, never through a float", () => {
  assert.equal(naira(150_005_000), "₦1,500,050.00");
  assert.equal(naira(5), "₦0.05");
  assert.equal(naira(-1_000_010), "₦10,000.10");
});

test("a credit reads as in credit, not owing", () => {
  // CONTROL 6: the renderer dropping the minus sign makes this red — a family
  // the school owes ₦5,000 would be told it owes ₦5,000.
  assert.deepEqual(balanceWords(-500_000), { tone: "credit", text: "In credit ₦5,000.00" });

  const standing = states.account({ account: account({ balance_kobo: -500_000 }) });
  assert.match(standing, /data-balance="credit">In credit ₦5,000\.00</);
  assert.doesNotMatch(standing, /Owes/);

  const row = states.classBalances({
    classBalances: {
      class_group: "JSS 1A",
      term: "2025/2026 First term",
      children: [{ student_membership_id: 3, student: "Ada Obi", reference: "SM/001", balance_kobo: -500_000 }],
    },
  });
  assert.match(row, /In credit ₦5,000\.00/);
  assert.doesNotMatch(row, /Owes/);
});

test("a debt reads as owing, and nothing as nothing", () => {
  assert.deepEqual(balanceWords(500_000), { tone: "owes", text: "Owes ₦5,000.00" });
  assert.deepEqual(balanceWords(0), { tone: "settled", text: "Nothing owed" });
});

test("an entry's amount carries its direction", () => {
  assert.equal(signed(-5_000_000), "−₦50,000.00");
  assert.equal(signed(15_000_000), "+₦150,000.00");
  const html = states.account({ account: account() });
  assert.match(html, /<td class="num">−₦50,000\.00<\/td>/);
  assert.match(html, /<td class="num">\+₦150,000\.00<\/td>/);
});

// -- the account --------------------------------------------------------------

test("a reader who may not write sees the account and no form", () => {
  const html = states.account({ account: account({ may_write: false }) });

  assert.match(html, /Ada Obi/);
  assert.doesNotMatch(html, /<form/);
  assert.doesNotMatch(html, /data-action="discount"/);
  assert.doesNotMatch(html, /data-action="reverse"/);
});

test("a discount is behind a button, and its form asks why", () => {
  const closed = states.account({ account: account() });
  assert.match(closed, /data-action="discount"/);
  assert.doesNotMatch(closed, /data-discount/);

  const open = states.account({ account: account(), discounting: true });
  const form = open.slice(open.indexOf("<form class=\"discount\""), open.indexOf("</form>", open.indexOf("data-discount")));
  assert.match(form, /name="intent" value="discount"/);
  assert.match(form, /<input name="reason" maxlength="255"[^>]* required>/);
  assert.doesNotMatch(open, /data-action="discount"/);
});

test("each form names its intent", () => {
  const html = states.account({ account: account(), discounting: true, reversing: 41 });

  for (const intent of ["payment", "discount", "reversal"]) {
    assert.match(html, new RegExp(`name="intent" value="${intent}"`), intent);
  }
});

test("a name is escaped", () => {
  const html = states.account({ account: account({ student: "<img src=x onerror=alert(1)>" }) });

  assert.doesNotMatch(html, /<img/);
});

// -- the receipt --------------------------------------------------------------

const RECEIPT = {
  receipt_number: "ST-MARYS-000041",
  school: "St Mary's",
  student: "Ada Obi",
  student_reference: "SM/001",
  amount_kobo: 5_000_000,
  method_label: "Bank transfer",
  payment_reference: "TRF-2231",
  effective_on: "2025-10-01",
  term: "2025/2026 First term",
  narration: "Payment received",
  received_by: "Bola Bursar",
  reversed: null,
};

test("a receipt prints what the entry recorded", () => {
  const html = states.receipt({ receipt: RECEIPT });

  assert.match(html, /ST-MARYS-000041/);
  assert.match(html, /₦50,000\.00/);
  assert.match(html, /TRF-2231/);
  assert.doesNotMatch(html, /UNDONE/);
});

test("an undone payment's receipt says so across its face", () => {
  const html = states.receipt({
    receipt: { ...RECEIPT, reversed: { on: "2025-10-03", reason: "Keyed twice" } },
  });

  assert.match(html, /UNDONE on 2025-10-03: Keyed twice/);
});

// -- what an answer means -----------------------------------------------------

test("a 404 is one answer: not something you can open", () => {
  assert.equal(refusalFor(404, {}), REFUSAL.NOT_YOURS);
  assert.match(htmlFor({ step: REFUSAL.NOT_YOURS }), /not something you can open/);
});

// -- writing, through mount() ---------------------------------------------------

async function openAccount(fetchImpl, newKey = keys()) {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  await mount(root, { fetchImpl, search: "?student=3", newKey, today: "2025-10-05" });
  return root;
}

const payment = { intent: "payment", term_id: "7", amount: "50,000", method: "cash", reference: "", effective_on: "2025-10-01" };
const discount = { intent: "discount", term_id: "7", amount: "15,000", reason: "Second child" };

test("a payment goes with its form's key, and the next form gets a new one", async () => {
  const fetchImpl = serve([
    ["/payments/", { status: 201, body: { entry: PAYMENT, posted: true, balance_kobo: 10_000_000 } }],
    ["/students/3/", { status: 200, body: account() }],
  ]);
  const root = await openAccount(fetchImpl);

  await root.submit(payment);
  await root.submit(payment);

  const keysSent = fetchImpl.posted.map((p) => p.body.form_key);
  assert.equal(keysSent.length, 2);
  assert.notEqual(keysSent[0], keysSent[1], "a new form reused the last one's key");
  assert.match(root.innerHTML, /Payment recorded\. Receipt ST-MARYS-000041\./);
});

test("a lost answer keeps the key, so sending again cannot pay twice", async () => {
  let first = true;
  const fetchImpl = serve([
    [
      "/payments/",
      () => {
        if (first) {
          first = false;
          return new Error("connection reset");
        }
        return { status: 200, body: { entry: PAYMENT, posted: false, balance_kobo: 10_000_000 } };
      },
    ],
    ["/students/3/", { status: 200, body: account() }],
  ]);
  const root = await openAccount(fetchImpl);

  await root.submit(payment);
  assert.match(root.innerHTML, /could not tell whether that payment was saved/);
  assert.match(root.innerHTML, /value="50,000"/, "what was typed was lost");

  await root.submit(payment);

  const keysSent = fetchImpl.posted.map((p) => p.body.form_key);
  assert.equal(keysSent.length, 2);
  assert.equal(keysSent[0], keysSent[1], "the retry went under a new key");
  assert.match(root.innerHTML, /already recorded; nothing new was added/);
});

test("a discount goes with its reason and a key of its own", async () => {
  const fetchImpl = serve([
    ["/payments/", { status: 201, body: { entry: PAYMENT, posted: true, balance_kobo: 10_000_000 } }],
    ["/discounts/", { status: 201, body: { entry: { ...PAYMENT, kind: "discount" }, posted: true, balance_kobo: 8_500_000 } }],
    ["/students/3/", { status: 200, body: account() }],
  ]);
  const root = await openAccount(fetchImpl);

  await root.click({ "data-action": "discount" });
  assert.match(root.innerHTML, /data-discount/);
  await root.submit(discount);

  const [sent] = fetchImpl.posted;
  assert.match(sent.url, /\/api\/fees\/students\/3\/discounts\/$/);
  assert.deepEqual(sent.body, { term_id: 7, amount: "15,000", reason: "Second child", form_key: "key-2" });
  assert.match(root.innerHTML, /Discount given/);
  assert.doesNotMatch(root.innerHTML, /data-discount/, "the form stayed open after it posted");
});

test("a discount the server refuses keeps what was typed and says why", async () => {
  const fetchImpl = serve([
    ["/discounts/", { status: 422, body: { detail: "Say why, in a few words. The books keep the reason." } }],
    ["/students/3/", { status: 200, body: account() }],
  ]);
  const root = await openAccount(fetchImpl);

  await root.click({ "data-action": "discount" });
  await root.submit({ ...discount, reason: "" });

  assert.match(root.innerHTML, /Say why, in a few words/);
  assert.match(root.innerHTML, /value="15,000"/);
  assert.match(root.innerHTML, /data-discount/);
});

test("an undo sends its reason", async () => {
  const fetchImpl = serve([
    ["/reversal/", { status: 201, body: { entry: { ...PAYMENT, kind: "reversal" }, balance_kobo: 15_000_000 } }],
    ["/students/3/", { status: 200, body: account() }],
  ]);
  const root = await openAccount(fetchImpl);

  await root.click({ "data-action": "reverse", "data-entry": "41" });
  await root.submit({ intent: "reversal", reason: "Keyed twice" });

  assert.deepEqual(fetchImpl.posted, [{ url: "/api/fees/entries/41/reversal/", body: { reason: "Keyed twice" } }]);
  assert.match(root.innerHTML, /Undone\./);
});

// -- B2: bills ------------------------------------------------------------------

const bill = (overrides = {}) => ({
  class_group_id: 5,
  class_group: "JSS 1A",
  term_id: 7,
  term: "2025/2026 First term",
  may_write: true,
  schedule_id: 9,
  lines: [
    { line_id: 1, description: "Tuition", amount_kobo: 15_000_000, charged: 2 },
    { line_id: 2, description: "Uniform", amount_kobo: 500_000, charged: 0 },
  ],
  total_kobo: 15_500_000,
  children: 2,
  ...overrides,
});

const BILLS = {
  terms: TERMS,
  term_id: 7,
  term: "2025/2026 First term",
  may_write: true,
  classes: [
    { class_group_id: 5, class_group: "JSS 1A", children: 2, schedule_id: 9, lines: 2, total_kobo: 15_500_000 },
    { class_group_id: 6, class_group: "JSS 2A", children: 0, schedule_id: null, lines: 0, total_kobo: 0 },
  ],
};

async function openBill(fetchImpl) {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  await mount(root, { fetchImpl, newKey: keys(), today: "2025-10-05" });
  await root.click({ "data-action": "open-bills" });
  await root.click({ "data-action": "open-bill", "data-class": "5" });
  return root;
}

const billRoutes = (extra = []) => [
  ...extra,
  ["/api/fees/bills/", { status: 200, body: BILLS }],
  ["/bill/?term_id=", { status: 200, body: bill() }],
  ["/api/fees/classes/", { status: 200, body: { terms: TERMS, term_id: 7, term: "2025/2026 First term", may_write: true, classes: [] } }],
];

test("the bills list says which classes have a bill and which do not", () => {
  const html = states.bills({ bills: BILLS });
  assert.match(html, /JSS 1A<\/button> <span class="quiet">2 lines, ₦155,000\.00; 2 children/);
  assert.match(html, /JSS 2A<\/button> <span class="quiet">no bill yet; 0 children/);
});

test("a line says how many it charged, and one that charged anybody cannot be removed", () => {
  const html = states.bill({ bill: bill() });
  assert.match(html, /charged 2/);
  assert.match(html, /nobody charged yet/);
  assert.match(html, /data-action="remove-line" data-line="2"/);
  assert.doesNotMatch(html, /data-action="remove-line" data-line="1"/);
  assert.match(html, /<th>Total<\/th><th class="num">₦155,000\.00/);
});

test("a reader sees the bill and no way to change it", () => {
  const html = states.bill({ bill: bill({ may_write: false }) });
  assert.match(html, /Tuition/);
  assert.doesNotMatch(html, /data-line-add|data-action="change-line"|data-action="remove-line"|charge-class/);
});

test("a line is added for the term on screen, and the bill is drawn from the answer", async () => {
  const after = bill({ lines: [...bill().lines, { line_id: 3, description: "PTA levy", amount_kobo: 1_500_000, charged: 0 }] });
  const fetchImpl = serve(billRoutes([["/bill/lines/", { status: 201, body: after }]]));
  const root = await openBill(fetchImpl);

  await root.submit({ intent: "add-line", description: "PTA levy", amount: "15,000" });

  assert.deepEqual(fetchImpl.posted, [
    { url: "/api/fees/classes/5/bill/lines/", body: { term_id: 7, description: "PTA levy", amount: "15,000" } },
  ]);
  assert.match(root.innerHTML, /PTA levy/);
  assert.match(root.innerHTML, /Added “PTA levy”\./);
});

test("a line refused for its name keeps what was typed and says why", async () => {
  const fetchImpl = serve(
    billRoutes([["/bill/lines/", { status: 409, body: { detail: "This bill already has a line called \"Tuition\", for a different amount." } }]]),
  );
  const root = await openBill(fetchImpl);

  await root.submit({ intent: "add-line", description: "Tuition", amount: "140,000" });

  assert.match(root.innerHTML, /already has a line called/);
  assert.match(root.innerHTML, /value="140,000"/);
});

test("changing a line is a PUT, and says the children already charged keep their charge", async () => {
  const fetchImpl = serve(billRoutes([["/bill-lines/1/", { status: 200, body: bill() }]]));
  const root = await openBill(fetchImpl);

  await root.click({ "data-action": "change-line", "data-line": "1" });
  assert.match(root.innerHTML, /The 2 already charged keep what they were charged/);
  await root.submit({ intent: "change-line", description: "Tuition", amount: "160,000" });

  assert.deepEqual(fetchImpl.others, [
    { method: "PUT", url: "/api/fees/bill-lines/1/", body: { description: "Tuition", amount: "160,000" } },
  ]);
  assert.match(root.innerHTML, /Children already charged keep what they were charged/);
});

test("removing an unused line is a DELETE", async () => {
  const fetchImpl = serve(billRoutes([["/bill-lines/2/", { status: 200, body: bill({ lines: bill().lines.slice(0, 1) }) }]]));
  const root = await openBill(fetchImpl);

  await root.click({ "data-action": "remove-line", "data-line": "2" });

  assert.deepEqual(fetchImpl.others, [{ method: "DELETE", url: "/api/fees/bill-lines/2/", body: undefined }]);
  assert.doesNotMatch(root.innerHTML, /Uniform/);
});

test("charging the class names who another class's bill already charged", async () => {
  const done = {
    students: 1, students_skipped: 0, charges_posted: 2, charges_skipped: 0, charged_kobo: 15_500_000,
    discounts_posted: 0, discounts_skipped: 0, discounted_kobo: 0,
    billed_elsewhere: [{ student_membership_id: 3, student: "Ada Obi" }],
    summary: "2 charged, 0 skipped; 0 discounts, 0 skipped; 1 already billed by another class's bill",
  };
  const fetchImpl = serve(billRoutes([["/bill/charges/", { status: 200, body: done }]]));
  const root = await openBill(fetchImpl);

  await root.click({ "data-action": "charge-class" });

  assert.deepEqual(fetchImpl.posted, [{ url: "/api/fees/classes/5/bill/charges/", body: { term_id: 7 } }]);
  assert.match(root.innerHTML, /2 charges posted/);
  assert.match(root.innerHTML, /another class's bill already charged them this term: Ada Obi\./);
});

test("a lost answer to charging says pressing again charges nobody twice", async () => {
  const fetchImpl = serve(billRoutes([["/bill/charges/", () => new Error("connection reset")]]));
  const root = await openBill(fetchImpl);

  await root.click({ "data-action": "charge-class" });

  assert.match(root.innerHTML, /data-state="bill"/);
  assert.match(root.innerHTML, /nobody is charged twice/);
});

// -- B2: concessions ------------------------------------------------------------

const CONCESSIONS = {
  student_membership_id: 3,
  student: "Ada Obi",
  may_write: true,
  concessions: [
    { concession_id: 12, amount_kobo: 5_000_000, reason: "Staff child", granted_at: "2025-09-20T09:00:00Z", revoked: null },
    {
      concession_id: 11,
      amount_kobo: 2_000_000,
      reason: "Sibling discount",
      granted_at: "2025-01-10T09:00:00Z",
      revoked: { reason: "Sibling left", revoked_by: "Bola Bursar", revoked_at: "2025-09-01T10:00:00Z" },
    },
  ],
};

test("a revoked concession stays on the account, with who, when and why", () => {
  const html = states.account({ account: account(), concessions: CONCESSIONS });
  assert.match(html, /Revoked 2025-09-01 by Bola Bursar: Sibling left/);
  assert.match(html, /data-action="revoke-concession" data-concession="12"/);
  assert.doesNotMatch(html, /data-concession="11"/, "a revoked concession offered a second revocation");
});

test("a reader sees concessions and cannot grant or revoke", () => {
  const html = states.account({ account: account({ may_write: false }), concessions: CONCESSIONS });
  assert.match(html, /Staff child/);
  assert.doesNotMatch(html, /revoke-concession|grant-concession/);
});

const concessionRoutes = (extra = []) => [
  ...extra,
  ["/concessions/", { status: 200, body: CONCESSIONS }],
  ["/students/3/", { status: 200, body: account() }],
];

test("a revocation sends its reason, and one refused for having none says why", async () => {
  let refused = true;
  const fetchImpl = serve(
    concessionRoutes([
      [
        "/revocation/",
        () =>
          refused
            ? ((refused = false), { status: 422, body: { detail: "Say why, in a few words. The books keep the reason." } })
            : { status: 201, body: { ...CONCESSIONS.concessions[0], revoked: { reason: "Left", revoked_by: "Bola Bursar", revoked_at: "2025-10-05T10:00:00Z" } } },
      ],
    ]),
  );
  const root = await openAccount(fetchImpl);

  await root.click({ "data-action": "revoke-concession", "data-concession": "12" });
  await root.submit({ intent: "revocation", reason: "" });
  assert.match(root.innerHTML, /Say why, in a few words/);
  assert.match(root.innerHTML, /data-revocation/, "the form closed on a refusal");

  await root.submit({ intent: "revocation", reason: "Left" });

  assert.deepEqual(fetchImpl.posted.map((p) => p.body), [{ reason: "" }, { reason: "Left" }]);
  assert.equal(fetchImpl.posted[1].url, "/api/fees/concessions/12/revocation/");
  assert.match(root.innerHTML, /Revoked\. No bill will give it from now on/);
});

test("a concession is granted under a key of its own", async () => {
  const fetchImpl = serve(
    concessionRoutes([["/students/3/concessions/", (options) => (options.method === "POST"
      ? { status: 201, body: { concession: CONCESSIONS.concessions[0], granted: true } }
      : { status: 200, body: CONCESSIONS })]]),
  );
  const root = await openAccount(fetchImpl);

  await root.click({ "data-action": "grant-concession" });
  await root.submit({ intent: "concession", amount: "50,000", reason: "Staff child" });

  assert.deepEqual(fetchImpl.posted, [
    { url: "/api/fees/students/3/concessions/", body: { amount: "50,000", reason: "Staff child", form_key: "key-3" } },
  ]);
  assert.match(root.innerHTML, /Concession granted/);
});
