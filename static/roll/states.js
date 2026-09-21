/**
 * Every screen the roll can show, as a pure function of an API body.
 *
 * **The two authorities are two booleans, and the page honours both
 * separately.** `may_admit` is ADMIN alone and `may_place` is principal or
 * admin, so a principal sees the roll, may move a child, and is offered no
 * admission form. Collapsing them into "is the office" would show her a form
 * that 403s on submit.
 */

import { esc } from "../web/html.js";
import { button as signOutButton } from "../web/signout.js";

/** The roll: every child, where they sit, and what may be done about it. */
export function roll({
  term = "",
  children = [],
  classes = [],
  may_admit = false,
  may_place = false,
  notes = {},
} = {}) {
  return [
    '<section class="state state-roll" data-state="roll">',
    "<h1>The roll</h1>",
    `<p class="term">${esc(term) || "No term is open"}</p>`,
    children.length
      ? `<ul class="children">${children
          .map((c) => childRow(c, { classes, may_place }))
          .join("")}</ul>`
      : '<p class="blank">Nobody is enrolled here yet.</p>',
    may_admit ? admitForm(classes, notes.admit) : notTheAdmissionsOffice(),
    notes.place ? `<p class="note" role="alert">${esc(notes.place.detail)}</p>` : "",
    signOutButton(),
    "</section>",
  ].join("");
}

/**
 * One child.
 *
 * A child with no class shows **"Not in a class yet"** rather than an empty
 * cell: admitted in August and placed in September is ordinary, and a blank
 * would read as a page that failed to draw.
 */
function childRow(c, { classes, may_place }) {
  const unplaced = c.class_group_id === null || c.class_group_id === undefined;
  return [
    `<li class="child${unplaced ? " unplaced" : ""}">`,
    `<span class="name">${esc(c.student)}</span>`,
    `<span class="handle">${esc(c.username)}</span>`,
    c.reference ? `<span class="reference">${esc(c.reference)}</span>` : "",
    may_place && classes.length
      ? classChooser(c, classes)
      : `<span class="standing">${
          unplaced ? "Not in a class yet" : esc(c.class_group)
        }</span>`,
    "</li>",
  ].join("");
}

/**
 * Which class this child is in.
 *
 * One control for placing and moving, because which of the two it is depends
 * on the child rather than on the person choosing — the server asks
 * `placement_of()` and picks. A screen with separate "place" and "move"
 * buttons would be making the office declare something it should not have to
 * know.
 */
function classChooser(c, classes) {
  const current = c.class_group_id === null || c.class_group_id === undefined
    ? ""
    : String(c.class_group_id);
  return [
    `<select data-child="${esc(c.student_membership_id)}" `,
    `aria-label="Class for ${esc(c.student)}">`,
    `<option value=""${current === "" ? " selected" : ""}>Not in a class yet</option>`,
    classes
      .map(
        (g) =>
          `<option value="${esc(g.class_group_id)}"${
            current === String(g.class_group_id) ? " selected" : ""
          }>${esc(g.name)}</option>`,
      )
      .join(""),
    "</select>",
  ].join("");
}

/**
 * Admitting a child.
 *
 * The handle is typed, never generated: `User.username` is school-issued —
 * "STM/2026/0042" is the model's own example — and a scheme this page invented
 * is one the school would have to live with on every register and every card.
 */
function admitForm(classes, note) {
  return [
    `<form class="admit${note ? ` ${esc(note.kind)}` : ""}" data-form="admit">`,
    "<h2>Admit a child</h2>",
    '<label for="full_name">Name</label>',
    '<input id="full_name" name="full_name" required>',
    '<label for="username">Handle your school gives them</label>',
    '<input id="username" name="username" placeholder="STM/2026/0042" required>',
    '<label for="reference">Admission number (optional)</label>',
    '<input id="reference" name="reference">',
    '<label for="class_group_id">Class (optional)</label>',
    '<select id="class_group_id" name="class_group_id">',
    '<option value="">Not yet</option>',
    classes
      .map((g) => `<option value="${esc(g.class_group_id)}">${esc(g.name)}</option>`)
      .join(""),
    "</select>",
    '<button type="submit">Admit</button>',
    note ? `<p class="note" role="alert">${esc(note.detail)}</p>` : "",
    "</form>",
  ].join("");
}

/**
 * A principal reading the roll.
 *
 * She may move a child between classes and may not admit one — ADMIN alone
 * hands out memberships. Said out loud rather than shown as a missing form,
 * because an absent form reads as a page that did not finish loading.
 */
function notTheAdmissionsOffice() {
  return (
    '<p class="quiet">Children are admitted by an administrator of the ' +
    "school. You can still move them between classes.</p>"
  );
}

/** Signed in, and with no part in the roll. */
export function notTheOffice({ detail = "" } = {}) {
  return [
    '<section class="state state-not-the-office" data-state="not-the-office">',
    "<h1>You cannot open the roll</h1>",
    `<p>${esc(detail) ||
      "Children are put in classes by a principal or an administrator of the " +
        "school."}</p>`,
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
    "<h1>The roll lives on your school's own web address</h1>",
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
      : "<p>Sign in with your password to open the roll.</p>",
    wayBack(portal),
    "</section>",
  ].join("");
}

function wayBack(portal) {
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
