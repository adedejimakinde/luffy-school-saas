/**
 * Every screen the marking flow can show, as a pure function of an API body.
 *
 * Strings rather than DOM, for `card/states.js`' reason: a refusal is the path
 * nobody demos, and a string can be asserted in `node --test` with no browser.
 *
 * What is **not** here is any authority question. Who may mark is
 * `can_enter_marks()`'s answer, asked by every route this page calls; a second
 * opinion rendered in a browser would be a rule that looked enforced and was
 * not.
 */

import { esc, numberOrBlank } from "../web/html.js";
import { button as signOutButton } from "../web/signout.js";

/**
 * Which assessment, and which class.
 *
 * **Every subject and every class the school has.** `can_enter_marks()` is
 * school-wide and carries no reference to either, so a shorter list would be a
 * scope the platform does not enforce, drawn as though it did — issue #128.
 * And a sheet cannot be scoped by subject even in principle: nothing models
 * which students take which subject, which is issue #127 and why SSS electives
 * cannot be expressed at all.
 */
export function choose({ term = "", assessments = [], classes = [] } = {}) {
  return [
    '<section class="state state-choose" data-state="choose">',
    "<h1>Enter marks</h1>",
    `<p class="term">${esc(term)}</p>`,
    "<p>Which paper?</p>",
    '<ul class="assessments">',
    assessments
      .map(
        (a) =>
          `<li><button type="button" data-action="pick-assessment" ` +
          `data-assessment="${esc(a.id)}">${esc(a.subject)} &middot; ` +
          `${esc(a.name)} <span class="quiet">out of ${esc(a.max_score)}</span>` +
          `</button></li>`,
      )
      .join(""),
    "</ul>",
    "<p>Which class?</p>",
    '<ul class="classes">',
    classes
      .map(
        (g) =>
          `<li><button type="button" data-action="pick-class" ` +
          `data-class="${esc(g.id)}">${esc(g.name)}</button></li>`,
      )
      .join(""),
    "</ul>",
    signOutButton(),
    "</section>",
  ].join("");
}

/**
 * No current term, so there is nothing to mark against.
 *
 * `Term.is_current` is a column the school sets. This page will not infer one
 * from the calendar: a mark filed against a guessed term carries nothing
 * saying it was a guess.
 */
export function noTerm() {
  return [
    '<section class="state state-no-term" data-state="no-term">',
    "<h1>No term is open</h1>",
    "<p>Your school has not marked a term as the current one, so there is ",
    "nothing to enter marks against yet. The school office sets this.</p>",
    signOutButton(),
    "</section>",
  ].join("");
}

/**
 * The sheet. One row per child, each a cell that saves when it loses focus.
 *
 * **`locked` disables every cell up front**, which is the whole reason the
 * flag is on the payload. Without it a teacher types a mark into a cell that
 * cannot accept it, tabs away, and learns from the 423 — after typing. The
 * number they just entered is the worst moment to find out the sheet shut.
 *
 * `numberOrBlank()` rather than `value || ""`: a mark of **0** is a real mark
 * and an unmarked cell is not the same thing. Truthiness cannot tell them
 * apart, and the nought-versus-null care the card page carries is the same
 * care a blank cell needs here.
 */
export function sheet({
  assessment = "",
  subject = "",
  term = "",
  class_group = "",
  max_score = 0,
  locked = false,
  locked_reason = "",
  rows = [],
  notes = {},
  kept = {},
  session = null,
  portal = "",
  warnings = [],
  notTheAuthor = false,
} = {}) {
  return [
    '<section class="state state-sheet" data-state="sheet">',
    `<h1>${esc(subject)} &middot; ${esc(assessment)}</h1>`,
    `<p class="when">${esc(class_group)} &middot; ${esc(term)} &middot; `,
    `out of ${esc(max_score)}</p>`,
    locked
      ? `<p class="locked" role="status">${esc(locked_reason) ||
          "This sheet has left draft, so its marks cannot be changed here."}</p>`
      : "",
    session ? sessionEndedHere({ portal, expired: session === "expired" }) : "",
    warnings.map((warning) => `<p class="warning" role="note">${esc(warning)}</p>`).join(""),
    notTheAuthor
      ? '<p class="not-the-author" role="alert">Somebody else is signed in on this browser now. ' +
        "Marks below that are not sent yet were entered under another account, and are sent " +
        "only when that account is signed in again.</p>"
      : "",
    '<ul class="roster">',
    rows
      .map((row) =>
        cell(row, {
          locked,
          max_score,
          note: notes[row.student_membership_id],
          held: kept[row.student_membership_id],
        }),
      )
      .join(""),
    "</ul>",
    '<button type="button" class="back" data-action="back">Another paper</button>',
    signOutButton(),
    "</section>",
  ].join("");
}

/**
 * One child's cell, and whatever the last save had to say about it.
 *
 * `data-version` is what the next save sends as `expected_version`, and it is
 * deliberately empty rather than `0` for an unmarked child: null is what tells
 * `set_score()` this must be an insert, and `0` would be a version claim.
 *
 * `held` is a mark the teacher typed that did not land (`app.js`, `kept`). When
 * typing again is the remedy it is what the box shows, so the teacher's number
 * is still there to correct or resend. Otherwise the note carries it and the box
 * shows the server's. Either way there is a **Dismiss**, because only the
 * teacher can decide their number is no longer wanted.
 */
function cell(row, { locked, max_score, note, held }) {
  const id = row.student_membership_id;
  const shown = held && held.inBox ? held.value : row.value;
  const value = shown === null || shown === undefined ? "" : shown;
  return [
    `<li class="row${note ? ` ${esc(note.kind)}` : ""}">`,
    `<label for="mark-${esc(id)}">${esc(row.student) || "(no name on record)"}</label>`,
    `<input id="mark-${esc(id)}" type="number" min="0" max="${esc(max_score)}" `,
    `inputmode="numeric" value="${esc(value)}" `,
    `data-child="${esc(id)}" `,
    `data-version="${row.version === null || row.version === undefined ? "" : esc(row.version)}"`,
    locked ? " disabled" : "",
    ">",
    `<span class="total">${numberOrBlank(row.total && row.total.scored)}`,
    `/${numberOrBlank(row.total && row.total.available)}</span>`,
    note
      ? `<span class="note" role="${note.kind === "queued" ? "status" : "alert"}">${esc(note.detail)}</span>`
      : "",
    held && held.retry && !locked
      ? `<button type="button" class="retry" data-action="retry" data-child="${esc(id)}">Try again</button>`
      : "",
    held && !held.queued
      ? `<button type="button" class="dismiss" data-action="dismiss" data-child="${esc(id)}">Dismiss</button>`
      : "",
    "</li>",
  ].join("");
}

/**
 * The session lapsed while the sheet was open, and the sheet stays.
 *
 * It used to be replaced by the signed-out screen, and every mark not yet saved
 * went with it. Now the marks stay in their boxes. The way back opens in a new
 * tab, so this one, and what is typed in it, is still here to press Try again
 * on once the teacher has signed in.
 */
function sessionEndedHere({ portal = "", expired = false } = {}) {
  const link = portal
    ? `<a href="//${esc(portal)}/staff-sign-in/" target="_blank" rel="noopener">Sign in again</a> ` +
      "in a new tab, then come back here and press Try again on each mark."
    : "Sign in again in a new tab, then come back here and press Try again on each mark.";
  return [
    '<div class="session-ended" role="alert">',
    `<p><strong>${expired ? "Your session has ended." : "You are signed out."}</strong> `,
    "Marks you had already saved were saved as you entered them. ",
    "The ones below marked <em>Not saved</em> are still on this page.</p>",
    `<p>${link}</p>`,
    "</div>",
  ].join("");
}

/**
 * Signed in, and not somebody who enters marks here.
 *
 * It does not offer the staff door: she is signed in with a password already,
 * and what she lacks is a role only the school can give her — the false-remedy
 * rule `accounts/refusals.py` turns on.
 */
export function notAMarker({ detail = "" } = {}) {
  return [
    '<section class="state state-not-a-marker" data-state="not-a-marker">',
    "<h1>You cannot enter marks here</h1>",
    `<p>${esc(detail) ||
      "Marking is done by a teacher, a principal or an administrator of the " +
        "school that set the paper."}</p>`,
    "<p>If that should be you, the school office is who can arrange it.</p>",
    signOutButton(),
    "</section>",
  ].join("");
}

/** This host is not a school's, so there is no gradebook behind this URL. */
export function wrongHost() {
  return [
    '<section class="state state-wrong-host" data-state="wrong-host">',
    "<h1>Marks live on your school's own web address</h1>",
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
      ? "<p>You were signed out after a period of inactivity. Marks you had " +
        "already saved were saved as you entered them.</p>"
      : "<p>Sign in with your password to enter marks.</p>",
    wayBack(portal),
    "</section>",
  ].join("");
}

/**
 * The link back to the staff door, which is on another host — or a sentence,
 * if this deployment cannot say which host.
 *
 * With no portal domain configured there is no link, only the sentence: a dead
 * link is worse than being told to go back the way you came, which is the rule
 * `schools.hosts.portal_host()` states and the card page, the 403 page and the
 * register all keep.
 */
function wayBack(portal) {
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
