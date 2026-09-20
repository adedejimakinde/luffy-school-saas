/**
 * The four states that are not a card, each as a pure function of the body.
 *
 * They are here rather than inside `app.js` so that a test can assert what a
 * parent is actually told, without a browser: `withheld(body)` is a string, and
 * a string can be asserted on. The states were the part of this page most
 * likely to be written once, never seen again, and quietly wrong — a refusal is
 * by definition the path nobody demos.
 */

import { esc } from "../web/html.js";

/** Before the answer arrives. Replaced by whatever comes back. */
export function loading() {
  return '<p class="state state-loading">Fetching this report card&hellip;</p>';
}

/**
 * 403: the school is holding this card back.
 *
 * `contact` is the point of this state and the reason
 * `ReportCardSettings.withholding_contact` is constrained non-empty — a refusal
 * that sends a parent nowhere is the dead end the whole withholding design
 * exists to avoid. So it is rendered as its own line, not folded into the
 * sentence, and a body that somehow arrives without one still gets a page that
 * names the school rather than a blank.
 *
 * It is **not** linkified. `contact` is free text a school typed: a phone
 * number, an email address, "the bursar's office, mornings". Guessing a scheme
 * would produce `tel:the bursar's office` on the page a parent is meant to act
 * on.
 *
 * No balance and no reason appear, because the API does not send them —
 * `WithheldOut` says why each is excluded.
 */
export function withheld(body) {
  const school = esc(body.school_name) || "This school";
  const detail =
    esc(body.detail) || `${school} is holding this report card.`;
  const contact = esc(body.contact);
  return [
    '<section class="state state-withheld">',
    "<h1>This card is being held</h1>",
    `<p>${detail}</p>`,
    contact ? `<p class="contact">Contact the school: <strong>${contact}</strong></p>` : "",
    "</section>",
  ].join("");
}

/**
 * 404: there is no card here to show.
 *
 * The API answers one flat 404 for every way this can fail — no such child, no
 * card released for that term, or a caller with no claim on this one — and it
 * does that on purpose, so that a stranger cannot use the page to find out
 * which children exist. This state therefore must **not** guess which of the
 * three happened. It says what is true of all of them and points at the person
 * who can actually tell the difference.
 */
export function missing() {
  return [
    '<section class="state state-missing">',
    "<h1>No report card here</h1>",
    "<p>There is no report card at this address. It may not have been ",
    "released yet, or the link may be wrong. The school office can tell you ",
    "which.</p>",
    "</section>",
  ].join("");
}

/**
 * 401 with `code: session_expired` — signed in once, not any more.
 *
 * Kept apart from `signedOut()` because they are different news. This one says
 * the reader *was* recognised and their session has lapsed, which is a page
 * refresh away from working; the other says nothing was ever signed in. The API
 * distinguishes them for exactly this reason and it would be a waste to
 * collapse them here.
 */
export function expired(body) {
  const detail =
    esc(body.detail) || "Your session has ended. Sign in again to see this card.";
  return [
    '<section class="state state-expired">',
    "<h1>Your session has ended</h1>",
    `<p>${detail}</p>`,
    '<p><a href="/">Sign in again</a></p>',
    "</section>",
  ].join("");
}

/** 401 with no session cookie at all: nobody is signed in on this browser. */
export function signedOut() {
  return [
    '<section class="state state-signed-out">',
    "<h1>Please sign in</h1>",
    "<p>Sign in to see this report card.</p>",
    '<p><a href="/">Sign in</a></p>',
    "</section>",
  ].join("");
}

/**
 * Anything else: a transport failure, a 500, a body that would not parse.
 *
 * It does not print the underlying error. A parent reading `SyntaxError:
 * Unexpected token <` learns nothing they can act on, and the text of a server
 * failure is written for whoever debugs it. The same argument the PDF's 202
 * makes about keeping the exception out of the body.
 */
export function broken() {
  return [
    '<section class="state state-broken">',
    "<h1>This page could not load the card</h1>",
    "<p>Something went wrong on our side. Please try again in a few minutes, ",
    "and tell the school office if it keeps happening.</p>",
    "</section>",
  ].join("");
}
