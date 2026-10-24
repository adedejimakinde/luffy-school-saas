/**
 * Every screen the exam slips page can show, as a pure function of the overview.
 *
 * Strings rather than DOM, for `card/states.js`' reason: a refusal is the path nobody
 * demos, and a string can be asserted in `node --test` with no browser.
 *
 * What is **not** here is any authority question. The page draws the officer form and
 * the End buttons only when the school says this login is the principal (`may_name`),
 * and every route is refused on the server for anybody else. No PIN is ever in a state:
 * the only place one exists is the PDF the browser saves.
 */

import { esc } from "../web/html.js";

const note = (n) => (n ? `<p class="note" role="alert">${esc(n.detail)}</p>` : "");
const done = (text) => (text ? `<p class="done" role="status">${esc(text)}</p>` : "");
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

/** The page: what a slip is, each class with its Print button, exam officers, the log. */
export function overview({
  term = null,
  may_name = false,
  classes = [],
  officers = [],
  candidates = [],
  prints = [],
  officer_changes = [],
  open = null,
  roster = null,
  confirming = null,
  notes = {},
  printed = {},
} = {}) {
  return [
    '<section class="state state-exam-slips" data-state="exam-slips">',
    "<h1>Exam slips</h1>",
    term
      ? `<p class="hint">For the current term: ${esc(term)}.</p>`
      : '<p class="note" role="alert">No term is open. The current term is set on the Setup page.</p>',
    '<div class="msg"><span class="label label-brand">How slips work</span>',
    "<p>Each student signs in to a test with the code their teacher reads out, their admission number and the exam PIN on their slip. ",
    "A slip works for this term only. Printing a class again gives everyone in it a new PIN, and the slips already given out stop working.</p></div>",
    '<h2 id="by-class">By class</h2>',
    term && classes.length
      ? `<ul class="classes slips">${classes.map((c) => classRow(c, { open, roster, confirming, notes, printed })).join("")}</ul>`
      : term
        ? '<p class="blank">No classes yet. They are opened on the Setup page.</p>'
        : "",
    officerSection({ may_name, officers, candidates, confirming, notes }),
    printLog(prints),
    officerLog(officer_changes),
    "</section>",
  ].join("");
}

function classRow(c, { open, roster, confirming, notes, printed }) {
  const key = `class${c.id}`;
  const asking = confirming === key;
  const counts = c.students
    ? `${plural(c.students, "student", "students")}, ${c.with_a_pin} with a slip`
    : "Nobody placed this term";
  const last = c.last_print ? `Last printed ${esc(c.last_print.at)} by ${esc(c.last_print.by)}` : "Not printed yet this term";
  const print = !c.students
    ? ""
    : asking
      ? `<div class="confirm" data-confirm="${esc(key)}"><p>${
          c.with_a_pin
            ? `${esc(c.name)} gets ${plural(c.students, "new slip", "new slips")}. The ${plural(c.with_a_pin, "slip", "slips")} already given out will stop working.`
            : `${esc(c.name)} gets ${plural(c.students, "slip", "slips")}.`
        }</p>` +
        `<button type="button" class="submit" data-action="print-class" data-class="${esc(c.id)}">Print ${esc(c.name)}</button>` +
        '<button type="button" class="again" data-action="keep">Not now</button></div>'
      : `<button type="button" data-action="ask-print-class" data-class="${esc(c.id)}">${c.with_a_pin ? "Print again" : "Print slips"}</button>`;
  const lost = c.students && c.with_a_pin
    ? `<button type="button" class="again" data-action="${open === c.id ? "close-class" : "open-class"}" data-class="${esc(c.id)}" aria-expanded="${open === c.id}">${open === c.id ? "Close" : "A lost slip"}</button>`
    : "";
  return [
    `<li class="group class-slips" data-class="${esc(c.id)}">`,
    `<span class="name">${esc(c.name)}</span>`,
    `<span class="level">${counts}. ${last}.</span>`,
    `<div class="actions">${print}${lost}</div>`,
    note(notes[key]),
    done(printed[key]),
    open === c.id ? studentList(c, roster, confirming, notes, printed) : "",
    "</li>",
  ].join("");
}

function studentList(c, roster, confirming, notes, printed) {
  if (!roster || roster.id !== c.id) return '<p class="hint">Loading the class&hellip;</p>';
  if (!roster.students.length) return '<p class="blank">Nobody is placed in this class this term.</p>';
  return `<ul class="students">${roster.students.map((s) => studentRow(c, s, confirming, notes, printed)).join("")}</ul>`;
}

function studentRow(c, s, confirming, notes, printed) {
  const key = `student${s.id}`;
  const asking = confirming === key;
  const button = !s.admission_number
    ? '<span class="hint">No admission number on the Roll</span>'
    : asking
      ? `<div class="confirm" data-confirm="${esc(key)}"><p>${esc(s.name)} gets a new slip${s.has_pin ? ", and the old one stops working" : ""}.</p>` +
        `<button type="button" class="submit" data-action="print-student" data-class="${esc(c.id)}" data-student="${esc(s.id)}">Print for ${esc(s.name)}</button>` +
        '<button type="button" class="again" data-action="keep">Not now</button></div>'
      : `<button type="button" data-action="ask-print-student" data-student="${esc(s.id)}" aria-label="New slip for ${esc(s.name)}">New slip</button>`;
  return [
    `<li data-student="${esc(s.id)}">`,
    `<span class="what"><strong>${esc(s.name)}</strong> <span class="who">${esc(s.admission_number || "")}${s.has_pin ? "" : s.admission_number ? ", no slip yet" : ""}</span></span>`,
    button,
    note(notes[key]),
    done(printed[key]),
    "</li>",
  ].join("");
}

function officerSection({ may_name, officers, candidates, confirming, notes }) {
  return [
    '<h2 id="officers">Exam officers</h2>',
    '<p class="hint">An exam officer prints exam slips for any class. ',
    may_name ? "You name them, and end it when they stop." : "The principal names them.",
    "</p>",
    officers.length
      ? `<ul class="officers">${officers.map((o) => officerRow(o, may_name, confirming, notes)).join("")}</ul>`
      : '<p class="blank">No exam officers yet.</p>',
    may_name ? officerForm(candidates, notes.name) : "",
  ].join("");
}

function officerRow(o, mayName, confirming, notes) {
  const key = `end${o.membership_id}`;
  const asking = confirming === key;
  const buttons = !mayName
    ? ""
    : asking
      ? `<div class="confirm" data-confirm="${esc(key)}"><p>${esc(o.name)} will no longer print exam slips.</p>` +
        `<button type="button" class="submit" data-action="end" data-member="${esc(o.membership_id)}">End it for ${esc(o.name)}</button>` +
        '<button type="button" class="again" data-action="keep">Keep them</button></div>'
      : `<button type="button" data-action="ask-end" data-member="${esc(o.membership_id)}" aria-label="End ${esc(o.name)} as exam officer">End</button>`;
  return [
    `<li data-officer="${esc(o.membership_id)}">`,
    `<span class="what"><strong>${esc(o.name)}</strong> <span class="who">${esc(o.role)}, named by ${esc(o.named_by)} ${esc(o.named_at)}${
      o.can_act ? "" : ". Cannot act while their place here is suspended or ended"
    }</span></span>`,
    buttons,
    note(notes[key]),
    "</li>",
  ].join("");
}

function officerForm(candidates, n) {
  const options =
    '<option value="">Choose a person</option>' +
    candidates.map((c) => `<option value="${esc(c.membership_id)}">${esc(c.name)} (${esc(c.role)})</option>`).join("");
  return [
    `<form class="name-officer${n ? ` ${esc(n.kind)}` : ""}" data-form="name-officer">`,
    "<h3>Name an exam officer</h3>",
    '<label for="eo_member">Teacher, vice principal or administrator</label>',
    `<select id="eo_member" name="member" required>${options}</select>`,
    '<label for="eo_note">Note (optional)</label>',
    '<input id="eo_note" name="note" maxlength="200" autocomplete="off">',
    '<button type="submit">Name exam officer</button>',
    candidates.length ? "" : '<p class="hint">Nobody else can be named. Staff are invited on the Staff page.</p>',
    note(n),
    "</form>",
  ].join("");
}

function printLine(p) {
  const what = p.kind === "student" ? `a new slip for ${esc(p.student)} in ${esc(p.class_group)}` : `${plural(p.count, "slip", "slips")} for ${esc(p.class_group)}`;
  const cancelled = p.cancelled ? `, ${plural(p.cancelled, "old PIN", "old PINs")} stopped` : "";
  const missing = p.without_a_number ? `, ${plural(p.without_a_number, "student", "students")} with no admission number` : "";
  return `${esc(p.by)} printed ${what}${cancelled}${missing}`;
}

function printLog(prints) {
  if (!prints.length) return "";
  return [
    '<details class="change-log">',
    "<summary>Slips printed this term</summary>",
    `<ul>${prints.map((p) => `<li>${printLine(p)} <span class="when">${esc(p.at)}</span></li>`).join("")}</ul>`,
    "</details>",
  ].join("");
}

function officerLog(changes) {
  if (!changes.length) return "";
  const line = (c) =>
    (c.kind === "named" ? `${esc(c.by)} named ${esc(c.name)} (${esc(c.role)}) exam officer` : `${esc(c.by)} ended ${esc(c.name)} as exam officer`) +
    (c.note ? `: ${esc(c.note)}` : "");
  return [
    '<details class="change-log">',
    "<summary>Exam officer changes</summary>",
    `<ul>${changes.map((c) => `<li>${line(c)} <span class="when">${esc(c.at)}</span></li>`).join("")}</ul>`,
    "</details>",
  ].join("");
}

export function notYours({ detail = "" } = {}) {
  return [
    '<section class="state state-refused" role="alert">',
    "<h1>This page is not yours</h1>",
    `<p>${esc(detail) || "Exam slips are printed by the principal, the administrator or an exam officer."}</p>`,
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
