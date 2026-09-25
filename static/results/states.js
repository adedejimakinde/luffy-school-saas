/**
 * Every screen the approval chain can show, as a pure function of an API body.
 *
 * Strings rather than DOM, for `card/states.js`' reason: a refusal is the path
 * nobody demos, and a string can be asserted in `node --test` with no browser.
 *
 * **The buttons are drawn from the payload's own booleans, never from a role
 * this module decides.** `chain_api._actions()` computes them from the same
 * sets `services` enforces, and the service asks again on the row read under
 * the lock. A page that worked out for itself who may approve would be a third
 * opinion, and the day it disagreed the wrong one would be the one on screen.
 */

import { esc } from "../web/html.js";
import { button as signOutButton } from "../web/signout.js";

/** The five steps, in the order the chain takes them, with what to call them. */
const STEPS = [
  ["may_submit", "submit", "Submit"],
  ["may_check", "check", "Check"],
  ["may_approve", "approve", "Approve"],
  ["may_release", "release", "Release to parents"],
];

/**
 * Where every class stands.
 *
 * **Every class is listed, including the ones this login cannot act on.** A
 * teacher reading "JSS 3B — awaiting check" is reading her own school's
 * progress, not somebody's results: the row carries no mark, no name and no
 * number. Hiding those rows would make an empty list ambiguous — nothing to
 * do, or nothing you may see.
 */
export function chain({ term = "", rows = [], notes = {}, asking = null } = {}) {
  return [
    '<section class="state state-chain" data-state="chain">',
    "<h1>Results</h1>",
    `<p class="term">${esc(term)}</p>`,
    '<ul class="classes">',
    rows.map((row) => classRow(row, notes[row.class_group_id], asking)).join(""),
    "</ul>",
    signOutButton(),
    "</section>",
  ].join("");
}

/** No current term, so there is no chain to walk. */
export function noTerm() {
  return [
    '<section class="state state-no-term" data-state="no-term">',
    "<h1>No term is open</h1>",
    "<p>Your school has not marked a term as the current one, so there are no ",
    "results to move along yet. The school office sets this.</p>",
    signOutButton(),
    "</section>",
  ].join("");
}

/**
 * One class, its state, and the steps this login may take.
 *
 * A released row offers nothing, and says so rather than going quiet: release
 * is final — a wrong card is corrected by reissuing it, not by moving the
 * sheet back — so an empty row would read as a page that failed to draw.
 */
function classRow(row, note, asking) {
  const actions = STEPS.filter(([flag]) => row[flag]).map(
    ([, step, label]) =>
      `<button type="button" data-action="step" data-step="${step}" ` +
      `data-class="${esc(row.class_group_id)}">${label}</button>`,
  );
  if (row.may_send_back) {
    actions.push(
      `<button type="button" class="send-back" data-action="ask-send-back" ` +
        `data-class="${esc(row.class_group_id)}">Send back</button>`,
    );
  }
  return [
    `<li class="row state-${esc(row.state)}${note ? ` ${esc(note.kind)}` : ""}">`,
    `<span class="name">${esc(row.class_group)}</span>`,
    `<span class="standing">${esc(row.state_label)}</span>`,
    // The sheet itself, so whoever is about to approve or release reads the
    // numbers first. The broadsheet route decides who may, as it always did.
    `<a class="broadsheet" href="/broadsheet/?class=${encodeURIComponent(row.class_group_id)}">Broadsheet</a>`,
    actions.length
      ? `<span class="actions">${actions.join("")}</span>`
      : `<span class="actions quiet">${
          row.state === "released" ? "Released — nothing further" : "Nothing for you here"
        }</span>`,
    asking === row.class_group_id ? sendBackForm(row) : "",
    leftOut(row),
    note ? `<span class="note" role="alert">${esc(note.detail)}</span>` : "",
    "</li>",
  ].join("");
}

/**
 * The children this release left without a card, by name. Issue #47.
 *
 * Only ever present for a login that may release — the API sends `null` to
 * everybody else, and this draws nothing for `null` or an empty list. A child
 * placed into the class while its release ran is not on it and cannot be added
 * to it. The sentence says what happened and offers no remedy: a revision can
 * give her a card, but one with no frozen sections (issue #31), and no page
 * offers it yet — pointing at a remedy that does not work is worse than none
 * (`accounts/refusals.py`).
 */
function leftOut(row) {
  if (row.left_out_checked === false) {
    // Not the same as nobody: the check after the release did not finish, and
    // an empty list here would read as "nobody was left out".
    return [
      '<div class="left-out" role="status">',
      "<p>The check for children this release left without a card did not finish. ",
      "Nobody is listed below, and that does not mean nobody was left out.</p>",
      "</div>",
    ].join("");
  }
  const children = row.without_a_card || [];
  if (!children.length) return "";
  const who = children
    .map((child) =>
      `<li>${esc(child.name || "A child with no name on record")}` +
      `${child.reference ? ` <span class="reference">${esc(child.reference)}</span>` : ""}</li>`,
    )
    .join("");
  const count = children.length === 1 ? "1 child has" : `${children.length} children have`;
  return [
    '<div class="left-out" role="status">',
    `<p>${count} no card from this release. They were placed into `,
    `${esc(row.class_group)} while it was being released, so they were not on it.</p>`,
    `<ul>${who}</ul>`,
    "</div>",
  ].join("");
}

/**
 * The send-back box.
 *
 * `required` on the field, because a refusal that does not say what is wrong
 * sends a teacher back to forty-five scores with no idea which to look at.
 * The service refuses a blank one too, and so does a check constraint — three
 * places, because the first is a courtesy, the second is callable without HTTP
 * and the third is the database.
 */
function sendBackForm(row) {
  return [
    `<form class="send-back-form" data-class="${esc(row.class_group_id)}">`,
    `<label for="reason-${esc(row.class_group_id)}">What needs fixing?</label>`,
    `<textarea id="reason-${esc(row.class_group_id)}" name="reason" required `,
    'rows="2"></textarea>',
    '<button type="submit">Send back</button>',
    "</form>",
  ].join("");
}

/**
 * Signed in, and with no part in this chain.
 *
 * A bursar, a parent. It does not offer the staff door: she is signed in with
 * a password already, and what she lacks is a role only the school can give
 * her — the false-remedy rule `accounts/refusals.py` turns on.
 */
export function notOnTheChain({ detail = "" } = {}) {
  return [
    '<section class="state state-not-on-the-chain" data-state="not-on-the-chain">',
    "<h1>You cannot move results along</h1>",
    `<p>${esc(detail) ||
      "Results are moved along by the class teacher, the vice principal " +
        "(academic) and the principal of the school the class belongs to."}</p>`,
    "<p>If that should be you, the school office is who can arrange it.</p>",
    signOutButton(),
    "</section>",
  ].join("");
}

/** This host is not a school's, so there are no results behind this URL. */
export function wrongHost() {
  return [
    '<section class="state state-wrong-host" data-state="wrong-host">',
    "<h1>Results live on your school's own web address</h1>",
    "<p>This page is open on the sign-in site. Open it again from your ",
    "school's own address — the link on the page you signed in on.</p>",
    "</section>",
  ].join("");
}

/** Signed out, or never signed in. The way back is on another host. */
export function signedOut({ portal = "", expired = false } = {}) {
  return [
    '<section class="state state-signed-out" data-state="signed-out">',
    `<h1>${expired ? "Your session has ended" : "Please sign in"}</h1>`,
    expired
      ? "<p>You were signed out after a period of inactivity. Any step you had " +
        "already taken was taken.</p>"
      : "<p>Sign in with your password to move results along.</p>",
    wayBack(portal),
    "</section>",
  ].join("");
}

function wayBack(portal) {
  // No portal domain configured means no link, only the sentence: a dead link
  // is worse than being told to go back the way you came — the rule
  // `schools.hosts.portal_host()` states and every other page here keeps.
  if (!portal) return "<p>Go back to the sign-in page you came from.</p>";
  return `<p><a href="//${esc(portal)}/staff-sign-in/">Sign in again</a></p>`;
}

/** Anything the page cannot explain: a 500, a dead transport, an unreadable body. */
export function broken() {
  return [
    '<section class="state state-broken" data-state="broken">',
    "<h1>This page is not working</h1>",
    "<p>Something went wrong on our side. Please try again in a few minutes, ",
    "and tell your school if it keeps happening.</p>",
    "</section>",
  ].join("");
}
