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

/**
 * The steps, in the order the chain takes them, with what to call them.
 *
 * Release is not among them: it cannot be taken back, so its button asks
 * first (`releaseQuestion()`), and only the answer to that question takes it.
 */
const STEPS = [
  ["may_submit", "submit", "Submit"],
  ["may_check", "check", "Check"],
  ["may_approve", "approve", "Approve"],
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
export function chain({
  term = "",
  rows = [],
  notes = {},
  asking = null,
  telling = null,
  confirming = null,
  focus = null,
} = {}) {
  return [
    '<section class="state state-chain" data-state="chain">',
    "<h1>Results</h1>",
    `<p class="term">${esc(term)}</p>`,
    '<ul class="classes">',
    rows
      .map((row) => classRow(row, notes[row.class_group_id], { asking, telling, confirming, focus }))
      .join(""),
    "</ul>",
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
function classRow(row, note, { asking, telling, confirming, focus }) {
  const actions = STEPS.filter(([flag]) => row[flag]).map(
    ([, step, label]) =>
      `<button type="button" data-action="step" data-step="${step}" ` +
      `data-class="${esc(row.class_group_id)}">${label}</button>`,
  );
  if (row.may_release) {
    actions.push(
      `<button type="button" data-action="ask-release" ` +
        `data-class="${esc(row.class_group_id)}">Release to parents</button>`,
    );
  }
  if (row.may_send_back) {
    actions.push(
      `<button type="button" class="send-back" data-action="ask-send-back" ` +
        `data-class="${esc(row.class_group_id)}">Send back</button>`,
    );
  }
  if (row.may_tell_families) {
    // Its own step after release (docs/messaging.md D9). Pressing it asks
    // first — how many, and when — and sends nothing until "Send them". The
    // count under the row is how many have been asked for already; pressing
    // again sends only to families not yet told.
    actions.push(
      `<button type="button" class="tell" data-action="tell-families" ` +
        `data-class="${esc(row.class_group_id)}">Tell families</button>`,
    );
  }
  if (row.may_print_slips) {
    // Result-checker slips (docs/messaging.md D11): a PDF with a PIN for each
    // child who has none yet. Pressing it again prints only the children still
    // without one, so no slip already handed out stops working.
    actions.push(
      `<button type="button" class="slips" data-action="print-slips" ` +
        `data-class="${esc(row.class_group_id)}">Print checker slips</button>`,
    );
  }
  return [
    `<li id="class-${esc(row.class_group_id)}" class="row state-${esc(row.state)}` +
      `${focus === row.class_group_id ? " focus" : ""}${note ? ` ${esc(note.kind)}` : ""}">`,
    `<span class="name">${esc(row.class_group)}</span>`,
    row.state === "released"
      ? `<span class="standing"><span class="label label-ok">${esc(row.state_label)}</span></span>`
      : `<span class="standing">${esc(row.state_label)}</span>`,
    // The sheet itself, so whoever is about to approve or release reads the
    // numbers first. The broadsheet route decides who may, as it always did.
    `<a class="broadsheet" href="/broadsheet/?class=${encodeURIComponent(row.class_group_id)}">Broadsheet</a>`,
    actions.length
      ? `<span class="actions">${actions.join("")}</span>`
      : `<span class="actions quiet">${
          row.state === "released" ? "Released: nothing further" : "Nothing for you here"
        }</span>`,
    confirming === row.class_group_id && row.may_release ? releaseQuestion(row) : "",
    asking === row.class_group_id ? sendBackForm(row) : "",
    telling && telling.class_group_id === row.class_group_id ? tellingQuestion(row, telling) : "",
    leftOut(row),
    row.may_tell_families && row.families_told
      ? `<span class="told">${esc(row.families_told)} message${row.families_told === 1 ? "" : "s"} to families so far.</span>`
      : "",
    row.may_print_slips ? slips(row) : "",
    note ? noteFor(note) : "",
    "</li>",
  ].join("");
}

/**
 * What a press did, as a neutral message carrying its label: status colour
 * goes on the label and nowhere else (`docs/design.md`). The sentence is the
 * server's, or the page's own for a slip download, and is never reworded here.
 */
const NOTE_LABELS = {
  "already-signed": ["label-warn", "Already signed"],
  moved: ["label-warn", "Moved on"],
  "needs-a-reason": ["label-stop", "Needs a reason"],
  "not-checked": ["label-stop", "Not released"],
  "not-allowed": ["label-stop", "Not allowed"],
  told: ["label-ok", "Sent"],
  "not-told": ["label-stop", "Not sent"],
  "slips-printed": ["label-ok", "Downloading"],
  "not-printed": ["label-stop", "Not printed"],
};

function noteFor(note) {
  const [tone, label] = NOTE_LABELS[note.kind] || ["", "Note"];
  return [
    '<div class="note msg" role="alert">',
    `<span class="label ${tone}">${label}</span>`,
    `<p>${esc(note.detail)}</p>`,
    "</div>",
  ].join("");
}

/**
 * The question "Release to parents" asks before it releases anything.
 *
 * A release cannot be taken back: a wrong card is corrected by reissuing it,
 * not by moving the sheet back. So the first press only asks, and the release
 * is the second, on a button that names the class.
 */
function releaseQuestion(row) {
  const id = esc(row.class_group_id);
  const name = esc(row.class_group);
  return [
    '<div class="confirm-release" role="group" aria-label="Release">',
    `<p>Release ${name}'s results to parents? Their report cards go out as they `,
    "stand now, and a released card can only be corrected by reissuing it.</p>",
    '<span class="actions">',
    `<button type="button" class="btn-primary" data-action="step" data-step="release" data-class="${id}">Release ${name}</button>`,
    `<button type="button" data-action="cancel-release" data-class="${id}">Cancel</button>`,
    "</span>",
    "</div>",
  ].join("");
}

/**
 * The question "Tell families" asks before it sends anything.
 *
 * docs/messaging.md D9: how many messages; D7: in quiet hours, that they go at
 * 07:00. The sentence is the server's preview, so the number read here is the
 * number the same code counted, not one the page worked out. With nothing left
 * to send there is nothing to confirm, only a box to close.
 */
function tellingQuestion(row, telling) {
  const some = telling.messages > 0;
  const id = esc(row.class_group_id);
  return [
    '<div class="telling" role="status">',
    `<p>${esc(telling.detail)}</p>`,
    some ? `<button type="button" data-action="send-to-families" data-class="${id}">Send them</button>` : "",
    `<button type="button" data-action="cancel-telling" data-class="${id}">${some ? "Cancel" : "Close"}</button>`,
    "</div>",
  ].join("");
}

/**
 * How many children have a result-checker slip, and the way to replace a lost one.
 *
 * docs/messaging.md D11. A new slip for a child **stops the old PIN working**,
 * and the form says so before it is pressed: a slip that is only mislaid, not
 * lost, is a slip the family can no longer use once this has been done.
 *
 * The class id travels in a hidden field rather than on the form's `data-`
 * attribute, so the submit handler reads it the way it reads the admission
 * number.
 */
function slips(row) {
  const n = row.slips_printed || 0;
  const id = esc(row.class_group_id);
  return [
    '<div class="slips">',
    n
      ? `<p>Result-checker slips printed for ${n} ${n === 1 ? "child" : "children"}.</p>`
      : "<p>No result-checker slips printed yet.</p>",
    `<form class="lost-slip-form" data-class="${id}">`,
    `<input type="hidden" name="class_group_id" value="${id}">`,
    `<label for="lost-slip-${id}">Replace a lost slip: admission number</label>`,
    `<input id="lost-slip-${id}" name="admission_number" autocomplete="off" required>`,
    '<button type="submit">Print a new slip</button>',
    '<span class="hint">The old slip\'s PIN stops working.</span>',
    "</form>",
    "</div>",
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
    // Not the same as nobody: this release has no record of a check, and an
    // empty list here would read as "nobody was left out".
    return [
      '<div class="left-out msg" role="status">',
      '<span class="label label-warn">Not checked</span>',
      "<p>Couldn't check who was left out of this release. ",
      "Nobody is listed here, and that does not mean nobody was left out.</p>",
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
    '<div class="left-out msg" role="status">',
    '<span class="label label-warn">No card</span>',
    '<div class="said">',
    `<p>${count} no card from this release. They were placed into `,
    `${esc(row.class_group)} while it was being released, so they were not on it.</p>`,
    `<ul>${who}</ul>`,
    "</div>",
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
    "</section>",
  ].join("");
}

/** This host is not a school's, so there are no results behind this URL. */
export function wrongHost() {
  return [
    '<section class="state state-wrong-host" data-state="wrong-host">',
    "<h1>Results live on your school's own web address</h1>",
    "<p>This page is open on the sign-in site. Open it again from your ",
    "school's own address: the link on the page you signed in on.</p>",
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
