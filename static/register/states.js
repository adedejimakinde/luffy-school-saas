/**
 * Every screen the register can show, as a pure function of an API body.
 *
 * Strings rather than DOM, for `card/states.js`' reason: a refusal is the path
 * nobody demos, and a string can be asserted in `node --test` with no browser.
 *
 * The screen has two halves — choose a class, then mark it — and a handful of
 * answers that are neither. What is *not* here is any authority question: who
 * may take a register is `attendance.api._refuse_non_markers()`'s answer, and
 * a second opinion rendered in a browser would be a rule that looked enforced
 * and was not.
 */

import { esc } from "../web/html.js";
import { button as signOutButton } from "../web/signout.js";

/**
 * Which class, and for which day.
 *
 * **Every class the school teaches, because that is who may mark them.**
 * `can_mark_attendance()` is school-wide and carries no reference to
 * `ClassTeacher`, so a shorter list here would be a scope the platform does not
 * enforce, drawn as though it did — issue #125, where the domain question
 * behind it also lives.
 *
 * The date defaults to today and is editable, because a register entered from
 * paper on Friday afternoon for Wednesday is ordinary office work — the case
 * `MARKING_ROLES` admits principals and administrators for.
 */
export function choose({ term = "", classes = [], on = "" } = {}) {
  return [
    '<section class="state state-choose" data-state="choose">',
    "<h1>Take a register</h1>",
    `<p class="term">${esc(term)}</p>`,
    '<label for="on">Which day</label>',
    `<input id="on" name="on" type="date" data-field="on" value="${esc(on)}">`,
    "<p>Which class?</p>",
    '<ul class="classes">',
    classes
      .map(
        (group) =>
          `<li><button type="button" data-action="open" data-class="${esc(
            group.id,
          )}">${esc(group.name)}</button></li>`,
      )
      .join(""),
    "</ul>",
    signOutButton(),
    "</section>",
  ].join("");
}

/**
 * No current term, so there is nothing a register could be filed against.
 *
 * `Term.is_current` is a column the school sets, and this page will not guess
 * from the calendar: a register filed against a guessed term is worse than a
 * register not taken, because nothing about the row says it was a guess.
 */
export function noTerm() {
  return [
    '<section class="state state-no-term" data-state="no-term">',
    "<h1>No term is open</h1>",
    "<p>Your school has not marked a term as the current one, so there is ",
    "nothing to file a register against yet. The school office sets this.</p>",
    signOutButton(),
    "</section>",
  ].join("");
}

/**
 * The register itself. Tap the children who are **not** here.
 *
 * Absence is what is tapped, and that is the whole reason this fits in thirty
 * seconds in a corridor: `TakeRegisterIn.absent_ids` is what the teacher
 * marked and everyone else the screen showed is present. An empty list is
 * therefore a meaningful submission — it says every child was there — rather
 * than an empty one.
 *
 * `status` is nullable and null means **not marked**, which is a third answer
 * and not a synonym for present. A register that exists with a child unmarked
 * is different from one where they were marked present, and `taken` is what
 * tells an untaken register from one in which everybody happens to be unmarked.
 */
export function marking({
  class_group = "",
  term = "",
  taken_on = "",
  taken = false,
  rows = [],
  absent = [],
} = {}) {
  const tapped = new Set(absent);
  return [
    '<section class="state state-marking" data-state="marking">',
    `<h1>${esc(class_group)}</h1>`,
    `<p class="when">${esc(term)} &middot; ${esc(taken_on)}</p>`,
    taken
      ? '<p class="already">This register has already been taken. Submitting ' +
        "again amends it.</p>"
      : "",
    "<p>Tap the children who are <strong>not</strong> here.</p>",
    '<ul class="roster">',
    rows
      .map((row) => {
        const id = row.student_membership_id;
        const isAbsent = tapped.has(id);
        return [
          `<li class="${isAbsent ? "absent" : "present"}">`,
          `<button type="button" data-action="toggle" data-child="${esc(id)}" `,
          `aria-pressed="${isAbsent ? "true" : "false"}">`,
          esc(row.student) || "(no name on record)",
          `</button></li>`,
        ].join("");
      })
      .join(""),
    "</ul>",
    `<p class="tally">${tapped.size} marked absent of ${rows.length}</p>`,
    '<button type="button" class="submit" data-action="submit">Submit register</button>',
    '<button type="button" class="back" data-action="back">Another class</button>',
    "</section>",
  ].join("");
}

/**
 * What the write actually did, which is more than "saved".
 *
 * Four lists, and two of them need saying out loud. A child who joined the
 * group after the screen loaded is **not marked** and is named, because
 * silently marking someone present on a screen that never showed them is the
 * thing `shown_ids` exists to prevent. An absentee who has since been moved out
 * of the group had nothing written for them, and is named for the same reason.
 */
export function done({
  present = [],
  absent = [],
  appeared = [],
  not_on_the_roster = [],
  names = {},
} = {}) {
  const nameOf = (id) => esc(names[id] || `child ${id}`);
  return [
    '<section class="state state-done" data-state="done">',
    "<h1>Register taken</h1>",
    `<p>${present.length} present, ${absent.length} absent.</p>`,
    appeared.length
      ? "<p class=\"warn\">Not marked, because they were not on the screen when " +
        `you loaded it: ${appeared.map(nameOf).join(", ")}. Take the register ` +
        "again to include them.</p>"
      : "",
    not_on_the_roster.length
      ? '<p class="warn">Marked absent but no longer in this class, so nothing ' +
        `was recorded for them: ${not_on_the_roster.map(nameOf).join(", ")}.</p>`
      : "",
    '<button type="button" class="again" data-action="back">Another class</button>',
    signOutButton(),
    "</section>",
  ].join("");
}

/** The API refused the submission and said why in a sentence for a person. */
export function refused({ detail = "" } = {}) {
  return [
    '<section class="state state-refused" data-state="refused">',
    "<h1>That register was not taken</h1>",
    `<p>${esc(detail) || "The school's records disagree with this register."}</p>`,
    '<button type="button" class="again" data-action="back">Another class</button>',
    // A 409 or a 422 came back to a caller `session_auth` had already
    // identified, so this state stops with a live session on the page — which
    // is the platform's rule for where the button goes.
    signOutButton(),
    "</section>",
  ].join("");
}

/**
 * Signed in, and not somebody who takes registers here.
 *
 * A bursar, a vice principal (academic), a parent. It does not offer the staff
 * door: she is already signed in with a password, and what she lacks is a role
 * only the school can give her — the same false-remedy rule
 * `accounts/refusals.py` turns on.
 */
export function notAMarker({ detail = "" } = {}) {
  return [
    '<section class="state state-not-a-marker" data-state="not-a-marker">',
    "<h1>You cannot take a register here</h1>",
    `<p>${esc(detail) ||
      "A register is taken by a teacher, a principal or an administrator of " +
        "the school the class belongs to."}</p>`,
    "<p>If that should be you, the school office is who can arrange it.</p>",
    signOutButton(),
    "</section>",
  ].join("");
}

/**
 * This host is not a school's, so there is no register behind this URL at all.
 *
 * The portal serves this frame — `urls_public.py` splats the tenant patterns in
 * — and every route it calls begins with `_school_of()`, which 404s there
 * because the register tables do not exist in the public schema. So the page
 * says where the work is rather than pretending the URL was wrong.
 */
export function wrongHost() {
  return [
    '<section class="state state-wrong-host" data-state="wrong-host">',
    "<h1>Registers live on your school's own web address</h1>",
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
      ? "<p>You were signed out after a period of inactivity. Nothing you had " +
        "already submitted was lost.</p>"
      : "<p>Sign in with your password to take a register.</p>",
    wayBack(portal),
    "</section>",
  ].join("");
}

/**
 * The link back to the staff door, which is on another host — or a sentence,
 * if this deployment cannot say which host.
 *
 * `/staff-sign-in/` is on the portal and this page is on a school's host, so
 * the link cannot be relative. With no portal domain configured there is no
 * link, only the sentence: a dead link is worse than being told to go back the
 * way you came, which is the rule `schools.hosts.portal_host()` states and both
 * the card page and the 403 page keep.
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
