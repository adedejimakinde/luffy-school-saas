/**
 * Who is absent too often.
 *
 * What it walks is `attendance/api.py`'s two absence routes: the list — a
 * 200, a flat 404 that means "refused or no such term" and nothing more, and
 * a 401 that is two states — and the threshold, whose 403 and 422 are
 * sentences for a person.
 *
 * **Every number and the order are the server's.** The page draws the
 * children in the order they came and prints the rate as sent.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { htmlFor, mount } from "../../static/absences/app.js";
import { REFUSAL, absencesUrl, refusalFor } from "../../static/absences/api.js";
import * as states from "../../static/absences/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const TERMS = [
  { term_id: 7, term: "2025/2026 First term", is_current: true },
  { term_id: 8, term: "2025/2026 Second term", is_current: false },
];

const LIST = {
  terms: TERMS,
  term_id: 7,
  term: "2025/2026 First term",
  threshold_percent: 10,
  min_marked_days: 10,
  may_change_threshold: true,
  registers_taken: 40,
  children: [
    { student_membership_id: 3, student: "Emeka E", class_group: "JSS 1A", absent: 6, marked: 20, rate: "30.0" },
    { student_membership_id: 1, student: "Ada A", class_group: "JSS 1B", absent: 2, marked: 16, rate: "12.5" },
  ],
};

function serve(routes) {
  const asked = [];
  const impl = async (url, init = {}) => {
    asked.push(init.method ? `${init.method} ${url}` : url);
    for (const [match, answer] of routes) {
      if (url.includes(match)) {
        const next = Array.isArray(answer) ? answer.shift() : answer;
        return { status: next.status, json: async () => next.body };
      }
    }
    throw new Error(`no stub for ${url}`);
  };
  impl.asked = asked;
  return impl;
}

// -- the list -----------------------------------------------------------------

test("the children are drawn in the server's order, with the server's rate", () => {
  const html = states.list({ absences: LIST });

  assert.ok(html.indexOf("Emeka E") < html.indexOf("Ada A"), "the page re-sorted the list");
  assert.match(html, /<td class="num">30\.0%<\/td>/);
  assert.match(html, /<td class="num">12\.5%<\/td>/);
  assert.match(html, /Absent on at least 10% of the days marked, once 10 days have been marked\./);
  assert.match(html, /A day with no register counts for nothing/);
});

test("nobody on the list after registers were taken is a finding", () => {
  const html = states.list({ absences: { ...LIST, children: [] } });

  assert.match(html, /data-empty="nobody"/);
  assert.match(html, /Nobody is absent that often this term/);
});

test("nobody on the list because no register was taken says that instead", () => {
  // The two sentences must not be one. "Nobody is absent too often" about a
  // term nobody has marked would be telling a principal something nobody
  // has looked at.
  const html = states.list({ absences: { ...LIST, children: [], registers_taken: 0 } });

  assert.match(html, /data-empty="no-registers"/);
  assert.match(html, /No register has been taken this term/);
  assert.doesNotMatch(html, /Nobody is absent that often/);
});

test("the threshold form is drawn only for those who may change it", () => {
  assert.match(states.list({ absences: LIST }), /data-threshold/);
  assert.doesNotMatch(
    states.list({ absences: { ...LIST, may_change_threshold: false } }),
    /data-threshold/,
  );
});

test("a school with terms and none current is asked to choose one", () => {
  const html = htmlFor({ step: "no-term", absences: { ...LIST, term_id: null, term: null, children: [] } });

  assert.match(html, /No term is marked current/);
  assert.match(html, /<option value="8">/);
});

test("a school with no terms is told the office sets them up", () => {
  const html = htmlFor({ step: "no-term", absences: { terms: [], term_id: null } });

  assert.match(html, /has not set up a term/);
});

// -- refusals -----------------------------------------------------------------

test("a 404 is one state: refused and missing read the same", () => {
  assert.equal(refusalFor(404), REFUSAL.NOT_YOURS);
  assert.match(htmlFor({ step: REFUSAL.NOT_YOURS }), /not a list you can open/);
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

  await mount(root, { fetchImpl: serve([["/absences/", { status: 404, body: { detail: "Not Found" } }]]) });

  assert.match(root.innerHTML, /data-state="not-yours"/);
});

// -- the flow -----------------------------------------------------------------

test("the page asks for the school's current term unless one is asked for", async () => {
  assert.equal(absencesUrl(null), "/api/attendance/absences/");
  assert.equal(absencesUrl(8), "/api/attendance/absences/?term_id=8");

  forgetToken();
  const fetchImpl = serve([["/absences/", { status: 200, body: LIST }]]);
  const root = fakeRoot({ onSchool: "yes" });
  await mount(root, { fetchImpl, search: "?term=8" });

  assert.deepEqual(fetchImpl.asked, ["/api/attendance/absences/?term_id=8"]);
});

test("choosing a term fetches that term's list", async () => {
  forgetToken();
  const fetchImpl = serve([["/absences/", { status: 200, body: LIST }]]);
  const root = fakeRoot({ onSchool: "yes" });
  await mount(root, { fetchImpl });

  await root.change({ "data-term": "" }, "8");

  assert.equal(fetchImpl.asked.at(-1), "/api/attendance/absences/?term_id=8");
});

test("a saved threshold is followed by the list drawn under it", async () => {
  forgetToken();
  const fetchImpl = serve([
    ["/api/csrf/", { status: 200, body: { csrf_token: "t" } }],
    ["/threshold/", { status: 200, body: { threshold_percent: 20, min_marked_days: 5 } }],
    [
      "/absences/",
      [
        { status: 200, body: LIST },
        { status: 200, body: { ...LIST, threshold_percent: 20, min_marked_days: 5 } },
      ],
    ],
  ]);
  const root = fakeRoot({ onSchool: "yes" });
  await mount(root, { fetchImpl });

  const prevented = await root.submit({ threshold_percent: "20", min_marked_days: "5" });

  assert.ok(prevented, "the form submitted to the page itself");
  assert.ok(fetchImpl.asked.includes("PUT /api/attendance/absences/threshold/"));
  assert.equal(fetchImpl.asked.at(-1), "/api/attendance/absences/?term_id=7");
  assert.match(root.innerHTML, /at least 20% of the days marked, once 5 days/);
  assert.match(root.innerHTML, /Saved\./);
});

test("a refused or out-of-range threshold keeps the list and says why", async () => {
  forgetToken();
  const fetchImpl = serve([
    ["/api/csrf/", { status: 200, body: { csrf_token: "t" } }],
    ["/threshold/", { status: 422, body: { detail: "The threshold is a percentage from 1 to 100." } }],
    ["/absences/", { status: 200, body: LIST }],
  ]);
  const root = fakeRoot({ onSchool: "yes" });
  await mount(root, { fetchImpl });

  await root.submit({ threshold_percent: "200", min_marked_days: "5" });

  assert.match(root.innerHTML, /data-state="list"/);
  assert.match(root.innerHTML, /The threshold is a percentage from 1 to 100\./);
  assert.match(root.innerHTML, /Emeka E/);
});
