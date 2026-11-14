/**
 * End-of-session promotion: the principal decides, then the school is moved.
 *
 * What is asserted above all:
 *
 * - **nothing is assumed for a child nobody has decided about** (audit finding
 *   G-04): no select starts at "promote", and the plan is not offered for
 *   confirming while anybody is undecided;
 * - **the plan sends what was decided**, never a field on the page;
 * - only the principal is offered the controls that record a decision, and
 *   recording is one request, with the reason, after which the page is drawn
 *   again from the school;
 * - **nothing moves until the second button**: the first submit posts nothing,
 *   the confirm posts once, and a refusal leaves the summary up with the
 *   server's sentence.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  decisionsFrom,
  fromReview,
  htmlFor,
  mount,
  planFrom,
  settingsFrom,
  summarise,
  undecidedIn,
} from "../../static/promotion/app.js";
import { REFUSAL, refusalFor } from "../../static/promotion/api.js";
import * as states from "../../static/promotion/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const OUTCOMES = [
  { value: "promoted", label: "Promote" },
  { value: "on_trial", label: "Promote on trial" },
  { value: "repeated", label: "Repeat" },
  { value: "graduated", label: "Graduated" },
  { value: "withdrawn", label: "Leaving" },
];

const decided = (status, label, reason = "Met the pass mark") => ({
  status, label, reason, by: "Ngozi Eze", at: "2026-07-24T10:00:00+01:00",
});

/** Everybody decided: Ada promoted, Emeka repeating, Chi graduated. */
const REVIEW = {
  term: "Third term 2025/2026",
  to_term: "First term 2026/2027",
  problem: null,
  may_decide: false,
  pass_mark: "50.00",
  undecided: 0,
  outcomes: OUTCOMES,
  targets: [
    { class_group_id: 1, name: "JSS 1A" },
    { class_group_id: 2, name: "JSS 2A" },
    { class_group_id: 3, name: "SS 3" },
  ],
  classes: [
    {
      class_group_id: 1, name: "JSS 1A", destination_id: 2, graduate: false,
      children: [
        { membership_id: 11, name: "Ada Obi", reference: "A1", action: "promote", average: "70.00", suggested: "promoted", decision: decided("promoted", "Promoted") },
        { membership_id: 12, name: "Emeka Nwosu", reference: "", action: "repeat", average: "40.00", suggested: "repeated", decision: decided("repeated", "Repeating the class", "Below the pass mark") },
      ],
    },
    {
      class_group_id: 3, name: "SS 3", destination_id: null, graduate: true,
      children: [{ membership_id: 31, name: "Chi Okafor", reference: "", action: "promote", average: null, suggested: "", decision: decided("graduated", "Graduated", "Completed SS 3") }],
    },
  ],
};

/** Nobody decided yet. */
const UNDECIDED = {
  ...REVIEW,
  undecided: 3,
  classes: REVIEW.classes.map((row) => ({
    ...row,
    children: row.children.map((c) => ({ ...c, action: null, decision: null })),
  })),
};

const SETTINGS = { averaging: "equal", first_weight: null, second_weight: null, third_weight: null, pass_mark: "50" };

const FORM = { dest_1: "2", dest_3: "graduate" };
const fields = (form) => Object.fromEntries(Object.entries(form).map(([k, v]) => [k, { value: v }]));

function serve(routes) {
  return async (url, options = {}) => {
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    for (const [match, answer] of routes) {
      if (url.includes(match)) {
        const value = typeof answer === "function" ? answer(options, url) : answer;
        return { status: value.status, json: async () => value.body };
      }
    }
    throw new Error(`no stub for ${url}`);
  };
}

/** The routes a page load makes, with the review served by `review`. */
const school = (review, more = []) => [
  ...more,
  ["/api/results/year-settings/", { status: 200, body: SETTINGS }],
  ["/api/academics/promotion/", typeof review === "function" ? review : { status: 200, body: review }],
];

test("every class and child is shown with the average, the suggestion and the decision", () => {
  const html = states.review(REVIEW);

  assert.match(html, /JSS 1A/);
  assert.match(html, /Ada Obi/);
  assert.match(html, /Year's average 70\.00%\. Classnode suggests: promote\./);
  assert.match(html, /Year's average 40\.00%\. Classnode suggests: repeat\./);
  assert.match(html, /Decided: Repeating the class<\/span> <small>Below the pass mark<\/small> <small>\(Ngozi Eze\)<\/small>/);
  assert.match(html, /No released results for the year, so nothing is suggested\./);
});

test("nobody is assumed promoted: an undecided child says so and nothing is preselected", () => {
  const html = states.review(UNDECIDED);

  assert.equal((html.match(/Not decided yet/g) || []).length, 3);
  assert.match(html, /3 children have no decision yet/);
  assert.match(html, /The principal decides; nothing can be moved/);
  assert.doesNotMatch(html, /name="child_/);
  assert.doesNotMatch(html, /name="decide_/);
});

test("only the principal is offered the controls that record a decision", () => {
  const office = states.review(UNDECIDED);
  const principal = states.review({ ...UNDECIDED, may_decide: true });

  assert.doesNotMatch(office, /data-action="decide"/);
  assert.match(principal, /name="decide_11"/);
  assert.match(principal, /name="reason_1"/);
  assert.match(principal, /data-action="decide" data-class="1">Record decisions for JSS 1A/);
  assert.match(principal, /Record a decision for each before the school can be promoted/);
});

test("the principal is offered Classnode's suggestion first, and never one for a child with none", () => {
  const html = states.review({ ...UNDECIDED, may_decide: true });
  const select = (id) => html.match(new RegExp(`name="decide_${id}"[^>]*>(.*?)</select>`, "s"))[1];

  assert.match(select(11), /<option value="promoted" selected>Promote</);
  assert.match(select(12), /<option value="repeated" selected>Repeat</);
  // No released year: nothing is suggested, so nothing is chosen for them.
  assert.match(select(31), /<option value="" selected>Decide…</);
  assert.match(select(31), /<option value="withdrawn">Leaving</);
  assert.equal(states.offered({ suggested: "promoted", decision: null }, true), "graduated");
  assert.equal(states.offered({ suggested: "promoted", decision: { status: "on_trial" } }, false), "on_trial");
});

test("JSS 1A is preselected to JSS 2A and the top class to graduated", () => {
  const html = states.review(REVIEW);

  assert.match(html, /name="dest_1"[^>]*>.*?<option value="2" selected>JSS 2A/s);
  assert.match(html, /name="dest_3"[^>]*>.*?<option value="graduate" selected>Graduated/s);
});

test("a class cannot be promoted into itself", () => {
  const html = states.review(REVIEW);
  const first = html.match(/name="dest_1">(.*?)<\/select>/s)[1];

  assert.doesNotMatch(first, /value="1"/);
});

test("a class with no default says to choose, and is not preselected", () => {
  const html = states.review({
    ...REVIEW,
    classes: [{ ...REVIEW.classes[0], destination_id: null, graduate: false }],
  });

  assert.match(html, /<option value="" selected>Choose a class/);
});

test("nothing to promote yet says why, with no plan, and still offers the year's settings", () => {
  const html = states.review({ ...REVIEW, problem: "Promotion happens at the end of the third term.", settings: SETTINGS });

  assert.match(html, /data-state="unavailable"/);
  assert.match(html, /end of the third term/);
  assert.doesNotMatch(html, /data-form="review"/);
  assert.match(html, /data-form="settings"/);
});

test("the settings show the weighting and the pass mark, and say what a change does not reach", () => {
  const html = states.yearSettings({ averaging: "weighted", first_weight: "20", second_weight: "20", third_weight: "60", pass_mark: "45" });

  assert.match(html, /value="weighted" checked/);
  assert.match(html, /name="third_weight"[^>]*value="60"/);
  assert.match(html, /name="pass_mark"[^>]*value="45"/);
  assert.match(html, /does not alter a report card that has gone home or a decision already recorded/);
  assert.equal(states.yearSettings(null), "");
});

test("settingsFrom sends the weights only when the terms are weighted", () => {
  const form = fields({ averaging: "weighted", first_weight: "20", second_weight: "20", third_weight: "60", pass_mark: "45" });
  assert.deepEqual(settingsFrom(form), { averaging: "weighted", first_weight: "20", second_weight: "20", third_weight: "60", pass_mark: "45" });
  assert.deepEqual(
    settingsFrom(fields({ averaging: "equal", first_weight: "20", second_weight: "", third_weight: "", pass_mark: "50" })),
    { averaging: "equal", first_weight: null, second_weight: null, third_weight: null, pass_mark: "50" },
  );
});

test("planFrom sends each child's decided choice, whatever the form holds", () => {
  const form = fields({ ...FORM, child_11: "leave", child_12: "promote", decide_12: "promoted" });

  assert.deepEqual(planFrom(form, REVIEW.classes), [
    { class_group_id: 1, graduate: false, destination_id: 2, children: { 11: "promote", 12: "repeat" } },
    { class_group_id: 3, graduate: true, destination_id: null, children: { 31: "promote" } },
  ]);
  assert.equal(undecidedIn(REVIEW.classes), 0);
  assert.equal(undecidedIn(UNDECIDED.classes), 3);
});

test("a class with no destination chosen makes no plan", () => {
  assert.equal(planFrom(fields({ ...FORM, dest_1: "" }), REVIEW.classes), null);
});

test("decisionsFrom names only the children whose decision would change", () => {
  const form = fields({ decide_11: "promoted", decide_12: "on_trial" });

  assert.deepEqual(decisionsFrom(form, REVIEW.classes[0]), { 12: "on_trial" });
  assert.deepEqual(decisionsFrom(fields({ decide_11: "promoted", decide_12: "" }), UNDECIDED.classes[0]), { 11: "promoted" });
});

test("the summary counts promoted, repeating and graduating", () => {
  const { summary, totals } = summarise(planFrom(fields(FORM), REVIEW.classes), REVIEW.classes, REVIEW.targets);

  assert.deepEqual(totals, { promoted: 1, repeated: 1, graduated: 1, left: 0 });
  assert.deepEqual(summary[0], { name: "JSS 1A", to: "JSS 2A", repeating: 1, leaving: 0 });
  assert.equal(summary[1].to, "Graduated");
});

test("the status codes mean what the page says they mean", () => {
  assert.equal(refusalFor(403), REFUSAL.NOT_ALLOWED);
  assert.equal(refusalFor(404), REFUSAL.WRONG_HOST);
  assert.equal(refusalFor(401, { code: "session_expired" }), REFUSAL.EXPIRED);
  assert.equal(refusalFor(401, {}), REFUSAL.SIGNED_OUT);
  assert.equal(refusalFor(500), REFUSAL.BROKEN);
});

test("reviewing writes nothing: the first submit posts no request", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  const seen = [];
  const fetchImpl = serve(school((options) => {
    seen.push(options.method || "GET");
    return { status: 200, body: REVIEW };
  }));

  await mount(root, { fetchImpl });
  await root.submit(FORM);

  assert.deepEqual(seen, ["GET"]);
  assert.match(root.innerHTML, /data-state="confirm"/);
  assert.match(root.innerHTML, /1 promoted, 1 repeating, 1 graduating/);
});

test("with a child undecided the plan is not offered for confirming, and nothing is posted", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  const seen = [];
  const fetchImpl = serve(school((options) => {
    seen.push(options.method || "GET");
    return { status: 200, body: UNDECIDED };
  }));

  await mount(root, { fetchImpl });
  await root.submit(FORM);

  assert.deepEqual(seen, ["GET"]);
  assert.match(root.innerHTML, /data-state="review"/);
  assert.match(root.innerHTML, /3 children have no decision from the principal yet/);
  assert.doesNotMatch(root.innerHTML, /Confirm promotion/);
});

test("an unfinished form stays on the review with a sentence, and posts nothing", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  const seen = [];
  const fetchImpl = serve(school((options) => {
    seen.push(options.method || "GET");
    return { status: 200, body: REVIEW };
  }));

  await mount(root, { fetchImpl });
  await root.submit({ ...FORM, dest_1: "" });

  assert.deepEqual(seen, ["GET"]);
  assert.match(root.innerHTML, /Choose where every class goes/);
  assert.match(root.innerHTML, /data-state="review"/);
});

test("confirming posts the decided plan once and shows what happened", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  let posted = null;
  const fetchImpl = serve(school((options) => {
    if (options.method === "POST") {
      posted = JSON.parse(options.body);
      return { status: 200, body: { promoted: 1, repeated: 1, graduated: 1, left: 0 } };
    }
    return { status: 200, body: REVIEW };
  }));

  await mount(root, { fetchImpl });
  await root.submit(FORM);
  await root.submit({ confirm: "yes" });

  assert.equal(posted.classes.length, 2);
  assert.deepEqual(posted.classes[0].children, { 11: "promote", 12: "repeat" });
  assert.match(root.innerHTML, /data-state="done"/);
  assert.match(root.innerHTML, /1 promoted, 1 repeating, 1 graduated/);
});

test("a refusal keeps the summary up with the school's sentence", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  const fetchImpl = serve(school((options) =>
    options.method === "POST"
      ? { status: 409, body: { detail: "This plan is not what the principal decided for Emeka Nwosu." } }
      : { status: 200, body: REVIEW }));

  await mount(root, { fetchImpl });
  await root.submit(FORM);
  await root.submit({ confirm: "yes" });

  assert.match(root.innerHTML, /data-state="confirm"/);
  assert.match(root.innerHTML, /not what the principal decided/);
});

test("going back shows where the classes were pointed, not the defaults", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  const fetchImpl = serve(school(REVIEW));

  await mount(root, { fetchImpl });
  await root.submit({ ...FORM, dest_1: "3" });
  await root.click({ "data-action": "back" });

  assert.match(root.innerHTML, /data-state="review"/);
  assert.match(root.innerHTML, /name="dest_1"[^>]*>.*?<option value="3" selected>SS 3/s);
});

test("recording a class's decisions is one request with the reason, and the page is drawn again", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  const posts = [];
  let reads = 0;
  const fetchImpl = serve(school(
    () => {
      reads += 1;
      return { status: 200, body: reads === 1 ? { ...UNDECIDED, may_decide: true } : { ...REVIEW, may_decide: true } };
    },
    [["/api/academics/promotion/decisions/", (options) => {
      posts.push(JSON.parse(options.body));
      return { status: 200, body: { decided: 2 } };
    }]],
  ));

  await mount(root, { fetchImpl });
  const form = fields({ dest_1: "3", decide_11: "promoted", decide_12: "repeated", reason_1: "  Staff meeting of 24 July " });
  await root.click({ "data-action": "decide", "data-class": "1" }, { form });

  assert.deepEqual(posts, [{ children: { 11: "promoted", 12: "repeated" }, reason: "Staff meeting of 24 July" }]);
  assert.equal(reads, 2);
  assert.match(root.innerHTML, /Decided: Repeating the class/);
  // Where the class was pointed is kept across the redraw.
  assert.match(root.innerHTML, /name="dest_1"[^>]*>.*?<option value="3" selected>SS 3/s);
});

test("no reason, or nothing to record, is said on the class and posts nothing", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  let posted = 0;
  const fetchImpl = serve(school({ ...REVIEW, may_decide: true }, [
    ["/api/academics/promotion/decisions/", () => { posted += 1; return { status: 200, body: { decided: 1 } }; }],
  ]));

  await mount(root, { fetchImpl });
  await root.click({ "data-action": "decide", "data-class": "1" }, { form: fields({ decide_11: "repeated", decide_12: "repeated", reason_1: " " }) });
  assert.match(root.innerHTML, /Say why\. The reason is kept with each decision\./);
  await root.click({ "data-action": "decide", "data-class": "1" }, { form: fields({ decide_11: "promoted", decide_12: "repeated", reason_1: "Same as before" }) });
  assert.match(root.innerHTML, /Nothing to record/);

  assert.equal(posted, 0);
});

test("the school's refusal of a decision is said on the class and the page stays up", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  const fetchImpl = serve(school({ ...UNDECIDED, may_decide: true }, [
    ["/api/academics/promotion/decisions/", { status: 403, body: { detail: "Whether a child moves up, repeats, graduates or leaves is the principal's decision." } }],
  ]));

  await mount(root, { fetchImpl });
  await root.click({ "data-action": "decide", "data-class": "1" }, { form: fields({ decide_11: "promoted", reason_1: "Passed" }) });

  assert.match(root.innerHTML, /data-state="review"/);
  assert.match(root.innerHTML, /is the principal's decision/);
});

test("saving the settings is one request, says so, and reads the school again", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  let put = null;
  let reads = 0;
  const fetchImpl = async (url, options = {}) => {
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    if (url.includes("/api/results/year-settings/")) {
      if (options.method === "PUT") {
        put = JSON.parse(options.body);
        return { status: 200, json: async () => ({ ...SETTINGS, pass_mark: "45" }) };
      }
      return { status: 200, json: async () => SETTINGS };
    }
    reads += 1;
    return { status: 200, json: async () => REVIEW };
  };

  await mount(root, { fetchImpl });
  await root.submit({ averaging: "equal", pass_mark: "45" }, { form: "settings" });

  assert.deepEqual(put, { averaging: "equal", first_weight: null, second_weight: null, third_weight: null, pass_mark: "45" });
  assert.equal(reads, 2);
  assert.match(root.innerHTML, /name="pass_mark"[^>]*value="45"/);
  assert.match(root.innerHTML, /Saved\./);
});

test("a refused setting keeps what was typed and says why", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  const fetchImpl = async (url, options = {}) => {
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    if (url.includes("/api/results/year-settings/")) {
      return options.method === "PUT"
        ? { status: 422, json: async () => ({ detail: "A weighting has to add up to 100. 20/20/50 adds up to 90." }) }
        : { status: 200, json: async () => SETTINGS };
    }
    return { status: 200, json: async () => REVIEW };
  };

  await mount(root, { fetchImpl });
  await root.submit({ averaging: "weighted", first_weight: "20", second_weight: "20", third_weight: "50", pass_mark: "50" }, { form: "settings" });

  assert.match(root.innerHTML, /adds up to 90/);
  assert.match(root.innerHTML, /name="third_weight"[^>]*value="50"/);
});

test("the wrong host draws before any fetch", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "" });
  const fetchImpl = async () => {
    throw new Error("should not have fetched");
  };

  assert.equal((await mount(root, { fetchImpl })).step, REFUSAL.WRONG_HOST);
});

test("fromReview and htmlFor draw every state", () => {
  assert.equal(fromReview({ ok: true, body: REVIEW }).step, "review");
  assert.equal(fromReview({ ok: false, refusal: REFUSAL.NOT_ALLOWED, body: {} }).step, REFUSAL.NOT_ALLOWED);
  assert.match(htmlFor({ step: REFUSAL.NOT_ALLOWED }), /data-state="not-allowed"/);
  assert.match(htmlFor({ step: REFUSAL.EXPIRED }, { portal: "app.example.com" }), /Your session has ended/);
  assert.match(htmlFor({ step: REFUSAL.SIGNED_OUT }, { portal: "app.example.com" }), /Please sign in/);
  assert.match(htmlFor({ step: REFUSAL.BROKEN }), /data-state="broken"/);
});

test("a child decided leaving is planned as leave and counted apart from graduating", async () => {
  forgetToken();
  const leaving = {
    ...REVIEW,
    classes: [
      { ...REVIEW.classes[0], children: [
        { ...REVIEW.classes[0].children[0], action: "leave", decision: decided("withdrawn", "Withdrawn", "Moving to Ibadan") },
        REVIEW.classes[0].children[1],
      ] },
      REVIEW.classes[1],
    ],
  };
  let posted;
  const root = fakeRoot({ onSchool: "yes" });
  const fetchImpl = serve(school((options) => {
    if (options.method !== "POST") return { status: 200, body: leaving };
    posted = JSON.parse(options.body);
    return { status: 200, body: { promoted: 0, repeated: 1, graduated: 1, left: 1 } };
  }));

  await mount(root, { fetchImpl });
  await root.submit(FORM);
  assert.match(root.innerHTML, /0 promoted, 1 repeating, 1 graduating, 1 leaving/);
  await root.submit({ confirm: "yes" });

  assert.deepEqual(posted.classes[0].children, { 11: "leave", 12: "repeat" });
  assert.match(root.innerHTML, /1 graduated, 1 left/);
});
