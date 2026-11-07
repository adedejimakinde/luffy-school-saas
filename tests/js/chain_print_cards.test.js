/**
 * "Print report cards" on the chain page: docs/class-print.md.
 *
 * The button is drawn from the row's own `may_print_cards`; pressing it asks
 * who could be printed and says first when the file will be a preview; the
 * form posts the children ticked (none for the whole class); the page then
 * asks how the job is getting on until it is ready and offers the download.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { printCardsUrl, printJobUrl } from "../../static/results/api.js";
import { mount } from "../../static/results/app.js";
import * as states from "../../static/results/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const row = (over = {}) => ({
  class_group_id: 11,
  class_group: "JSS 1A",
  sheet_id: 5,
  state: "draft",
  state_label: "Draft",
  may_print_cards: true,
  ...over,
});

const CHAIN = { term_id: 7, term: "2025/2026 First term", rows: [row()] };
const PRINTABLE = {
  class_group_id: 11,
  class_group: "JSS 1A",
  term_id: 7,
  term: "First term",
  preview: true,
  children: [
    { student_membership_id: 3, name: "Ada Obi" },
    { student_membership_id: 4, name: "Bola Eze" },
  ],
};
const job = (over = {}) => ({
  id: 9,
  state: "pending",
  state_label: "Waiting to start",
  class_group: "JSS 1A",
  term: "First term",
  done: 0,
  total: 1,
  preview: null,
  card_count: null,
  created_at: "2026-11-07T10:00:00Z",
  expires_at: null,
  download_url: null,
  detail: "Waiting to start. This page will show progress.",
  ...over,
});

function json(status, body) {
  return { status, headers: { get: () => null }, json: async () => body };
}

/** A fetch that answers by URL and method, and remembers what it was sent. */
function server(answers) {
  const sent = [];
  const fetchImpl = async (url, options = {}) => {
    const method = options.method || "GET";
    sent.push({ url, method, body: options.body ? JSON.parse(options.body) : null });
    if (url === "/api/csrf/") return json(200, { csrf_token: "t" });
    const key = `${method} ${url}`;
    const queue = answers[key];
    if (!queue || !queue.length) throw new Error(`nothing to answer ${key}`);
    return queue.length > 1 ? queue.shift() : queue[0];
  };
  return { fetchImpl, sent };
}

test("the button is drawn only for a row that may print", () => {
  assert.match(states.chain({ ...CHAIN, rows: [row()] }), /data-action="ask-print-cards"/);
  assert.doesNotMatch(states.chain({ ...CHAIN, rows: [row({ may_print_cards: false })] }), /ask-print-cards/);
});

test("the panel says a preview is a preview before anything is made", () => {
  const html = states.printCards(row(), { class_group_id: 11, ...PRINTABLE, chosen: [], job: null });
  assert.match(html, /PREVIEW, NOT RELEASED/);
  assert.match(html, /Tick none to print the whole class \(2 cards\)/);
  assert.match(html, /data-print-child="3"/);
  const released = states.printCards(row(), { class_group_id: 11, ...PRINTABLE, preview: false, chosen: [], job: null });
  assert.doesNotMatch(released, /PREVIEW/);
});

test("ticked children are sent, the job is watched, and the file is offered", async () => {
  forgetToken();
  const { fetchImpl, sent } = server({
    "GET /api/results/chain/": [json(200, CHAIN)],
    [`GET ${printCardsUrl(11, 7)}`]: [json(200, PRINTABLE)],
    [`POST ${printCardsUrl(11, 7)}`]: [json(202, job())],
    [`GET ${printJobUrl(9)}`]: [
      json(200, job({ state: "building", done: 0, detail: "Making the cards: 0 of 1 done." })),
      json(
        200,
        job({
          state: "ready",
          done: 1,
          preview: true,
          card_count: 1,
          download_url: "/api/results/print-jobs/9/pdf/",
          detail: "1 report card ready, as a preview.",
        }),
      ),
    ],
  });
  let waits = 0;
  const root = fakeRoot();
  await mount(root, { fetchImpl, wait: async () => { waits += 1; } });

  assert.match(root.innerHTML, /Print report cards/);
  await root.click({ "data-action": "ask-print-cards", "data-class": "11" });
  assert.match(root.innerHTML, /PREVIEW, NOT RELEASED/);

  await root.change({ "data-print-child": "4" }, "4", { checked: true });
  await root.submit({}, { print: "11" });

  const posted = sent.find((s) => s.method === "POST" && s.url === printCardsUrl(11, 7));
  assert.deepEqual(posted.body, { student_ids: [4] });
  assert.equal(waits, 2, "asked twice: building, then ready");
  assert.match(root.innerHTML, /href="\/api\/results\/print-jobs\/9\/pdf\/"/);
  assert.match(root.innerHTML, /Download the PDF/);
});

test("a refusal is a sentence on the row", async () => {
  forgetToken();
  const { fetchImpl } = server({
    "GET /api/results/chain/": [json(200, CHAIN)],
    [`GET ${printCardsUrl(11, 7)}`]: [json(403, { detail: "Report cards for a class are printed by its class teacher." })],
  });
  const root = fakeRoot();
  await mount(root, { fetchImpl, wait: async () => {} });
  await root.click({ "data-action": "ask-print-cards", "data-class": "11" });
  assert.match(root.innerHTML, /Not printed/);
  assert.match(root.innerHTML, /printed by its class teacher/);
});
