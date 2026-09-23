/**
 * Every screen the roll can show, as a pure function of an API body.
 *
 * **The two authorities are two booleans, and the page honours both
 * separately.** `may_admit` is ADMIN alone and `may_place` is principal or
 * admin, so a principal sees the roll, may move a child, and is offered no
 * admission form. Collapsing them into "is the office" would show her a form
 * that 403s on submit.
 *
 * **A child's guardians open in a panel**, loaded when asked for rather than
 * with the roll, so the roll costs nothing per child. `may_link` is the
 * panel's own boolean: ADMIN alone links and removes, and a principal reads.
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
  panel = null,
} = {}) {
  return [
    '<section class="state state-roll" data-state="roll">',
    "<h1>The roll</h1>",
    `<p class="term">${esc(term) || "No term is open"}</p>`,
    panel ? guardiansPanel(panel) : "",
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
    `<button type="button" data-action="guardians" data-child="${esc(c.student_membership_id)}">`,
    "Guardians</button>",
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

/**
 * One child's guardians.
 *
 * **What a guardian is here comes from the server and is not decided here.**
 * `status` is read from the guardian's membership at this school, and a link
 * starts `pending verification` whoever the guardian is — a parent verified at
 * another school included (#135). This renderer says what the server said; a
 * page that assumed "not live" would pass every test that only looked at new
 * guardians, and would go on saying it after a guardian had answered.
 *
 * `name` and `contact` are what this school typed, and nothing else until the
 * guardian is live here — see `GuardianOut` for why.
 */
export function guardiansPanel({ body = {}, note = null, confirming = null } = {}) {
  const { student = "", guardians = [], may_link = false, relationships = [] } = body;
  return [
    '<section class="guardians" data-panel="guardians">',
    `<h2>Guardians of ${esc(student)}</h2>`,
    guardians.length
      ? `<ul class="guardian-list">${guardians
          .map((g) => guardianRow(g, { may_link, confirming, student }))
          .join("")}</ul>`
      : '<p class="blank">No guardian is linked to this child yet.</p>',
    may_link
      ? linkForm(relationships, note)
      : '<p class="quiet">Guardians are linked by an administrator of the school.</p>',
    !may_link && note ? `<p class="note" role="alert">${esc(note.detail)}</p>` : "",
    '<button type="button" data-action="close-guardians">Close</button>',
    "</section>",
  ].join("");
}

function guardianRow(g, { may_link, confirming, student }) {
  return [
    `<li class="guardian" data-status="${esc(g.status)}">`,
    `<span class="name">${esc(g.name) || "—"}</span>`,
    `<span class="contact">${esc(g.contact) || "—"}</span>`,
    `<span class="relationship">${esc(g.relationship)}</span>`,
    `<p class="standing">${standing(g, student)}</p>`,
    may_link ? removeControl(g, confirming, student) : "",
    "</li>",
  ].join("");
}

/**
 * The link, in a sentence. **"Not live yet" is said out loud**, because an
 * administrator who links a parent and walks away believing they are done has
 * done half a job — and nothing on this screen can send the code yet, so it
 * says that too rather than offering a button that goes nowhere.
 */
function standing(g, student) {
  if (g.status === "live") {
    return g.channel === "dormant"
      ? "Live, but their phone has been quiet for 180 days, so they cannot sign " +
          "in until the school reactivates it."
      : `Live: they can see ${esc(student)}.`;
  }
  if (g.status === "suspended") {
    return `Suspended by the school: they cannot see ${esc(student)}.`;
  }
  return (
    `Pending verification — not live yet. They cannot see ${esc(student)} ` +
    "until they confirm with this school. Sending them a code is not " +
    "connected yet."
  );
}

/**
 * Removing a guardian takes **two clicks**. D11 calls it an authority
 * decision, and a slipped hand on a list of parents is not one.
 */
function removeControl(g, confirming, student) {
  if (String(confirming) === String(g.link_id)) {
    return [
      '<p class="confirm" role="alert">',
      `Remove ${esc(g.name) || "this guardian"} from ${esc(student)}? `,
      `<button type="button" data-action="remove-guardian" data-link="${esc(g.link_id)}">`,
      "Yes, remove</button> ",
      '<button type="button" data-action="cancel-remove">Cancel</button>',
      "</p>",
    ].join("");
  }
  return (
    `<button type="button" data-action="ask-remove" data-link="${esc(g.link_id)}">` +
    "Remove</button>"
  );
}

/**
 * Linking a guardian. **A refused link keeps what was typed** — a mistyped
 * number is one field to fix, not a name and a number to type again.
 */
function linkForm(relationships, note) {
  const typed = (note && note.typed) || {};
  const chosen = typed.relationship || "guardian";
  return [
    `<form class="link-guardian${note ? ` ${esc(note.kind)}` : ""}" data-form="guardian">`,
    "<h3>Link a guardian</h3>",
    '<label for="guardian_name">Name</label>',
    `<input id="guardian_name" name="guardian_name" value="${esc(typed.full_name)}" required>`,
    '<label for="guardian_contact">Phone number or email</label>',
    '<input id="guardian_contact" name="guardian_contact" placeholder="0803 123 4567" ',
    `value="${esc(typed.contact)}" required>`,
    '<label for="relationship">Relationship</label>',
    '<select id="relationship" name="relationship">',
    relationships
      .map(
        (r) =>
          `<option value="${esc(r)}"${r === chosen ? " selected" : ""}>${esc(
            r.charAt(0).toUpperCase() + r.slice(1),
          )}</option>`,
      )
      .join(""),
    "</select>",
    '<button type="submit">Link guardian</button>',
    note ? `<p class="note" role="alert">${esc(note.detail)}</p>` : "",
    "</form>",
  ].join("");
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
