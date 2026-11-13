/**
 * Every screen the ID cards page can show, as a pure function of what the API said.
 *
 * Strings rather than DOM, for `card/states.js`' reason: a refusal is the path
 * nobody demos, and a string can be asserted in `node --test` with no browser.
 *
 * What is **not** here is any authority question. The page is drawn for the
 * three roles the server admits, and every route is refused on the server for
 * anybody else; a page that hid a button would restrict nothing.
 */

import { dayFirst, esc } from "../web/html.js";

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const note = (n) => (n ? `<p class="note" role="alert">${esc(n)}</p>` : "");

/** The page: the term, its classes with a Print button each, and the log. */
export function overview({
  terms = [],
  term = null,
  classes = [],
  phone_set = true,
  prints = [],
  printing = null,
  notes = {},
} = {}) {
  return [
    '<section class="state state-id-cards" data-state="id-cards">',
    "<h1>Student ID cards</h1>",
    '<div class="msg"><span class="label label-brand">What you get</span>',
    "<p>A credit-card sized card for each child, front and back: the school&#39;s crest and colour, the child&#39;s photo, name, admission number, class and session, ",
    "the date it expires, the school&#39;s phone for emergencies, and a QR code that opens a page confirming the card is valid. ",
    "Ten cards fit an A4 sheet, with cut marks.</p></div>",
    phone_set
      ? ""
      : '<p class="note" role="status">The school has no phone number on record, so the back of each card will say &ldquo;contact the school office&rdquo; with no number. Add it where the school&#39;s contact details are kept.</p>',
    termPicker(terms, term),
    term
      ? `<p class="hint">Cards printed for ${esc(term.label)} are valid until ${esc(dayFirst(term.expires_on))}, the end of the ${esc(term.session)} session.</p>`
      : '<p class="note" role="alert">No term has been set up yet. Terms are set on the Setup page.</p>',
    term && classes.length
      ? `<ul class="classes id-classes">${classes.map((c) => classRow(c, printing, notes)).join("")}</ul>`
      : term
        ? '<p class="blank">No classes yet. They are made on the Setup page.</p>'
        : "",
    printLog(prints),
    "</section>",
  ].join("");
}

function termPicker(terms, term) {
  if (terms.length < 2) return "";
  const options = terms
    .map((t) => `<option value="${esc(t.id)}"${term && t.id === term.id ? " selected" : ""}>${esc(t.label)}${t.is_current ? " (current)" : ""}</option>`)
    .join("");
  return `<div class="term-pick"><label for="idc_term">Term</label><select id="idc_term" name="term" data-term-select>${options}</select></div>`;
}

function classRow(c, printing, notes) {
  const open = printing && printing.class_group_id === c.id;
  const counts = c.students ? plural(c.students, "child", "children") : "Nobody placed this term";
  const action = !c.students
    ? ""
    : open
      ? ""
      : `<button type="button" data-action="ask-print" data-class="${esc(c.id)}" aria-label="Print ID cards for ${esc(c.name)}">Print ID cards</button>`;
  return [
    `<li class="group id-class" data-class="${esc(c.id)}">`,
    `<span class="name">${esc(c.name)}</span>`,
    `<span class="level">${counts}</span>`,
    `<div class="actions">${action}</div>`,
    note(notes[c.id]),
    open ? printPanel(c, printing) : "",
    "</li>",
  ].join("");
}

/**
 * Choose the children, then watch the file being made, then download it.
 *
 * Before the job: the class's children as boxes to tick, and a sentence saying
 * that ticking none prints the whole class. During it: the server's own
 * sentence and a progress bar. After: a link to the file, which is the
 * server's route and is kept for a day.
 */
export function printPanel(c, printing) {
  const id = esc(c.id);
  const parts = [`<div class="id-panel" role="group" aria-label="Print ID cards for ${esc(c.name)}">`];
  const job = printing.job;
  if (!job) {
    const children = printing.children;
    if (!children) return `${parts[0]}<p class="hint">Loading the class&hellip;</p></div>`;
    const n = children.length;
    parts.push(
      `<form class="id-form" data-print="${id}">`,
      "<fieldset>",
      `<legend>Which children? Tick none to print the whole class (${plural(n, "card", "cards")}).</legend>`,
      children
        .map((child) => {
          const childId = esc(child.student_membership_id);
          const ticked = (printing.chosen || []).includes(child.student_membership_id) ? " checked" : "";
          const adm = child.admission_number ? ` <span class="who">${esc(child.admission_number)}</span>` : ' <span class="who">no admission number</span>';
          return `<label class="pick"><input type="checkbox" data-print-child="${childId}" value="${childId}"${ticked}> <span>${esc(child.name || "A child with no name on record")}${adm}</span></label>`;
        })
        .join(""),
      "</fieldset>",
      '<span class="actions">',
      '<button type="submit">Make the PDF</button>',
      `<button type="button" class="again" data-action="cancel-print" data-class="${id}">Cancel</button>`,
      "</span>",
      "</form>",
    );
  } else {
    parts.push(`<p role="status">${esc(job.detail)}</p>`);
    if (job.state === "pending" || job.state === "building") {
      parts.push(`<progress max="${esc(job.total || 1)}" value="${esc(job.done || 0)}">${esc(job.done || 0)} of ${esc(job.total || 0)}</progress>`);
    }
    parts.push('<span class="actions">');
    if (job.download_url) parts.push(`<a class="btn btn-primary" href="${esc(job.download_url)}" download>Download the PDF</a>`);
    parts.push(`<button type="button" class="again" data-action="cancel-print" data-class="${id}">Close</button>`, "</span>");
  }
  parts.push("</div>");
  return parts.join("");
}

function printLog(prints) {
  if (!prints.length) return "";
  const line = (p) => {
    const what = p.card_count == null ? `ID cards for ${esc(p.class_group)}` : `${plural(p.card_count, "ID card", "ID cards")} for ${esc(p.class_group)}`;
    const state = p.state === "ready" ? "" : `, ${esc(String(p.state_label).toLowerCase())}`;
    const get = p.mine_to_download ? ` <a href="/api/id-cards/jobs/${esc(p.id)}/pdf/" download>Download</a>` : "";
    return `<li>${esc(p.by)} printed ${what} (${esc(p.term)})${state} <span class="when">${esc(p.at)}</span>${get}</li>`;
  };
  return [
    '<details class="change-log">',
    "<summary>Recent prints</summary>",
    `<ul>${prints.map(line).join("")}</ul>`,
    "</details>",
  ].join("");
}

export function notYours({ detail = "" } = {}) {
  return [
    '<section class="state state-refused" role="alert">',
    "<h1>This page is not yours</h1>",
    `<p>${esc(detail) || "Student ID cards are printed by the principal, the vice principal and the administrator."}</p>`,
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
