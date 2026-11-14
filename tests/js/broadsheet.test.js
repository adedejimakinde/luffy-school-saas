/**
 * Broadsheets and the school overview.
 *
 * What it walks is `results/api.py`'s three read routes: terms, the overview,
 * and one class's broadsheet — 200s, a flat 404 that means "refused or no
 * such thing" and nothing more, and a 401 that is two states.
 *
 * **Every rank is the server's.** The page sorts by `current_rank` and marks
 * a shared rank "="; it never numbers rows itself.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { chosenTerm, htmlFor, mount } from "../../static/broadsheet/app.js";
import { REFUSAL, refusalFor } from "../../static/broadsheet/api.js";
import * as states from "../../static/broadsheet/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const subjects = (maths, mathsRank, english, englishRank) => [
  { subject_id: 1, subject: "English", percentage: english, current_subject_rank: englishRank },
  { subject_id: 2, subject: "Mathematics", percentage: maths, current_subject_rank: mathsRank },
];

const SHEET = {
  class_group: "JSS 1A",
  term: "2025/2026 First term",
  class_average: "74.50",
  from_snapshot: false,
  rows: [
    // Deliberately out of rank order: the page must sort by the server's rank.
    { student_membership_id: 3, student: "Chike C", average: "61.00", current_rank: 2, subjects: subjects("61.00", 2, null, null) },
    { student_membership_id: 1, student: "Ada A", average: "88.00", current_rank: 1, subjects: subjects("88.00", 1, "88.00", 1) },
    { student_membership_id: 2, student: "Bisi B", average: "88.00", current_rank: 1, subjects: subjects("88.00", 1, null, null) },
    { student_membership_id: 4, student: "Dayo D", average: null, current_rank: null, subjects: subjects(null, null, null, null) },
  ],
};

const TERMS = {
  terms: [
    { term_id: 8, term: "2025/2026 Second term", is_current: false },
    { term_id: 7, term: "2025/2026 First term", is_current: true },
  ],
};

const OVERVIEW = {
  term_id: 7,
  term: "2025/2026 First term",
  classes: [
    { class_group_id: 11, class_group: "JSS 1A", class_average: "74.50", children_ranked: 3, from_snapshot: true },
    { class_group_id: 12, class_group: "JSS 1B", class_average: null, children_ranked: 0, from_snapshot: false },
  ],
};

function serve(routes) {
  const asked = [];
  const impl = async (url) => {
    asked.push(url);
    for (const [match, answer] of routes) {
      if (url.includes(match)) return { status: answer.status, json: async () => answer.body };
    }
    throw new Error(`no stub for ${url}`);
  };
  impl.asked = asked;
  return impl;
}

// -- the numbers -------------------------------------------------------------

test("no marks is a dash, never a zero", () => {
  // CONTROL 3: printing a null average as 0 makes this red.
  const html = states.sheet({ broadsheet: SHEET });
  const dayo = html.slice(html.indexOf("Dayo<br>D"));
  const row = dayo.slice(0, dayo.indexOf("</tr>"));

  assert.match(row, /<span class="sc">-<\/span><\/td>$/, "the average cell is not a dash");
  assert.doesNotMatch(html, /<span class="sc">0(\.00)?<\/span>/);
});

test("rows follow the server's rank and a shared rank is marked, not split", () => {
  // CONTROL 4: numbering rows by their place on the page makes this red —
  // two children on 88.00 would print as 1st and 2nd.
  const html = states.sheet({ broadsheet: SHEET });
  const order = ["Ada<br>A", "Bisi<br>B", "Chike<br>C", "Dayo<br>D"].map((n) => html.indexOf(n));

  assert.deepEqual([...order].sort((a, b) => a - b), order, "rows are not in rank order");
  const ranks = [...html.matchAll(/<td class="rank pos">(?:<span[^>]*>)?([^<]*)(?:<\/span>)?<\/td>/g)].map((m) => m[1]);
  assert.deepEqual(ranks, ["1=", "1=", "2", "-"]);
});

test("a subject rank is the server's too, with its tie marked", () => {
  const html = states.sheet({ broadsheet: SHEET });

  assert.match(html, /<span class="sc">88<\/span><small>1=<\/small>/);
  assert.match(html, /<span class="sc">88<\/span><small>1st<\/small>/);
  assert.match(html, /<span class="sc">61<\/span><small>2nd<\/small>/);
});

test("the class average is at the foot, and a dash when nobody has one", () => {
  assert.match(states.sheet({ broadsheet: SHEET }), /Class average \(ranked students\)<\/th><td colspan="2"><\/td><td class="num subj"><span class="sc">74\.5<\/span><\/td>/);
  assert.match(
    states.sheet({ broadsheet: { ...SHEET, class_average: null } }),
    /Class average \(ranked students\)<\/th><td colspan="2"><\/td><td class="num subj"><span class="sc">-<\/span><\/td>/,
  );
});

test("the banner says which figures these are", () => {
  // CONTROL 5: a banner that ignores `from_snapshot` makes this red.
  assert.match(states.sheet({ broadsheet: { ...SHEET, from_snapshot: true } }), /figures that went home/);
  assert.match(states.sheet({ broadsheet: { ...SHEET, from_snapshot: false } }), /live\s+marks/);
  assert.doesNotMatch(states.sheet({ broadsheet: { ...SHEET, from_snapshot: false } }), /went home/);
});

test("a name is escaped", () => {
  const html = states.sheet({
    broadsheet: { ...SHEET, rows: [{ ...SHEET.rows[1], student: "<img src=x onerror=alert(1)>" }] },
  });

  assert.doesNotMatch(html, /<img/);
});

test("a class with nobody in it says so", () => {
  assert.match(states.sheet({ broadsheet: { ...SHEET, rows: [] } }), /Nobody in this class has a result/);
});

// -- the overview -------------------------------------------------------------

test("the overview is classes and their averages, released or live, and nobody's name", () => {
  const html = states.overview({ terms: TERMS.terms, overview: OVERVIEW });

  assert.match(html, /JSS 1A/);
  assert.match(html, /74\.50/);
  // What the average is over, in the headings and in the cell a phone's card labels.
  assert.match(html, /<th>Class average \(ranked students\)<\/th><th>Children ranked<\/th>/);
  assert.match(html, /<td class="num" data-label="Children ranked">3<\/td>/);
  assert.doesNotMatch(html, /Children with an average/);
  assert.match(html, /<td class="num" data-label="Class average \(ranked students\)">-<\/td>/);
  assert.match(html, /Released/);
  assert.match(html, /Live/);
  assert.doesNotMatch(html, /Ada A|current_rank|Pos\.|\branks?\b/);
  assert.match(html, /<option value="7" selected>2025\/2026 First term \(current\)<\/option>/);
});

test("the term opened is the one asked for, else the current one", () => {
  assert.equal(chosenTerm(TERMS.terms, "8"), 8);
  assert.equal(chosenTerm(TERMS.terms, "99"), 7);
  assert.equal(chosenTerm(TERMS.terms, null), 7);
  assert.equal(chosenTerm([{ term_id: 5, is_current: false }], null), 5);
});

// -- refusals -----------------------------------------------------------------

test("a 404 is one state: refused and missing read the same", () => {
  assert.equal(refusalFor(404), REFUSAL.NOT_YOURS);
  assert.match(htmlFor({ step: REFUSAL.NOT_YOURS }), /not a broadsheet you can open/);
  assert.equal(refusalFor(401, { code: "session_expired" }), REFUSAL.EXPIRED);
  assert.equal(refusalFor(401, {}), REFUSAL.SIGNED_OUT);
});

test("a frame on a host that is not a school's asks for nothing", async () => {
  forgetToken();
  const fetchImpl = serve([]);
  const root = fakeRoot({ onSchool: "" });

  await mount(root, { fetchImpl });

  assert.match(root.innerHTML, /your school's own web address/);
  assert.deepEqual(fetchImpl.asked, []);
});

test("a reader the routes refuse is told once, without a guess about why", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });

  await mount(root, { fetchImpl: serve([["/broadsheets/", { status: 404, body: { detail: "Not Found" } }]]) });

  assert.match(root.innerHTML, /data-state="not-yours"/);
});

// -- the flow -----------------------------------------------------------------

test("the page opens on the current term's overview, and a class opens its sheet", async () => {
  forgetToken();
  const fetchImpl = serve([
    ["/broadsheets/", { status: 200, body: TERMS }],
    ["/overview/?term_id=7", { status: 200, body: OVERVIEW }],
    ["/classes/11/broadsheet/?term_id=7", { status: 200, body: SHEET }],
  ]);
  const root = fakeRoot({ onSchool: "yes" });
  await mount(root, { fetchImpl });
  assert.match(root.innerHTML, /data-state="overview"/);

  await root.click({ "data-action": "open-class", "data-class": "11" });

  assert.match(root.innerHTML, /data-state="sheet"/);
  assert.match(root.innerHTML, /JSS 1A/);
});

test("the chain's link lands on the class it names", async () => {
  forgetToken();
  const fetchImpl = serve([
    ["/broadsheets/", { status: 200, body: TERMS }],
    ["/classes/11/broadsheet/?term_id=7", { status: 200, body: SHEET }],
  ]);
  const root = fakeRoot({ onSchool: "yes" });

  await mount(root, { fetchImpl, search: "?class=11" });

  assert.match(root.innerHTML, /data-state="sheet"/);
  assert.ok(!fetchImpl.asked.some((u) => u.includes("/overview/")), "the overview was fetched on the way");
});

test("choosing a term reads that term's overview", async () => {
  forgetToken();
  const fetchImpl = serve([
    ["/broadsheets/", { status: 200, body: TERMS }],
    ["/overview/?term_id=8", { status: 200, body: { ...OVERVIEW, term_id: 8, term: "2025/2026 Second term" } }],
    ["/overview/?term_id=7", { status: 200, body: OVERVIEW }],
  ]);
  const root = fakeRoot({ onSchool: "yes" });
  await mount(root, { fetchImpl });

  await root.change({ "data-term": "" }, "8");

  assert.match(root.innerHTML, /<h2>2025\/2026 Second term<\/h2>/);
});

// -- a child with a paper not yet marked ---------------------------------------

const PARTIAL_SHEET = {
  ...SHEET,
  ranked: 2,
  rows: [
    { student_membership_id: 1, student: "Ada A", average: "88.00", current_rank: 1, is_complete: true, subjects: subjects("88.00", 1, "88.00", 1).map((s) => ({ ...s, is_complete: true })) },
    { student_membership_id: 2, student: "Bisi B", average: "70.00", current_rank: 2, is_complete: true, subjects: subjects("70.00", 2, "70.00", 2).map((s) => ({ ...s, is_complete: true })) },
    {
      student_membership_id: 3, student: "Chike C", average: "92.28", current_rank: null, is_complete: false,
      subjects: [
        { subject_id: 1, subject: "English", percentage: "90.00", current_subject_rank: 1, is_complete: true },
        { subject_id: 2, subject: "Mathematics", percentage: "94.55", current_subject_rank: null, is_complete: false },
      ],
    },
  ],
};

test("a child with a paper unmarked has no position, only 'not ranked', and is not last of the ranked", () => {
  const html = states.sheet({ broadsheet: PARTIAL_SHEET });
  const names = [...html.matchAll(/<td class="name">([A-Z][a-z]+)<br>([A-Z])<\/td>/g)].map((m) => `${m[1]} ${m[2]}`);
  const chike = html.slice(html.indexOf("Chike<br>C") - 160);

  assert.deepEqual(names, ["Ada A", "Bisi B", "Chike C"], "the unranked after the ranked");
  assert.match(chike, /<td class="rank pos"><span class="not-ranked" title="Not ranked" aria-label="Not ranked">-<\/span><\/td>/);
  assert.match(html, /<td class="rank pos">1<\/td>/);
  assert.match(html, /<td class="rank pos">2<\/td>/);
});

test("the partial figures print beside 'incomplete', and a whole figure does not", () => {
  const html = states.sheet({ broadsheet: PARTIAL_SHEET });
  const chike = html.slice(html.indexOf("Chike<br>C"), html.indexOf("</tr>", html.indexOf("Chike<br>C")));
  const ada = html.slice(html.indexOf("Ada<br>A"), html.indexOf("</tr>", html.indexOf("Ada<br>A")));

  assert.match(chike, /<span class="sc">94\.55<\/span><small>incomplete<\/small>/, "the unfinished subject");
  assert.match(chike, /<span class="sc">92\.28<\/span><small>incomplete<\/small>/, "and the average built on it");
  assert.doesNotMatch(chike.replace(/<span class="sc">90<\/span><small>1st<\/small>/, ""), /<span class="sc">90<\/span><small>incomplete/, "a whole subject is not marked");
  assert.doesNotMatch(ada, /incomplete/);
});

test("a child with no marks at all is a dash, not 'incomplete' with nothing to show", () => {
  const sheet = {
    ...PARTIAL_SHEET,
    rows: [{ student_membership_id: 4, student: "Dayo D", average: null, current_rank: null, is_complete: false, subjects: subjects(null, null, null, null).map((s) => ({ ...s, is_complete: false })) }],
  };
  const row = states.sheet({ broadsheet: sheet }).match(/Dayo<br>D.*?<\/tr>/)[0];

  assert.doesNotMatch(row, /incomplete/);
  assert.match(row, /<span class="sc">-<\/span><\/td><\/tr>$/);
});

test("the page says how many are ranked, and why the others are not", () => {
  const html = states.sheet({ broadsheet: PARTIAL_SHEET });

  assert.match(html, /<p class="ranked-count" data-ranked="2">2 of 3 ranked\. A child with a paper not yet marked is not ranked\.<\/p>/);
});

test("a sheet from before the rule says nothing of incomplete, and keeps every rank", () => {
  const html = states.sheet({ broadsheet: { ...SHEET, ranked: 3 } });

  assert.doesNotMatch(html, /incomplete|not ranked<|A child with a paper/);
  assert.match(html, /3 of 4 ranked\.<\/p>/);
});

test("scores drop a trailing .00, subject places are ordinals, headers are short", () => {
  assert.equal(states.score("70.00"), "70");
  assert.equal(states.score("72.50"), "72.5");
  assert.equal(states.score("94.55"), "94.55");
  assert.equal(states.score(null), "-");
  const none = new Map();
  assert.deepEqual([1, 2, 3, 5, 11, 12, 13, 21, 22].map((n) => states.subjectPlace(n, none)), ["1st", "2nd", "3rd", "5th", "11th", "12th", "13th", "21st", "22nd"]);
  assert.equal(states.subjectPlace(3, new Map([[3, 2]])), "3=");
  assert.equal(states.shortSubject("Mathematics"), "Maths");
  assert.equal(states.shortSubject("English Language"), "Eng.");
  assert.equal(states.shortSubject("Basic Science"), "Basic Sci.");
  assert.equal(states.nameCell("Ada Okafor"), "Ada<br>Okafor");
});
