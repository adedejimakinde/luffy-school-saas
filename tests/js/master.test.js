/**
 * The master broadsheet page: docs/broadsheet.md.
 *
 * What it walks is `results/broadsheet_api.py`: the table, and the job that
 * makes a PDF or an Excel file, watched through `/api/results/print-jobs/`.
 *
 * **Every figure is the server's.** The page adds nothing up and ranks nothing;
 * the rows come in the order the server chose. A cell the server sent as null
 * is a dash, never a zero, and the position column is not drawn when the
 * server did not send positions.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { POLL_MS, htmlFor, mount } from "../../static/master/app.js";
import { REFUSAL, filesUrl, jobUrl, refusalFor, sheetUrl } from "../../static/master/api.js";
import * as states from "../../static/master/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const COLUMNS = [
  { subject_id: 1, subject: "English", key: "ca", label: "CA", out_of: 20 },
  { subject_id: 1, subject: "English", key: "exam", label: "Exam", out_of: 100 },
  { subject_id: 1, subject: "English", key: "pct", label: "%", out_of: 100 },
  { subject_id: 2, subject: "Mathematics", key: "ca", label: "CA", out_of: 10 },
  { subject_id: 2, subject: "Mathematics", key: "exam", label: "Exam", out_of: 100 },
  { subject_id: 2, subject: "Mathematics", key: "pct", label: "%", out_of: 100 },
];

const SHEET = {
  class_group_id: 11,
  class_group: "JSS 1A",
  term_id: 7,
  term: "2025/2026 First term",
  school: "St Mary's",
  preview: true,
  template: "standard",
  show_position: true,
  ranked: 2,
  columns: COLUMNS,
  grade_letters: ["A", "B"],
  rows: [
    // In the server's order, which is rank order here; the page must not re-sort.
    { student_membership_id: 3, name: "Zainab Yusuf", cells: ["18", "80", "81.67", "10", "95", "95.45"], total: "203", average: "88.56", position: 1, grades: { A: 2, B: 0 }, promotion: null },
    { student_membership_id: 1, name: "Ada Obi", cells: ["15", "74", "74.17", "9", "88", "88.18"], total: "186", average: "81.18", position: 2, grades: { A: 1, B: 1 }, promotion: "Promoted to JSS 2A" },
    { student_membership_id: 4, name: "Dayo Bello", cells: [null, "40", null, null, null, null], total: null, average: null, position: null, grades: null, promotion: null },
  ],
  footer: [
    { label: "Highest", cells: ["18", "80", "81.67", "10", "95", "95.45"] },
    { label: "Lowest", cells: ["15", "40", "74.17", "9", "88", "88.18"] },
    { label: "Class average", cells: ["16.50", "64.67", "77.92", "9.50", "91.50", "91.82"] },
  ],
};

const job = (over = {}) => ({
  id: 9,
  state: "pending",
  state_label: "Waiting to start",
  kind: "broadsheet_pdf",
  paper: "A3",
  class_group: "JSS 1A",
  term: "First term",
  done: 0,
  total: 3,
  download_url: null,
  detail: "Waiting to start. This page will show progress.",
  ...over,
});

function json(status, body) {
  return { status, headers: { get: () => null }, json: async () => body };
}

/** A fetch that answers by URL and method, and remembers what it was sent. */
function server(answers) {
  const sent = [];
  const fetchImpl = async (url, options = {}) => {
    const method = options.method || "GET";
    sent.push({ url, method, body: options.body ? JSON.parse(options.body) : null });
    if (url === "/api/csrf/") return json(200, { csrf_token: "t" });
    const queue = answers[`${method} ${url}`];
    if (!queue || !queue.length) throw new Error(`nothing to answer ${method} ${url}`);
    return queue.length > 1 ? queue.shift() : queue[0];
  };
  return { fetchImpl, sent };
}

const frame = (extra = {}) => fakeRoot({ onSchool: "yes", class: "11", term: "7", portal: "", ...extra });
const noWait = async () => {};

// -- the table ----------------------------------------------------------------

test("the name is the first column, then each subject's columns, then the totals", () => {
  const html = states.sheet({ sheet: SHEET });
  const head = html.slice(html.indexOf("<thead>"), html.indexOf("</thead>"));

  assert.match(head, /<th class="name">Name<\/th>/);
  // Both header rows start with the name column, so the table's pinned first
  // cell is the name's in every row and never the first subject's.
  const rowsOfHead = head.split("<tr>").slice(1);
  assert.equal(rowsOfHead.length, 2);
  for (const r of rowsOfHead) assert.match(r, /^<th class="name">/);
  assert.ok(head.indexOf("Name") < head.indexOf("English"));
  assert.match(head, /<th class="group" colspan="3">English<\/th>/);
  assert.match(head, /<th class="group" colspan="3">Mathematics<\/th>/);
  for (const word of ["Total", "Average", "Position", "Grades", "Promotion"]) assert.match(head, new RegExp(word));
  // What each paper is out of is under its name.
  assert.match(head, /CA<small>20<\/small>/);
  // And the first cell of every row is the name, which `.scroll` holds in place.
  for (const name of ["Zainab Yusuf", "Ada Obi", "Dayo Bello"]) {
    assert.match(html, new RegExp(`<tr><td class="name">${name}</td>`));
  }
  assert.match(html, /class="scroll wide"/);
});

test("a paper not marked is a dash, never a zero", () => {
  const html = states.sheet({ sheet: SHEET });
  const dayo = html.slice(html.indexOf("Dayo Bello"));
  const row = dayo.slice(0, dayo.indexOf("</tr>"));

  assert.equal((row.match(/<td class="num[^"]*">-<\/td>/g) || []).length, 5 + 3 + 2, "cells, total, average, position, grades");
  assert.match(row, /<td class="num">40<\/td>/);
  assert.doesNotMatch(row, /<td class="num[^"]*">0(\.00)?<\/td>/);
  assert.doesNotMatch(row, />0</);
  // Ada's zero grade count is a real zero: she has graded subjects.
  assert.match(html, /<td class="num">0<\/td>/);
});

test("rows are in the server's order: the page ranks nothing", () => {
  const html = states.sheet({ sheet: SHEET });
  const order = ["Zainab Yusuf", "Ada Obi", "Dayo Bello"].map((n) => html.indexOf(n));
  assert.deepEqual([...order].sort((a, b) => a - b), order);
  const reversed = { ...SHEET, rows: [...SHEET.rows].reverse() };
  const again = states.sheet({ sheet: reversed });
  assert.ok(again.indexOf("Dayo Bello") < again.indexOf("Zainab Yusuf"), "the page re-sorted what it was given");
});

test("the position column is drawn only when the school shows positions", () => {
  const shown = states.sheet({ sheet: SHEET });
  assert.match(shown, /<th rowspan="2">Position<\/th>/);
  assert.deepEqual([...shown.matchAll(/<td class="num rank">([^<]*)<\/td>/g)].map((m) => m[1]), ["1", "2", "-"]);

  const hidden = states.sheet({ sheet: { ...SHEET, show_position: false, ranked: 0, rows: SHEET.rows.map((r) => ({ ...r, position: null })) } });
  assert.doesNotMatch(hidden, /Position/);
  assert.doesNotMatch(hidden, /class="num rank"/);
  assert.doesNotMatch(hidden, /data-ranked/);
});

test("the footer is highest, lowest and class average, under the subjects", () => {
  const html = states.sheet({ sheet: SHEET });
  const foot = html.slice(html.indexOf("<tfoot>"), html.indexOf("</tfoot>"));
  assert.deepEqual([...foot.matchAll(/<th class="name">([^<]*)<\/th>/g)].map((m) => m[1]), ["Highest", "Lowest", "Class average"]);
  assert.match(foot, /<td class="num">95\.45<\/td>/);
  assert.match(foot, /<td class="num group">91\.50<\/td>|<td class="num">91\.50<\/td>/);
});

test("a name typed into the roll cannot execute in a teacher's browser", () => {
  const evil = { ...SHEET, rows: [{ ...SHEET.rows[0], name: '<img src=x onerror="alert(1)">' }], class_group: "<b>JSS</b>" };
  const html = states.sheet({ sheet: evil });
  assert.doesNotMatch(html, /<img/);
  assert.doesNotMatch(html, /<b>JSS/);
  assert.match(html, /&lt;img/);
});

test("an unreleased sheet says so, and so does a released one", () => {
  assert.match(states.sheet({ sheet: SHEET }), /data-figures="live"[^]*Not released[^]*PREVIEW, NOT RELEASED/);
  const released = states.sheet({ sheet: { ...SHEET, preview: false } });
  assert.match(released, /data-figures="released"/);
  assert.doesNotMatch(released, /PREVIEW/);
});

test("a class nobody is in says so rather than drawing an empty table", () => {
  const html = states.sheet({ sheet: { ...SHEET, columns: [], rows: [], footer: [] } });
  assert.match(html, /Nobody in this class has a result this term/);
  assert.doesNotMatch(html, /<table/);
});

// -- files --------------------------------------------------------------------

test("the controls offer A4 and A3 landscape, the PDF and Excel", () => {
  const html = states.files(null);
  assert.match(html, /<option value="A4" selected>A4, landscape<\/option>/);
  assert.match(html, /<option value="A3">A3, landscape<\/option>/);
  assert.match(html, /data-action="make-pdf">Make the PDF/);
  assert.match(html, /data-action="make-xlsx">Export to Excel/);
});

test("a running job shows the server's sentence and progress, and a ready one the download", () => {
  const making = states.files(job({ state: "building", done: 1, detail: "Making the broadsheet." }));
  assert.match(making, /Making the broadsheet\./);
  assert.match(making, /<progress max="3" value="1">/);
  assert.doesNotMatch(making, /download/);

  const pdf = states.files(job({ state: "ready", download_url: "/api/results/print-jobs/9/pdf/", detail: "The A3 PDF is ready to download." }));
  assert.match(pdf, /href="\/api\/results\/print-jobs\/9\/pdf\/" download>Download the PDF/);
  const xlsx = states.files(job({ kind: "broadsheet_xlsx", state: "ready", download_url: "/api/results/print-jobs/9/file/" }));
  assert.match(xlsx, /Download the Excel file/);
});

// -- refusals -----------------------------------------------------------------

test("a 403 and a 404 are different sentences, and nothing guesses why", () => {
  assert.equal(refusalFor(403), REFUSAL.NOT_YOURS);
  assert.equal(refusalFor(404), REFUSAL.NOT_FOUND);
  assert.equal(refusalFor(401, { code: "session_expired" }), REFUSAL.EXPIRED);
  assert.equal(refusalFor(401, {}), REFUSAL.SIGNED_OUT);
  assert.equal(refusalFor(500), REFUSAL.BROKEN);
  assert.match(htmlFor({ step: REFUSAL.NOT_YOURS }), /not a broadsheet you can open/);
  assert.match(htmlFor({ step: REFUSAL.NOT_FOUND }), /No such broadsheet/);
});

test("a frame on a host that is not a school's asks for nothing", async () => {
  forgetToken();
  const { fetchImpl, sent } = server({});
  const root = frame({ onSchool: "" });
  await mount(root, { fetchImpl });
  assert.match(root.innerHTML, /your school's own web address/);
  assert.deepEqual(sent, []);
});

test("a reader the route refuses gets the refusal and no table", async () => {
  forgetToken();
  const { fetchImpl } = server({ [`GET ${sheetUrl(11, 7)}`]: [json(403, { detail: "no" })] });
  const root = frame();
  await mount(root, { fetchImpl });
  assert.match(root.innerHTML, /data-state="not-yours"/);
  assert.doesNotMatch(root.innerHTML, /<table/);
});

// -- the flow -----------------------------------------------------------------

test("the page reads the class and term it was opened for", async () => {
  forgetToken();
  const { fetchImpl, sent } = server({ [`GET ${sheetUrl(11, 7)}`]: [json(200, SHEET)] });
  const root = frame();
  await mount(root, { fetchImpl });
  assert.match(root.innerHTML, /data-state="sheet"/);
  assert.match(root.innerHTML, /Broadsheet: JSS 1A/);
  assert.deepEqual(sent.map((s) => s.url), [sheetUrl(11, 7)]);
});

test("a PDF is asked for on the paper chosen, watched, and offered when ready", async () => {
  forgetToken();
  const { fetchImpl, sent } = server({
    [`GET ${sheetUrl(11, 7)}`]: [json(200, SHEET)],
    [`POST ${filesUrl(11, 7)}`]: [json(202, job())],
    [`GET ${jobUrl(9)}`]: [
      json(200, job({ state: "building", done: 1, detail: "Making the broadsheet." })),
      json(200, job({ state: "ready", done: 3, download_url: "/api/results/print-jobs/9/pdf/", detail: "The A3 PDF is ready to download." })),
    ],
  });
  const root = frame().type("[data-paper]", "A3");
  await mount(root, { fetchImpl, wait: noWait });

  await root.click({ "data-action": "make-pdf" });

  const post = sent.find((s) => s.method === "POST" && s.url === filesUrl(11, 7));
  assert.deepEqual(post.body, { format: "pdf", paper: "A3" });
  assert.match(root.innerHTML, /The A3 PDF is ready to download\./);
  assert.match(root.innerHTML, /href="\/api\/results\/print-jobs\/9\/pdf\/"/);
  assert.equal(sent.filter((s) => s.url === jobUrl(9)).length, 2, "it asked until the job was ready");
});

test("Excel is asked for as xlsx and downloaded from the file route", async () => {
  forgetToken();
  const { fetchImpl, sent } = server({
    [`GET ${sheetUrl(11, 7)}`]: [json(200, SHEET)],
    [`POST ${filesUrl(11, 7)}`]: [json(202, job({ kind: "broadsheet_xlsx", paper: "" }))],
    [`GET ${jobUrl(9)}`]: [
      json(200, job({ kind: "broadsheet_xlsx", state: "ready", download_url: "/api/results/print-jobs/9/file/", detail: "The Excel file is ready to download." })),
    ],
  });
  const root = frame();
  await mount(root, { fetchImpl, wait: noWait });

  await root.click({ "data-action": "make-xlsx" });

  assert.equal(sent.find((s) => s.method === "POST" && s.url === filesUrl(11, 7)).body.format, "xlsx");
  assert.match(root.innerHTML, /href="\/api\/results\/print-jobs\/9\/file\/" download>Download the Excel file/);
});

test("a refusal to start says the server's sentence and offers the controls again", async () => {
  forgetToken();
  const { fetchImpl } = server({
    [`GET ${sheetUrl(11, 7)}`]: [json(200, SHEET)],
    [`POST ${filesUrl(11, 7)}`]: [json(409, { detail: "JSS 1A has no children with results." })],
  });
  const root = frame();
  await mount(root, { fetchImpl, wait: noWait });

  await root.click({ "data-action": "make-pdf" });
  assert.match(root.innerHTML, /JSS 1A has no children with results\./);

  await root.click({ "data-action": "close-file" });
  assert.match(root.innerHTML, /data-action="make-pdf"/);
});

test("the poll is a couple of seconds, not a hammer", () => {
  assert.ok(POLL_MS >= 1000);
});
