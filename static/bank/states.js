/**
 * Every screen the bank page can show, as a pure function of an API body.
 *
 * Money goes straight to the school's own bank account through Paystack; this
 * platform never holds it, and the page says so. The account number is shown in
 * full to the bursar and administrator and as its last four digits to anybody
 * else (the server does the masking; this only draws what it was given).
 */

import { esc } from "../web/html.js";

const SAYS_SO =
  "Fees paid by families go straight to this account through Paystack. Classnode never holds the money, and the school pays Paystack's fees.";

function note(text) {
  return text ? `<p class="note" role="alert">${esc(text)}</p>` : "";
}

/** Whole kobo as naira, by hand: `5000000` is `NGN 50,000`. No float, no locale. */
export function naira(kobo) {
  const whole = Math.floor(kobo / 100);
  const part = kobo % 100;
  const grouped = String(whole).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `NGN ${grouped}${part ? `.${String(part).padStart(2, "0")}` : ""}`;
}

/**
 * Money Paystack confirmed that could not be placed on a child. It is listed and
 * never guessed onto anybody: the bursar sees what arrived, how much, and why it
 * was not placed. A person who may place it (`mayPlace`) is offered a button on
 * each one still waiting; one already placed says where it went and who put it
 * there, and offers nothing.
 */
export function unmatchedList(payments = [], { mayPlace = false } = {}) {
  if (!payments.length) return "";
  const row = (p) => {
    const money =
      `<strong>${esc(naira(p.amount_kobo))}</strong> ` +
      `<span class="reference">${esc(p.reference)}</span> `;
    if (p.placed) {
      return `<li class="placed">${money}<span class="why">Placed on ${esc(p.placed.student)} by ${esc(p.placed.placed_by)}.</span></li>`;
    }
    const action = mayPlace
      ? ` <button type="button" class="btn" data-action="place" data-payment="${esc(p.payment_id)}">Place on a child</button>`
      : "";
    return `<li>${money}<span class="why">${esc(p.reason_label)}</span>${action}</li>`;
  };
  return [
    '<section class="unmatched" data-state="unmatched">',
    "<h2>Payments we could not match</h2>",
    '<p class="hint">These arrived through Paystack and are not in any child\'s account. Nothing has been guessed.</p>',
    `<ul class="payments">${payments.map(row).join("")}</ul>`,
    "</section>",
  ].join("");
}

/** Choosing the child a payment goes on: the class, then the child. Writes nothing. */
export function place({ payment = {}, classes = [], classId = null, children = [], childId = null, note: text = null } = {}) {
  const options = (rows, value, chosen, label) =>
    rows
      .map(
        (r) =>
          `<option value="${esc(r[value])}"${r[value] === chosen ? " selected" : ""}>${esc(r[label])}</option>`,
      )
      .join("");
  return [
    '<section class="state state-place" data-state="place">',
    "<h1>Place this payment on a child</h1>",
    `<p><strong>${esc(naira(payment.amount_kobo))}</strong> <span class="reference">${esc(payment.reference)}</span></p>`,
    '<form class="place-form" data-form="pick">',
    '<label class="field"><span class="label">Class</span>',
    `<select name="class_group" data-field="class"><option value=""${classId ? "" : " selected"}>Choose a class…</option>`,
    options(classes, "class_group_id", classId, "class_group"),
    "</select></label>",
    '<label class="field"><span class="label">Child</span>',
    `<select name="child" data-field="child"${classId ? "" : " disabled"}><option value=""${childId ? "" : " selected"}>Choose a child…</option>`,
    options(children, "student_membership_id", childId, "student"),
    "</select></label>",
    note(text),
    '<button type="submit" class="btn primary">Review</button> ',
    '<button type="button" class="btn" data-action="cancel-place">Cancel</button>',
    "</form>",
    "</section>",
  ].join("");
}

/** The amount, the reference and the child, read back before the only write. */
export function placeConfirm({ payment = {}, child = {}, note: text = null } = {}) {
  return [
    '<section class="state state-place-confirm" data-state="place-confirm">',
    "<h1>Place this payment?</h1>",
    '<section class="card">',
    `<p><strong>${esc(naira(payment.amount_kobo))}</strong> <span class="reference">${esc(payment.reference)}</span></p>`,
    `<p>on <strong>${esc(child.student)}</strong></p>`,
    "</section>",
    "<p>It goes into their account now, with a receipt, and your name is kept with it. ",
    "If it is wrong, reverse the entry on the child's account; this payment cannot be placed again.</p>",
    '<form data-form="place-confirm"><input type="hidden" name="confirm" value="yes">',
    `<button type="submit" class="btn primary">Yes, place ${esc(naira(payment.amount_kobo))} on ${esc(child.student)}</button> `,
    '<button type="button" class="btn" data-action="back-to-pick">No, go back</button>',
    note(text),
    "</form>",
    "</section>",
  ].join("");
}

export function status({
  connected = null,
  may_write = false,
  note: text = null,
  unmatched = [],
  mayPlace = false,
} = {}) {
  const head = '<div class="page-head"><div><h1>School bank account</h1></div></div>';
  if (!connected) {
    return [
      '<section class="state state-status" data-state="status">',
      head,
      "<p>No bank account is connected yet, so fees cannot be paid online.</p>",
      `<p class="hint">${esc(SAYS_SO)}</p>`,
      may_write
        ? '<button type="button" class="btn primary" data-action="start">Connect a bank account</button>'
        : "<p>The bursar or an administrator connects it.</p>",
      note(text),
      unmatchedList(unmatched, { mayPlace }),
      "</section>",
    ].join("");
  }
  return [
    '<section class="state state-status" data-state="status">',
    head,
    '<section class="card connected">',
    `<p class="account-name">${esc(connected.account_name)}</p>`,
    `<p>${esc(connected.bank_name)} <span class="account-number">${esc(connected.account_number)}</span></p>`,
    `<p class="hint">Connected by ${esc(connected.connected_by)}.</p>`,
    "</section>",
    `<p class="hint">${esc(SAYS_SO)}</p>`,
    may_write
      ? '<button type="button" class="btn" data-action="start">Change bank account</button>'
      : "",
    note(text),
    unmatchedList(unmatched, { mayPlace }),
    "</section>",
  ].join("");
}

export function form({ banks = [], values = {}, note: text = null } = {}) {
  return [
    '<section class="state state-form" data-state="form">',
    "<h1>Connect a bank account</h1>",
    '<form class="bank-form" data-form="account">',
    '<label class="field"><span class="label">Bank</span>',
    '<select name="bank_code" required>',
    `<option value=""${values.bank_code ? "" : " selected"}>Choose the bank…</option>`,
    banks
      .map(
        (b) =>
          `<option value="${esc(b.code)}"${b.code === values.bank_code ? " selected" : ""}>${esc(b.name)}</option>`,
      )
      .join(""),
    "</select></label>",
    '<label class="field"><span class="label">Account number</span>',
    `<input name="account_number" inputmode="numeric" autocomplete="off" maxlength="10" value="${esc(values.account_number || "")}" required></label>`,
    note(text),
    '<button type="submit" class="btn primary">Find the account name</button> ',
    '<button type="button" class="btn" data-action="cancel">Cancel</button>',
    "</form>",
    "</section>",
  ].join("");
}

export function confirm({ bankName = "", account = {}, accountName = "", note: text = null } = {}) {
  return [
    '<section class="state state-confirm" data-state="confirm">',
    "<h1>Is this your school's account?</h1>",
    `<section class="card"><p class="account-name">${esc(accountName)}</p>`,
    `<p>${esc(bankName)} ${esc(account.account_number)}</p></section>`,
    `<p>${esc(SAYS_SO)} Only confirm if the name above is your school's.</p>`,
    '<form data-form="confirm"><input type="hidden" name="confirm" value="yes">',
    '<button type="submit" class="btn primary">Yes, connect this account</button> ',
    '<button type="button" class="btn" data-action="back">No, go back</button>',
    note(text),
    "</form>",
    "</section>",
  ].join("");
}

export function notAllowed({ detail = "" } = {}) {
  return [
    '<section class="state state-not-allowed" data-state="not-allowed">',
    "<h1>You cannot connect a bank account</h1>",
    `<p>${esc(detail) || "The bursar or an administrator of the school does this."}</p>`,
    "</section>",
  ].join("");
}

export function wrongHost() {
  return [
    '<section class="state state-wrong-host" data-state="wrong-host">',
    "<h1>This lives on your school's own web address</h1>",
    "<p>This page is open on the sign-in site, or you may not read the school's fees. ",
    "Open it again from your school's own address.</p>",
    "</section>",
  ].join("");
}

export function signedOut({ portal = "", expired = false } = {}) {
  return [
    '<section class="state state-signed-out" data-state="signed-out">',
    `<h1>${expired ? "Your session has ended" : "Please sign in"}</h1>`,
    expired
      ? "<p>You were signed out after a period of inactivity.</p>"
      : "<p>Sign in with your password to open this page.</p>",
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
    "<p>Something went wrong on our side. Please try again in a few minutes.</p>",
    "</section>",
  ].join("");
}
