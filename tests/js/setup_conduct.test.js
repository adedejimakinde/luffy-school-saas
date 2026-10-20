/**
 * The setup page's affective and psychomotor section: what it draws from
 * `SetUpOut.conduct`, and the one request each control sends.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { mount, movedOrder } from "../../static/setup/app.js";
import * as states from "../../static/setup/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const trait = (id, name, extra = {}) => ({ trait_id: id, name, is_hidden: false, has_ratings: false, ...extra });
const CONDUCT = {
  sections: [
    {
      group: "affective",
      label: "Affective (conduct)",
      enabled: true,
      traits: [trait(1, "Punctuality"), trait(2, "Neatness"), trait(3, "Honesty", { is_hidden: true, has_ratings: true })],
    },
    { group: "psychomotor", label: "Psychomotor (skills)", enabled: false, traits: [trait(7, "Handwriting")] },
  ],
  scale: [5, 4, 3, 2, 1].map((value, i) => ({ value, label: ["Excellent", "Good", "Average", "Below Average", "Unsatisfactory"][i] })),
  changes: [{ at: "2026-10-20T14:05:00", by: "Tunde Alabi", summary: "Switched Affective (conduct) on" }],
};
const SETUP = { terms: [], classes: [], may_set_up: true, conduct: CONDUCT };

function recording(responses = {}) {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    const method = options.method || "GET";
    calls.push({ url, method, body: options.body ? JSON.parse(options.body) : undefined });
    const answer = responses[`${method} ${url}`];
    if (answer) return { status: answer.status, json: async () => answer.body };
    return { status: 200, json: async () => SETUP };
  };
  return { calls, fetchImpl };
}

test("each section has its own switch, named, with what off means", () => {
  const html = states.shape(SETUP);

  assert.match(html, /<input type="checkbox" role="switch" data-switch="affective" checked>/);
  assert.match(html, /<input type="checkbox" role="switch" data-switch="psychomotor">/);
  assert.match(html, /<strong id="conduct-affective">Affective \(conduct\)<\/strong>/);
  assert.match(html, /<strong id="conduct-psychomotor">Psychomotor \(skills\)<\/strong>/);
  assert.match(html, /Off\. No rating grid for teachers and no section on new cards\. Ratings already entered are kept\./);
  assert.match(html, /a card already sent home keeps the lines, ratings and words it was sent with/);
});

test("the trait list is the school's, hidden ones muted with a way back, never a delete", () => {
  const html = states.shape(SETUP);

  assert.match(html, /data-trait-name="1"[^>]*value="Punctuality"|value="Punctuality"[^>]*data-trait-name="1"/);
  assert.match(html, /<li class="trait hidden">/);
  assert.match(html, /data-action="show-trait" data-trait="3">Show</);
  assert.match(html, /data-action="hide-trait" data-trait="1">Hide</);
  assert.doesNotMatch(html, /delete|remove-trait/i);
  assert.match(html, /aria-label="Move Punctuality up" disabled/, "the first cannot go up");
  assert.match(html, /aria-label="Move Honesty down" disabled/, "the last cannot go down");
});

test("the scale is five words for fixed numbers 1 to 5, highest first", () => {
  const html = states.shape(SETUP);

  const inputs = [...html.matchAll(/data-scale="(\d)"/g)].map((m) => m[1]);
  assert.deepEqual(inputs, ["5", "4", "3", "2", "1"]);
  assert.match(html, /Always 1 to 5\. You can change the words, not the numbers\./);
  assert.match(html, /value="Excellent"/);
});

test("the log shows who and when, and is absent when there is nothing to show", () => {
  assert.match(states.shape(SETUP), /Recent changes[\s\S]*Switched Affective \(conduct\) on <span class="hint">by Tunde Alabi/);
  assert.match(states.shape(SETUP), /class="when">2026-10-20 14:05</);
  assert.doesNotMatch(states.shape({ ...SETUP, conduct: { ...CONDUCT, changes: [] } }), /Recent changes/);
});

test("nobody but the office is sent the block, so a page without it draws no section", () => {
  assert.doesNotMatch(states.shape({ terms: [], classes: [] }), /Affective/);
});

test("a refusal's sentence sits under its own section", () => {
  const html = states.shape({
    ...SETUP,
    notes: { conduct_affective: { kind: "rejected", detail: "A trait needs a name." } },
  });

  assert.match(html, /data-group="affective"[\s\S]*A trait needs a name\.[\s\S]*data-group="psychomotor"/);
});

test("a name from the school is escaped", () => {
  const html = states.shape({
    ...SETUP,
    conduct: { ...CONDUCT, sections: [{ ...CONDUCT.sections[0], traits: [trait(1, '"><img src=x>')] }] },
  });
  assert.doesNotMatch(html, /<img src=x>/);
});

test("movedOrder swaps with the neighbour, sends the hidden ones too, and stops at the ends", () => {
  const state = { conduct: CONDUCT };
  assert.deepEqual(movedOrder(state, "affective", 2, -1), [2, 1, 3]);
  assert.deepEqual(movedOrder(state, "affective", 1, 1), [2, 1, 3]);
  assert.equal(movedOrder(state, "affective", 1, -1), null);
  assert.equal(movedOrder(state, "affective", 3, 1), null);
  assert.equal(movedOrder(state, "nothing", 1, 1), null);
});

async function opened(responses) {
  forgetToken();
  const { calls, fetchImpl } = recording(responses);
  const root = fakeRoot({});
  await mount(root, { fetchImpl });
  calls.length = 0;
  return { root, calls };
}

test("a switch is saved as it is flipped, then the page reloads", async () => {
  const { root, calls } = await opened();

  await root.change({ "data-switch": "psychomotor" }, "", { checked: true });

  assert.equal(calls[0].method, "PUT");
  assert.equal(calls[0].url, "/api/results/report-card/conduct/psychomotor/enabled/");
  assert.deepEqual(calls[0].body, { enabled: true });
  assert.equal(calls[1].url, "/api/academics/setup/");
});

test("renaming sends the new name; leaving it as it was sends nothing", async () => {
  const { root, calls } = await opened();

  await root.change({ "data-trait-name": "1" }, "Punctuality");
  assert.equal(calls.length, 0);

  await root.change({ "data-trait-name": "1" }, "Time-keeping");
  assert.equal(calls[0].url, "/api/results/report-card/conduct/traits/1/");
  assert.deepEqual(calls[0].body, { name: "Time-keeping" });
});

test("Hide and Show send the flag, and an up button sends the whole new order", async () => {
  const { root, calls } = await opened();

  await root.click({ "data-action": "hide-trait", "data-trait": "1" });
  await root.click({ "data-action": "show-trait", "data-trait": "3" });
  await root.click({ "data-action": "move-up", "data-group": "affective", "data-trait": "2" });
  await root.click({ "data-action": "move-up", "data-group": "affective", "data-trait": "1" });

  const writes = calls.filter((c) => c.method === "PUT");
  assert.deepEqual(writes[0].body, { hidden: true });
  assert.deepEqual(writes[1].body, { hidden: false });
  assert.equal(writes[2].url, "/api/results/report-card/conduct/affective/order/");
  assert.deepEqual(writes[2].body, { trait_ids: [2, 1, 3] });
  assert.equal(writes.length, 3, "the first trait cannot move up, so nothing is sent");
});

test("adding a trait posts its name to its own section", async () => {
  const { root, calls } = await opened();

  await root.submit({ name: "Kindness" }, { form: "add-trait", group: "psychomotor" });

  assert.equal(calls[0].method, "POST");
  assert.equal(calls[0].url, "/api/results/report-card/conduct/psychomotor/traits/");
  assert.deepEqual(calls[0].body, { name: "Kindness" });
});

test("a scale word is saved against its number", async () => {
  const { root, calls } = await opened();

  await root.change({ "data-scale": "4" }, "Very Good");

  assert.equal(calls[0].url, "/api/results/report-card/conduct/scale/4/");
  assert.deepEqual(calls[0].body, { label: "Very Good" });
});

test("a 422 keeps the sentence under the section and does not reload", async () => {
  const { root, calls } = await opened({
    "POST /api/results/report-card/conduct/affective/traits/": { status: 422, body: { detail: "A trait needs a name." } },
  });

  await root.submit({ name: " " }, { form: "add-trait", group: "affective" });

  assert.equal(calls.filter((c) => c.url === "/api/academics/setup/").length, 0);
  assert.match(root.innerHTML, /A trait needs a name\./);
});
