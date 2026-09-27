/**
 * Every screen the roll import can show, as a pure function of its state.
 *
 * **Nothing is saved until the office says so, and only a whole file is.**
 * The page checks a chosen file first and shows the verdict on every row, by
 * the row number in their spreadsheet; the button that admits appears only
 * when no row has a problem. That is `accounts/bulk.py`'s all-or-nothing rule,
 * drawn: a file that half-applied would leave an office reading the roll
 * against the spreadsheet by hand to learn which children landed.
 */

import { esc } from "../web/html.js";
import { TEMPLATE_URL } from "./api.js";

/** The heading each column has in the template, for the preview's header. */
export const COLUMNS = [
  ["full_name", "Full name"],
  ["class_group", "Class group"],
  ["reference", "Reference"],
  ["username", "Username"],
  ["guardian_name", "Guardian name"],
  ["guardian_contact", "Guardian contact"],
];

/** What each value is called on a phone's card, in the office's words. */
const CARD_LABEL = {
  full_name: "Name",
  class_group: "Class",
  reference: "Admission no.",
  username: "Username",
  guardian_name: "Guardian",
  guardian_contact: "Guardian contact",
};

const HEADING = Object.fromEntries(COLUMNS);

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

function head(term) {
  return [
    '<div class="page-head"><div>',
    "<h1>Import students</h1>",
    `<p>${term ? esc(term) : "No term is open"}</p>`,
    "</div>",
    '<a class="btn btn-quiet" href="/roll/">Back to the roll</a>',
    "</div>",
  ].join("");
}

/** Where every visit starts: the template, and the file chooser. */
export function choose({ term = null, classes = [], note = null, busy = false } = {}) {
  return [
    '<section class="state state-choose" data-state="choose">',
    head(term),
    term ? "" : noTerm(),
    '<div class="split">',
    chooser({ disabled: !term, note, busy }),
    template(classes),
    "</div>",
    "</section>",
  ].join("");
}

function noTerm() {
  return [
    '<div class="msg" role="alert"><span class="label label-stop">No term</span>',
    "<p>There is no class to place anybody in until the current term is set. ",
    'Set it on <a href="/setup/">Setup</a>, then come back.</p></div>',
  ].join("");
}

function chooser({ disabled, note, busy }) {
  return [
    '<section class="card chooser">',
    "<h2>Choose your file</h2>",
    '<form data-form="check">',
    '<div class="field"><label for="file">An Excel workbook (.xlsx) or a CSV file</label>',
    '<input id="file" name="file" type="file" required ',
    'accept=".xlsx,.csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,text/csv"',
    disabled ? " disabled" : "",
    ">",
    '<span class="hint">Every row is checked before anything is saved.</span></div>',
    `<button type="submit"${disabled || busy ? " disabled" : ""}>`,
    busy ? "Checking the file&hellip;" : "Check the file",
    "</button>",
    note ? `<div class="msg" role="alert"><span class="label label-stop">Not read</span><p>${esc(note)}</p></div>` : "",
    "</form>",
    "</section>",
  ].join("");
}

function template(classes) {
  return [
    '<section class="card template">',
    "<h2>Start from the template</h2>",
    "<p>One child to a row. <strong>Full name</strong> and <strong>Class group</strong> ",
    "are required. <strong>Reference</strong> is the admission number. A blank ",
    "<strong>Username</strong> is made from it. Give a guardian's name and contact ",
    "together, or neither.</p>",
    classes.length
      ? `<p class="classes"><span class="quiet">Classes this term:</span> ${classes.map(esc).join(", ")}</p>`
      : '<p class="quiet">This school has no classes yet. Add them on Setup first.</p>',
    `<a class="btn" href="${TEMPLATE_URL}" download>Download the template</a>`,
    "</section>",
  ].join("");
}

/**
 * The verdict on every row.
 *
 * Rows stay in file order, because the office fixes them by row number in
 * their spreadsheet. A row's problems are in the column beside its number,
 * each naming the column it is about.
 */
export function preview({ term = null, fileName = "", preview: p, busy = false, note = null } = {}) {
  const rows = p.rows || [];
  const fixes = p.problem_rows || 0;
  return [
    '<section class="state state-preview" data-state="preview">',
    head(term),
    '<section class="card">',
    `<div class="card-head"><h2>${esc(fileName) || "Your file"}</h2>`,
    `<span class="label">${plural(rows.length, "row", "rows")}</span></div>`,
    p.admissible ? ready(rows.length, busy) : toFix(fixes),
    note ? `<div class="msg" role="alert"><span class="label label-stop">Not admitted</span><p>${esc(note)}</p></div>` : "",
    '<div class="table-scroll"><table class="rows stack">',
    "<thead><tr>",
    '<th class="num">Row</th>',
    "<th>Check</th>",
    COLUMNS.map(([, heading]) => `<th>${heading}</th>`).join(""),
    "</tr></thead><tbody>",
    rows.map(row).join(""),
    "</tbody></table></div>",
    "</section>",
    "</section>",
  ].join("");
}

function ready(n, busy) {
  return [
    '<div class="msg"><span class="label label-ok">Ready</span>',
    `<p>Every row passed. Nothing is saved until you admit ${n === 1 ? "this child" : `all ${n}`}.</p></div>`,
    '<div class="actions">',
    `<button type="button" class="submit" data-action="admit"${busy ? " disabled" : ""}>`,
    busy ? "Admitting&hellip;" : `Admit ${plural(n, "child", "children")}`,
    "</button>",
    '<button type="button" data-action="again">Choose another file</button>',
    "</div>",
  ].join("");
}

function toFix(n) {
  return [
    '<div class="msg" role="alert">',
    `<span class="label label-stop">${plural(n, "row", "rows")} to fix</span>`,
    "<p>Nothing has been saved. Fix the rows marked below in your spreadsheet, ",
    "save it, and choose it again.</p></div>",
    '<div class="actions"><button type="button" data-action="again">Choose the file again</button></div>',
  ].join("");
}

function row(r) {
  const problems = r.problems || [];
  const bad = new Set(problems.map((p) => p.column));
  const cell = ([key]) => {
    const value = r[key] || "";
    const shown = value
      ? esc(value)
      : key === "username" && !bad.has(key)
        ? '<span class="quiet">Made on import</span>'
        : "";
    return `<td data-label="${CARD_LABEL[key]}"${bad.has(key) ? ' class="bad"' : ""}>${shown}</td>`;
  };
  const verdict = problems.length
    ? '<span class="label label-stop">Fix</span>'
    : '<span class="label label-ok">Ready</span>';
  return [
    `<tr${problems.length ? ' class="to-fix"' : ""} data-line="${esc(r.line)}">`,
    // The phone's card opens with "Row 3" and its verdict; the table has
    // them as its first two columns instead, so this cell is phone-only.
    `<td class="stack-head card-only">Row ${esc(r.line)} ${verdict}</td>`,
    `<td class="num stack-hide">${esc(r.line)}</td>`,
    // Straight after the row number on a desktop. On a phone the verdict is
    // in the card's head, and the problems close the card.
    `<td class="check${problems.length ? " stack-full" : " stack-hide"}">`,
    verdict,
    problems.length
      ? '<ul class="problems">' +
        problems.map((p) => `<li><strong>${HEADING[p.column] || esc(p.column)}:</strong> ${esc(p.detail)}</li>`).join("") +
        "</ul>"
      : "",
    "</td>",
    COLUMNS.map(cell).join(""),
    "</tr>",
  ].join("");
}

/**
 * What the import did. The handles it made are listed by row and name,
 * because a child cannot be handed a login nobody wrote down.
 */
export function done({ term = null, report = {}, preview: p = { rows: [] } } = {}) {
  const names = Object.fromEntries((p.rows || []).map((r) => [String(r.line), r.full_name]));
  const generated = Object.entries(report.generated || {});
  const pending = report.guardians_pending || 0;
  return [
    '<section class="state state-done" data-state="done">',
    head(term),
    '<section class="card">',
    '<div class="msg" role="status"><span class="label label-ok">Admitted</span>',
    `<p>${plural(report.admitted || 0, "child was", "children were")} admitted and placed in their classes.</p></div>`,
    pending
      ? '<div class="msg"><span class="label label-warn">Guardians to confirm</span>' +
        `<p>${plural(pending, "guardian link is", "guardian links are")} waiting for the guardian to answer ` +
        "the school. Send each a code from the child's Guardians on the roll.</p></div>"
      : "",
    generated.length
      ? [
          "<h2>Usernames made on import</h2>",
          "<p>Write these down for the children: nobody else has them.</p>",
          '<div class="table-scroll"><table class="made stack">',
          '<thead><tr><th class="num">Row</th><th>Name</th><th>Username</th></tr></thead><tbody>',
          generated
            .map(
              ([line, handle]) =>
                `<tr><td class="num" data-label="Row">${esc(line)}</td>` +
                `<td class="stack-head">${esc(names[line] || "")}</td>` +
                `<td data-label="Username">${esc(handle)}</td></tr>`,
            )
            .join(""),
          "</tbody></table></div>",
        ].join("")
      : "",
    '<div class="actions">',
    '<a class="btn btn-primary" href="/roll/">Open the roll</a>',
    '<button type="button" data-action="again">Import another file</button>',
    "</div>",
    "</section>",
    "</section>",
  ].join("");
}

/** Signed in, and not somebody who may admit children here. */
export function notTheOffice({ detail = "" } = {}) {
  return [
    '<section class="state state-not-the-office" data-state="not-the-office">',
    "<h1>You cannot import students</h1>",
    `<p>${esc(detail) || "Children are admitted by an administrator of the school."}</p>`,
    "<p>If that should be you, whoever runs this system for your school can arrange it.</p>",
    "</section>",
  ].join("");
}

/** This host is not a school's. */
export function wrongHost() {
  return [
    '<section class="state state-wrong-host" data-state="wrong-host">',
    "<h1>The import lives on your school's own web address</h1>",
    "<p>This page is open on the sign-in site. Open it again from your ",
    "school's own address, the link on the page you signed in on.</p>",
    "</section>",
  ].join("");
}

/** Signed out, or never signed in. The way back is on another host. */
export function signedOut({ portal = "", expired = false } = {}) {
  return [
    '<section class="state state-signed-out" data-state="signed-out">',
    `<h1>${expired ? "Your session has ended" : "Please sign in"}</h1>`,
    expired
      ? "<p>You were signed out after a period of inactivity. Nothing from this " +
        "page was saved unless it said so.</p>"
      : "<p>Sign in with your password to import students.</p>",
    portal
      ? `<p><a href="//${esc(portal)}/staff-sign-in/">Sign in again</a></p>`
      : "<p>Go back to the sign-in page you came from.</p>",
    "</section>",
  ].join("");
}

/** Anything the page cannot explain. */
export function broken() {
  return [
    '<section class="state state-broken" data-state="broken">',
    "<h1>This page is not working</h1>",
    "<p>Something went wrong on our side. Nothing from this page was saved. ",
    "Please try again in a few minutes, and tell whoever runs this system for your school.</p>",
    "</section>",
  ].join("");
}
