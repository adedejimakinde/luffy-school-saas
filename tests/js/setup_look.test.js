/**
 * The setup page's report-card section: the school's crest and its one colour.
 *
 * What the section draws is a function of `SetUpOut.card`; what it sends is
 * three calls, each asserted against a stub so the shape of the request is
 * pinned: JSON for the colour, the file itself (multipart, with the CSRF
 * header) for the crest, and a DELETE to go back to the initials.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { mount } from "../../static/setup/app.js";
import { removeCrest, saveColour, uploadCrest } from "../../static/setup/api.js";
import * as states from "../../static/setup/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const CARD = { colour: "#7A1F2B", default_colour: "#143D8C", has_crest: false, crest_version: null, initials: "SD" };
const SETUP = { terms: [], classes: [], may_set_up: true, card: CARD };

test("the preview is the card's header on white: the name and rule in its colour, initials with no crest", () => {
  const html = states.shape(SETUP);

  assert.match(html, /<span class="look-name" style="color: #7A1F2B">/);
  assert.match(html, /<div class="look-rule" style="background: #7A1F2B"><\/div>/);
  assert.match(html, /<span class="initials" aria-hidden="true" style="background: #7A1F2B">SD<\/span>/);
  assert.match(html, /<input id="colour" name="colour" type="color" value="#7A1F2B">/);
  assert.doesNotMatch(html, /remove-crest/, "nothing to remove");
});

test("with a crest the preview shows it, versioned, and offers to remove it", () => {
  const html = states.shape({ ...SETUP, card: { ...CARD, has_crest: true, crest_version: "1790000000" } });

  assert.match(html, /<img class="crest-mark" src="\/api\/academics\/card\/crest\/\?v=1790000000"/);
  assert.match(html, /data-action="remove-crest"/);
});

test("the form says what a crest may be before anybody picks one", () => {
  const html = states.shape(SETUP);

  assert.match(html, /accept="image\/png,image\/jpeg"/);
  assert.match(html, /PNG or JPG, up to 1 MB/);
  assert.match(html, /too light to read is refused/);
  assert.doesNotMatch(html, /in white/, "the card no longer prints the name in white");
});

test("a refused colour keeps its sentence under the form", () => {
  const html = states.shape({
    ...SETUP,
    notes: { colour: { kind: "rejected", detail: "#FFFF00 is too light to read on a white page. Choose a darker shade." } },
  });

  assert.match(html, /<form class="colour-form rejected"/);
  assert.match(html, /too light to read on a white page/);
});

test("with no card block the section is not drawn", () => {
  assert.doesNotMatch(states.shape({ terms: [], classes: [] }), /Report card/);
});

function recording(answer = { status: 200, body: CARD }) {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    calls.push({ url, options });
    return { status: answer.status, json: async () => answer.body };
  };
  return { calls, fetchImpl };
}

test("the colour is sent as typed, and the server decides", async () => {
  forgetToken();
  const { calls, fetchImpl } = recording();

  const result = await saveColour({ colour: "#7a1f2b", fetchImpl });

  assert.equal(result.ok, true);
  assert.equal(calls[0].url, "/api/academics/card/colour/");
  assert.equal(calls[0].options.method, "PUT");
  assert.deepEqual(JSON.parse(calls[0].options.body), { colour: "#7a1f2b" });
});

test("a 422 is a sentence to show, not a page-level failure", async () => {
  forgetToken();
  const { fetchImpl } = recording({ status: 422, body: { detail: "too light" } });

  const result = await saveColour({ colour: "#FFFF00", fetchImpl });

  assert.equal(result.ok, false);
  assert.equal(result.outcome, "rejected");
});

test("the crest is sent as the file itself, with the CSRF header", async () => {
  forgetToken();
  const { calls, fetchImpl } = recording();
  const file = new Blob([new Uint8Array([137, 80, 78, 71])], { type: "image/png" });

  await uploadCrest({ file, fetchImpl });

  const { url, options } = calls[0];
  assert.equal(url, "/api/academics/card/crest/");
  assert.equal(options.method, "POST");
  assert.equal(options.headers["X-CSRFToken"], "t");
  assert.ok(options.body instanceof FormData);
  assert.ok(options.body.get("crest"));
  // The browser writes multipart's boundary; a Content-Type set here would break it.
  assert.equal(options.headers["Content-Type"], undefined);
});

test("Remove crest is a DELETE, and the page reloads the look after it", async () => {
  forgetToken();
  const calls = [];
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: async (url, options = {}) => {
      if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
      calls.push({ url, method: options.method || "GET" });
      if (url.startsWith("/api/academics/card/crest/")) return { status: 200, json: async () => ({ ...CARD, has_crest: false }) };
      return { status: 200, json: async () => ({ ...SETUP, card: { ...CARD, has_crest: true, crest_version: "1" } }) };
    },
  });

  await root.click({ "data-action": "remove-crest" });

  assert.deepEqual(
    calls.map((c) => `${c.method} ${c.url}`),
    ["GET /api/academics/setup/", "DELETE /api/academics/card/crest/", "GET /api/academics/setup/"],
  );
});

test("removeCrest classifies a refusal like every other write", async () => {
  forgetToken();
  const { fetchImpl } = recording({ status: 403, body: { detail: "A school's crest and colour are set by its principal or an administrator." } });

  const result = await removeCrest({ fetchImpl });

  assert.equal(result.outcome, "not-allowed");
});

test("the page body has no sign-out: it is not what this page is for", () => {
  assert.doesNotMatch(states.shape(SETUP), /data-action="sign-out"/);
});
