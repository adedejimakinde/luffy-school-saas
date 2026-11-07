/**
 * Every screen the master broadsheet page can show, as a pure function of API bodies.
 *
 * **Every figure is the server's, already worked out.** A cell is a string or
 * null; null is a paper not marked and draws "-", never 0. The page adds no
 * total, no average and no rank, and sorts nothing: the rows come in the order
 * the server chose, which is by name when the school hides positions, because
 * rows in rank order would print a position that was meant to be hidden.
 *
 * **The position column exists only if the server sent one** (`show_position`).
 * It is not drawn and then hidden.
 *
 * The first column is the child's name, so the shared `.scroll` table keeps it
 * in place while the subjects scroll sideways on a phone.
 */

import { esc } from "../web/html.js";

const DASH = "-";

/** `value`, or a dash for none, and never a zero for nothing. */
export function figure(value) {
  return value === null || value === undefined || value === "" ? DASH : esc(value);
}

/** The subjects, each with how many columns it spans, in column order. */
export function subjectSpans(columns) {
  const spans = [];
  for (const column of columns) {
    const last = spans[spans.length - 1];
    if (last && last.subject_id === column.subject_id) last.span += 1;
    else spans.push({ subject_id: column.subject_id, subject: column.subject, span: 1 });
  }
  return spans;
}

/** Which columns start a subject, so the table can draw a rule before it. */
function firsts(columns) {
  return columns.map((column, i) => i === 0 || columns[i - 1].subject_id !== column.subject_id);
}

export function banner(preview) {
  return preview
    ? '<div class="msg" data-figures="live"><span class="label label-warn">Not released</span>' +
        "<p>These are live marks, and they change as teachers mark. A PDF of this sheet says " +
        "PREVIEW, NOT RELEASED on every page.</p></div>"
    : '<div class="msg" data-figures="released"><span class="label label-ok">Released</span>' +
        "<p>These are the figures that went home on the report cards, and they do not change.</p></div>";
}

/**
 * The file controls: the paper for a PDF, the PDF, and the Excel file, or the
 * running job in their place. The sentence is the server's.
 */
export function files(job, paper = "A4") {
  if (job) {
    const parts = ['<div class="files" role="status">', `<p>${esc(job.detail)}</p>`];
    if (job.state === "pending" || job.state === "building") {
      parts.push(`<progress max="${esc(job.total || 1)}" value="${esc(job.done || 0)}"></progress>`);
    }
    if (job.download_url) {
      const label = job.kind === "broadsheet_xlsx" ? "Download the Excel file" : "Download the PDF";
      parts.push(`<a class="btn btn-primary" href="${esc(job.download_url)}" download>${label}</a>`);
    }
    parts.push('<button type="button" data-action="close-file">Close</button>', "</div>");
    return parts.join("");
  }
  return [
    '<div class="files">',
    '<label for="paper">Paper</label>',
    '<select id="paper" data-paper>',
    ["A4", "A3"].map((p) => `<option value="${p}"${p === paper ? " selected" : ""}>${p}, landscape</option>`).join(""),
    "</select>",
    '<button type="button" data-action="make-pdf">Make the PDF</button>',
    '<button type="button" data-action="make-xlsx">Export to Excel</button>',
    "</div>",
  ].join("");
}

/** The table. */
export function sheet({ sheet: body = {}, job = null, paper = "A4" } = {}) {
  const { class_group = "", term = "", school = "", columns = [], rows = [], footer = [], grade_letters: letters = [] } = body;
  const starts = firsts(columns);
  const showPosition = body.show_position === true;
  const head = [
    '<section class="state state-sheet" data-state="sheet">',
    '<p class="back"><a href="/results/">All classes</a></p>',
    `<h1>Broadsheet: ${esc(class_group)}</h1>`,
    `<p class="term">${esc(term)}${school ? `, ${esc(school)}` : ""}</p>`,
    banner(body.preview),
    files(job, paper),
  ];
  if (!rows.length) {
    return head.concat(['<p class="blank">Nobody in this class has a result this term.</p>', "</section>"]).join("");
  }
  const spans = subjectSpans(columns);
  const tail = 2 + (showPosition ? 1 : 0) + letters.length + 1;
  return head
    .concat([
      showPosition && body.ranked != null
        ? `<p class="ranked-count" data-ranked="${esc(body.ranked)}">${esc(body.ranked)} of ${esc(rows.length)} ranked.</p>`
        : "",
      '<p class="swipe-cue">Swipe for more subjects</p>',
      '<div class="scroll wide"><table class="broadsheet master">',
      "<thead><tr>",
      // The name cell is in both header rows: the shared `.scroll` table holds
      // the first cell of every row in place, and the second header row's first
      // cell must be the name column's, not the first subject's.
      '<th class="name">Name</th>',
      spans.map((s) => `<th class="group" colspan="${esc(s.span)}">${esc(s.subject)}</th>`).join(""),
      '<th class="group" rowspan="2">Total</th><th rowspan="2">Average</th>',
      showPosition ? '<th rowspan="2">Position</th>' : "",
      letters.length ? `<th class="group" colspan="${letters.length}">Grades</th>` : "",
      '<th class="group" rowspan="2">Promotion</th>',
      '</tr><tr><th class="name"></th>',
      columns
        .map(
          (c, i) =>
            `<th${starts[i] ? ' class="group"' : ""}>${esc(c.label)}` +
            `${c.out_of ? `<small>${esc(c.out_of)}</small>` : ""}</th>`,
        )
        .join(""),
      letters.map((l, i) => `<th${i === 0 ? ' class="group"' : ""}>${esc(l)}</th>`).join(""),
      "</tr></thead><tbody>",
      rows
        .map(
          (r) =>
            "<tr>" +
            `<td class="name">${esc(r.name || "A child with no name on record")}</td>` +
            r.cells.map((v, i) => `<td class="num${starts[i] ? " group" : ""}">${figure(v)}</td>`).join("") +
            `<td class="num group">${figure(r.total)}</td>` +
            `<td class="num">${figure(r.average)}</td>` +
            (showPosition ? `<td class="num rank">${figure(r.position)}</td>` : "") +
            letters
              .map((l, i) => `<td class="num${i === 0 ? " group" : ""}">${figure(r.grades ? r.grades[l] : null)}</td>`)
              .join("") +
            `<td class="promotion group">${figure(r.promotion)}</td>` +
            "</tr>",
        )
        .join(""),
      "</tbody><tfoot>",
      footer
        .map(
          (f) =>
            `<tr><th class="name">${esc(f.label)}</th>` +
            f.cells.map((v, i) => `<td class="num${starts[i] ? " group" : ""}">${figure(v)}</td>`).join("") +
            `<td colspan="${tail}"></td></tr>`,
        )
        .join(""),
      "</tfoot></table></div>",
      "</section>",
    ])
    .join("");
}

export function notYours() {
  return [
    '<section class="state state-not-yours" data-state="not-yours">',
    "<h1>This is not a broadsheet you can open</h1>",
    "<p>A class's broadsheet is read by its class teacher, the vice principal ",
    "(academic), the principal and the school's administrators. If that should ",
    "include you, whoever runs this system for your school can arrange it.</p>",
    "</section>",
  ].join("");
}

export function notFound() {
  return [
    '<section class="state state-not-found" data-state="not-found">',
    "<h1>No such broadsheet</h1>",
    '<p>There is no such class or term here. <a href="/results/">Go back to the results.</a></p>',
    "</section>",
  ].join("");
}

export function wrongHost() {
  return [
    '<section class="state state-wrong-host" data-state="wrong-host">',
    "<h1>Broadsheets live on your school's own web address</h1>",
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
      : "<p>Sign in with your password to read the broadsheet.</p>",
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
