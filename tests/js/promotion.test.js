/**
 * End-of-session promotion: review every class, then confirm once.
 *
 * What is asserted above all is that **nothing is written until the second
 * button**: the first submit posts nothing, the confirm posts once, and a
 * refusal leaves the summary up with the server's sentence.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { fromReview, htmlFor, mount, planFrom, summarise } from "../../static/promotion/app.js";
import { REFUSAL, refusalFor } from "../../static/promotion/api.js";
import * as states from "../../static/promotion/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const REVIEW = {
  term: "Third term 2025/2026",
  to_term: "First term 2026/2027",
  problem: null,
  targets: [
    { class_group_id: 1, name: "JSS 1A" },
    { class_group_id: 2, name: "JSS 2A" },
    { class_group_id: 3, name: "SS 3" },
  ],
  classes: [
    {
      class_group_id: 1, name: "JSS 1A", destination_id: 2, graduate: false,
      children: [
        { membership_id: 11, name: "Ada Obi", reference: "A1", action: "promote" },
        { membership_id: 12, name: "Emeka Nwosu", reference: "", action: "promote" },
      ],
    },
    {
      class_group_id: 3, name: "SS 3", destination_id: null, graduate: true,
      children: [{ membership_id: 31, name: "Chi Okafor", reference: "", action: "promote" }],
    },
  ],
};

const FORM = {
  dest_1: "2", dest_3: "graduate",
  child_11: "promote", child_12: "repeat", child_31: "promote",
};

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

test("every class and every child is shown, each defaulting to promote", () => {
  const html = states.review(REVIEW);

  assert.match(html, /JSS 1A/);
  assert.match(html, /Ada Obi/);
  assert.match(html, /Chi Okafor/);
  assert.equal((html.match(/<option value="promote" selected>/g) || []).length, 3);
  assert.doesNotMatch(html, /<option value="repeat" selected>/);
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

test("nothing to promote yet says why, with no form", () => {
  const html = states.review({ ...REVIEW, problem: "Promotion happens at the end of the third term." });

  assert.match(html, /data-state="unavailable"/);
  assert.match(html, /end of the third term/);
  assert.doesNotMatch(html, /<form/);
});

test("planFrom reads every destination and every child's choice", () => {
  assert.deepEqual(
    planFrom(Object.fromEntries(Object.entries(FORM).map(([k, v]) => [k, { value: v }])), REVIEW.classes),
    [
      { class_group_id: 1, graduate: false, destination_id: 2, children: { 11: "promote", 12: "repeat" } },
      { class_group_id: 3, graduate: true, destination_id: null, children: { 31: "promote" } },
    ],
  );
});

test("a class with no destination chosen makes no plan", () => {
  const form = Object.fromEntries(Object.entries({ ...FORM, dest_1: "" }).map(([k, v]) => [k, { value: v }]));

  assert.equal(planFrom(form, REVIEW.classes), null);
});

test("the summary counts promoted, repeating and graduating", () => {
  const form = Object.fromEntries(Object.entries(FORM).map(([k, v]) => [k, { value: v }]));
  const { summary, totals } = summarise(planFrom(form, REVIEW.classes), REVIEW.classes, REVIEW.targets);

  assert.deepEqual(totals, { promoted: 1, repeated: 1, graduated: 1 });
  assert.deepEqual(summary[0], { name: "JSS 1A", to: "JSS 2A", repeating: 1 });
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
  const fetchImpl = serve([
    ["/api/academics/promotion/", (options) => {
      seen.push(options.method || "GET");
      return { status: 200, body: REVIEW };
    }],
  ]);

  await mount(root, { fetchImpl });
  await root.submit(FORM);

  assert.deepEqual(seen, ["GET"]);
  assert.match(root.innerHTML, /data-state="confirm"/);
  assert.match(root.innerHTML, /1 promoted, 1 repeating, 1 graduating/);
});

test("an unfinished form stays on the review with a sentence, and posts nothing", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  const seen = [];
  const fetchImpl = serve([
    ["/api/academics/promotion/", (options) => {
      seen.push(options.method || "GET");
      return { status: 200, body: REVIEW };
    }],
  ]);

  await mount(root, { fetchImpl });
  await root.submit({ ...FORM, dest_1: "" });

  assert.deepEqual(seen, ["GET"]);
  assert.match(root.innerHTML, /Choose where every class goes/);
  assert.match(root.innerHTML, /data-state="review"/);
});

test("confirming posts the whole plan once and shows what happened", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  let posted = null;
  const fetchImpl = serve([
    ["/api/academics/promotion/", (options) => {
      if (options.method === "POST") {
        posted = JSON.parse(options.body);
        return { status: 200, body: { promoted: 1, repeated: 1, graduated: 1 } };
      }
      return { status: 200, body: REVIEW };
    }],
  ]);

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
  const fetchImpl = serve([
    ["/api/academics/promotion/", (options) =>
      options.method === "POST"
        ? { status: 409, body: { detail: "The classes changed since this page was drawn." } }
        : { status: 200, body: REVIEW }],
  ]);

  await mount(root, { fetchImpl });
  await root.submit(FORM);
  await root.submit({ confirm: "yes" });

  assert.match(root.innerHTML, /data-state="confirm"/);
  assert.match(root.innerHTML, /The classes changed/);
});

test("going back shows the choices just made, not the defaults", async () => {
  forgetToken();
  const root = fakeRoot({ onSchool: "yes" });
  const fetchImpl = serve([["/api/academics/promotion/", { status: 200, body: REVIEW }]]);

  await mount(root, { fetchImpl });
  await root.submit(FORM);
  await root.click({ "data-action": "back" });

  assert.match(root.innerHTML, /data-state="review"/);
  assert.match(root.innerHTML, /<option value="repeat" selected>/);
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
