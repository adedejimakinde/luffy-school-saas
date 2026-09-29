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
          `<span class="count">${esc(s.students)} ${s.students === 1 ? "student" : "students"}</span></li>`,
      )
      .join(""),
    "</ul>",
  ].join("");
}

/** The list, and the form to add another. `made` is the last add's answer, if any. */
export function main({ schools = [], made = null, note = null, values = {} } = {}) {
  return [
    '<section class="state state-main" data-state="main">',
    '<div class="page-head"><div><h1>Schools</h1></div></div>',
    made ? invited(made) : "",
    addForm(made ? {} : values, note),
    `<h2>${esc(schools.length)} ${schools.length === 1 ? "school" : "schools"}</h2>`,
    schoolList(schools),
    "</section>",
  ].join("");
}

/** What happened to the new school's invitation, in words. */
export function invited(made) {
  const name = esc(made.school.name);
  if (made.emailed) {
    return `<p class="hint" role="status"><strong>${name}</strong> is at ${esc(made.school.host)}. The invitation was sent to ${esc(made.invited)}.</p>`;
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
