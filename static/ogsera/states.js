/**
 * Every screen of the OGSERA filler, as a pure function of its state.
 *
 * Three steps: choose the class, the subject and the file; map the template's
 * headings (the first time, or when asked); read the check and download.
 * Download is offered only when every row is matched to a child of the class.
 */

import { esc } from "../web/html.js";

function head() {
  return [
    '<div class="page-head"><div>',
    "<h1>Fill an OGSERA template</h1>",
    "<p>Upload the Excel file OGSERA gave you. Classnode fills in what it holds and gives it back.</p>",
    "</div></div>",
  ].join("");
}

function options(items, chosen, blank) {
  return [
    blank ? `<option value="">${esc(blank)}</option>` : "",
    ...items.map((i) => `<option value="${esc(i.id)}"${String(chosen) === String(i.id) ? " selected" : ""}>${esc(i.name)}</option>`),
  ].join("");
}

function note(n) {
  return n ? `<div class="msg" role="alert"><span class="label label-stop">Not done</span><p>${esc(n)}</p></div>` : "";
}

/** Where every visit starts. */
export function choose({ term = null, classes = [], subjects = [], picked = {}, note: n = null, busy = false } = {}) {
  return [
    '<section class="state state-choose" data-state="choose">',
    head(),
    term ? `<p class="term">${esc(term)}</p>` : '<p class="term">No term is open, so there is nothing to fill in.</p>',
    note(n),
    '<form class="card chooser" data-form="choose">',
    '<label for="class_group_id">Class</label>',
    `<select id="class_group_id" name="class_group_id" required>${options(classes, picked.classGroupId, "Choose a class")}</select>`,
    '<label for="subject_id">Subject</label>',
    `<select id="subject_id" name="subject_id">${options(subjects, picked.subjectId, "Not a subject's template")}</select>`,
    '<label for="file">OGSERA template</label>',
    '<input id="file" name="file" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" required>',
    `<button type="submit"${busy || !term ? " disabled" : ""}>${busy ? "Reading&hellip;" : "Check the file"}</button>`,
    "</form>",
    "</section>",
  ].join("");
}

/**
 * Which Classnode value each heading holds. A heading left on "Leave it" is
 * never written to.
 */
export function mapping({ headings = [], fields = [], note: n = null, busy = false } = {}) {
  const select = (h, i) =>
    `<select id="map_${i}" name="map_${i}" data-heading="${esc(h.heading)}" aria-label="${esc(h.heading)}">` +
    '<option value="">Leave it</option>' +
    fields.map((f) => `<option value="${esc(f.key)}"${f.key === h.field ? " selected" : ""}>${esc(f.label)}</option>`).join("") +
    "</select>";
  return [
    '<section class="state state-mapping" data-state="mapping">',
    head(),
    "<h2>What is in each column</h2>",
    "<p>Say which Classnode value goes in each column. This is saved for your school; change it whenever OGSERA changes a template. One column must be the learner&#39;s ID.</p>",
    note(n),
    '<form class="card" data-form="mapping">',
    '<ul class="headings">',
    headings
      .map((h, i) => `<li><span class="col">${esc(h.column)}</span><label for="map_${i}">${esc(h.heading)}</label>${select(h, i)}</li>`)
      .join(""),
    "</ul>",
    `<button type="submit"${busy ? " disabled" : ""}>Save and check</button>`,
    '<button type="button" data-action="again">Choose another file</button>',
    "</form>",
    "</section>",
  ].join("");
}

function list(title, items, render, kind = "stop") {
  if (!items || !items.length) return "";
  return [
    `<div class="msg"><span class="label label-${kind}">${esc(title)}</span>`,
    `<ul>${items.map((i) => `<li>${render(i)}</li>`).join("")}</ul></div>`,
  ].join("");
}

/** The check: what will be filled, and what stands in the way. */
export function checked({ check = {}, replace = false, note: n = null, busy = false, download = null } = {}) {
  const blocked = !check.may_download;
  return [
    '<section class="state state-checked" data-state="checked">',
    head(),
    `<p>${esc(check.matched)} rows matched to children. ${esc(check.filled)} cells to fill; ${esc(check.kept)} already have a value.</p>`,
    note(n),
    list("Not a child of this class", check.unmatched, (u) => `Row ${esc(u.row)}: learner ID ${esc(u.learner_id)}`),
    list("No learner ID", check.missing_id, (u) => `Row ${esc(u.row)}: ${esc(u.name)}`),
    list("Not in the file", check.not_in_file, esc, "warn"),
    list("No learner ID in Classnode", check.no_learner_id, esc, "warn"),
    list("Not entered yet", check.missing_values, esc, "warn"),
    blocked
      ? '<p class="blocked">Fix the rows above in the file, or the children&#39;s learner IDs on the roll, and check again. The file can be downloaded once every row is matched.</p>'
      : "",
    '<form class="card" data-form="fill">',
    `<label class="choice"><input type="checkbox" name="replace"${replace ? " checked" : ""}> <span>Replace existing values</span></label>`,
    `<button type="submit"${blocked || busy ? " disabled" : ""}>Download the filled file</button>`,
    '<button type="button" data-action="remap">Change the mapping</button>',
    '<button type="button" data-action="again">Choose another file</button>',
    "</form>",
    download ? `<p><a class="btn" href="${esc(download.url)}" download="${esc(download.name)}">Save ${esc(download.name)}</a></p>` : "",
    "</section>",
  ].join("");
}

export function notTheOffice({ detail = "" } = {}) {
  return `<section class="state" data-state="not-the-office"><h1>You cannot fill OGSERA templates</h1><p>${esc(detail) || "OGSERA templates are filled in by a principal or an administrator of the school."}</p></section>`;
}

export function notOgun({ detail = "" } = {}) {
  return `<section class="state" data-state="not-ogun"><h1>This is part of the Ogun State template</h1><p>${esc(detail)}</p><p><a class="btn" href="/setup/#report-card">Open setup</a></p></section>`;
}

export function wrongHost() {
  return '<section class="state" data-state="wrong-host"><h1>This page lives on your school&#39;s own web address</h1></section>';
}

export function signedOut({ portal = "", expired = false } = {}) {
  const back = portal ? `<p><a href="//${esc(portal)}/staff-sign-in/">Sign in again</a></p>` : "";
  return `<section class="state" data-state="signed-out"><h1>${expired ? "Your session has ended" : "Please sign in"}</h1>${back}</section>`;
}

export function broken() {
  return '<section class="state" data-state="broken"><h1>This page is not working</h1><p>Please try again in a few minutes.</p></section>';
}
