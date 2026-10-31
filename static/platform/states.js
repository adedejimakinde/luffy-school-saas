/**
 * Every screen the platform page can show, as a pure function of an API body.
 */

import { esc } from "../web/html.js";

function addForm(values = {}, note = null) {
  const v = (name) => esc(values[name] || "");
  return [
    `<form class="add" data-form="add" novalidate><h2>Add a school</h2>`,
    `<label for="name">School name</label><input id="name" name="name" value="${v("name")}" autocomplete="off" required>`,
    `<label for="subdomain">Subdomain <small>the school's own address</small></label>`,
    `<input id="subdomain" name="subdomain" value="${v("subdomain")}" autocapitalize="none" autocomplete="off" required>`,
    `<label for="admin_name">First administrator's name <small>optional</small></label>`,
    `<input id="admin_name" name="admin_name" value="${v("admin_name")}" autocomplete="off">`,
    `<label for="admin_email">Their email</label>`,
    `<input id="admin_email" name="admin_email" type="email" value="${v("admin_email")}" autocomplete="off">`,
    `<label for="admin_phone">or their phone</label>`,
    `<input id="admin_phone" name="admin_phone" type="tel" value="${v("admin_phone")}" autocomplete="off">`,
    note ? `<p class="note" role="alert">${esc(note)}</p>` : "",
    `<button type="submit" class="btn primary">Add school and invite them</button>`,
    "</form>",
  ].join("");
}

function schoolList(schools) {
  if (!schools.length) return '<p class="blank">No school has been added yet.</p>';
  return [
    '<ul class="schools">',
    schools
      .map(
        (s) =>
          `<li><span><strong>${esc(s.name)}</strong> <span class="host">${esc(s.host || s.subdomain)}</span></span>` +
          `<span class="count">${esc(s.students)} ${s.students === 1 ? "student" : "students"}</span>` +
          `<a href="/platform/handover/?school=${encodeURIComponent(s.subdomain)}">Handover</a></li>`,
      )
      .join(""),
    "</ul>",
  ].join("");
}

/** Whole kobo as naira, by hand: `5000000` is `NGN 50,000`. No float, no locale. */
export function naira(kobo) {
  const whole = Math.floor(kobo / 100);
  const part = kobo % 100;
  const grouped = String(whole).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `NGN ${grouped}${part ? `.${String(part).padStart(2, "0")}` : ""}`;
}

/**
 * Payments Paystack confirmed for an account number no school owns. No school's
 * bursar can see them, so they are listed here for platform staff to look into;
 * nothing here places them, which would be putting money in a school's books.
 */
export function unroutedList(payments = []) {
  if (!payments.length) return "";
  return [
    '<section class="unrouted" data-state="unrouted">',
    `<h2>${esc(payments.length)} ${payments.length === 1 ? "payment" : "payments"} no school owns</h2>`,
    '<p class="hint">Paystack confirmed these, and the account they were paid into belongs to no school here. Nothing has been guessed.</p>',
    '<ul class="payments">',
    payments
      .map(
        (p) =>
          `<li><strong>${esc(naira(p.amount_kobo))}</strong> ` +
          `<span class="reference">${esc(p.reference)}</span> ` +
          `<span class="account">account ${esc(p.account_number || "unknown")}</span></li>`,
      )
      .join(""),
    "</ul>",
    "</section>",
  ].join("");
}

/** Bytes as MB or GB, by hand: `1073741824` is `1.0 GB`. */
export function size(bytes) {
  const n = Number(bytes) || 0;
  if (n >= 1024 ** 3) return `${(n / 1024 ** 3).toFixed(1)} GB`;
  return `${Math.round(n / 1024 ** 2)} MB`;
}

/**
 * What each school keeps on the server's disk, against its quota, and how full
 * the disk is. The disk line is marked once it passes the warning line (70%),
 * the point at which an alert is emailed. Each school's quota can be changed
 * here; an empty box goes back to the platform's default.
 */
export function storageSection(storage, note = null) {
  if (!storage) return "";
  const disk = storage.disk || {};
  const warn = disk.percent >= disk.warn_percent;
  return [
    '<section class="storage" data-state="storage">',
    "<h2>Storage</h2>",
    `<p class="disk${warn ? " warn" : ""}"${warn ? ' role="alert"' : ""}>`,
    `The disk is <strong>${esc(disk.percent)}%</strong> full (${esc(size(disk.used_bytes))} of ${esc(size(disk.total_bytes))}).`,
    warn
      ? ` Past ${esc(disk.warn_percent)}%: an alert has been emailed. Uploads stop at ${esc(disk.refuse_percent)}%.`
      : ` An alert is emailed past ${esc(disk.warn_percent)}%, and uploads stop at ${esc(disk.refuse_percent)}%.`,
    "</p>",
    `<p class="hint">Classnode's blog keeps ${esc(size(storage.platform_bytes))}. The default quota is ${esc(size(storage.default_quota_bytes))} a school.</p>`,
    note ? `<p class="note" role="alert">${esc(note)}</p>` : "",
    '<ul class="schools storage-list">',
    (storage.schools || [])
      .map(
        (s) =>
          `<li><span><strong>${esc(s.name)}</strong> <span class="count">${esc(size(s.bytes))} of ${esc(size(s.quota_bytes))}` +
          ` (${esc(s.percent)}%), ${esc(s.files)} ${s.files === 1 ? "file" : "files"}</span></span>` +
          `<form class="quota" data-form="quota" data-school="${esc(s.subdomain)}">` +
          `<label for="quota-${esc(s.subdomain)}">Quota in MB</label>` +
          `<input id="quota-${esc(s.subdomain)}" name="quota_mb" type="number" min="1" inputmode="numeric" ` +
          `value="${s.default_quota ? "" : esc(Math.round(s.quota_bytes / 1024 ** 2))}" placeholder="default">` +
          '<button type="submit">Save</button></form></li>',
      )
      .join(""),
    "</ul>",
    "</section>",
  ].join("");
}

/** The list, and the form to add another. `made` is the last add's answer, if any. */
export function main({ schools = [], made = null, note = null, values = {}, unrouted = [], storage = null, storageNote = null } = {}) {
  return [
    '<section class="state state-main" data-state="main">',
    '<div class="page-head"><div><h1>Schools</h1></div><a href="/platform/handover/">New school handover</a></div>',
    made ? invited(made) : "",
    addForm(made ? {} : values, note),
    `<h2>${esc(schools.length)} ${schools.length === 1 ? "school" : "schools"}</h2>`,
    schoolList(schools),
    storageSection(storage, storageNote),
    unroutedList(unrouted),
    "</section>",
  ].join("");
}

/** What happened to the new school's invitation, in words. */
export function invited(made) {
  const name = esc(made.school.name);
  if (made.emailed) {
    return `<p class="hint" role="status"><strong>${name}</strong> is at ${esc(made.school.host)}. The invitation was sent to ${esc(made.invited)}.</p>`;
  }
  if (made.texted) {
    return `<p class="hint" role="status"><strong>${name}</strong> is at ${esc(made.school.host)}. The invitation was texted to ${esc(made.invited)}.</p>`;
  }
  return [
    `<p class="hint" role="status"><strong>${name}</strong> is at ${esc(made.school.host)}. Nothing was sent: give ${esc(made.invited)} this link yourself.`,
    " Whoever opens it becomes the school's administrator, so hand it to that person only.</p>",
    `<p class="handover">${esc(made.link_to_hand_over)}</p>`,
  ].join("");
}

export function notAllowed() {
  return [
    '<section class="state state-not-allowed" data-state="not-allowed">',
    "<h1>This page is not for you</h1>",
    "<p>The platform screen is for the platform's own staff.</p>",
    "</section>",
  ].join("");
}

export function wrongHost() {
  return [
    '<section class="state state-wrong-host" data-state="wrong-host">',
    "<h1>This lives on the platform's own address</h1>",
    "<p>Open it from the sign-in site, not from a school's address.</p>",
    "</section>",
  ].join("");
}

export function signedOut({ expired = false } = {}) {
  return [
    '<section class="state state-signed-out" data-state="signed-out">',
    `<h1>${expired ? "Your session has ended" : "Please sign in"}</h1>`,
    '<p><a href="/staff-sign-in/">Sign in</a>, then open this page again.</p>',
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
