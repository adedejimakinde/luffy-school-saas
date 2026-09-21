/**
 * Every screen the setup page can show, as a pure function of an API body.
 *
 * Strings rather than DOM, for `card/states.js`' reason: a refusal is the path
 * nobody demos, and a string can be asserted in `node --test` with no browser.
 */

import { esc, numberOrBlank } from "../web/html.js";
import { button as signOutButton } from "../web/signout.js";

/**
 * The school's shape: its terms and its class groups.
 *
 * **Exactly one term is marked current, and the others offer to become it.**
 * The constraint behind that is `one_current_term`, and the server clears the
 * old one in the same transaction — so the screen never has to ask anybody to
 * unset a term first, and never shows two as current.
 */
export function shape({ terms = [], classes = [], notes = {} } = {}) {
  return [
    '<section class="state state-setup" data-state="setup">',
    "<h1>School setup</h1>",

    "<h2>Terms</h2>",
    terms.length
      ? `<ul class="terms">${terms.map((t) => termRow(t)).join("")}</ul>`
      : '<p class="blank">No terms yet. The first one opens the school\'s calendar.</p>',
    newTermForm(notes.term),

    "<h2>Classes</h2>",
    classes.length
      ? `<ul class="classes">${classes.map(classRow).join("")}</ul>`
      : '<p class="blank">No class groups yet.</p>',
    newClassForm(notes.class),

    signOutButton(),
    "</section>",
  ].join("");
}

/**
 * One term.
 *
 * `school_days` is `numberOrBlank()` and not `|| "—"`: a term declared as
 * having nought teaching days is a real (if odd) statement, and one nobody has
 * declared yet is a different one. Truthiness cannot tell them apart, which is
 * the same care the card page takes with attendance.
 */
function termRow(t) {
  return [
    `<li class="term${t.is_current ? " current" : ""}">`,
    `<span class="name">${esc(t.session)} &middot; ${esc(t.name_label)}</span>`,
    `<span class="dates">${esc(t.starts_on)} to ${esc(t.ends_on)}</span>`,
    `<span class="days">${numberOrBlank(t.school_days)} school days</span>`,
    t.is_current
      ? '<span class="standing">Current</span>'
      : `<button type="button" data-action="make-current" ` +
        `data-term="${esc(t.term_id)}">Make current</button>`,
    "</li>",
  ].join("");
}

function classRow(c) {
  return [
    `<li class="group${c.is_active ? "" : " inactive"}">`,
    `<span class="name">${esc(c.name)}</span>`,
    `<span class="level">level ${esc(c.level)}</span>`,
    c.is_active ? "" : '<span class="standing">No longer taught</span>',
    "</li>",
  ].join("");
}

/**
 * Opening a term's record.
 *
 * It does **not** offer "and make it current" as a checkbox. Those are two
 * decisions, and a school opening next term's record while this one is still
 * being taught is the ordinary case — a checkbox defaulting either way would
 * be wrong for somebody.
 */
function newTermForm(note) {
  return [
    `<form class="new-term${note ? ` ${esc(note.kind)}` : ""}" data-form="term">`,
    "<h3>Open a term</h3>",
    '<label for="session">Session</label>',
    '<input id="session" name="session" placeholder="2026/2027" required>',
    '<label for="name">Term</label>',
    '<select id="name" name="name">',
    '<option value="first">First term</option>',
    '<option value="second">Second term</option>',
    '<option value="third">Third term</option>',
    "</select>",
    '<label for="starts_on">Starts</label>',
    '<input id="starts_on" name="starts_on" type="date" required>',
    '<label for="ends_on">Ends</label>',
    '<input id="ends_on" name="ends_on" type="date" required>',
    '<button type="submit">Open the term</button>',
    note ? `<p class="note" role="alert">${esc(note.detail)}</p>` : "",
    "</form>",
  ].join("");
}

function newClassForm(note) {
  return [
    `<form class="new-class${note ? ` ${esc(note.kind)}` : ""}" data-form="class">`,
    "<h3>Open a class group</h3>",
    '<label for="class_name">Name</label>',
    '<input id="class_name" name="name" placeholder="JSS 1A" required>',
    // Not derived from the name: "JSS 1A" sorts before "JSS 10A" as text, and
    // no string rule survives a school running Nursery, Primary and Senior.
    '<label for="level">Where it sits in your order</label>',
    '<input id="level" name="level" type="number" min="0" value="0">',
    '<button type="submit">Open the group</button>',
    note ? `<p class="note" role="alert">${esc(note.detail)}</p>` : "",
    "</form>",
  ].join("");
}

/** Signed in, and not somebody who shapes this school. */
export function notTheOffice({ detail = "" } = {}) {
  return [
    '<section class="state state-not-the-office" data-state="not-the-office">',
    "<h1>You cannot set this school up</h1>",
    `<p>${esc(detail) ||
      "The calendar and the class groups are set up by a principal or an " +
        "administrator of the school."}</p>`,
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
    "<h1>Setup lives on your school's own web address</h1>",
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
      ? "<p>You were signed out after a period of inactivity. Anything you had " +
        "already saved was saved.</p>"
      : "<p>Sign in with your password to set your school up.</p>",
    wayBack(portal),
    "</section>",
  ].join("");
}

function wayBack(portal) {
  // No portal domain configured means no link, only the sentence.
  if (!portal) return "<p>Go back to the sign-in page you came from.</p>";
  return `<p><a href="//${esc(portal)}/staff-sign-in/">Sign in again</a></p>`;
}

/** Anything the page cannot explain. */
export function broken() {
  return [
    '<section class="state state-broken" data-state="broken">',
    "<h1>This page is not working</h1>",
    "<p>Something went wrong on our side. Please try again in a few minutes, ",
    "and tell whoever runs this system for your school.</p>",
    "</section>",
  ].join("");
}
