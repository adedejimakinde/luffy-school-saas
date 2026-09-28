/**
 * Every screen the notices settings page can show, as a pure function of an
 * API body.
 *
 * **Nobody gets the daily money summary until the school says so.** Turning
 * the switch on picks no staff by itself — that would be this platform
 * emailing somebody's money figures because of a click that only said "turn
 * this feature on" — so the empty state names the fact rather than leaving a
 * blank list to explain itself.
 */

import { esc } from "../web/html.js";

export function settings({
  payment_receipts = false,
  absence_alerts = false,
  daily_money_summary = false,
  money_summary_recipient_ids = [],
  staff = [],
  note = null,
} = {}) {
  const chosen = new Set(money_summary_recipient_ids);
  return [
    '<section class="state state-settings" data-state="settings">',
    "<h1>Notices</h1>",
    `<form class="settings${note ? " rejected" : ""}" data-form="settings">`,
    switchRow(
      "payment_receipts",
      "Payment receipts",
      "Email a receipt to whoever receives invoices when a payment is recorded.",
      payment_receipts,
    ),
    switchRow(
      "absence_alerts",
      "Absence alerts",
      "Email every guardian of a child marked absent when a register is taken.",
      absence_alerts,
    ),
    switchRow(
      "daily_money_summary",
      "Daily money summary",
      "Email a digest of the day's payments to whichever staff are chosen below.",
      daily_money_summary,
    ),
    recipients(staff, chosen),
    '<button type="submit">Save</button>',
    note ? `<p class="note" role="alert">${esc(note)}</p>` : "",
    "</form>",
    "</section>",
  ].join("");
}

function switchRow(name, label, hint, checked) {
  return [
    '<label class="switch-row">',
    `<input type="checkbox" name="${esc(name)}" ${checked ? "checked" : ""}>`,
    `<span class="switch-label">${esc(label)}</span>`,
    `<span class="hint">${esc(hint)}</span>`,
    "</label>",
  ].join("");
}

function recipients(staff, chosen) {
  return [
    '<fieldset class="recipients">',
    "<legend>Who gets the daily money summary</legend>",
    chosen.size === 0
      ? '<p class="note">Nobody is chosen yet — tick whoever on the staff below ' +
        "should see the day's money figures. Nobody will be emailed until " +
        "somebody is ticked.</p>"
      : "",
    staff.length
      ? staff
          .map(
            (m) =>
              `<label class="recipient"><input type="checkbox" name="recipient_${esc(m.membership_id)}" ` +
              `${chosen.has(m.membership_id) ? "checked" : ""}>` +
              `<span class="who">${esc(m.name)}</span>` +
              `<span class="role">${esc(m.role_display)}</span></label>`,
          )
          .join("")
      : '<p class="blank">Nobody is on the live staff list yet.</p>',
    "</fieldset>",
  ].join("");
}

/** Signed in, and not the principal or an administrator. */
export function notAllowed({ detail = "" } = {}) {
  return [
    '<section class="state state-not-allowed" data-state="not-allowed">',
    "<h1>You cannot open these settings</h1>",
    `<p>${esc(detail) || "Only the principal or an administrator decides what this school sends."}</p>`,
    "</section>",
  ].join("");
}

/** This host is not a school's. */
export function wrongHost() {
  return [
    '<section class="state state-wrong-host" data-state="wrong-host">',
    "<h1>Notices settings live on your school's own web address</h1>",
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
      : "<p>Sign in with your password to open notices settings.</p>",
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
