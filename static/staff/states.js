/**
 * Every screen the staff invitations page can show, as a pure function of an
 * API body.
 *
 * **"Who" is only ever what the office typed** (`sent_to`). The account an
 * address resolved to may be somebody else's teacher, with a name and a
 * second identifier from another school, and neither is this school's to
 * read — `api.InvitationOut` says why. An invitation from before the column
 * existed has nothing to show, and says "-" rather than borrowing a name.
 */

import { esc } from "../web/html.js";
import { button as signOutButton } from "../web/signout.js";

/** What each status means to the person reading the list. */
const STANDING = {
  pending: "Waiting for them to accept.",
  expired: "The link ran out before they used it.",
  revoked: "Cancelled. Nobody can use that link now.",
};

export function list({ invitations = [], roles = [], note = null, typed = null } = {}) {
  return [
    '<section class="state state-list" data-state="list">',
    "<h1>Staff invitations</h1>",
    inviteForm(roles, note, typed),
    invitations.length
      ? `<ul class="invitations">${invitations.map(row).join("")}</ul>`
      : '<p class="blank">Nobody is waiting on an invitation from this school.</p>',
    signOutButton(),
    "</section>",
  ].join("");
}

function row(inv) {
  return [
    `<li class="invitation" data-status="${esc(inv.status)}">`,
    `<span class="who">${esc(inv.sent_to) || "-"}</span>`,
    `<span class="role">${esc(inv.role_display)}</span>`,
    `<span class="standing">${STANDING[inv.status] || esc(inv.status)}</span>`,
    // A revoked or expired link is exactly when somebody asks for another,
    // so resend is offered on all three; revoking is only for a live one.
    `<button type="button" data-action="resend" data-invitation="${esc(inv.id)}">Send again</button>`,
    inv.status === "pending"
      ? `<button type="button" data-action="revoke" data-invitation="${esc(inv.id)}">Cancel it</button>`
      : "",
    "</li>",
  ].join("");
}

/** Inviting somebody. **A refused invite keeps what was typed.** */
function inviteForm(roles, note, typed) {
  const t = typed || {};
  return [
    `<form class="invite${note ? " rejected" : ""}" data-form="invite">`,
    "<h2>Invite a member of staff</h2>",
    '<label for="address">Their email address or phone number</label>',
    `<input id="address" name="address" value="${esc(t.address)}" required>`,
    '<label for="full_name">Their name (optional)</label>',
    `<input id="full_name" name="full_name" value="${esc(t.full_name)}">`,
    '<label for="role">Role</label>',
    '<select id="role" name="role">',
    roles
      .map(
        (r) =>
          `<option value="${esc(r)}"${r === t.role ? " selected" : ""}>${esc(
            r.replace(/_/g, " "),
          )}</option>`,
      )
      .join(""),
    "</select>",
    '<button type="submit">Send the invitation</button>',
    note ? `<p class="note" role="alert">${esc(note)}</p>` : "",
    "</form>",
  ].join("");
}

/** Signed in, and not somebody who may invite staff here. */
export function notTheOffice({ detail = "" } = {}) {
  return [
    '<section class="state state-not-the-office" data-state="not-the-office">',
    "<h1>You cannot open staff invitations</h1>",
    `<p>${esc(detail) || "Staff are invited by an administrator of the school."}</p>`,
    "<p>If that should be you, whoever runs this system for your school can ",
    "arrange it.</p>",
    signOutButton(),
    "</section>",
  ].join("");
}

/** This host is not a school's. */
export function wrongHost() {
  return [
    '<section class="state state-wrong-host" data-state="wrong-host">',
    "<h1>Staff invitations live on your school's own web address</h1>",
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
      : "<p>Sign in with your password to open staff invitations.</p>",
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
