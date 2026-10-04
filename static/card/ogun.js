/**
 * The Ogun State report sheet, as the parent's page draws it.
 *
 * Everything comes off `payload.ogun` (`results/ogun_card.py`) and the
 * payload's own fields, the same objects the PDF is rendered from, so the page
 * and the file cannot disagree. A renderer and nothing else.
 *
 * **The subject grid is turned on its side here.** The paper sheet runs the
 * subjects across the page; a phone cannot, so each subject is a row and the
 * sheet's rows (Cont. Assess, Exam, Weighted Average, and on a third-term card
 * the three terms and the annual score) are its columns, in the sheet's order,
 * with department headings between the rows of a senior card.
 *
 * `health` is the child's record from `/api/results/health/`, fetched by
 * `app.js` only for this layout and passed in; null when the reader is not one
 * of the four who may see it, and the section says so.
 */

import { esc } from "../web/html.js";
import { date } from "./render.js";

const dash = (value) => (value === null || value === undefined || value === "" ? "-" : esc(value));

export function ogunCard(payload, { pdfUrl = null, health = null } = {}) {
  const o = payload.ogun;
  return [
    head(payload, o, pdfUrl),
    o.promotion ? `<p class="ogun-promotion">${esc(o.promotion)}</p>` : "",
    who(payload, o),
    grid(o),
    summary(payload, o),
    traits(o),
    healthSection(health),
    remarks(payload),
  ].join("");
}

function head(payload, o, pdfUrl) {
  const photo = o.photo
    ? `<img class="ogun-photo" src="${esc(o.photo)}" alt="Photo of ${esc(payload.student_name)}" width="92" height="118">`
    : "";
  return [
    '<header class="masthead ogun-head">',
    photo,
    ...o.ministry.map((line) => `<p class="ministry">${esc(line)}</p>`),
    `<p class="sheet-title">${esc(o.title)}</p>`,
    `<h1>${esc(o.school_line)}</h1>`,
    `<p class="term">${esc(payload.term_label)} &middot; ${esc(payload.academic_session)}</p>`,
    payload.is_revised ? '<p class="revised">Revised</p>' : "",
    pdfUrl
      ? `<p class="pdf-link"><a class="btn" href="${esc(pdfUrl)}" target="_blank" rel="noopener">Download PDF</a></p>`
      : "",
    "</header>",
  ].join("");
}

function who(payload, o) {
  const line = (label, value) => `<div><dt>${label}</dt><dd>${esc(value) || "—"}</dd></div>`;
  return [
    '<section class="summary"><dl class="ogun-who">',
    line("Learner&#39;s name", payload.student_name),
    line("Learner&#39;s ID", o.learner_id),
    line("Admission no.", payload.admission_number),
    line("Class", payload.class_group_name),
    line("Sex", o.sex),
    line("Date of birth", o.date_of_birth),
    "</dl></section>",
  ].join("");
}

function grid(o) {
  const ca = `Cont. Assess${o.ca_out_of ? ` (${esc(o.ca_out_of)})` : ""}`;
  const exam = `Exam${o.exam_out_of ? ` (${esc(o.exam_out_of)})` : ""}`;
  const heads = [ca, exam, "Weighted Average (100)"];
  if (o.third_term) heads.push("1st Term (100)", "2nd Term (100)", "3rd Term (100)", "Weighted Annual Score");
  const cells = (s) => {
    const values = [s.ca, s.exam, s.weighted];
    if (o.third_term) values.push(s.first, s.second, s.third, s.annual);
    return values.map((v, i) => `<td class="n${i === 2 || i === 6 ? " strong" : ""}">${dash(v)}</td>`).join("");
  };
  const body = o.groups
    .map((g) =>
      [
        g.label ? `<tr class="department"><th scope="rowgroup" colspan="${heads.length + 1}">${esc(g.label)}</th></tr>` : "",
        ...g.subjects.map((s) => `<tr><th scope="row">${esc(s.name)}</th>${cells(s)}</tr>`),
      ].join(""),
    )
    .join("");
  return [
    '<section class="ogun-marks">',
    "<h2>Subjects</h2>",
    '<p class="swipe-cue">Swipe for more</p>',
    '<div class="scroll wide"><table class="ogun-grid">',
    `<thead><tr><th scope="col">Subject</th>${heads.map((h) => `<th scope="col" class="n">${h}</th>`).join("")}</tr></thead>`,
    `<tbody>${body}</tbody>`,
    "</table></div>",
    "</section>",
  ].join("");
}

function summary(payload, o) {
  const cell = (label, value) => `<div><dt>${label}</dt><dd>${value}</dd></div>`;
  return [
    '<section class="ogun-pair">',
    '<div><h2>Attendance</h2><dl class="ogun-facts">',
    cell("Times school opened", dash(o.times_opened)),
    cell("Times present", dash(o.times_present)),
    cell("Times absent", dash(o.times_absent)),
    "</dl></div>",
    '<div><h2>Summary</h2><dl class="ogun-facts">',
    cell("Marks obtainable", dash(payload.total_available)),
    cell("Marks obtained", dash(payload.total_scored)),
    cell("Percentage", payload.percentage ? `${esc(payload.percentage)}%` : "-"),
    payload.place_in_class ? cell("Class position", esc(payload.place_in_class.label)) : "",
    "</dl></div>",
    "</section>",
  ].join("");
}

function traits(o) {
  if (!o.traits.length) return "";
  const points = o.key.map((p) => p.value);
  return [
    '<section class="ogun-pair">',
    ...o.traits.map((g) =>
      [
        `<div><h2>${esc(g.label)}</h2><table class="ogun-traits">`,
        `<thead><tr><th scope="col">Trait</th>${points.map((p) => `<th scope="col" class="n">${esc(p)}</th>`).join("")}</tr></thead><tbody>`,
        ...g.traits.map(
          (t) =>
            `<tr><th scope="row">${esc(t.name)}</th>${points
              .map((p) => `<td class="n">${t.score === p ? '<span aria-label="ticked">&#10003;</span>' : ""}</td>`)
              .join("")}</tr>`,
        ),
        `<tr class="total"><th scope="row">Total</th><td class="n" colspan="${points.length}">${
          g.total === null || g.total === undefined ? "-" : `${esc(g.total)} of ${esc(g.out_of)}`
        }</td></tr>`,
        "</tbody></table></div>",
      ].join(""),
    ),
    "</section>",
    `<p class="ogun-key"><strong>Rating key:</strong> ${o.key.map((p) => `${esc(p.value)} ${esc(p.label)}`).join(", ")}</p>`,
  ].join("");
}

function healthSection(h) {
  const head = "<section class=\"ogun-health\"><h2>Physical development and health</h2>";
  if (!h) {
    return `${head}<p class="blank">Shown only to the child&#39;s parents, class teacher and the school office.</p></section>`;
  }
  const v = (value, unit = "") => (value === null || value === undefined || value === "" ? "-" : `${esc(value)}${unit}`);
  return [
    head,
    '<table class="ogun-health-table"><thead><tr><th></th><th scope="col">Beginning of term</th><th scope="col">End of term</th></tr></thead><tbody>',
    `<tr><th scope="row">Height</th><td>${v(h.height_start_m, " m")}</td><td>${v(h.height_end_m, " m")}</td></tr>`,
    `<tr><th scope="row">Weight</th><td>${v(h.weight_start_kg, " kg")}</td><td>${v(h.weight_end_kg, " kg")}</td></tr>`,
    "</tbody></table>",
    '<dl class="ogun-facts">',
    `<div><dt>Days absent through illness</dt><dd>${v(h.days_absent_ill)}</dd></div>`,
    `<div><dt>Nature of illness</dt><dd>${v(h.illness)}</dd></div>`,
    "</dl></section>",
  ].join("");
}

function remarks(payload) {
  const by = Object.fromEntries((payload.comments || []).map((c) => [c.author, c.body]));
  const row = (label, body) =>
    `<div class="ogun-remark"><h2>${label}</h2><p>${body ? esc(body) : '<span class="blank">Not written.</span>'}</p></div>`;
  return [
    '<section class="ogun-remarks">',
    row("Class teacher&#39;s comment", by.class_teacher),
    row("Principal&#39;s remark", by.principal),
    payload.next_term_begins ? `<p class="resume"><strong>Next term begins:</strong> ${date(payload.next_term_begins)}</p>` : "",
    "</section>",
  ].join("");
}
