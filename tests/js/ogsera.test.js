/**
 * The OGSERA filler page: choose, map the first time, check, download.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { htmlFor, mount, needsMapping } from "../../static/ogsera/app.js";
import * as states from "../../static/ogsera/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const DOOR = {
  term: "2025/2026 First term",
  fields: [{ key: "learner_id", label: "Learner's ID" }, { key: "exam", label: "Exam" }],
  mapping: [],
  classes: [{ id: 11, name: "JSS 1A" }],
  subjects: [{ id: 3, name: "Mathematics" }],
};

const HEADINGS = { sheet_name: "S", header_row: 5, headings: [
  { column: "B", heading: "Learner ID", field: "" },
  { column: "H", heading: "Exam (70)", field: "" },
] };

const CHECK = {
  sheet_name: "S", header_row: 5, headings: [], unmatched: [], missing_id: [],
  not_in_file: [], no_learner_id: ["Tunde Cole"], missing_values: ["Emeka Nwosu: no Exam"],
  matched: 3, filled: 5, kept: 0, may_download: true,
};

function serve(routes, log = []) {
  return async (url, options = {}) => {
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    for (const [match, answer] of routes) {
      if (url === match || url.endsWith(match)) {
        log.push({ url, options });
        const value = typeof answer === "function" ? answer(options) : answer;
        return {
          status: value.status,
          json: async () => value.body,
          blob: async () => new Blob(["xlsx"]),
          clone() { return this; },
        };
      }
    }
    throw new Error(`no stub for ${url}`);
  };
}

const file = { name: "JSS1A.xlsx" };
const chooseForm = { dataset: { form: "choose" }, file: { files: [file] }, class_group_id: "11", subject_id: "3" };

test("a template with no learner ID column mapped goes to the mapping step", () => {
  assert.equal(needsMapping(HEADINGS.headings), true);
  assert.equal(needsMapping([{ heading: "Learner ID", field: "learner_id" }]), false);
});

test("the first file goes to mapping, then saving checks it", async () => {
  forgetToken();
  const log = [];
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/api/results/ogsera/headings/", { status: 200, body: HEADINGS }],
      ["/api/results/ogsera/mapping/", { status: 200, body: { ...DOOR, mapping: [{ heading: "Learner ID", field: "learner_id" }] } }],
      ["/api/results/ogsera/check/", { status: 200, body: CHECK }],
      ["/api/results/ogsera/", { status: 200, body: DOOR }],
    ], log),
  });

  await root.submit(chooseForm);
  assert.match(root.innerHTML, /data-state="mapping"/);
  assert.match(root.innerHTML, /Learner ID/);

  await root.submit({ dataset: { form: "mapping" }, map_0: "learner_id", map_1: "exam" });

  const saved = log.find((c) => c.url.endsWith("/mapping/"));
  assert.deepEqual(JSON.parse(saved.options.body), { columns: { "Learner ID": "learner_id", "Exam (70)": "exam" } });
  assert.match(root.innerHTML, /data-state="checked"/);
  assert.match(root.innerHTML, /3 rows matched/);
  assert.match(root.innerHTML, /Emeka Nwosu: no Exam/);
});

test("a blocked check offers no download", () => {
  const html = states.checked({
    check: { ...CHECK, may_download: false, unmatched: [{ row: 7, learner_id: "OG/9" }], missing_id: [{ row: 8, name: "X" }] },
  });
  assert.match(html, /Row 7: learner ID OG\/9/);
  assert.match(html, /Row 8: X/);
  assert.match(html, /Download the filled file<\/button>/);
  assert.match(html, /type="submit" disabled>Download/);
});

test("downloading posts the file with replace, and offers the saved file", async () => {
  forgetToken();
  const log = [];
  const root = fakeRoot({});
  const mapped = { ...HEADINGS, headings: [{ column: "B", heading: "Learner ID", field: "learner_id" }] };
  await mount(root, {
    makeUrl: () => "blob:filled",
    fetchImpl: serve([
      ["/api/results/ogsera/headings/", { status: 200, body: mapped }],
      ["/api/results/ogsera/check/", { status: 200, body: CHECK }],
      ["/api/results/ogsera/fill/", { status: 200, body: null }],
      ["/api/results/ogsera/", { status: 200, body: DOOR }],
    ], log),
  });
  await root.submit(chooseForm);
  assert.match(root.innerHTML, /data-state="checked"/);

  await root.submit({ dataset: { form: "fill" }, replace: { checked: true } });

  const fill = log.find((c) => c.url.endsWith("/fill/"));
  assert.equal(fill.options.body.get("replace"), "1");
  assert.equal(fill.options.body.get("class_group_id"), "11");
  assert.match(root.innerHTML, /href="blob:filled" download="JSS1A-filled.xlsx"/);
});

test("a school not on the Ogun card is told where to choose it", async () => {
  forgetToken();
  const root = fakeRoot({});
  await mount(root, { fetchImpl: serve([["/api/results/ogsera/", { status: 409, body: { detail: "Choose it on the setup page first." } }]]) });
  assert.match(root.innerHTML, /part of the Ogun State template/);
  assert.match(root.innerHTML, /href="\/setup\/#report-card"/);
});

test("what a school typed is escaped", () => {
  const html = htmlFor({ step: "mapping", headings: [{ column: "A", heading: "<b>x</b>", field: "" }], fields: [] });
  assert.doesNotMatch(html, /<b>x<\/b>/);
});
