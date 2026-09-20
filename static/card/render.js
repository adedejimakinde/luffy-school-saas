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

/** The whole page body for one card payload. */
export function card(payload) {
  return [
    masthead(payload),
    who(payload),
    marks(payload),
    sections(payload),
    comments(payload),
    sessionLine(payload),
    promotion(payload),
  ].join("");
}

function masthead(payload) {
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
    "</header>",
  ].join("");
}

function who(payload) {
  return [
    '<table class="who">',
    `<tr><th scope="row">Name</th><td>${esc(payload.student_name)}</td>`,
    `<th scope="row">Class</th><td>${esc(payload.class_group_name)}</td></tr>`,
    `<tr><th scope="row">Average</th><td>${percentage(payload.own_average)}</td>`,
    `<th scope="row">Attendance</th><td>${attendance(payload)}</td></tr>`,
    "</table>",
  ].join("");
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

  const body = (payload.subjects || []).map((line) => row(line, columns.length)).join("");

  return [
    // The scroll box `card.css` needs: eleven columns cannot fit a phone, and
    // the honest answer is a table that scrolls inside its own box rather than
    // a page that scrolls sideways and takes the headings with it. `print.css`
    // unsets it, because paper has no scroll.
    '<div class="grid-scroll">',
    '<table class="grid">',
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

function row(line, columnCount) {
  // `cells` is already the length of `columns`; slicing or padding here would
  // be this file deciding the alignment after all. If the two ever disagree
  // that is a payload bug, and a short row is visible rather than papered over.
  const cells = (line.cells || []).map((cell) => `<td class="n">${mark(cell)}</td>`).join("");
  return [
    "<tr>",
    `<td>${esc(line.subject_name)}</td>`,
    cells,
    `<td class="n">${esc(line.total_scored)}<span class="max">/${esc(
      line.total_available,
    )}</span></td>`,
    `<td class="n">${percentage(line.percentage)}</td>`,
    `<td class="n">${esc(line.grade_letter)}</td>`,
    `<td>${esc(line.grade_remark)}</td>`,
    "</tr>",
  ].join("");
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
