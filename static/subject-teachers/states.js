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
  marking = "not-yet",
  carried = null,
  switching = false,
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
    carriedNote(carried),
    standing(marking, may_change, switching, notes.switch),
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

/** This term began with last term's assignments, copied in by the system. */
function carriedNote(carried) {
  if (!carried) return "";
  return (
    '<div class="msg" data-carried><span class="label label-brand">Copied</span>' +
    `<p>This term began with ${esc(carried.copied)} copied from ${esc(carried.from_term)}` +
    (carried.skipped
      ? `, and ${esc(carried.skipped)} not copied because the teacher, subject or class is gone (under Recent changes)`
      : "") +
    ". Check each class below.</p></div>"
  );
}

/** The switch, and the second tap that says what it will do before it does it. */
function switchFor(opening, switching, n) {
  if (!switching) {
    return (
      `<button type="button" data-action="ask-switch">${opening ? "Open marking to all teachers" : "Restrict marking again"}</button>` +
      note(n)
    );
  }
  const what = opening
    ? "Every teacher will be able to mark every subject in every class this term, whoever is given it here. The list stays, and you can restrict marking again here."
    : "Each teacher will mark only the subjects and classes given to them here. A teacher given none will mark nothing.";
  return (
    `<div class="confirm" data-confirm="switch"><p>${what}</p>` +
    `<button type="button" class="submit" data-action="switch" data-open="${opening}">${opening ? "Open marking to all" : "Restrict marking"}</button>` +
    `<button type="button" class="again" data-action="keep">${opening ? "Keep it restricted" : "Keep it open"}</button></div>`
  );
}

/** What the assignments are doing to marking right now, in one sentence, and the switch. */
function standing(marking, mayChange, switching, n) {
  const sw = (opening) => (mayChange ? switchFor(opening, switching, n) : "");
  if (marking === "restricted") {
    return (
      '<div class="msg" data-standing="in-force"><span class="label label-ok">In use</span>' +
      "<p>Each teacher marks only the subjects and classes given to them here, and a teacher " +
      "given none marks nothing. The principal and the administrator can still mark any.</p>" +
      sw(true) +
      "</div>"
    );
  }
  if (marking === "open") {
    return (
      '<div class="msg" data-standing="open"><span class="label label-brand">Open to all</span>' +
      "<p>The principal has opened marking to every teacher this term, so any teacher can mark " +
      "any subject in any class, whoever is given it here.</p>" +
      sw(false) +
      "</div>"
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

/** One line of the log. The system's own lines name the term they came from instead of a person. */
function changeLine(c) {
  const pair = `${esc(c.subject)} in ${esc(c.class_group)}`;
  const from = esc(c.from_term);
  switch (c.kind) {
    case "added":
      return c.from_term
        ? `Copied from ${from}: ${esc(c.teacher)}, ${pair}`
        : `${esc(c.by)} gave ${esc(c.teacher)} ${pair}`;
    case "removed":
      return `${esc(c.by)} took ${pair} from ${esc(c.teacher)}`;
    case "skipped":
      return `Not copied from ${from}: ${esc(c.teacher) || "a former teacher"}, ${pair} (${esc(c.reason)})`;
    case "opened":
      return c.from_term
        ? `Marking stayed open to all teachers, as it was in ${from}`
        : `${esc(c.by)} opened marking to all teachers`;
    default:
      return `${esc(c.by)} restricted marking to the teachers given each subject`;
  }
}

function changeLog(changes) {
  if (!changes.length) return "";
  const line = changeLine;
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
