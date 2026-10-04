/**
 * The card, as markup. A renderer and nothing else.
 *
 * ## It computes nothing about the table
 *
 * `card.columns` is the header in print order and each `card.subjects[i].cells`
 * is that subject's marks already aligned to it, `null` where the subject has
 * no such paper. Both are assembled by `card_api.card_payload()`, from the same
 * `card_columns()`/`card_rows()` the PDF renderer uses. So this walks two lists
 * in the order given and never sorts, groups, matches or pads anything.
 *
 * That is deliberate and it is the second time this platform has made the
 * choice: the PDF renderer used to own the alignment, and moving it into the
 * payload was PR #117. A browser deriving its own columns would be a third
 * assembly of "what a card says", in the layer with the least test coverage,
 * and the day it disagreed with the file a parent would be holding two
 * documents that put the same mark under different headings.
 *
 * ## Two absences that must not look the same
 *
 * | on the page | means |
 * | --- | --- |
 * | `·` in a cell | this subject has no such paper at all |
 * | `—` in a cell | the child was not marked in it |
 * | `0 of 60 days` | present on none of the days the school was open |
 *
 * A `null` entry in `cells` is the first; an entry whose `score` is `null` is
 * the second. `docs/report-card-pdf.md` has the same table, because the file
 * and the page have to agree about it.
 */

import { esc, numberOrBlank } from "../web/html.js";
import { ogunCard } from "./ogun.js";

/**
 * The whole page body for one card payload.
 *
 * `pdfUrl` is the one thing here that is not on the payload: it is built from
 * the ids already in the page's own URL (`app.js`), the same two the payload
 * itself was fetched with, never derived from anything in `payload`. Absent
 * where the caller has none to give, and then the button is not drawn — a
 * link to a file this page cannot name would be worse than no button.
 */
export function card(payload, { pdfUrl = null, health = null } = {}) {
  // The Ogun State sheet, for a school that prints it (`docs/ogun-template.md`).
  if (payload.ogun) return ogunCard(payload, { pdfUrl, health });
  return [
    masthead(payload, pdfUrl),
    who(payload),
    marks(payload),
    sections(payload),
    comments(payload),
    sessionLine(payload),
    promotion(payload),
  ].join("");
}

function masthead(payload, pdfUrl) {
  return [
    '<header class="masthead">',
    `<h1>${esc(payload.school_name)}</h1>`,
    `<p class="term">${esc(payload.term_label)} &middot; ${esc(
      payload.academic_session,
    )}</p>`,
    // The word "Revised" comes from `is_revised` and from nowhere else: a
    // parent holding two cards for one term has to be able to tell which
    // supersedes the other. Not the reason and not who signed it — that is the
    // school's audit, not a line on a child's card.
    payload.is_revised ? '<p class="revised">Revised</p>' : "",
    // Parents look for this first — the same line the PDF prints under its
    // own masthead, from the same field on the payload.
    payload.next_term_begins
      ? `<p class="resume"><strong>Next term begins:</strong> ${date(payload.next_term_begins)}</p>`
      : "",
    pdfUrl
      ? `<p class="pdf-link"><a class="btn" href="${esc(pdfUrl)}" target="_blank" rel="noopener">Download PDF</a></p>`
      : "",
    "</header>",
  ].join("");
}

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

/**
 * "l j F Y" the way `django.utils.dateformat` prints the same field in the
 * PDF: "Monday 21 December 2026". Built by hand rather than with
 * `toLocaleDateString`, whose weekday form inserts a comma Django's does not
 * and whose available locales are a property of the machine running the
 * browser or the test, not of this page.
 */
export function date(isoDate) {
  const parsed = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(isoDate));
  if (!parsed) return esc(String(isoDate));
  const [, year, month, day] = parsed;
  const at = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  return `${WEEKDAYS[at.getUTCDay()]} ${Number(day)} ${MONTHS[Number(month) - 1]} ${year}`;
}

/**
 * The blue summary card: who this is, and the two numbers a parent opens the
 * card for. The table inside is unchanged from before this had a colour —
 * `tests/js/card_render.test.js` reads `Attendance</th><td>` straight out of
 * it — this only wraps it.
 */
function who(payload) {
  const adm = payload.admission_number
    ? `<span class="adm">Adm. no. ${esc(payload.admission_number)}</span>`
    : "";
  return [
    '<section class="summary">',
    '<table class="who">',
    `<tr><th scope="row">Name</th><td>${esc(payload.student_name)}${adm}</td>`,
    `<th scope="row">Class</th><td>${esc(payload.class_group_name)}</td></tr>`,
    `<tr><th scope="row">Average</th><td>${percentage(payload.own_average)}</td>`,
    `<th scope="row">Attendance</th><td>${attendance(payload)}</td></tr>`,
    // The summary: marks obtained over obtainable, and the percentage of it.
    // The position only where the card carries one, which is only where the
    // school prints it (`place_in_class`).
    `<tr><th scope="row">Marks</th><td>${marksSummary(payload)}</td>`,
    payload.place_in_class
      ? `<th scope="row">Position</th><td>${esc(payload.place_in_class.label)}</td></tr>`
      : "<td></td><td></td></tr>",
    "</table>",
    "</section>",
  ].join("");
}

function marksSummary(payload) {
  if (!payload.percentage) return '<span class="blank">—</span>';
  return `${esc(payload.total_scored)} of ${esc(payload.total_available)} obtainable &middot; ${esc(payload.percentage)}%`;
}

/**
 * The marks table: one header cell per column, one row per subject.
 *
 * The header carries each paper's maximum because `max_score` is per
 * `(term, subject, name)` — a bare "45" under "Exam" does not tell a parent
 * whether that was a good mark, and two subjects' "Exam" can be out of two
 * different totals, which is why they are two columns rather than one.
 */
function marks(payload) {
  const columns = payload.columns || [];
  const head = columns
    .map(
      (column) =>
        `<th scope="col" class="n">${esc(column.name)}<span class="max">/${esc(
          column.max_score,
        )}</span></th>`,
    )
    .join("");

  const body = (payload.subjects || []).map((line) => row(line, columns)).join("");

  return [
    // The scroll box `card.css` needs: eleven columns cannot fit a phone, and
    // the honest answer is a table that scrolls inside its own box rather than
    // a page that scrolls sideways and takes the headings with it. `print.css`
    // unsets it, because paper has no scroll.
    // Below 640px `design.css` stacks it instead: one card per subject, each
    // paper a labelled line.
    '<div class="grid-scroll">',
    '<table class="grid stack">',
    "<thead><tr>",
    '<th scope="col">Subject</th>',
    head,
    '<th scope="col" class="n">Total</th>',
    '<th scope="col" class="n">%</th>',
    '<th scope="col" class="n">Grade</th>',
    '<th scope="col">Remark</th>',
    "</tr></thead><tbody>",
    body ||
      `<tr><td colspan="${columns.length + 5}" class="blank">No subjects were marked this term.</td></tr>`,
    "</tbody></table>",
    "</div>",
  ].join("");
}

function row(line, columns) {
  // `cells` is already the length of `columns`; slicing or padding here would
  // be this file deciding the alignment after all. If the two ever disagree
  // that is a payload bug, and a short row is visible rather than papered over.
  // Each cell names its paper for the phone's card, where there is no header.
  const cells = (line.cells || [])
    .map((cell, i) => {
      const column = columns[i];
      const label = column ? ` data-label="${esc(column.name)} /${esc(column.max_score)}"` : "";
      // `.paper` is hidden below 640px (`card.css`): on a phone the same
      // figures print again, joined, on the summary line — a subject with six
      // papers is not six lines on a screen this narrow.
      return `<td class="n paper"${label}>${mark(cell)}</td>`;
    })
    .join("");
  return [
    "<tr>",
    // The bar stays here, under the name, on a desktop table and a phone
    // card alike — it was always this cell's, and moving it to the phone-only
    // line below would have lost it from the wide table. `.grade-pct` is the
    // phone card's line 1 addition and `card.css` hides it on a desktop,
    // where Grade and % already have their own columns.
    `<td class="stack-head">` +
      `<span class="subject">${esc(line.subject_name)}</span>` +
      `<span class="grade-pct">${gradeAndPercentage(line)}</span>` +
      scorebar(line.percentage) +
      "</td>",
    cells,
    `<td class="n total" data-label="Total">${esc(line.total_scored)}<span class="max">/${esc(
      line.total_available,
    )}</span></td>`,
    `<td class="n pct" data-label="%">${percentage(line.percentage)}</td>`,
    `<td class="n grade" data-label="Grade">${esc(line.grade_letter)}</td>`,
    `<td class="remark" data-label="Remark">${esc(line.grade_remark)}</td>`,
    // Phone only (`card.css` shows it, and hides everything above): every
    // paper this subject has, and the total, on one small line —
    // "First CA 13 &middot; Exam 45 &middot; Total 58/80" — rather than the
    // same figures spread over six labelled lines. Absent papers (`·`) are
    // left out entirely; an unmarked one still prints its dash, because that
    // is a fact about the term rather than a column this subject does not
    // have.
    `<td class="stack-full marks-line"><span class="marks-summary">${summaryLine(line, columns)}</span></td>`,
    "</tr>",
  ].join("");
}

/** "B2 &middot; 74.17%", or just the percentage where there is no grade yet
 * (`grade_letter` is blank when a subject has no total to grade). */
function gradeAndPercentage(line) {
  const pct = percentage(line.percentage);
  if (!line.grade_letter) return pct;
  return `${esc(line.grade_letter)} &middot; ${pct}`;
}

/** The phone card's second line: every paper this subject has, then the total. */
function summaryLine(line, columns) {
  const papers = (line.cells || [])
    .map((cell, i) => {
      if (cell === null || cell === undefined) return null; // no such paper here
      const column = columns[i];
      const name = column ? esc(column.name) : "";
      return `${name} ${mark(cell)}`;
    })
    .filter((part) => part !== null);
  papers.push(
    `Total ${esc(line.total_scored)}<span class="max">/${esc(line.total_available)}</span>`,
  );
  return papers.join(" &middot; ");
}

/** One cell: a gap, a dash, or a mark. The three are not interchangeable. */
function mark(cell) {
  if (cell === null || cell === undefined) return '<span class="blank">&middot;</span>';
  if (cell.score === null || cell.score === undefined)
    return '<span class="blank">&mdash;</span>';
  return esc(cell.score);
}

/**
 * A percentage, printed exactly as the API sent it.
 *
 * It arrives as a **string** and is not turned into a number here. It is a
 * `Decimal` all the way down the server and was serialised as text precisely so
 * that nothing rounds it at the last step — and `Number("74.17").toFixed(1)` on
 * the one figure a parent is most likely to check with a calculator is exactly
 * that last step.
 */
function percentage(value) {
  if (value === null || value === undefined || value === "")
    return '<span class="blank">&mdash;</span>';
  return `${esc(value)}%`;
}

/**
 * The bar under a subject's name, reading `line.percentage` — the same string
 * `percentage()` prints, so the bar and the number in the row's own `%`
 * column never disagree.
 *
 * Absent, not zero-width, where there is nothing to show: a subject with no
 * percentage (nobody marked, or none of its papers carry a maximum yet) is
 * `percentage()`'s blank dash, and a bar under a dash would be a measurement
 * this page did not make. `parseFloat` rather than `Number` so a string with
 * trailing content the server never sends still fails safe to `NaN` rather
 * than `0`.
 */
function scorebar(value) {
  if (value === null || value === undefined || value === "") return "";
  const width = parseFloat(value);
  if (Number.isNaN(width)) return "";
  const clamped = Math.max(0, Math.min(100, width));
  return `<div class="scorebar"><span style="width:${clamped}%"></span></div>`;
}

/**
 * The attendance line. **This function formats and does not decide.**
 *
 * Which of four things a card's attendance is gets settled once on the server,
 * in `results.card_api.attendance_of()`, and arrives as `payload.attendance.state`.
 * This matters because the PDF renders from the very same payload — `pdf.html_for()`
 * calls `card_payload()` — so one answer reaches both renderers by construction.
 * They diverged once before, when this function keyed on `days_present` and the
 * template keyed on `days_open`, and it was invisible only because the columns
 * were always null.
 *
 * The rule the states encode: **the denominator is only ever the days actually
 * marked.** The school's declared term length is context and never a divisor,
 * because dividing by it invites subtracting from it and reading the remainder
 * as absence — which is a false accusation against a class whose school simply
 * did not keep the register.
 */
function attendance(payload) {
  const a = payload.attendance || {};
  switch (a.state) {
    case "absent":
      return '<span class="blank">&mdash;</span>';
    case "not_recorded":
      return '<span class="blank">Not recorded this term</span>';
    case "partial": {
      const counts = `${numberOrBlank(a.present)} present, ${numberOrBlank(
        a.absent,
      )} absent`;
      // No parenthetical when the school never declared a term length: there is
      // nothing to have kept the register *of*, and "40 of — days" would be a
      // sentence with a hole in it. What was observed is still printed, because
      // gating the whole line on the denominator throws the recorded half away
      // and tells a parent nobody kept a register.
      if (a.school_days === null || a.school_days === undefined) return counts;
      return `${counts} <span class="note">(register kept on ${numberOrBlank(
        a.marked,
      )} of ${numberOrBlank(a.school_days)} days)</span>`;
    }
    case "complete":
      return `Present ${numberOrBlank(a.present)} of ${numberOrBlank(
        a.school_days,
      )} days`;
    default:
      // An unknown state is a server this client does not understand, and a
      // guess here would be a number nobody computed. Blank, like `absent`.
      return '<span class="blank">&mdash;</span>';
  }
}

function sections(payload) {
  return (payload.sections || [])
    .map((section) =>
      [
        '<section class="conduct">',
        `<h2>${esc(section.group_label)}</h2>`,
        "<table>",
        (section.traits || [])
          .map(
            (trait) =>
              `<tr><td>${esc(trait.trait_name)}</td><td class="n">${esc(
                trait.score_label,
              )}</td></tr>`,
          )
          .join(""),
        "</table>",
        "</section>",
      ].join(""),
    )
    .join("");
}

function comments(payload) {
  return (payload.comments || [])
    .map((comment) =>
      [
        '<section class="remark">',
        `<h2>${esc(comment.author_label)}</h2>`,
        `<p>${esc(comment.body)}</p>`,
        "</section>",
      ].join(""),
    )
    .join("");
}

/** Third term only, and absent otherwise — never a first term wearing a year. */
function sessionLine(payload) {
  const line = payload.session;
  if (!line) return "";
  return [
    '<section class="session">',
    "<h2>The year so far</h2>",
    "<table>",
    `<tr><td>First term</td><td class="n">${percentage(line.first_average)}</td></tr>`,
    `<tr><td>Second term</td><td class="n">${percentage(line.second_average)}</td></tr>`,
    `<tr><td>Third term</td><td class="n">${percentage(line.third_average)}</td></tr>`,
    `<tr><td><strong>Session</strong></td><td class="n"><strong>${percentage(
      line.session_average,
    )}</strong></td></tr>`,
    "</table>",
    "</section>",
  ].join("");
}

/** The school's decision, if one has been recorded. Never the suggestion. */
function promotion(payload) {
  const decision = payload.promotion;
  if (!decision) return "";
  return [
    '<section class="promotion">',
    "<h2>Next session</h2>",
    `<p>${esc(decision.status_label)}</p>`,
    "</section>",
  ].join("");
}
