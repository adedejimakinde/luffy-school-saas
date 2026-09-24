/**
 * Every screen the fees page can show, as a pure function of API bodies.
 *
 * **Each form names its intent** in a hidden field, and `app.js` dispatches on
 * that rather than on which fields a form happens to have: a payment and a
 * discount both have an amount, and a discount and a reversal both have a
 * reason.
 *
 * **Every number is the server's**, in kobo, and `money.js` is the only thing
 * that turns one into naira. A balance is said in words — "owes", "in
 * credit", "nothing owed" — never left to a minus sign.
 *
 * **A receipt says what the entry recorded**, and says across its face when
 * the payment has since been undone.
 */

import { esc } from "../web/html.js";
import { button as signOutButton } from "../web/signout.js";
import { balanceWords, naira, signed } from "./money.js";

function termOptions(terms, chosen) {
  return terms
    .map(
      (t) =>
        `<option value="${esc(t.term_id)}"${String(t.term_id) === String(chosen) ? " selected" : ""}>` +
        `${esc(t.term)}${t.is_current ? " (current)" : ""}</option>`,
    )
    .join("");
}

export function balance(kobo) {
  const { tone, text } = balanceWords(kobo);
  return `<span class="balance ${tone}" data-balance="${tone}">${esc(text)}</span>`;
}

// -- the way in ---------------------------------------------------------------

export function books({ books: body = {} } = {}) {
  const { terms = [], term_id: termId, term = "", classes = [] } = body;
  return [
    '<section class="state state-books" data-state="books">',
    "<h1>Fees</h1>",
    `<form class="chooser"><label for="term">Term</label>`,
    `<select id="term" data-term>${termOptions(terms, termId)}</select></form>`,
    `<h2>${esc(term)}</h2>`,
    classes.length
      ? '<ul class="classes">' +
        classes
          .map(
            (c) =>
              `<li><button type="button" data-action="open-class" data-class="${esc(c.class_group_id)}">` +
              `${esc(c.class_group)}</button> <span class="quiet">${esc(c.children)} ` +
              `${c.children === 1 ? "child" : "children"}</span></li>`,
          )
          .join("") +
        "</ul>"
      : '<p class="blank">No class has anybody in it this term.</p>',
    signOutButton(),
    "</section>",
  ].join("");
}

export function classBalances({ classBalances: body = {} } = {}) {
  const { class_group = "", term = "", children = [] } = body;
  return [
    '<section class="state state-class" data-state="class">',
    '<p class="back"><button type="button" data-action="back-to-books">All classes</button></p>',
    `<h1>${esc(class_group)}</h1>`,
    `<p class="quiet">${esc(term)}. Each balance is the whole account, every term.</p>`,
    children.length
      ? [
          '<div class="scroll"><table class="balances"><thead><tr>',
          "<th>Name</th><th>Admission no.</th><th>Account</th></tr></thead><tbody>",
          children
            .map(
              (c) =>
                "<tr>" +
                `<td><button type="button" data-action="open-account" data-student="${esc(c.student_membership_id)}">` +
                `${esc(c.student)}</button></td>` +
                `<td>${esc(c.reference)}</td>` +
                `<td>${balance(c.balance_kobo)}</td>` +
                "</tr>",
            )
            .join(""),
          "</tbody></table></div>",
        ].join("")
      : '<p class="blank">Nobody is in this class this term.</p>',
    signOutButton(),
    "</section>",
  ].join("");
}

// -- one child's account ------------------------------------------------------

/**
 * `draft` is what was last submitted, drawn back in when the answer was not a
 * success — so a bursar corrects one field rather than typing the payment
 * again, and a retry after a lost answer resends the same payment under the
 * same form key.
 */
function paymentForm(body, { termId, today, draft = {} }) {
  const methods = body.methods || [];
  const chosen = draft.method || "";
  return [
    '<form class="payment" data-payment>',
    '<input type="hidden" name="intent" value="payment">',
    "<fieldset><legend>Record a payment</legend>",
    `<label>Term <select name="term_id">${termOptions(body.terms || [], draft.term_id ?? termId)}</select></label>`,
    `<label>Amount (₦) <input name="amount" inputmode="decimal" autocomplete="off" value="${esc(draft.amount || "")}" required></label>`,
    '<label>Method <select name="method" required><option value="">Choose…</option>',
    methods
      .map((m) => `<option value="${esc(m.value)}"${m.value === chosen ? " selected" : ""}>${esc(m.label)}</option>`)
      .join(""),
    "</select></label>",
    `<label>Teller or transfer reference <input name="reference" maxlength="64" autocomplete="off" value="${esc(draft.reference || "")}"></label>`,
    `<label>Date paid <input type="date" name="effective_on" value="${esc(draft.effective_on || today)}" max="${esc(today)}" required></label>`,
    '<button type="submit">Record payment</button>',
    "</fieldset></form>",
  ].join("");
}

/**
 * A discount given by hand, for one term, with its reason. Behind a button
 * rather than always open beside the payment form: waiving money is rarer
 * than taking it, and a form a bursar tabs into by accident is how it would
 * happen by mistake. `draft` as for a payment.
 */
function discountForm(body, { termId, draft = {} }) {
  return [
    '<form class="discount" data-discount>',
    '<input type="hidden" name="intent" value="discount">',
    "<fieldset><legend>Give a discount</legend>",
    `<label>Term <select name="term_id">${termOptions(body.terms || [], draft.term_id ?? termId)}</select></label>`,
    `<label>Amount (₦) <input name="amount" inputmode="decimal" autocomplete="off" value="${esc(draft.amount || "")}" required></label>`,
    `<label>Why? <input name="reason" maxlength="255" autocomplete="off" value="${esc(draft.reason || "")}" required></label>`,
    '<button type="submit">Give discount</button> ',
    '<button type="button" data-action="cancel-discount">Cancel</button>',
    "</fieldset></form>",
  ].join("");
}

function reversalForm(entry) {
  return [
    `<form class="reversal" data-reversal data-entry="${esc(entry.entry_id)}">`,
    '<input type="hidden" name="intent" value="reversal">',
    `<label>Why is this being undone? <input name="reason" maxlength="255" required></label>`,
    '<button type="submit">Undo it</button> ',
    '<button type="button" data-action="cancel-reversal">Keep it</button>',
    "</form>",
  ].join("");
}

function entryRow(entry, { mayWrite, reversing }) {
  const actions = [];
  if (entry.receipt_number) {
    actions.push(
      `<button type="button" data-action="receipt" data-entry="${esc(entry.entry_id)}">Receipt</button>`,
    );
  }
  if (mayWrite && entry.may_reverse && reversing !== entry.entry_id) {
    actions.push(`<button type="button" data-action="reverse" data-entry="${esc(entry.entry_id)}">Undo</button>`);
  }
  const undone = entry.reversed_by_id ? ' <span class="tag">undone</span>' : "";
  return [
    `<tr data-entry-row="${esc(entry.entry_id)}"${entry.reversed_by_id ? ' class="undone"' : ""}>`,
    `<td>${esc(entry.effective_on)}</td>`,
    `<td>${esc(entry.kind_label)}${undone}</td>`,
    `<td>${esc(entry.narration)}<br><small>${esc(entry.term)}</small></td>`,
    `<td>${esc(entry.method_label)}${entry.reference ? `<br><small>${esc(entry.reference)}</small>` : ""}</td>`,
    `<td class="num">${esc(signed(entry.amount_kobo))}</td>`,
    `<td class="actions">${actions.join(" ")}</td>`,
    "</tr>",
    reversing === entry.entry_id ? `<tr><td colspan="6">${reversalForm(entry)}</td></tr>` : "",
  ].join("");
}

export function account({
  account: body = {},
  note = "",
  noteTone = "",
  termId = null,
  today = "",
  reversing = null,
  discounting = false,
  draft = {},
  discountDraft = {},
} = {}) {
  const { student = "", reference = "", balance_kobo = 0, may_write: mayWrite = false, entries = [] } = body;
  const current = termId ?? ((body.terms || []).find((t) => t.is_current) || (body.terms || [])[0] || {}).term_id;
  return [
    '<section class="state state-account" data-state="account">',
    '<p class="back"><button type="button" data-action="back-to-class">Back</button></p>',
    `<h1>${esc(student)}</h1>`,
    reference ? `<p class="quiet">Admission no. ${esc(reference)}</p>` : "",
    `<p class="standing">${balance(balance_kobo)}</p>`,
    note ? `<p class="note ${esc(noteTone)}" role="status">${esc(note)}</p>` : "",
    mayWrite ? paymentForm(body, { termId: current, today, draft }) : "",
    mayWrite && discounting ? discountForm(body, { termId: current, draft: discountDraft }) : "",
    mayWrite && !discounting
      ? '<p class="more"><button type="button" data-action="discount">Give a discount</button></p>'
      : "",
    "<h2>Account</h2>",
    entries.length
      ? [
          '<div class="scroll"><table class="entries"><thead><tr>',
          '<th>Date</th><th>What</th><th>For</th><th>How</th><th class="num">Amount</th><th></th>',
          "</tr></thead><tbody>",
          entries.map((e) => entryRow(e, { mayWrite, reversing })).join(""),
          "</tbody></table></div>",
        ].join("")
      : '<p class="blank">Nothing has been charged or paid on this account yet.</p>',
    signOutButton(),
    "</section>",
  ].join("");
}

// -- the receipt --------------------------------------------------------------

export function receipt({ receipt: body = {} } = {}) {
  const r = body;
  return [
    '<section class="state state-receipt" data-state="receipt">',
    '<p class="back"><button type="button" data-action="back-to-account">Back</button> ',
    '<button type="button" data-action="print">Print</button></p>',
    '<article class="receipt">',
    `<header><h1>${esc(r.school)}</h1><p>Receipt <strong>${esc(r.receipt_number)}</strong></p></header>`,
    r.reversed
      ? `<p class="void" data-void>UNDONE on ${esc(r.reversed.on)}: ${esc(r.reversed.reason)}. ` +
        "This payment is no longer on the account.</p>"
      : "",
    "<dl>",
    `<dt>Received from</dt><dd>${esc(r.student)}${r.student_reference ? ` (${esc(r.student_reference)})` : ""}</dd>`,
    `<dt>Amount</dt><dd class="amount">${esc(naira(r.amount_kobo))}</dd>`,
    `<dt>Paid by</dt><dd>${esc(r.method_label)}</dd>`,
    r.payment_reference ? `<dt>Reference</dt><dd>${esc(r.payment_reference)}</dd>` : "",
    `<dt>Date paid</dt><dd>${esc(r.effective_on)}</dd>`,
    `<dt>Towards</dt><dd>${esc(r.term)}</dd>`,
    `<dt>For</dt><dd>${esc(r.narration)}</dd>`,
    r.received_by ? `<dt>Received by</dt><dd>${esc(r.received_by)}</dd>` : "",
    "</dl>",
    "</article>",
    "</section>",
  ].join("");
}

// -- nothing to show ----------------------------------------------------------

export function noTerms() {
  return [
    '<section class="state state-no-terms" data-state="no-terms">',
    "<h1>No terms yet</h1>",
    "<p>Your school has not set up a term, so there are no classes to show. ",
    "The school office sets terms up.</p>",
    signOutButton(),
    "</section>",
  ].join("");
}

/** Refused, or no such child or entry — one state, because one answer. */
export function notYours() {
  return [
    '<section class="state state-not-yours" data-state="not-yours">',
    "<h1>This is not something you can open</h1>",
    "<p>The school's fees are kept by the bursar and the administrators, and read ",
    "by the principal and the vice principal (academic). If that should include ",
    "you, whoever runs this system for your school can arrange it.</p>",
    signOutButton(),
    "</section>",
  ].join("");
}

export function wrongHost() {
  return [
    '<section class="state state-wrong-host" data-state="wrong-host">',
    "<h1>Fees live on your school's own web address</h1>",
    "<p>This page is open on the sign-in site. Open it again from your ",
    "school's own address.</p>",
    "</section>",
  ].join("");
}

export function signedOut({ portal = "", expired = false } = {}) {
  return [
    '<section class="state state-signed-out" data-state="signed-out">',
    `<h1>${expired ? "Your session has ended" : "Please sign in"}</h1>`,
    expired
      ? "<p>You were signed out after a period of inactivity.</p>"
      : "<p>Sign in with your password to open the school's fees.</p>",
    portal
      ? `<p><a href="//${esc(portal)}/staff-sign-in/">Sign in again</a></p>`
      : "<p>Go back to the sign-in page you came from.</p>",
    "</section>",
  ].join("");
}

export function broken() {
  return [
    '<section class="state state-broken" data-state="broken">',
    "<h1>This page is not working</h1>",
    "<p>Something went wrong on our side. Please try again in a few minutes, ",
    "and tell whoever runs this system for your school.</p>",
    "</section>",
  ].join("");
}
