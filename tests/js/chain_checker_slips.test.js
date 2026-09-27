/**
 * Result-checker slips on the chain page: docs/messaging.md D11.
 *
 * "Print checker slips" posts once and the answer is a PDF, which is saved and
 * never kept by the page; "Replace a lost slip" does the same for one admission
 * number, and says first that the old PIN stops working. Every test that clicks
 * a button first asserts the button was drawn, because the fake DOM's click
 * needs only the attributes, not the markup.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { printSlips, slipsUrl } from "../../static/results/api.js";
import { mount } from "../../static/results/app.js";
import * as states from "../../static/results/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const released = (over = {}) => ({
  class_group_id: 11,
  class_group: "JSS 1A",
  sheet_id: 5,
  state: "released",
  state_label: "Released",
  may_submit: false,
  may_check: false,
  may_approve: false,
  may_release: false,
  may_send_back: false,
  may_tell_families: false,
  families_told: null,
  may_print_slips: true,
  slips_printed: 0,
  ...over,
});

const CHAIN = { term_id: 7, term: "2025/2026 First term", rows: [released()] };
const SLIPS = "/api/results/chain/11/checker-slips/";
const PDF = { size: 2048, type: "application/pdf" };
const DISPOSITION = 'attachment; filename="checker-slips-jss-1a-first-term-20252026.pdf"';

/** A PDF answer: `blob()` and a `Content-Disposition`, as a real response has. */
function pdf() {
  return {
    status: 200,
    headers: { get: (name) => (name === "Content-Disposition" ? DISPOSITION : null) },
    blob: async () => PDF,
    json: async () => {
      throw new SyntaxError("a PDF is not JSON");
    },
  };
}

function json(status, body) {
  return { status, headers: { get: () => null }, json: async () => body };
}

/** Routes by URL, recording each call; `/api/csrf/` always answers a token. */
function serve(routes, calls = []) {
  let tokens = 0;
  return async (url, options = {}) => {
    if (url === "/api/csrf/") {
      tokens += 1;
      return json(200, { csrf_token: `t${tokens}` });
    }
    for (const [match, answer] of routes) {
      if (url === match) {
        calls.push({ method: options.method || "GET", url, ...options });
        return typeof answer === "function" ? answer(options) : answer;
      }
    }
    throw new Error(`no stub for ${url}`);
  };
}

const posts = (calls) => calls.filter((call) => call.method === "POST" && call.url === SLIPS);

// -- what the row offers -------------------------------------------------------

test("a released row the principal may print for offers the button and says how many have one", () => {
  const html = states.chain({ ...CHAIN, rows: [released({ slips_printed: 3 })] });

  assert.match(html, /data-action="print-slips" data-class="11">Print checker slips</);
  assert.match(html, /Result-checker slips printed for 3 children\./);
  assert.match(states.chain({ ...CHAIN, rows: [released({ slips_printed: 1 })] }), /printed for 1 child\./);
  assert.match(states.chain(CHAIN), /No result-checker slips printed yet\./);
});

test("replacing a lost slip says, before it is pressed, that the old PIN stops working", () => {
  const html = states.chain(CHAIN);

  assert.match(html, /<form class="lost-slip-form" data-class="11">/);
  assert.match(html, /name="admission_number"/);
  assert.match(html, /The old slip&#39;s PIN stops working\.|The old slip's PIN stops working\./);
});

test("nobody else is offered either", () => {
  const html = states.chain({ ...CHAIN, rows: [released({ may_print_slips: false, slips_printed: null })] });

  assert.doesNotMatch(html, /print-slips/);
  assert.doesNotMatch(html, /lost-slip-form/);
  assert.doesNotMatch(html, /checker slips/i);
});

// -- the request ---------------------------------------------------------------

test("the class's slips: one POST with the token and no admission number, and the file comes back", async () => {
  forgetToken();
  const calls = [];
  const result = await printSlips({ classGroupId: 11, fetchImpl: serve([[SLIPS, pdf()]], calls) });

  assert.equal(slipsUrl(11), SLIPS);
  assert.deepEqual(result, { ok: true, blob: PDF, filename: "checker-slips-jss-1a-first-term-20252026.pdf" });
  assert.equal(posts(calls).length, 1);
  assert.equal(posts(calls)[0].headers["X-CSRFToken"], "t1");
  assert.equal(posts(calls)[0].credentials, "same-origin");
  assert.deepEqual(JSON.parse(posts(calls)[0].body), {});
});

test("a lost slip names the child by admission number", async () => {
  forgetToken();
  const calls = [];
  await printSlips({ classGroupId: 11, admissionNumber: "SM/001", fetchImpl: serve([[SLIPS, pdf()]], calls) });

  assert.deepEqual(JSON.parse(posts(calls)[0].body), { admission_number: "SM/001" });
});

test("a refusal is its sentence, for the row", async () => {
  forgetToken();
  const every = "Every child in this class already has a slip. To replace a lost one, give that child's admission number.";
  for (const status of [403, 409, 422]) {
    const result = await printSlips({
      classGroupId: 11,
      fetchImpl: serve([[SLIPS, json(status, { detail: every })]]),
    });
    assert.deepEqual(result, { ok: false, status, detail: every }, `status ${status}`);
  }
});

test("a stale token is fetched again and the press retried once, not until it works", async () => {
  forgetToken();
  const calls = [];
  let presses = 0;
  const result = await printSlips({
    classGroupId: 11,
    fetchImpl: serve([[SLIPS, () => (++presses === 1 ? json(403, { code: "csrf_failed", detail: "stale" }) : pdf())]], calls),
  });

  assert.equal(result.ok, true);
  assert.equal(posts(calls).length, 2);
  assert.equal(posts(calls)[1].headers["X-CSRFToken"], "t2");

  forgetToken();
  const again = [];
  const refused = await printSlips({
    classGroupId: 11,
    fetchImpl: serve([[SLIPS, json(403, { code: "csrf_failed", detail: "stale" })]], again),
  });
  assert.equal(posts(again).length, 2, "a third press against a refusing route");
  assert.equal(refused.ok, false);
});

test("a lapsed session is the page's refusal, not a note on the row", async () => {
  forgetToken();
  const result = await printSlips({
    classGroupId: 11,
    fetchImpl: serve([[SLIPS, json(401, { code: "session_expired", detail: "Your session has ended." })]]),
  });

  assert.equal(result.ok, false);
  assert.equal(result.refusal, "expired");
});

// -- the page, driven ----------------------------------------------------------

test("pressing it saves the file, then fetches the rows again for the count", async () => {
  forgetToken();
  const calls = [];
  const saved = [];
  let printed = false;
  const root = fakeRoot({});
  await mount(root, {
    download: (blob, filename) => saved.push([blob, filename]),
    fetchImpl: serve([
      [SLIPS, () => {
        printed = true;
        return pdf();
      }],
      ["/api/results/chain/", () => json(200, { ...CHAIN, rows: [released({ slips_printed: printed ? 4 : 0 })] })],
    ], calls),
  });
  assert.match(root.innerHTML, /data-action="print-slips"/);

  await root.click({ "data-action": "print-slips", "data-class": "11" });

  assert.equal(posts(calls).length, 1);
  assert.deepEqual(saved, [[PDF, "checker-slips-jss-1a-first-term-20252026.pdf"]]);
  assert.match(root.innerHTML, /The slips are downloading as checker-slips-jss-1a-first-term-20252026\.pdf\./);
  assert.match(root.innerHTML, /Result-checker slips printed for 4 children\./);
});

test("a refusal is a sentence on the row, saves nothing and leaves the chain up", async () => {
  forgetToken();
  const saved = [];
  const every = "Every child in this class already has a slip. To replace a lost one, give that child's admission number.";
  const root = fakeRoot({});
  await mount(root, {
    download: (...args) => saved.push(args),
    fetchImpl: serve([
      [SLIPS, json(409, { detail: every })],
      ["/api/results/chain/", json(200, CHAIN)],
    ]),
  });

  await root.click({ "data-action": "print-slips", "data-class": "11" });

  assert.deepEqual(saved, []);
  assert.match(root.innerHTML, /data-state="chain"/);
  assert.match(root.innerHTML, /Every child in this class already has a slip\./);
});

test("the lost-slip form posts the admission number typed, for its own class", async () => {
  forgetToken();
  const calls = [];
  const saved = [];
  const root = fakeRoot({});
  await mount(root, {
    download: (...args) => saved.push(args),
    fetchImpl: serve([
      [SLIPS, pdf()],
      ["/api/results/chain/", json(200, CHAIN)],
    ], calls),
  });
  assert.match(root.innerHTML, /lost-slip-form/);

  const prevented = await root.submit({ class_group_id: "11", admission_number: "SM/001" });

  assert.equal(prevented, true);
  assert.deepEqual(JSON.parse(posts(calls)[0].body), { admission_number: "SM/001" });
  assert.equal(saved.length, 1);
});

test("the send-back form is still the send-back form", async () => {
  forgetToken();
  const calls = [];
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/api/results/chain/11/send-back/", json(409, { detail: "moved" })],
      ["/api/results/chain/", json(200, CHAIN)],
    ], calls),
  });

  await root.click({ "data-action": "ask-send-back", "data-class": "11" });
  await root.submit({ reason: "Fix JSS 1A's maths" });

  assert.deepEqual(posts(calls), [], "a send-back was sent as a slip");
  assert.ok(calls.some((call) => call.url.endsWith("/send-back/")));
});
