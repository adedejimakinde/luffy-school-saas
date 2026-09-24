/**
 * Every screen the invitation page can show, as a pure function.
 *
 * The invitee's name and the school's come from the preview, which is shown
 * only to whoever holds the token — so they are the one person entitled to
 * read them. Every one of them goes through `esc()`: a name is typed by an
 * administrator, and this page runs on the portal, where the session cookie of
 * everybody who signs in lives.
 */

import { esc } from "../web/html.js";

/** At least what `AUTH_PASSWORD_VALIDATORS` asks, said before they type. */
export const MIN_PASSWORD = 10;

export function offer({ preview = {}, note = "" } = {}) {
  const { school = "", role_display = "", invitee = "", needs_password = false } = preview;
  return [
    '<section class="state state-offer" data-state="offer">',
    "<h1>Your invitation</h1>",
    `<p class="lead">${esc(invitee) ? `${esc(invitee)}, ` : ""}${esc(school)} has invited you ` +
      `to join as <strong>${esc(role_display)}</strong>.</p>`,
    `<form class="accept${note ? " rejected" : ""}" data-form="accept">`,
    needs_password
      ? [
          `<p>Choose a password. At least ${MIN_PASSWORD} characters.</p>`,
          '<label for="password">Password</label>',
          '<input id="password" name="password" type="password" autocomplete="new-password" required>',
          '<label for="confirm">The same password again</label>',
          '<input id="confirm" name="confirm" type="password" autocomplete="new-password" required>',
        ].join("")
      : `<p>You already have a password. Accepting adds ${esc(school)} to your account.</p>`,
    '<button type="submit">Accept the invitation</button>',
    note ? `<p class="note" role="alert">${esc(note)}</p>` : "",
    "</form>",
    "</section>",
  ].join("");
}

export function accepted({ school = "" } = {}) {
  return [
    '<section class="state state-accepted" data-state="accepted">',
    "<h1>You are in</h1>",
    `<p>You are now part of ${esc(school)} on Classnode.</p>`,
    '<p><a href="/staff-sign-in/">Sign in</a></p>',
    "</section>",
  ].join("");
}

/**
 * **One state for every refusal about the token** — see `api.js`. It says
 * what somebody holding a dead link can do, which is the same whichever of the
 * reasons it is.
 */
export function dead() {
  return [
    '<section class="state state-dead" data-state="dead">',
    "<h1>This invitation link does not work</h1>",
    "<p>It may have been used already, replaced by a newer invitation, or run ",
    "out of time. Ask the school that invited you to send it again.</p>",
    "</section>",
  ].join("");
}

export function broken() {
  return [
    '<section class="state state-broken" data-state="broken">',
    "<h1>This page is not working</h1>",
    "<p>Something went wrong on our side. Your invitation has not been used. ",
    "Please try again in a few minutes.</p>",
    "</section>",
  ].join("");
}
