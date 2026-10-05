/**
 * Every screen the teaching page can show, as a pure function of the school's overview.
 *
 * Strings rather than DOM, for `card/states.js`' reason: a refusal is the path nobody demos,
 * and a string can be asserted in `node --test` with no browser.
 */

import { esc } from "../web/html.js";

const note = (n) => (n ? `<p class="note" role="alert">${esc(n.detail)}</p>` : "");
const formClass = (base, n) => `${base}${n ? ` ${esc(n.kind)}` : ""}`;

/** The first screen: who is class teacher of each class, and the subjects. */
export function overview({ term = null, subjects = [], classes = [], teachers = [], notes = {} } = {}) {
  return [
    '<section class="state state-teaching" data-state="teaching">',
    "<h1>Subjects and teachers</h1>",
    term
      ? `<p class="hint">Papers and class teachers are for the current term: ${esc(term)}.</p>`
      : '<p class="note" role="alert">No term is open. Set the current term on the Setup page first.</p>',

    "<h2>Class teachers</h2>",
    '<p class="hint">The class teacher submits the class&#39;s results and signs its report cards.</p>',
    classes.length
      ? `<ul class="classes">${classes.map((c) => classTeacherRow(c, teachers, notes["class" + c.class_group_id])).join("")}</ul>`
      : '<p class="blank">No classes yet. Open them on the Setup page.</p>',
    teachers.length ? "" : '<p class="hint">No teachers yet. Invite them on the Staff page.</p>',

    "<h2>Subjects</h2>",
    subjects.length
      ? `<ul class="subjects-list">${subjects.map(subjectRow).join("")}</ul>`
      : '<p class="blank">No subjects yet.</p>',
    `<form class="${formClass("new-subject", notes.subject)}" data-form="subject">`,
    "<h3>Add a subject</h3>",
    '<label for="subject_name">Name</label>',
    '<input id="subject_name" name="name" placeholder="Mathematics" maxlength="100" required>',
    '<label for="subject_code">Short code</label>',
    '<input id="subject_code" name="code" placeholder="MTH" maxlength="16" required>',
    '<button type="submit">Add the subject</button>',
    note(notes.subject),
    "</form>",
    "</section>",
  ].join("");
}

function classTeacherRow(c, teachers, n) {
  const options = teachers
    .map(
      (t) =>
        `<option value="${esc(t.membership_id)}"${t.membership_id === c.class_teacher_id ? " selected" : ""}>${esc(t.name)}</option>`,
    )
    .join("");
  return [
    `<li class="group${n ? ` ${esc(n.kind)}` : ""}">`,
    `<label class="name" for="ct-${esc(c.class_group_id)}">${esc(c.name)}</label>`,
    `<select id="ct-${esc(c.class_group_id)}" data-class="${esc(c.class_group_id)}">`,
    `<option value="">No class teacher</option>${options}`,
    "</select>",
    note(n),
    "</li>",
  ].join("");
}

function subjectRow(s) {
  return [
    `<li class="group${s.is_active ? "" : " inactive"}">`,
    `<span class="name">${esc(s.name)}</span>`,
    `<span class="level">${esc(s.code)} &middot; ${esc(s.papers.length)} ${s.papers.length === 1 ? "paper" : "papers"} this term</span>`,
    s.is_active ? "" : '<span class="standing">No longer taught</span>',
    `<button type="button" data-action="open-subject" data-subject="${esc(s.subject_id)}">Open</button>`,
    "</li>",
  ].join("");
}

/** One subject: its details, this term's papers, and the ways to remove it. */
export function subject(s, { editing = null, confirming = null, notes = {} } = {}) {
  return [
    '<section class="state state-subject" data-state="subject">',
    '<button type="button" class="again" data-action="back">All subjects</button>',
    `<h1>${esc(s.name)}</h1>`,
    `<form class="${formClass("edit-subject", notes.subject)}" data-form="subject-edit" data-subject="${esc(s.subject_id)}">`,
    '<label for="name">Name</label>',
    `<input id="name" name="name" value="${esc(s.name)}" maxlength="100" required>`,
    '<label for="code">Short code</label>',
    `<input id="code" name="code" value="${esc(s.code)}" maxlength="16" required>`,
    `<label class="choice"><input type="checkbox" name="retired"${s.is_active ? "" : " checked"}> <span>No longer taught</span></label>`,
    '<button type="submit">Save</button>',
    note(notes.subject),
    "</form>",

    "<h2>Papers this term</h2>",
    s.papers.length
      ? `<ul class="classes">${s.papers.map((p) => paperRow(p, editing, confirming, notes["paper" + p.assessment_id])).join("")}</ul>`
      : '<p class="blank">No papers yet. Add the first CA and the exam.</p>',
    `<form class="${formClass("new-paper", notes.paper)}" data-form="paper" data-subject="${esc(s.subject_id)}">`,
    "<h3>Add a paper</h3>",
    '<label for="paper_name">Name</label>',
    '<input id="paper_name" name="name" placeholder="First CA" maxlength="64" required>',
    '<label for="paper_out_of">Out of</label>',
    '<input id="paper_out_of" name="max_score" type="number" min="1" max="1000" inputmode="numeric" placeholder="20" required>',
    '<button type="submit">Add the paper</button>',
    note(notes.paper),
    "</form>",

    "<h2>Remove</h2>",
    removeSubject(s, confirming, notes.remove),
    "</section>",
  ].join("");
}

function paperRow(p, editing, confirming, n) {
  if (editing === p.assessment_id) {
    return [
      `<li class="group editing${n ? ` ${esc(n.kind)}` : ""}">`,
      `<form data-form="paper-edit" data-paper="${esc(p.assessment_id)}">`,
      `<label for="pn-${esc(p.assessment_id)}">Name</label>`,
      `<input id="pn-${esc(p.assessment_id)}" name="name" value="${esc(p.name)}" maxlength="64" required>`,
      `<label for="po-${esc(p.assessment_id)}">Out of</label>`,
      `<input id="po-${esc(p.assessment_id)}" name="max_score" type="number" min="1" max="1000" inputmode="numeric" value="${esc(p.max_score)}"${p.has_marks ? " readonly" : ""} required>`,
      p.has_marks ? '<span class="hint">It has marks, so what it is out of cannot change.</span>' : "",
      '<button type="submit">Save</button>',
      '<button type="button" class="again" data-action="cancel-edit">Cancel</button>',
      note(n),
      "</form>",
      "</li>",
    ].join("");
  }
  const confirm = confirming && confirming.paper === p.assessment_id;
  return [
    `<li class="group${n ? ` ${esc(n.kind)}` : ""}">`,
    `<span class="name">${esc(p.name)}</span>`,
    `<span class="level">out of ${esc(p.max_score)}${p.has_marks ? " &middot; has marks" : ""}</span>`,
    `<button type="button" data-action="edit-paper" data-paper="${esc(p.assessment_id)}">Edit</button>`,
    p.has_marks
      ? ""
      : confirm
        ? `<button type="button" class="submit" data-action="remove-paper" data-paper="${esc(p.assessment_id)}">Remove ${esc(p.name)}</button>` +
          '<button type="button" class="again" data-action="keep">Keep it</button>'
        : `<button type="button" data-action="ask-remove-paper" data-paper="${esc(p.assessment_id)}">Remove</button>`,
    note(n),
    "</li>",
  ].join("");
}

function removeSubject(s, confirming, n) {
  if (s.papers_ever > 0) {
    return (
      `<p class="hint">${esc(s.name)} has papers, so it cannot be removed. ` +
      "Tick &quot;No longer taught&quot; above instead.</p>"
    );
  }
  const asking = confirming && confirming.subject === s.subject_id;
  return [
    asking
      ? `<button type="button" class="submit" data-action="remove-subject" data-subject="${esc(s.subject_id)}">Remove ${esc(s.name)}</button>` +
        '<button type="button" class="again" data-action="keep">Keep it</button>'
      : `<button type="button" data-action="ask-remove-subject" data-subject="${esc(s.subject_id)}">Remove this subject</button>`,
    note(n),
  ].join("");
}

export function notTheOffice({ detail = "" } = {}) {
  return [
    '<section class="state state-refused" role="alert">',
    "<h1>This page is the office&#39;s</h1>",
    `<p>${esc(detail) || "Subjects, papers and class teachers are set by a principal or an administrator of the school."}</p>`,
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
