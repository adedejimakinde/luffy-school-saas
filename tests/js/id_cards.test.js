/**
 * "Student ID cards": docs/id-cards.md.
 *
 * What the page draws from the server's answers, and what it asks next: the
 * term and its classes, a panel to choose the children (none for the whole
 * class), the job watched until it is ready, and the file offered as a plain
 * link to the server's own route. The refusals are here too, because a refusal
 * is the path nobody demos: the page for somebody who may not print, a lapsed
 * session, a wrong address. The authority itself is the server's and is tested
 * there on every route; this file holds that the page says so when it is told.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { jobUrl, overviewUrl, printUrl, refusalFor, rosterUrl } from "../../static/id-cards/api.js";
import { htmlFor, mount, stillMaking } from "../../static/id-cards/app.js";
import * as states from "../../static/id-cards/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const TERM = { id: 7, label: "First term 2026/2027", session: "2026/2027", expires_on: "2027-08-10" };
const OVERVIEW = {
  terms: [
    { id: 7, label: "First term 2026/2027", is_current: true },
    { id: 8, label: "Second term 2026/2027", is_current: false },
  ],
  term: TERM,
  classes: [
    { id: 11, name: "JSS 1A", students: 2 },
    { id: 12, name: "JSS 2A", students: 0 },
  ],
  phone_set: true,
  prints: [],
};
const ROSTER = {
  class_group_id: 11,
  class_group: "JSS 1A",
  term_id: 7,
  term: "First term 2026/2027",
  children: [
    { student_membership_id: 3, name: "Ada Obi", admission_number: "STM/001" },
    { student_membership_id: 4, name: "Bola Eze", admission_number: "" },
  ],
};
const job = (over = {}) => ({
  id: 9,
  state: "pending",
  state_label: "Waiting to start",
  class_group: "JSS 1A",
  term: "First term 2026/2027",
  done: 0,
  total: 2,
  card_count: null,
  created_at: "2026-11-13T10:00:00Z",
  expires_at: null,
  download_url: null,
  detail: "Waiting to start. This page will show progress.",
  ...over,
});

function json(status, body) {
  return { status, headers: { get: () => null }, json: async () => body };
}

/** A fetch that answers by method and URL, and remembers what it was sent. */
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

const nowait = { wait: async () => {} };

// -- what is drawn ----------------------------------------------------------------

test("the page names the expiry, lists each class, and offers Print only where there are children", () => {
  const html = states.overview({ ...OVERVIEW, printing: null, notes: {} });
  assert.match(html, /<h1>Student ID cards<\/h1>/);
  assert.match(html, /valid until 10 Aug 2027/);
  assert.match(html, /2026\/2027 session/);
  assert.match(html, /data-class="11"[\s\S]*2 children/);
  assert.match(html, /data-action="ask-print" data-class="11"/);
  assert.match(html, /Nobody placed this term/);
  assert.doesNotMatch(html, /data-action="ask-print" data-class="12"/);
});

test("a school with no phone on record is told what the back of the card will say", () => {
  assert.match(states.overview({ ...OVERVIEW, phone_set: false }), /no phone number on record/);
  assert.doesNotMatch(states.overview({ ...OVERVIEW, phone_set: true }), /no phone number on record/);
});

test("the term picker is drawn for two terms or more, with the current one named", () => {
  const html = states.overview({ ...OVERVIEW });
  assert.match(html, /data-term-select/);
  assert.match(html, /<option value="7" selected>First term 2026\/2027 \(current\)<\/option>/);
  assert.doesNotMatch(states.overview({ ...OVERVIEW, terms: [OVERVIEW.terms[0]] }), /data-term-select/);
});

test("no term, and no classes, each say so instead of drawing an empty list", () => {
  assert.match(states.overview({ ...OVERVIEW, term: null, classes: [] }), /No term has been set up yet/);
  assert.match(states.overview({ ...OVERVIEW, classes: [] }), /No classes yet/);
});

test("the choosing panel says that ticking none prints the whole class, and shows admission numbers", () => {
  const html = states.printPanel({ id: 11, name: "JSS 1A" }, { class_group_id: 11, children: ROSTER.children, chosen: [], job: null });
  assert.match(html, /Tick none to print the whole class \(2 cards\)/);
  assert.match(html, /data-print-child="3"/);
  assert.match(html, /STM\/001/);
  assert.match(html, /no admission number/);
  assert.match(html, /Make the PDF/);
  const ticked = states.printPanel({ id: 11, name: "JSS 1A" }, { class_group_id: 11, children: ROSTER.children, chosen: [4], job: null });
  assert.match(ticked, /data-print-child="4" value="4" checked/);
});

test("while the roll loads the panel says so and offers nothing to press", () => {
  const html = states.printPanel({ id: 11, name: "JSS 1A" }, { class_group_id: 11, children: null, chosen: [], job: null });
  assert.match(html, /Loading the class/);
  assert.doesNotMatch(html, /Make the PDF/);
});

test("a job in progress shows the server's sentence and a progress bar; a ready one offers the file", () => {
  const panel = (j) => states.printPanel({ id: 11, name: "JSS 1A" }, { class_group_id: 11, children: [], chosen: [], job: j });
  const building = panel(job({ state: "building", done: 1, detail: "Making the cards: 1 of 2 done." }));
  assert.match(building, /Making the cards: 1 of 2 done\./);
  assert.match(building, /<progress max="2" value="1">/);
  assert.doesNotMatch(building, /Download/);

  const ready = panel(job({ state: "ready", done: 2, card_count: 2, download_url: "/api/id-cards/jobs/9/pdf/", detail: "2 ID cards ready" }));
  assert.match(ready, /href="\/api\/id-cards\/jobs\/9\/pdf\/" download/);
  assert.match(ready, /Download the PDF/);
  assert.doesNotMatch(ready, /<progress/);

  const gone = panel(job({ state: "ready", detail: "This file was removed a day after it was made" }));
  assert.doesNotMatch(gone, /Download the PDF/);
});

test("the log names who printed what, and offers the file only to the person who asked while it lasts", () => {
  const prints = [
    { id: 5, class_group: "JSS 1A", term: "First term", card_count: 2, by: "Pat Principal", at: "13 Nov 2026, 10:00", state: "ready", state_label: "Ready to download", mine_to_download: true },
    { id: 4, class_group: "JSS 2A", term: "First term", card_count: 1, by: "Ade Admin", at: "12 Nov 2026, 09:00", state: "ready", state_label: "Ready to download", mine_to_download: false },
    { id: 3, class_group: "JSS 3A", term: "First term", card_count: null, by: "Pat Principal", at: "11 Nov 2026, 09:00", state: "failed", state_label: "Could not be made", mine_to_download: false },
  ];
  const html = states.overview({ ...OVERVIEW, prints });
  assert.match(html, /Pat Principal printed 2 ID cards for JSS 1A/);
  assert.match(html, /Ade Admin printed 1 ID card for JSS 2A/);
  assert.match(html, /could not be made/);
  assert.equal((html.match(/\/api\/id-cards\/jobs\/\d+\/pdf\//g) || []).length, 1);
  assert.match(html, /jobs\/5\/pdf/);
});

test("names from the roll are escaped", () => {
  const html = states.printPanel(
    { id: 11, name: "<img src=x onerror=alert(1)>" },
    { class_group_id: 11, children: [{ student_membership_id: 3, name: '<script>alert("x")</script>', admission_number: "<b>1</b>" }], chosen: [], job: null },
  );
  assert.doesNotMatch(html, /<script>|<img src=x|<b>1/);
  const row = states.overview({ ...OVERVIEW, classes: [{ id: 11, name: "<i>JSS</i>", students: 1 }] });
  assert.doesNotMatch(row, /<i>JSS/);
});

// -- the refusals -----------------------------------------------------------------

test("every refusal has a page of its own, and none of them draws a class or a name", () => {
  for (const [step, pattern] of [
    ["not-yours", /This page is not yours/],
    ["wrong-host", /not a school/],
    ["expired", /Your session has ended/],
    ["signed-out", /You are signed out/],
    ["broken", /Something went wrong/],
  ]) {
    const html = htmlFor({ step }, { portal: "app.example.test" });
    assert.match(html, pattern, step);
    assert.doesNotMatch(html, /JSS 1A|data-action="ask-print"/, step);
  }
  assert.match(htmlFor({ step: "signed-out" }, { portal: "app.example.test" }), /href="\/\/app\.example\.test\/staff-sign-in\/"/);
});

test("the server's sentence is the refusal page's when it gives one", () => {
  assert.match(states.notYours({ detail: "Only the principal." }), /Only the principal\./);
  assert.match(states.notYours({}), /principal, the vice principal and the administrator/);
});

test("which answer is which refusal", () => {
  assert.equal(refusalFor(403, {}), "not-yours");
  assert.equal(refusalFor(404, {}), "wrong-host");
  assert.equal(refusalFor(401, { code: "session_expired" }), "expired");
  assert.equal(refusalFor(401, {}), "signed-out");
  assert.equal(refusalFor(500, {}), "broken");
});

test("the urls the page asks are the server's routes", () => {
  assert.equal(overviewUrl(), "/api/id-cards/");
  assert.equal(overviewUrl(8), "/api/id-cards/?term_id=8");
  assert.equal(rosterUrl(11, 7), "/api/id-cards/classes/11/7/");
  assert.equal(printUrl(11, 7), "/api/id-cards/classes/11/7/print/");
  assert.equal(jobUrl(9), "/api/id-cards/jobs/9/");
});

test("only a job still being made is watched", () => {
  assert.equal(stillMaking({ state: "pending" }), true);
  assert.equal(stillMaking({ state: "building" }), true);
  assert.equal(stillMaking({ state: "ready" }), false);
  assert.equal(stillMaking({ state: "failed" }), false);
});

// -- the page, driven --------------------------------------------------------------

test("the whole class: nothing ticked sends no ids, the job is watched, the file is offered", async () => {
  forgetToken();
  const { fetchImpl, sent } = server({
    "GET /api/id-cards/": [json(200, OVERVIEW)],
    [`GET ${rosterUrl(11, 7)}`]: [json(200, ROSTER)],
    [`POST ${printUrl(11, 7)}`]: [json(202, job())],
    [`GET ${jobUrl(9)}`]: [
      json(200, job({ state: "building", done: 1, detail: "Making the cards: 1 of 2 done." })),
      json(200, job({ state: "ready", done: 2, card_count: 2, download_url: "/api/id-cards/jobs/9/pdf/", detail: "2 ID cards ready" })),
    ],
  });
  let waits = 0;
  const root = fakeRoot({ portal: "app.example.test" });
  await mount(root, { fetchImpl, wait: async () => { waits += 1; } });
  assert.match(root.innerHTML, /Student ID cards/);

  await root.click({ "data-action": "ask-print", "data-class": "11" });
  assert.match(root.innerHTML, /Tick none to print the whole class/);
  await root.submit({}, { print: "11" });

  const posted = sent.find((s) => s.method === "POST" && s.url === printUrl(11, 7));
  assert.deepEqual(posted.body, { student_ids: [] });
  assert.equal(waits, 2, "asked twice: building, then ready");
  assert.match(root.innerHTML, /href="\/api\/id-cards\/jobs\/9\/pdf\/"/);
  assert.match(root.innerHTML, /Download the PDF/);
});

test("ticked children are the ones sent, and unticking takes one back", async () => {
  forgetToken();
  const { fetchImpl, sent } = server({
    "GET /api/id-cards/": [json(200, OVERVIEW)],
    [`GET ${rosterUrl(11, 7)}`]: [json(200, ROSTER)],
    [`POST ${printUrl(11, 7)}`]: [json(202, job({ state: "ready", download_url: "/x", card_count: 1 }))],
  });
  const root = fakeRoot();
  await mount(root, { fetchImpl, ...nowait });
  await root.click({ "data-action": "ask-print", "data-class": "11" });
  await root.change({ "data-print-child": "3" }, "3", { checked: true });
  await root.change({ "data-print-child": "4" }, "4", { checked: true });
  await root.change({ "data-print-child": "3" }, "3", { checked: false });
  await root.submit({}, { print: "11" });
  assert.deepEqual(sent.find((s) => s.method === "POST" && s.url === printUrl(11, 7)).body, { student_ids: [4] });
});

test("a sentence from the server (a stray child, an empty class) is on the row, and the page stays", async () => {
  forgetToken();
  const { fetchImpl } = server({
    "GET /api/id-cards/": [json(200, OVERVIEW)],
    [`GET ${rosterUrl(11, 7)}`]: [json(200, ROSTER)],
    [`POST ${printUrl(11, 7)}`]: [json(422, { detail: "1 of the children chosen is not in JSS 1A for First term. Reload the page and choose again." })],
  });
  const root = fakeRoot();
  await mount(root, { fetchImpl, ...nowait });
  await root.click({ "data-action": "ask-print", "data-class": "11" });
  await root.submit({}, { print: "11" });
  assert.match(root.innerHTML, /is not in JSS 1A/);
  assert.match(root.innerHTML, /Student ID cards/, "still the page, not a refusal");
  assert.match(root.innerHTML, /data-action="ask-print" data-class="11"/, "and the button is back");
});

test("a job that fails says so and stops being watched", async () => {
  forgetToken();
  const { fetchImpl } = server({
    "GET /api/id-cards/": [json(200, OVERVIEW)],
    [`GET ${rosterUrl(11, 7)}`]: [json(200, ROSTER)],
    [`POST ${printUrl(11, 7)}`]: [json(202, job())],
    [`GET ${jobUrl(9)}`]: [json(200, job({ state: "failed", detail: "The cards could not be made. Try again, and tell Classnode if it keeps happening." }))],
  });
  let waits = 0;
  const root = fakeRoot();
  await mount(root, { fetchImpl, wait: async () => { waits += 1; } });
  await root.click({ "data-action": "ask-print", "data-class": "11" });
  await root.submit({}, { print: "11" });
  assert.equal(waits, 1);
  assert.match(root.innerHTML, /could not be made/);
  assert.doesNotMatch(root.innerHTML, /Download the PDF/);
});

test("somebody who may not print gets the refusal page and no class", async () => {
  forgetToken();
  const { fetchImpl } = server({ "GET /api/id-cards/": [json(403, { detail: "Student ID cards are printed by the principal." })] });
  const root = fakeRoot();
  await mount(root, { fetchImpl, ...nowait });
  assert.match(root.innerHTML, /This page is not yours/);
  assert.match(root.innerHTML, /printed by the principal/);
  assert.doesNotMatch(root.innerHTML, /JSS 1A/);
});

test("a 403 in the middle (a role taken away mid-print) is the refusal page too", async () => {
  forgetToken();
  const { fetchImpl } = server({
    "GET /api/id-cards/": [json(200, OVERVIEW)],
    [`GET ${rosterUrl(11, 7)}`]: [json(403, { detail: "No." })],
  });
  const root = fakeRoot();
  await mount(root, { fetchImpl, ...nowait });
  await root.click({ "data-action": "ask-print", "data-class": "11" });
  assert.match(root.innerHTML, /This page is not yours/);
});

test("signed out, and the portal, are their own pages", async () => {
  for (const [status, body, pattern] of [
    [401, {}, /You are signed out/],
    [401, { code: "session_expired" }, /Your session has ended/],
    [404, {}, /not a school/],
    [500, {}, /Something went wrong/],
  ]) {
    forgetToken();
    const { fetchImpl } = server({ "GET /api/id-cards/": [json(status, body)] });
    const root = fakeRoot();
    await mount(root, { fetchImpl, ...nowait });
    assert.match(root.innerHTML, pattern, String(status));
  }
});

test("choosing another term reads that term's classes", async () => {
  forgetToken();
  const second = { ...OVERVIEW, term: { id: 8, label: "Second term 2026/2027", session: "2026/2027", expires_on: "2027-08-10" }, classes: [{ id: 11, name: "JSS 1A", students: 3 }] };
  const { fetchImpl, sent } = server({
    "GET /api/id-cards/": [json(200, OVERVIEW)],
    "GET /api/id-cards/?term_id=8": [json(200, second)],
  });
  const root = fakeRoot();
  await mount(root, { fetchImpl, ...nowait });
  await root.change({ "data-term-select": "" }, "8");
  assert.ok(sent.some((s) => s.url === "/api/id-cards/?term_id=8"));
  assert.match(root.innerHTML, /3 children/);
});

test("closing a finished panel reads the page again, so the print is in the log", async () => {
  forgetToken();
  const logged = { ...OVERVIEW, prints: [{ id: 9, class_group: "JSS 1A", term: "First term", card_count: 2, by: "Pat Principal", at: "13 Nov 2026, 10:00", state: "ready", state_label: "Ready to download", mine_to_download: true }] };
  const { fetchImpl } = server({
    "GET /api/id-cards/": [json(200, OVERVIEW), json(200, logged)],
    "GET /api/id-cards/?term_id=7": [json(200, logged)],
    [`GET ${rosterUrl(11, 7)}`]: [json(200, ROSTER)],
    [`POST ${printUrl(11, 7)}`]: [json(202, job({ state: "ready", download_url: "/x", card_count: 2 }))],
  });
  const root = fakeRoot();
  await mount(root, { fetchImpl, ...nowait });
  await root.click({ "data-action": "ask-print", "data-class": "11" });
  await root.submit({}, { print: "11" });
  await root.click({ "data-action": "cancel-print", "data-class": "11" });
  assert.match(root.innerHTML, /Pat Principal printed 2 ID cards for JSS 1A/);
});
