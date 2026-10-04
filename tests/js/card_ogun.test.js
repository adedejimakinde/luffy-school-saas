/**
 * The Ogun State sheet on the parent's page (`static/card/ogun.js`).
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { htmlFor, mount } from "../../static/card/app.js";
import { card } from "../../static/card/render.js";
import { fakeRoot } from "./fake_dom.js";

const subject = (name, over = {}) => ({
  name, department: "", ca: 24, ca_max: 30, exam: 58, exam_max: 70, weighted: "82",
  first: null, second: null, third: null, annual: null, ...over,
});

const OGUN = {
  ministry: ["OGUN STATE GOVERNMENT", "MINISTRY OF EDUCATION, SCIENCE AND TECHNOLOGY"],
  title: "JUNIOR SECONDARY SCHOOL CONTINUOUS ASSESSMENT REPORT SHEET",
  school_line: "St Mary's (Abeokuta South LGA) [B13003]",
  school_name: "St Mary's", school_place: "(Abeokuta South LGA) [B13003]", crest: null,
  ca_out_of: 30, exam_out_of: 70,
  learner_id: "OG/ABS/0042", sex: "Female", date_of_birth: "02/05/2013", photo: null,
  senior: false, third_term: false,
  groups: [{ label: "", subjects: [subject("Mathematics"), subject("English Studies", { exam: null, weighted: null })] }],
  promotion: null, times_opened: 62, times_present: 58, times_absent: 4,
  traits: [{ label: "Affective", traits: [{ name: "Punctuality", score: 4 }, { name: "Neatness", score: null }], total: 4, out_of: 10 }],
  key: [5, 4, 3, 2, 1].map((value, i) => ({ value, label: ["Excellent", "Good", "Average", "Below Average", "Unsatisfactory"][i] })),
};

const PAYLOAD = {
  school_name: "St Mary's", student_name: "Ada Obi", class_group_name: "JSS 2A",
  academic_session: "2025/2026", term_label: "Second term", admission_number: "0042",
  is_revised: false, total_scored: 140, total_available: 200, percentage: "70.00",
  place_in_class: { place: 4, out_of: 31, label: "4th of 31" },
  comments: [{ author: "class_teacher", author_label: "Class teacher", body: "A steady term." }],
  next_term_begins: "2026-04-27", ogun: OGUN,
};

test("the Ogun sheet heads the page with the ministry, the school line and the child", () => {
  const html = card(PAYLOAD);

  assert.match(html, /OGUN STATE GOVERNMENT/);
  assert.match(html, /St Mary&#39;s \(Abeokuta South LGA\) \[B13003\]|St Mary's \(Abeokuta South LGA\) \[B13003\]/);
  assert.match(html, /OG\/ABS\/0042/);
  assert.match(html, /Female/);
  assert.match(html, /02\/05\/2013/);
});

test("without the ministry's heading the school leads: crest, name, then its LGA and code", () => {
  const html = card({
    ...PAYLOAD,
    ogun: { ...OGUN, ministry: [], crest: "data:image/png;base64,AAAA" },
  });

  assert.doesNotMatch(html, /OGUN STATE GOVERNMENT|MINISTRY OF EDUCATION/);
  assert.match(html, /<img class="ogun-crest" src="data:image\/png;base64,AAAA"/);
  assert.match(html, /<h1>St Mary&#39;s<\/h1><p class="place">\(Abeokuta South LGA\) \[B13003\]<\/p><p class="sheet-title">JUNIOR/);
  assert.ok(html.indexOf("ogun-crest") < html.indexOf("<h1>"), "the crest comes first");
});

test("each subject's CA, exam and weighted average, a dash where there is none", () => {
  const html = card(PAYLOAD);

  assert.match(html, /Cont. Assess \(30\)/);
  assert.match(html, /<th scope="row">Mathematics<\/th><td class="n">24<\/td><td class="n">58<\/td><td class="n strong">82<\/td>/);
  assert.match(html, /<th scope="row">English Studies<\/th><td class="n">24<\/td><td class="n">-<\/td><td class="n strong">-<\/td>/);
  assert.doesNotMatch(html, /Weighted Annual Score/);
});

test("a senior card groups the subjects under department headings", () => {
  const html = card({
    ...PAYLOAD,
    ogun: { ...OGUN, senior: true, groups: [
      { label: "General", subjects: [subject("English Language")] },
      { label: "Science & Mathematics", subjects: [subject("Physics")] },
    ] },
  });

  assert.match(html, /<tr class="department"><th scope="rowgroup" colspan="4">General<\/th><\/tr>/);
  assert.match(html, /Science &amp; Mathematics/);
});

test("a third-term card adds the three terms and the annual score", () => {
  const html = card({
    ...PAYLOAD,
    ogun: { ...OGUN, third_term: true, promotion: "Promoted to JSS 3A", groups: [
      { label: "", subjects: [subject("Mathematics", { first: "70", second: null, third: "82", annual: "76" })] },
    ] },
  });

  assert.match(html, /Weighted Annual Score/);
  assert.match(html, /<td class="n">70<\/td><td class="n">-<\/td><td class="n">82<\/td><td class="n strong">76<\/td>/);
  assert.match(html, /<p class="ogun-promotion">Promoted to JSS 3A<\/p>/);
});

test("the summary, the position and the ticks", () => {
  const html = card(PAYLOAD);

  assert.match(html, /Marks obtainable<\/dt><dd>200/);
  assert.match(html, /70.00%/);
  assert.match(html, /4th of 31/);
  assert.match(html, /<th scope="row">Punctuality<\/th><td class="n"><\/td><td class="n"><span aria-label="ticked">/);
  assert.match(html, /4 of 10/);
  assert.match(html, /5 Excellent, 4 Good, 3 Average, 2 Below Average, 1 Unsatisfactory/);
});

test("health shows for a reader who was served it, and a note for anyone else", () => {
  const without = card(PAYLOAD);
  const withIt = card(PAYLOAD, { health: {
    height_start_m: "1.42", height_end_m: "1.45", weight_start_kg: "38.5", weight_end_kg: null,
    days_absent_ill: 3, illness: "Malaria",
  } });

  assert.match(without, /Shown only to the child&#39;s parents/);
  assert.doesNotMatch(without, /Malaria/);
  assert.match(withIt, /1.42 m/);
  assert.match(withIt, /Malaria/);
});

test("a Standard card is drawn as before", () => {
  const html = htmlFor({ ok: true, card: { ...PAYLOAD, ogun: null, subjects: [], columns: [], sections: [], attendance: { state: "absent" } } });
  assert.doesNotMatch(html, /OGUN STATE GOVERNMENT/);
});

test("the page asks for health only for an Ogun card", async () => {
  const asked = [];
  const serve = (ogun) => async (url) => {
    asked.push(url);
    if (url.includes("/health/")) return { status: 404, json: async () => ({}) };
    return { status: 200, json: async () => ({ ...PAYLOAD, ogun }) };
  };
  const root = fakeRoot({ studentMembershipId: "1", termId: "7" });
  await mount(root, { fetchImpl: serve(OGUN) });
  assert.ok(asked.some((u) => u === "/api/results/health/1/?term_id=7"));
  assert.match(root.innerHTML, /Shown only to the child/);
});
