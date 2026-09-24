/**
 * The timetable page.
 *
 * What it walks is `timetable/api.py`: the index and one class's week — a 200,
 * a flat 404 that means "refused or no such thing" and nothing more, and a 401
 * that is two states — and the writes, whose 403, 409 and 422 are sentences
 * for a person.
 *
 * **The grid draws what the week holds and nothing it does not**: a double
 * period is two cells that say the same thing, and a free period is a cell
 * that says so.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { htmlFor, mount } from "../../static/timetable/app.js";
import { REFUSAL, indexUrl, refusalFor, slotUrl, weekUrl } from "../../static/timetable/api.js";
import * as states from "../../static/timetable/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const DAYS = [
  { weekday: 1, day: "Monday" },
  { weekday: 2, day: "Tuesday" },
  { weekday: 3, day: "Wednesday" },
  { weekday: 4, day: "Thursday" },
  { weekday: 5, day: "Friday" },
];

const INDEX = {
  terms: [
    { term_id: 8, term: "2025/2026 Second term", is_current: false },
    { term_id: 7, term: "2025/2026 First term", is_current: true },
  ],
  term_id: 7,
  classes: [
    { class_group_id: 3, class_group: "JSS 1A" },
    { class_group_id: 4, class_group: "JSS 1B" },
  ],
  periods: [
    { period_id: 11, starts_at: "08:00", ends_at: "08:40", label: "Period 1" },
    { period_id: 12, starts_at: "08:40", ends_at: "09:20", label: "" },
  ],
  days: DAYS,
  may_edit: false,
  subjects: [],
  teachers: [],
  term_is_empty: false,
  has_earlier_term: false,
};

const EDITOR = {
  ...INDEX,
  may_edit: true,
  subjects: [
    { subject_id: 21, subject: "Mathematics", code: "MTH" },
    { subject_id: 22, subject: "English", code: "ENG" },
  ],
  teachers: [
    { teacher_membership_id: 31, teacher: "Kemi Maths" },
    { teacher_membership_id: 32, teacher: "Tunde English" },
  ],
};

const MATHS = { subject_id: 21, subject: "Mathematics", code: "MTH", teacher_membership_id: 31, teacher: "Kemi Maths" };

const WEEK = {
  class_group_id: 3,
  class_group: "JSS 1A",
  term_id: 7,
  term: "2025/2026 First term",
  lessons: [
    { weekday: 1, period_id: 11, ...MATHS },
    { weekday: 1, period_id: 12, ...MATHS },
    { weekday: 5, period_id: 12, subject_id: 22, subject: "English", code: "ENG", teacher_membership_id: 32, teacher: "Tunde English" },
  ],
};

function serve(routes) {
  const asked = [];
  const impl = async (url, init = {}) => {
    asked.push(init.method ? `${init.method} ${url}` : url);
    for (const [match, answer] of routes) {
      const [method, part] = match.includes(" ") ? match.split(" ") : [null, match];
      if (method && method !== (init.method || "GET")) continue;
      if (url.includes(part)) {
        const next = Array.isArray(answer) ? answer.shift() : answer;
        return { status: next.status, json: async () => next.body };
      }
    }
    throw new Error(`no stub for ${init.method || "GET"} ${url}`);
  };
  impl.asked = asked;
  return impl;
}

const CSRF = ["/api/csrf/", { status: 200, body: { csrf_token: "t" } }];

/** The cells of each row of the grid, as text, Monday first. */
function cells(html) {
  const body = html.split("<tbody>")[1].split("</tbody>")[0];
  return body
    .split("</tr>")
    .filter((r) => r.includes("<td"))
    .map((r) =>
      r
        .split("<td")
        .slice(1)
        .map((c) => c.replace(/^[^>]*>/, "").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim()),
    );
}

// -- the grid -----------------------------------------------------------------

test("each lesson lands in its weekday's column and its period's row", () => {
  assert.deepEqual(cells(states.grid(INDEX, WEEK)), [
    ["Mathematics Kemi Maths", "Free", "Free", "Free", "Free"],
    ["Mathematics Kemi Maths", "Free", "Free", "Free", "English Tunde English"],
  ]);
});

test("a double period is two cells saying the same thing, not one merged cell", () => {
  const html = states.grid(INDEX, WEEK);

  assert.equal((html.match(/Kemi Maths/g) || []).length, 2);
  assert.doesNotMatch(html, /rowspan/);
});

test("a period with no label is named by its times", () => {
  const html = states.grid(INDEX, WEEK);

  assert.match(html, /Period 1 <span class="times">08:00–08:40<\/span>/);
  assert.match(html, /<th scope="row">08:40–09:20<\/th>/);
});

test("what a school typed is escaped", () => {
  const week = { ...WEEK, lessons: [{ ...WEEK.lessons[0], subject: "<b>Maths</b>", teacher: "O'Neil & Co" }] };

  const html = states.grid(INDEX, week);

  assert.match(html, /&lt;b&gt;Maths&lt;\/b&gt;/);
  assert.doesNotMatch(html, /<b>Maths/);
});

// -- who sees the controls ----------------------------------------------------

test("a teacher reads the week and is offered nothing to change", () => {
  const html = htmlFor({ step: "week", index: INDEX, week: WEEK, classId: 3 });

  assert.match(html, /Mathematics/);
  for (const control of [/data-lesson/, /data-bell/, /data-action="clear"/, /data-action="remove-period"/, /data-action="copy"/]) {
    assert.doesNotMatch(html, control);
  }
});

test("an editor gets the lesson form, the bell form and a Free button per lesson", () => {
  const html = htmlFor({ step: "week", index: EDITOR, week: WEEK, classId: 3 });

  assert.match(html, /data-lesson/);
  assert.match(html, /data-bell/);
  assert.equal((html.match(/data-action="clear"/g) || []).length, 3);
  assert.equal((html.match(/data-action="remove-period"/g) || []).length, 2);
  assert.match(html, /<option value="31">Kemi Maths<\/option>/);
});

test("copying last term is offered only into an empty term with one before it", () => {
  const offered = (index) => /data-action="copy"/.test(htmlFor({ step: "week", index, week: { ...WEEK, lessons: [] }, classId: 3 }));

  assert.ok(offered({ ...EDITOR, term_is_empty: true, has_earlier_term: true }));
  assert.ok(!offered({ ...EDITOR, term_is_empty: false, has_earlier_term: true }));
  assert.ok(!offered({ ...EDITOR, term_is_empty: true, has_earlier_term: false }));
  assert.ok(!offered({ ...INDEX, term_is_empty: true, has_earlier_term: true }), "offered to a reader");
});

test("a day with no periods says so, and an editor is told where to add them", () => {
  const reader = htmlFor({ step: "week", index: { ...INDEX, periods: [] }, week: null, classId: 3 });
  const editor = htmlFor({ step: "week", index: { ...EDITOR, periods: [] }, week: null, classId: 3 });

  assert.match(reader, /data-empty="no-periods"/);
  assert.doesNotMatch(reader, /data-bell/);
  assert.match(editor, /Add them below/);
  assert.match(editor, /data-bell/);
  assert.doesNotMatch(editor, /data-lesson/, "a lesson form with no period to choose");
});

test("what a copy left behind is said, and why", () => {
  assert.equal(
    states.copiedSentence({ from_term: "2025/2026 First term", copied: 1, skipped_class: 0, skipped_subject: 0, skipped_teacher: 0 }),
    "Copied 1 lesson from 2025/2026 First term.",
  );
  assert.equal(
    states.copiedSentence({ from_term: "2025/2026 First term", copied: 9, skipped_class: 0, skipped_subject: 2, skipped_teacher: 1 }),
    "Copied 9 lessons from 2025/2026 First term. Left behind: 2 of a subject no longer taught; " +
      "1 by a teacher who has left. Those slots are free.",
  );
});

// -- refusals -----------------------------------------------------------------

test("a 404 is one state: refused and missing read the same", () => {
  assert.equal(refusalFor(404), REFUSAL.NOT_YOURS);
  assert.match(htmlFor({ step: REFUSAL.NOT_YOURS }), /not a timetable you can open/);
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

test("a reader the route refuses is told once, without a guess about why", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });

  await mount(root, { fetchImpl: serve([["/api/timetable/", { status: 404, body: { detail: "Not Found" } }]]) });

  assert.match(root.innerHTML, /data-state="not-yours"/);
});

// -- the flow -----------------------------------------------------------------

test("the page opens the current term's first class unless told otherwise", async () => {
  assert.equal(indexUrl(null), "/api/timetable/");
  assert.equal(weekUrl(4, 7), "/api/timetable/classes/4/?term_id=7");

  forgetToken();
  let fetchImpl = serve([
    ["/classes/", { status: 200, body: WEEK }],
    ["/api/timetable/", { status: 200, body: INDEX }],
  ]);
  await mount(fakeRoot({ onSchool: "yes" }), { fetchImpl });
  assert.deepEqual(fetchImpl.asked, ["/api/timetable/", "/api/timetable/classes/3/?term_id=7"]);

  fetchImpl = serve([
    ["/classes/", { status: 200, body: { ...WEEK, class_group_id: 4, class_group: "JSS 1B" } }],
    ["/api/timetable/", { status: 200, body: { ...INDEX, term_id: 8 } }],
  ]);
  await mount(fakeRoot({ onSchool: "yes" }), { fetchImpl, search: "?term=8&class=4" });
  assert.deepEqual(fetchImpl.asked, ["/api/timetable/?term_id=8", "/api/timetable/classes/4/?term_id=8"]);
});

test("choosing a class fetches that class's week in the same term", async () => {
  forgetToken();
  const fetchImpl = serve([
    ["/classes/", { status: 200, body: WEEK }],
    ["/api/timetable/", { status: 200, body: INDEX }],
  ]);
  const root = fakeRoot({ onSchool: "yes" });
  await mount(root, { fetchImpl });

  await root.change({ "data-class": "" }, "4");

  assert.equal(fetchImpl.asked.at(-1), "/api/timetable/classes/4/?term_id=7");
});

test("a saved lesson is followed by the week as the server now holds it", async () => {
  forgetToken();
  const after = { ...WEEK, lessons: [...WEEK.lessons, { weekday: 3, period_id: 11, ...MATHS }] };
  const fetchImpl = serve([
    CSRF,
    ["PUT /lessons/", { status: 201, body: { weekday: 3, period_id: 11, ...MATHS } }],
    ["/classes/", [{ status: 200, body: WEEK }, { status: 200, body: after }]],
    ["/api/timetable/", { status: 200, body: EDITOR }],
  ]);
  const root = fakeRoot({ onSchool: "yes" });
  await mount(root, { fetchImpl });

  const prevented = await root.submit({ weekday: "3", period_id: "11", subject_id: "21", teacher_membership_id: "31" });

  assert.ok(prevented, "the form submitted to the page itself");
  assert.ok(fetchImpl.asked.includes("PUT /api/timetable/classes/3/lessons/"));
  assert.equal(fetchImpl.asked.at(-1), "/api/timetable/classes/3/?term_id=7");
  assert.equal((root.innerHTML.match(/Kemi Maths<\/span>/g) || []).length, 3);
  assert.match(root.innerHTML, /Saved\./);
});

test("a clash keeps the week on screen and says what the teacher is already doing", async () => {
  forgetToken();
  const clash =
    "That teacher is teaching Mathematics to JSS 1B in that period. A teacher can take two " +
    "classes at once only for the same subject.";
  const fetchImpl = serve([
    CSRF,
    ["PUT /lessons/", { status: 409, body: { detail: clash } }],
    ["/classes/", { status: 200, body: WEEK }],
    ["/api/timetable/", { status: 200, body: EDITOR }],
  ]);
  const root = fakeRoot({ onSchool: "yes" });
  await mount(root, { fetchImpl });

  await root.submit({ weekday: "2", period_id: "11", subject_id: "22", teacher_membership_id: "31" });

  assert.match(root.innerHTML, /data-state="week"/);
  assert.match(root.innerHTML, /teaching Mathematics to JSS 1B in that period/);
  assert.match(root.innerHTML, /Tunde English/, "the week was lost");
});

test("the principal told they may not is a sentence, not a refusal screen", async () => {
  forgetToken();
  const fetchImpl = serve([
    CSRF,
    ["PUT /lessons/", { status: 403, body: { detail: "The timetable is set by an administrator or the vice principal (academic)." } }],
    ["/classes/", { status: 200, body: WEEK }],
    ["/api/timetable/", { status: 200, body: EDITOR }],
  ]);
  const root = fakeRoot({ onSchool: "yes" });
  await mount(root, { fetchImpl });

  await root.submit({ weekday: "2", period_id: "11", subject_id: "22", teacher_membership_id: "31" });

  assert.match(root.innerHTML, /data-state="week"/);
  assert.match(root.innerHTML, /set by an administrator or the vice principal/);
});

test("Free clears exactly the slot it sits in", async () => {
  assert.equal(slotUrl(3, 7, 5, 12), "/api/timetable/classes/3/lessons/?term_id=7&weekday=5&period_id=12");

  forgetToken();
  const fetchImpl = serve([
    CSRF,
    ["DELETE /lessons/", { status: 204, body: null }],
    ["/classes/", { status: 200, body: WEEK }],
    ["/api/timetable/", { status: 200, body: EDITOR }],
  ]);
  const root = fakeRoot({ onSchool: "yes" });
  await mount(root, { fetchImpl });

  await root.click({ "data-action": "clear", "data-weekday": "5", "data-period": "12" });

  assert.ok(fetchImpl.asked.includes("DELETE /api/timetable/classes/3/lessons/?term_id=7&weekday=5&period_id=12"));
  assert.match(root.innerHTML, /That period is free now\./);
});

test("copying last term reports what it copied and what it left behind", async () => {
  forgetToken();
  const fetchImpl = serve([
    CSRF,
    [
      "POST /copy/",
      { status: 201, body: { from_term: "2025/2026 First term", copied: 2, skipped_class: 1, skipped_subject: 0, skipped_teacher: 0 } },
    ],
    ["/classes/", { status: 200, body: WEEK }],
    ["/api/timetable/", { status: 200, body: { ...EDITOR, term_id: 8, term_is_empty: true, has_earlier_term: true } }],
  ]);
  const root = fakeRoot({ onSchool: "yes" });
  await mount(root, { fetchImpl });

  await root.click({ "data-action": "copy" });

  assert.ok(fetchImpl.asked.includes("POST /api/timetable/terms/8/copy/"));
  assert.match(root.innerHTML, /Copied 2 lessons from 2025\/2026 First term\. Left behind: 1 in a class no longer in use/);
});

test("a period that overlaps another is refused in a sentence", async () => {
  forgetToken();
  const fetchImpl = serve([
    CSRF,
    ["POST /periods/", { status: 422, body: { detail: "A period has to end after it starts, and cannot overlap another period." } }],
    ["/classes/", { status: 200, body: WEEK }],
    ["/api/timetable/", { status: 200, body: EDITOR }],
  ]);
  const root = fakeRoot({ onSchool: "yes" });
  await mount(root, { fetchImpl });

  await root.submit({ starts_at: "08:20", ends_at: "09:00", label: "" });

  assert.ok(fetchImpl.asked.includes("POST /api/timetable/periods/"));
  assert.match(root.innerHTML, /cannot overlap another period/);
});

test("a session that ended during a write shows the signed-out state", async () => {
  forgetToken();
  const fetchImpl = serve([
    CSRF,
    ["PUT /lessons/", { status: 401, body: { code: "session_expired" } }],
    ["/classes/", { status: 200, body: WEEK }],
    ["/api/timetable/", { status: 200, body: EDITOR }],
  ]);
  const root = fakeRoot({ onSchool: "yes" });
  await mount(root, { fetchImpl });

  await root.submit({ weekday: "2", period_id: "11", subject_id: "22", teacher_membership_id: "31" });

  assert.match(root.innerHTML, /Your session has ended/);
});
