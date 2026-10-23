/**
 * Every screen the subject teachers page can show, as a pure function of the overview.
 *
 * Strings rather than DOM, for `card/states.js`' reason: a refusal is the path nobody
 * demos, and a string can be asserted in `node --test` with no browser.
 *
 * What is **not** here is any authority question. The page draws the form and the
 * Remove buttons only when the school says this login may change them (`may_change`),
 * and every write is refused on the server for anybody else.
 */

import { esc } from "../web/html.js";

const note = (n) => (n ? `<p class="note" role="alert">${esc(n.detail)}</p>` : "");

const options = (rows, blank) =>
  `<option value="">${esc(blank)}</option>` +
  rows.map((r) => `<option value="${esc(r.id)}">${esc(r.name)}</option>`).join("");

/** The page: what assignments do, the form (the principal's), the list by class, the log. */
export function overview({
  term = null,
  may_change = false,
  in_force = false,
  classes = [],
  subjects = [],
  teachers = [],
  assignments = [],
  changes = [],
  confirming = null,
  notes = {},
} = {}) {
  return [
    '<section class="state state-subject-teachers" data-state="subject-teachers">',
    "<h1>Who teaches what</h1>",
    term
      ? `<p class="hint">For the current term: ${esc(term)}.</p>`
      : '<p class="note" role="alert">No term is open. The current term is set on the Setup page.</p>',
    standing(in_force, may_change),
    term && may_change ? form({ classes, subjects, teachers, n: notes.assign }) : "",
    may_change ? "" : '<p class="hint">Only the principal changes these.</p>',
    '<h2 id="by-class">By class</h2>',
    classes.length
      ? `<ul class="classes">${classes.map((c) => classRow(c, assignments, may_change, confirming, notes)).join("")}</ul>`
      : '<p class="blank">No classes yet. They are opened on the Setup page.</p>',
    changeLog(changes),
    "</section>",
  ].join("");
}

/** What the assignments are doing to marking right now, in one sentence. */
function standing(inForce, mayChange) {
  if (inForce) {
    return (
      '<div class="msg" data-standing="in-force"><span class="label label-ok">In use</span>' +
      "<p>Each teacher marks only the subjects and classes given to them here. The principal " +
      "and the administrator can still mark any.</p></div>"
    );
  }
  return (
    '<div class="msg" data-standing="not-yet"><span class="label label-brand">Not yet</span>' +
    "<p>Nobody has been given a subject yet, so any teacher can mark any subject. " +
    `${mayChange ? "Once you give the first one" : "Once the principal gives the first one"}, ` +
    "each teacher marks only their own.</p></div>"
  );
}

function form({ classes, subjects, teachers, n }) {
  return [
    `<form class="assign${n ? ` ${esc(n.kind)}` : ""}" data-form="assign">`,
    "<h2>Give a teacher a subject</h2>",
    '<label for="st_teacher">Teacher</label>',
    `<select id="st_teacher" name="teacher" required>${options(teachers, "Choose a teacher")}</select>`,
    '<label for="st_subject">Subject</label>',
    `<select id="st_subject" name="subject" required>${options(subjects, "Choose a subject")}</select>`,
    '<label for="st_class">Class</label>',
    `<select id="st_class" name="class_group" required>${options(classes, "Choose a class")}</select>`,
    '<button type="submit">Give it to them</button>',
    teachers.length ? "" : '<p class="hint">No teachers yet. They are invited on the Staff page.</p>',
    subjects.length ? "" : '<p class="hint">No subjects yet. They are added on the Subjects page.</p>',
    note(n),
    "</form>",
  ].join("");
}

function classRow(c, assignments, mayChange, confirming, notes) {
  const mine = assignments.filter((a) => a.class_group_id === c.id);
  return [
    `<li class="group class-teachers" data-class="${esc(c.id)}">`,
    `<span class="name">${esc(c.name)}</span>`,
    mine.length
      ? `<ul class="taught">${mine.map((a) => assignmentRow(a, mayChange, confirming, notes["remove" + a.id])).join("")}</ul>`
      : '<span class="level">Nobody yet</span>',
    "</li>",
  ].join("");
}

function assignmentRow(a, mayChange, confirming, n) {
  const asking = confirming === a.id;
  const buttons = !mayChange
    ? ""
    : asking
      ? `<button type="button" class="submit" data-action="unassign" data-assignment="${esc(a.id)}">Take ${esc(a.subject)} from ${esc(a.teacher)}</button>` +
        '<button type="button" class="again" data-action="keep">Keep it</button>'
      : `<button type="button" data-action="ask-unassign" data-assignment="${esc(a.id)}" aria-label="Remove ${esc(a.teacher)} from ${esc(a.subject)}">Remove</button>`;
  return [
    `<li data-assignment="${esc(a.id)}">`,
    `<span class="what"><strong>${esc(a.subject)}</strong> <span class="who">${esc(a.teacher)}</span></span>`,
    buttons,
    note(n),
    "</li>",
  ].join("");
}

function changeLog(changes) {
  if (!changes.length) return "";
  const line = (c) =>
    c.kind === "added"
      ? `${esc(c.by)} gave ${esc(c.teacher)} ${esc(c.subject)} in ${esc(c.class_group)}`
      : `${esc(c.by)} took ${esc(c.subject)} in ${esc(c.class_group)} from ${esc(c.teacher)}`;
  return [
    '<details class="change-log">',
    "<summary>Recent changes</summary>",
    `<ul>${changes.map((c) => `<li>${line(c)} <span class="when">${esc(c.at)}</span></li>`).join("")}</ul>`,
    "</details>",
  ].join("");
}

export function notYours({ detail = "" } = {}) {
  return [
    '<section class="state state-refused" role="alert">',
    "<h1>This page is not yours</h1>",
    `<p>${esc(detail) || "Who teaches what is shown to the principal, the vice principal and the administrator."}</p>`,
    "</section>",
  ].join("");
}

export function wrongHost() {
  return [
    '<section class="state state-refused" role="alert">',
    "<h1>This is not a school&#39;s address</h1>",
    "<p>Open this page from your school&#39;s own address.</p>",
    "</section>",
  ].join("");
}

export function signedOut({ portal = "", expired = false } = {}) {
  const link = portal ? `<a href="//${esc(portal)}/staff-sign-in/">Sign in</a>` : "Sign in";
  return [
    '<section class="state state-refused" role="alert">',
    `<h1>${expired ? "Your session has ended" : "You are signed out"}</h1>`,
    `<p>${link} again to carry on.</p>`,
    "</section>",
  ].join("");
}

export function broken() {
  return [
    '<section class="state state-refused" role="alert">',
    "<h1>Something went wrong</h1>",
    "<p>This page could not be loaded. Please try again in a moment.</p>",
    "</section>",
  ].join("");
}
