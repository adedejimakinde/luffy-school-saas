/**
 * Every screen the timetable page can show, as a pure function of API bodies.
 *
 * **A week is periods down and days across**, the way a school pins one to a
 * classroom wall. A cell is a lesson or it is free; a double period is two
 * cells that happen to say the same thing, because that is what the timetable
 * stores (two slots), and a page that merged them would be drawing a lesson
 * the data does not hold.
 *
 * **The editing controls are drawn only when the index says `may_edit`.** That
 * is not the guard — every write route asks again — it is so that a teacher,
 * who reads, is not shown buttons that would answer "you may not".
 */

import { esc } from "../web/html.js";
import { button as signOutButton } from "../web/signout.js";

function select(id, attribute, options, chosen) {
  return [
    `<select id="${id}" ${attribute}>`,
    options
      .map(
        ([value, label]) =>
          `<option value="${esc(value)}"${String(value) === String(chosen) ? " selected" : ""}>` +
          `${esc(label)}</option>`,
      )
      .join(""),
    "</select>",
  ].join("");
}

function chooser(index, classId) {
  const terms = index.terms.map((t) => [t.term_id, `${t.term}${t.is_current ? " (current)" : ""}`]);
  const classes = index.classes.map((c) => [c.class_group_id, c.class_group]);
  return [
    '<form class="chooser">',
    '<label for="term">Term</label>',
    select("term", "data-term", terms, index.term_id),
    classes.length ? '<label for="class">Class</label>' : "",
    classes.length ? select("class", "data-class", classes, classId) : "",
    "</form>",
  ].join("");
}

function periodName(p) {
  const times = `${p.starts_at}–${p.ends_at}`;
  return p.label ? `${esc(p.label)} <span class="times">${esc(times)}</span>` : esc(times);
}

function cell(lesson, editing, { weekday, periodId }) {
  if (!lesson) return '<td class="free"><span class="blank">Free</span></td>';
  const clear = editing
    ? ` <button type="button" class="small" data-action="clear" data-weekday="${esc(weekday)}" ` +
      `data-period="${esc(periodId)}" aria-label="Make this a free period">Free</button>`
    : "";
  return (
    `<td class="lesson"><span class="subject">${esc(lesson.subject)}</span>` +
    `<span class="teacher">${esc(lesson.teacher)}</span>${clear}</td>`
  );
}

/** The grid. Every lesson lands in the cell its weekday and period name. */
export function grid(index, week) {
  const editing = Boolean(index.may_edit);
  const at = new Map(week.lessons.map((l) => [`${l.weekday}:${l.period_id}`, l]));
  return [
    '<div class="scroll"><table class="week">',
    "<thead><tr><th>Period</th>",
    index.days.map((d) => `<th>${esc(d.day)}</th>`).join(""),
    "</tr></thead><tbody>",
    index.periods
      .map((p) => {
        const remove = editing
          ? ` <button type="button" class="small" data-action="remove-period" ` +
            `data-period="${esc(p.period_id)}" aria-label="Remove this period">Remove</button>`
          : "";
        return (
          `<tr><th scope="row">${periodName(p)}${remove}</th>` +
          index.days
            .map((d) =>
              cell(at.get(`${d.weekday}:${p.period_id}`), editing, {
                weekday: d.weekday,
                periodId: p.period_id,
              }),
            )
            .join("") +
          "</tr>"
        );
      })
      .join(""),
    "</tbody></table></div>",
  ].join("");
}

function lessonForm(index) {
  if (!index.may_edit || !index.periods.length) return "";
  const days = index.days.map((d) => [d.weekday, d.day]);
  const periods = index.periods.map((p) => [p.period_id, p.label || `${p.starts_at}–${p.ends_at}`]);
  const subjects = index.subjects.map((s) => [s.subject_id, s.subject]);
  const teachers = index.teachers.map((t) => [t.teacher_membership_id, t.teacher]);
  return [
    '<form class="edit" data-lesson>',
    "<fieldset><legend>Set a lesson</legend>",
    `<label>Day ${select("weekday", 'name="weekday"', days, "")}</label>`,
    `<label>Period ${select("period", 'name="period_id"', periods, "")}</label>`,
    `<label>Subject ${select("subject", 'name="subject_id"', subjects, "")}</label>`,
    `<label>Teacher ${select("teacher", 'name="teacher_membership_id"', teachers, "")}</label>`,
    '<button type="submit">Save</button>',
    '<p class="rule">A double period is the same lesson in two periods. A teacher can take ',
    "two classes at once only for the same subject.</p>",
    "</fieldset></form>",
  ].join("");
}

function bellForm(index) {
  if (!index.may_edit) return "";
  return [
    '<form class="edit" data-bell>',
    "<fieldset><legend>Add a period to the school day</legend>",
    '<label>Starts <input type="time" name="starts_at" required></label>',
    '<label>Ends <input type="time" name="ends_at" required></label>',
    '<label>Name <input type="text" name="label" maxlength="32" placeholder="Period 1"></label>',
    '<button type="submit">Add</button>',
    '<p class="rule">The same periods every weekday, for every class and every term.</p>',
    "</fieldset></form>",
  ].join("");
}

function copyOffer(index) {
  if (!index.may_edit || !index.term_is_empty || !index.has_earlier_term) return "";
  return (
    '<p class="copy">This term has no lessons yet. ' +
    '<button type="button" data-action="copy">Copy last term\'s timetable</button></p>'
  );
}

/** What the last action did, in a sentence — or nothing. */
function note(text) {
  return text ? `<p class="note" role="status">${esc(text)}</p>` : "";
}

export function week({ index, week: body = null, classId = null, note: said = "" } = {}) {
  let middle;
  if (!index.classes.length) {
    middle = "<p class=\"blank\">No classes are set up yet. The school office sets classes up.</p>";
  } else if (!index.periods.length) {
    middle = index.may_edit
      ? '<p class="blank" data-empty="no-periods">The school day has no periods yet. Add them below, then set lessons.</p>'
      : '<p class="blank" data-empty="no-periods">The school day has no periods yet, so there is no timetable to show.</p>';
  } else if (body) {
    middle = `<h2>${esc(body.class_group)}, ${esc(body.term)}</h2>` + grid(index, body);
  } else {
    middle = "";
  }
  return [
    '<section class="state state-week" data-state="week">',
    "<h1>Timetable</h1>",
    chooser(index, classId),
    note(said),
    copyOffer(index),
    middle,
    body ? lessonForm(index) : "",
    bellForm(index),
    signOutButton(),
    "</section>",
  ].join("");
}

/** No term to show: none set up, or none marked current and none chosen. */
export function noTerm({ index = {} } = {}) {
  const { terms = [] } = index;
  return [
    '<section class="state state-no-term" data-state="no-term">',
    "<h1>Timetable</h1>",
    terms.length
      ? `<p>No term is marked current. Choose one:</p>${chooser({ ...index, classes: [] }, null)}`
      : "<p>Your school has not set up a term, so there is no timetable yet. " +
        "The school office sets terms up.</p>",
    signOutButton(),
    "</section>",
  ].join("");
}

/**
 * Refused, or no such class or term. **One state for both**, because the
 * server gives one answer for both — see `api.js`.
 */
export function notYours() {
  return [
    '<section class="state state-not-yours" data-state="not-yours">',
    "<h1>This is not a timetable you can open</h1>",
    "<p>The timetable is read by the school's teachers, the principal, the vice ",
    "principal (academic) and the administrators. If that should include you, ",
    "whoever runs this system for your school can arrange it.</p>",
    signOutButton(),
    "</section>",
  ].join("");
}

export function wrongHost() {
  return [
    '<section class="state state-wrong-host" data-state="wrong-host">',
    "<h1>The timetable lives on your school's own web address</h1>",
    "<p>This page is open on the sign-in site. Open it again from your ",
    "school's own address.</p>",
    "</section>",
  ].join("");
}

export function signedOut({ portal = "", expired = false } = {}) {
  return [
    '<section class="state state-signed-out" data-state="signed-out">',
    `<h1>${expired ? "Your session has ended" : "Please sign in"}</h1>`,
    expired
      ? "<p>You were signed out after a period of inactivity.</p>"
      : "<p>Sign in with your password to read the timetable.</p>",
    portal
      ? `<p><a href="//${esc(portal)}/staff-sign-in/">Sign in again</a></p>`
      : "<p>Go back to the sign-in page you came from.</p>",
    "</section>",
  ].join("");
}

export function broken() {
  return [
    '<section class="state state-broken" data-state="broken">',
    "<h1>This page is not working</h1>",
    "<p>Something went wrong on our side. Please try again in a few minutes, ",
    "and tell whoever runs this system for your school.</p>",
    "</section>",
  ].join("");
}

/** "Copied 12 lessons from 2025/2026 First term." and what was left behind. */
export function copiedSentence(done) {
  const left = [
    [done.skipped_class, "in a class no longer in use"],
    [done.skipped_subject, "of a subject no longer taught"],
    [done.skipped_teacher, "by a teacher who has left"],
  ]
    .filter(([n]) => n)
    .map(([n, why]) => `${n} ${why}`);
  const lessons = done.copied === 1 ? "lesson" : "lessons";
  const base = `Copied ${done.copied} ${lessons} from ${done.from_term}.`;
  return left.length ? `${base} Left behind: ${left.join("; ")}. Those slots are free.` : base;
}
