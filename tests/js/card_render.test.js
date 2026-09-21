/**
 * The renderer, and the claim that it is only a renderer.
 *
 * The page is handed `columns` in print order and each line's `cells` already
 * aligned to them. These tests are what say it walks those two lists and
 * decides nothing: the strongest of them hands the renderer a column order no
 * sort could produce and asserts the page prints it as given.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { card } from "../../static/card/render.js";
import { htmlFor, mount } from "../../static/card/app.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

/** A card whose column order is neither alphabetical nor creation order. */
function payload(overrides = {}) {
  return {
    school_name: "St Mary's",
    student_name: "Ada Obi",
    class_group_name: "JSS 1A",
    academic_session: "2025/2026",
    term_name: "first",
    term_label: "First term",
    term_id: 1,
    version: 1,
    is_revised: false,
    total_scored: 216,
    total_available: 260,
    own_average: "83.08",
    days_present: null,
    days_absent: null,
    days_open: null,
    // The decision the server took, which is the only thing `attendance()`
    // reads. The three raw columns above are still on the payload and are
    // deliberately *not* what the renderer branches on.
    attendance: {
      state: "absent",
      present: null,
      absent: null,
      school_days: null,
      marked: null,
      not_marked: null,
    },
    columns: [
      { name: "First CA", max_score: 20 },
      { name: "Exam", max_score: 100 },
      { name: "Mid-term", max_score: 30 },
      { name: "Exam", max_score: 90 },
    ],
    subjects: [
      {
        subject_name: "English",
        subject_code: "ENG",
        total_scored: 89,
        total_available: 120,
        percentage: "74.17",
        grade_letter: "B2",
        grade_remark: "Very Good",
        assessments: [
          { assessment_name: "First CA", max_score: 20, score: 15 },
          { assessment_name: "Exam", max_score: 100, score: 74 },
        ],
        cells: [
          { assessment_name: "First CA", max_score: 20, score: 15 },
          { assessment_name: "Exam", max_score: 100, score: 74 },
          null,
          null,
        ],
      },
      {
        subject_name: "Mathematics",
        subject_code: "MTH",
        total_scored: 127,
        total_available: 140,
        percentage: "90.71",
        grade_letter: "A1",
        grade_remark: "Excellent",
        assessments: [
          { assessment_name: "First CA", max_score: 20, score: 17 },
          { assessment_name: "Mid-term", max_score: 30, score: null },
          { assessment_name: "Exam", max_score: 90, score: 88 },
        ],
        cells: [
          { assessment_name: "First CA", max_score: 20, score: 17 },
          null,
          { assessment_name: "Mid-term", max_score: 30, score: null },
          { assessment_name: "Exam", max_score: 90, score: 88 },
        ],
      },
    ],
    sections: [],
    comments: [],
    session: null,
    promotion: null,
    ...overrides,
  };
}

/** The header cells, in the order the page printed them. */
function header(html) {
  // `[^<]*` and not `.*?`: the `Total`, `%` and `Grade` headers carry no
  // maximum, so a capture allowed to cross a tag boundary runs from "Total"
  // all the way into the first row's own `/120` and reports a fifth column
  // that does not exist. The test found that on itself.
  return [
    ...html.matchAll(/<th scope="col" class="n">([^<]*)<span class="max">\/(\d+)<\/span>/g),
  ].map((m) => `${m[1]}/${m[2]}`);
}

test("the header is the column list in the order given", () => {
  assert.deepEqual(header(card(payload())), [
    "First CA/20",
    "Exam/100",
    "Mid-term/30",
    "Exam/90",
  ]);
});

test("a column order no sort could produce is printed as given", () => {
  // The control on the claim above. If anything in the renderer sorted — by
  // name, by maximum, by anything — this order could not come out intact, and
  // an alphabetical page would read "Exam, Exam, First CA, Mid-term".
  const shuffled = payload({
    columns: [
      { name: "Mid-term", max_score: 30 },
      { name: "Exam", max_score: 90 },
      { name: "First CA", max_score: 20 },
      { name: "Exam", max_score: 100 },
    ],
  });
  assert.deepEqual(header(card(shuffled)), [
    "Mid-term/30",
    "Exam/90",
    "First CA/20",
    "Exam/100",
  ]);
});

test("the same paper name out of two totals stays two columns", () => {
  // Keyed on `(name, max_score)` server-side. 45 out of 60 and 45 out of 100
  // read as equal performance in one column headed "Exam", and are not.
  const html = card(payload());
  assert.equal(header(html).filter((h) => h.startsWith("Exam")).length, 2);
});

test("a gap and an unmarked paper do not print the same", () => {
  // `·` is "this subject has no such paper"; `—` is "the child was not marked
  // in it". Two absences that mean different things, on a page somebody will
  // ask a teacher about.
  const row = card(payload()).match(/<tr><td>Mathematics<\/td>(.*?)<\/tr>/)[1];
  const cells = [...row.matchAll(/<td class="n">(.*?)<\/td>/g)].map((m) => m[1]);
  assert.match(cells[0], /^17$/, "the mark");
  assert.match(cells[1], /&middot;/, "Mathematics has no Exam out of 100: a gap");
  assert.match(cells[2], /&mdash;/, "nobody marked the Mid-term: a dash");
  assert.match(cells[3], /^88$/);
});

test("every row is as long as the header", () => {
  const html = card(payload());
  const rows = [...html.matchAll(/<tr><td>(?:English|Mathematics)<\/td>(.*?)<\/tr>/g)];
  assert.equal(rows.length, 2);
  for (const [, row] of rows) {
    // Four column cells, plus total, percentage, grade.
    assert.equal([...row.matchAll(/<td class="n">/g)].length, 7);
  }
});

test("a school's typed text cannot execute in a parent's browser", () => {
  // `school_name`, a subject name and every remark are typed into the admin by
  // a school. This page builds markup by hand, so it has no default escaping
  // to rely on — the escape is a rule with this test on it.
  const html = card(
    payload({
      school_name: '<script>alert("x")</script>',
      comments: [
        {
          author: "principal",
          author_label: "Principal",
          body: '<img src=x onerror="alert(1)">',
        },
      ],
    }),
  );
  assert.doesNotMatch(html, /<script>/);
  assert.doesNotMatch(html, /<img src=x/);
  assert.match(html, /&lt;script&gt;/);
});

test("a percentage is printed exactly as it arrived", () => {
  // It is a string because it is a Decimal all the way down the server, and
  // turning it into a number here would round the one figure a parent is most
  // likely to check with a calculator.
  const html = card(payload({ own_average: "83.08" }));
  assert.match(html, /83\.08%/);
  assert.doesNotMatch(html, /83\.1%|83%/);
});

const attending = (state, extra = {}) =>
  payload({
    attendance: {
      state,
      present: null,
      absent: null,
      school_days: null,
      marked: null,
      not_marked: null,
      ...extra,
    },
  });

test("a fully marked term prints present of declared, which is the target case", () => {
  const html = card(
    attending("complete", { present: 58, absent: 4, school_days: 62, marked: 62, not_marked: 0 }),
  );
  assert.match(html, /Present 58 of 62 days/);
});

test("nought days present is not the same as no register kept", () => {
  // Absent every day of a fully marked term. `0` is a real measurement and the
  // one case where "Present 0 of 60" is true.
  const kept = card(
    attending("complete", { present: 0, absent: 60, school_days: 60, marked: 60, not_marked: 0 }),
  );
  assert.match(kept, /Present 0 of 60 days/, "present on none of the days the school opened");

  const none = card(payload());
  assert.doesNotMatch(none, /of\s+days|0 of/, "no attendance on this card: blank, not a zero");
});

test("a term nobody marked never prints a number", () => {
  // The case this whole design exists for. `0, 0, 62` is a school that kept no
  // register, and "Present 0 out of 62 days" would accuse every child in the
  // class of never turning up.
  const html = card(
    attending("not_recorded", { present: 0, absent: 0, school_days: 62, marked: 0, not_marked: 62 }),
  );
  assert.match(html, /Not recorded this term/);
  assert.doesNotMatch(html, /0 of 62|of 62 days/, "no denominator, because nothing was measured");
});

test("a partly marked term never divides by the declared days", () => {
  const html = card(
    attending("partial", { present: 38, absent: 2, school_days: 62, marked: 40, not_marked: 22 }),
  );
  assert.match(html, /38 present, 2 absent/);
  assert.match(html, /register kept on 40 of 62 days/);
  assert.doesNotMatch(
    html,
    /38 of 62/,
    "62 is never a denominator: subtracting from it reads unmarked days as absence",
  );
});

/** The attendance cell alone. Asserting against the whole card would match any
 *  digit in the marks table, which is how the first draft of the test below
 *  passed for the wrong reason. */
const attendanceCell = (html) =>
  (html.match(/Attendance<\/th><td>([\s\S]*?)<\/td>/) || [])[1] || "";

test("an unknown state is blank rather than a guess", () => {
  const cell = attendanceCell(
    card(attending("something_new", { present: 5, school_days: 62, marked: 5 })),
  );
  assert.match(cell, /&mdash;/, "blank, like a card with no attendance at all");
  assert.doesNotMatch(cell, /5|62/, "a client that does not understand the state invents nothing");
});

test("the revised marker appears only when the payload says so", () => {
  assert.doesNotMatch(card(payload()), /Revised/);
  assert.match(card(payload({ is_revised: true })), /Revised/);
});

test("a staff-only field in the payload still does not reach the page", () => {
  // The structural guarantee is server-side: `ReportCardOut` has no slot for
  // these. This is the renderer's half — it prints the fields it knows, so a
  // payload that somehow carried a rank would not leak one through here.
  const html = card(
    payload({
      position: 1,
      roster_size: 45,
      subjects: payload().subjects.map((s) => ({ ...s, subject_position: 2 })),
    }),
  );
  assert.doesNotMatch(html, /\bPosition\b|\bRank\b|roster/i);
});

test("mount puts the card in the element and names the state it settled in", async () => {
  // The whole pipeline — read the ids, fetch, render, record the state — with
  // a stub element and a stub fetch. No DOM: `mount` touches `innerHTML` and
  // `dataset` and a click listener, and `fakeRoot()` is those three.
  const root = fakeRoot({ studentMembershipId: "5", termId: "9" });
  const calls = [];
  const answer = await mount(root, {
    fetchImpl: async (url) => {
      calls.push(url);
      return { status: 200, json: async () => payload() };
    },
  });

  assert.deepEqual(calls, ["/api/results/cards/5/9/"]);
  assert.equal(answer.ok, true);
  assert.equal(root.dataset.state, "card");
  assert.match(root.innerHTML, /Ada Obi/);
});

test("mount settles in the withheld state and says so on the element", async () => {
  const root = fakeRoot({ studentMembershipId: "5", termId: "9" });
  await mount(root, {
    fetchImpl: async () => ({
      status: 403,
      json: async () => ({ school_name: "St Mary's", contact: "0803 000 0001", detail: "held" }),
    }),
  });
  assert.equal(root.dataset.state, "withheld");
  assert.match(root.innerHTML, /0803 000 0001/);
  assert.doesNotMatch(root.innerHTML, /Ada Obi/, "no card content on a refusal");
});

test("a fetch that never lands is the broken state, not a blank page", async () => {
  const root = fakeRoot({ studentMembershipId: "5", termId: "9" });
  await mount(root, {
    fetchImpl: async () => {
      throw new TypeError("Failed to fetch");
    },
  });
  assert.equal(root.dataset.state, "broken");
  assert.doesNotMatch(root.innerHTML, /Failed to fetch/, "not the transport's words");
  assert.match(root.innerHTML, /try again/i);
});

test("htmlFor renders a card for an ok answer and a state for every other", () => {
  assert.match(htmlFor({ ok: true, card: payload() }), /Ada Obi/);
  assert.match(htmlFor({ ok: false, refusal: "missing", body: {} }), /No report card here/);
});

test("mount signs out and the card goes with the session", async () => {
  forgetToken();
  const root = fakeRoot({ studentMembershipId: "5", termId: "9", portal: "portal.example.test" });
  const calls = [];
  await mount(root, {
    fetchImpl: async (url) => {
      calls.push(url);
      if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
      if (url === "/api/logout/") return { status: 200, json: async () => ({ detail: "Signed out." }) };
      return { status: 200, json: async () => payload() };
    },
  });
  assert.match(root.innerHTML, /Ada Obi/);

  await root.click({ "data-action": "sign-out" });

  assert.ok(calls.includes("/api/logout/"));
  // A card left on screen after its claim has been given up is a child's marks
  // waiting for whoever picks the handset up next — which is the case the
  // guardian flow exists for, so it is the case sign-out has to answer.
  assert.doesNotMatch(root.innerHTML, /Ada Obi/, "the marks outlived the session");
  assert.equal(root.dataset.state, "signed-out");
  assert.match(root.innerHTML, /\/\/portal\.example\.test\/sign-in\//);
});

test("a sign-out the server would not confirm leaves the card alone", async () => {
  forgetToken();
  const root = fakeRoot({ studentMembershipId: "5", termId: "9", portal: "portal.example.test" });
  await mount(root, {
    fetchImpl: async (url) => {
      if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
      if (url === "/api/logout/") return { status: 0, json: async () => ({}) };
      return { status: 200, json: async () => payload() };
    },
  });

  await root.click({ "data-action": "sign-out" });

  assert.match(root.innerHTML, /Ada Obi/, "a card cleared on an unproved sign-out");
  assert.match(root.innerHTML, /could not sign you out/i);
  assert.equal(root.dataset.state, "card");
});
