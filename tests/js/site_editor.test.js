/**
 * The website editor (`static/site-editor/`, `docs/school-sites.md` PR 4).
 *
 * What it walks is `schoolsite/api.py`'s answer set: one overview read, every write answering
 * with the whole overview, a 422 sentence to print under the form it came from, a 409 for a
 * save based on somebody else's older change (with a Reload), a 403 for anybody who may not, a
 * 404 off a school's host, and a 401 that is two states.
 *
 * And what it promises a person: each form has its own Save and nothing is kept in the browser,
 * so leaving a form with edits asks first; removing asks twice; publishing has its own confirm
 * screen and names the draft the principal confirmed; the Ready button is the delegated
 * administrator's; news and gallery are offered as "coming soon", never as something to add.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { footerFrom, fromOverview, htmlFor, mount, moved, valuesOf } from "../../static/site-editor/app.js";
import { REFUSAL, classify, refusalFor } from "../../static/site-editor/api.js";
import { collect, fields, summary } from "../../static/site-editor/forms.js";
import * as states from "../../static/site-editor/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const kinds = (extra = []) => [
  { kind: "hero", label: "Hero", available: true, hint: "" },
  { kind: "text", label: "Text", available: true, hint: "" },
  ...extra,
];

const page = (ref, over = {}) => ({
  key: ref === "boarding" ? "" : ref, kind: ref === "boarding" ? "custom" : "fixed", slug: ref === "boarding" ? "boarding" : "",
  ref, label: ref[0].toUpperCase() + ref.slice(1), title: ref === "boarding" ? "Boarding" : "", description: "",
  path: ref === "home" ? "/" : ref === "boarding" ? "/pages/boarding/" : `/${ref}/`,
  preview: ref === "home" ? "/website/preview/" : `/website/preview/${ref === "boarding" ? "pages/boarding" : ref}/`,
  enabled: ref === "home", version: 1, menu_position: 0, address_fixed: ref !== "boarding", sections: [], kinds: kinds(),
  ...over,
});

const OVERVIEW = {
  role: "principal", can_edit: true, can_publish: true, delegated: false, school: "St Mary's <College>",
  state: { published: true, revision: 2, published_at: "2026-10-30T10:00:00Z", published_by: "Rev. Sr. Okafor",
    changes: true, ready: false, ready_by: "", ready_at: null, draft_version: 7 },
  version: 3, colour: "", card_colour: "#143D8C", footer: { address_line: "Off Ring Road", social: [] },
  networks: ["facebook", "instagram"], preview: "/website/preview/",
  pages: [
    page("home", { sections: [{ id: 11, kind: "hero", variant: "plain", version: 2, data: { heading: "Welcome", buttons: [], image: 5 } },
      { id: 12, kind: "text", variant: "default", version: 1, data: { heading: "", body: "Hello" } }],
    kinds: kinds([{ kind: "news", label: "News", available: false, hint: "Coming soon: news arrives in a later update." }]) }),
    page("about"),
    page("boarding"),
  ],
  log: [
    { kind: "published", revision: 2, rollback_of: null, note: "", by: "Rev. Sr. Okafor", at: "2026-10-30T10:00:00Z" },
    { kind: "published", revision: 1, rollback_of: null, note: "First", by: "Rev. Sr. Okafor", at: "2026-10-29T10:00:00Z" },
  ],
};

const ADMIN = { ...OVERVIEW, role: "admin", can_publish: false, delegated: true };

function serve(routes) {
  return async (url, options = {}) => {
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    for (const [match, answer] of routes) {
      if (url.includes(match) && (!answer.method || answer.method === (options.method || "GET"))) {
        const value = typeof answer.reply === "function" ? answer.reply(options, url) : answer;
        return { status: value.status, json: async () => value.body };
      }
    }
    throw new Error(`no stub for ${options.method || "GET"} ${url}`);
  };
}

const opened = async (routes = [], body = OVERVIEW, { ask = () => true } = {}) => {
  forgetToken();
  const root = fakeRoot({ portal: "app.example.test" });
  const app = await mount(root, {
    fetchImpl: serve([...routes, ["/api/website/", { status: 200, body, method: "GET" }]]), ask, win: { addEventListener() {} },
  });
  return { root, app };
};

// -- the answers -------------------------------------------------------------

test("each answer is the overview, a sentence to print, a stale save to reload, or a refusal", () => {
  assert.equal(classify({ status: 200, body: OVERVIEW }).ok, true);
  assert.deepEqual(classify({ status: 422, body: { detail: "No." } }), { ok: false, rejected: true, stale: false, body: { detail: "No." } });
  assert.equal(classify({ status: 409, body: { detail: "Reload." } }).stale, true);
  assert.equal(refusalFor(403), REFUSAL.NOT_YOURS);
  assert.equal(refusalFor(404), REFUSAL.WRONG_HOST);
  assert.equal(refusalFor(401, { code: "session_expired" }), REFUSAL.EXPIRED);
  assert.equal(refusalFor(401, {}), REFUSAL.SIGNED_OUT);
  assert.equal(refusalFor(500), REFUSAL.BROKEN);
});

test("every refusal has its own screen, and none of them is the editor", () => {
  assert.match(htmlFor({ step: REFUSAL.NOT_YOURS }), /looked after by its principal/);
  assert.match(htmlFor({ step: REFUSAL.WRONG_HOST }), /school&#39;s own address/);
  assert.match(htmlFor({ step: REFUSAL.SIGNED_OUT }, { portal: "app.example.test" }), /href="\/\/app.example.test\/staff-sign-in\/"/);
  assert.match(htmlFor({ step: REFUSAL.EXPIRED }), /signed out after a while/);
  assert.match(htmlFor({ step: REFUSAL.BROKEN }), /Try again/);
});

// -- the first screen ---------------------------------------------------------

test("the principal sees the state, Publish while there are changes, the pages, the colour and who edits", () => {
  const html = htmlFor(fromOverview({ ok: true, body: OVERVIEW }));
  assert.match(html, /Published<\/strong> Version 2/);
  assert.match(html, /Changes not yet published/);
  assert.match(html, /data-action="publish"/);
  assert.doesNotMatch(html, /Ready for the principal/, "the principal has Publish, not Ready");
  assert.match(html, /data-form="add-page"/);
  assert.match(html, /data-form="colour"/);
  assert.match(html, /data-action="delegation"/);
  assert.match(html, /Go back to version 1/);
  assert.doesNotMatch(html, /Go back to version 2/, "the live version is not offered");
  assert.match(html, /<span class="standing">Always on<\/span>/);
  assert.doesNotMatch(html, /data-action="page-up" data-ref="home"/, "Home never moves");
});

test("with nothing to publish there is no Publish, and an unpublished site says so", () => {
  const same = htmlFor(fromOverview({ ok: true, body: { ...OVERVIEW, state: { ...OVERVIEW.state, changes: false } } }));
  assert.doesNotMatch(same, /data-action="publish"/);
  assert.match(same, /The draft is what is live/);
  const never = htmlFor(fromOverview({ ok: true, body: { ...OVERVIEW, state: { published: false, changes: true, draft_version: 1 } } }));
  assert.match(never, /Draft<\/strong> Not published yet/);
});

test("the delegated administrator has Ready for the principal and none of the principal's", () => {
  const html = htmlFor(fromOverview({ ok: true, body: ADMIN }));
  assert.match(html, /data-form="ready"/);
  assert.doesNotMatch(html, /data-action="publish"|data-form="colour"|data-action="delegation"|Go back to version/);
  const told = htmlFor({ ...fromOverview({ ok: true, body: { ...ADMIN, state: { ...ADMIN.state, ready: true, ready_by: "Ade" } } }), told: 0 });
  assert.match(told, /no email address on file/);
  assert.match(told, /Marked ready for the principal by Ade/);
  assert.doesNotMatch(told, /data-form="ready"/);
});

test("an administrator not allowed to edit sees the history and why there is nothing to edit", () => {
  const html = htmlFor(fromOverview({ ok: true, body: { ...ADMIN, can_edit: false, pages: [] } }));
  assert.match(html, /has not let you edit/);
  assert.doesNotMatch(html, /data-form="add-page"|data-form="ready"/);
  assert.match(html, /History/);
});

test("whatever a school wrote is printed as text", () => {
  const hostile = { ...OVERVIEW, pages: [page("home"), page("boarding", { label: "<img src=x onerror=alert(1)>" })] };
  const html = htmlFor(fromOverview({ ok: true, body: hostile }));
  assert.doesNotMatch(html, /<img src=x/);
  assert.match(html, /&lt;img src=x/);
  assert.match(states.confirmPublish(OVERVIEW), /St Mary&#39;s &lt;College&gt;/);
});

// -- a page and its sections --------------------------------------------------

test("a page lists its sections, offers its kinds, and news is coming soon, never added", () => {
  const html = states.page(OVERVIEW, "home");
  assert.match(html, /<option value="hero">Hero<\/option>/);
  assert.match(html, /<option value="news" disabled data-description="Coming soon: news arrives in a later update.">News \(coming soon\)<\/option>/);
  assert.match(html, /data-action="edit-section" data-id="11"/);
  assert.match(html, /data-action="section-up" data-id="11" disabled/);
  assert.match(html, /data-action="section-down" data-id="12" disabled/);
  assert.doesNotMatch(html, /Delete this page/, "a fixed page is never deleted");
  assert.match(states.page(OVERVIEW, "boarding"), /Delete this page/);
  assert.match(states.page(OVERVIEW, "boarding"), /name="slug"/, "an address not yet fixed can change");
  assert.doesNotMatch(states.page(OVERVIEW, "about"), /name="slug"/);
});

test("a full page offers no Add", () => {
  const full = { ...OVERVIEW, pages: [page("home", { sections: Array.from({ length: 15 }, (_, i) => ({ id: i + 1, kind: "text", version: 1, data: { body: "x" } })) })] };
  assert.match(states.page(full, "home"), /<button type="submit" disabled>Add<\/button>/);
});

// -- the forms ----------------------------------------------------------------

test("each kind's form reads back as the data the server checks", () => {
  assert.deepEqual(
    collect("hero", {
      heading: "Welcome", subheading: "", button1_label: "Apply", button1_link: "/admissions/",
      button2_label: "Call", button2_link: "other", button2_link_other: " tel:+2348031112222 ",
    }, { image: 5, focal: { x: 0.5, y: 0.5 } }),
    { heading: "Welcome", subheading: "", buttons: [{ label: "Apply", link: "/admissions/" }, { label: "Call", link: "tel:+2348031112222" }],
      image: 5, focal: { x: 0.5, y: 0.5 } },
    "a picture it does not show yet is kept",
  );
  assert.deepEqual(collect("facts", { fact1_figure: "98%", fact1_label: "WAEC credits", fact2_figure: "", fact2_label: "" }).items,
    [{ figure: "98%", label: "WAEC credits", source: "" }]);
  assert.deepEqual(collect("crest_motto", { motto: "Lux", language: "la", translation: "", founded: "" }),
    { motto: "Lux", language: "la", translation: "" }, "a blank year is left out");
  assert.deepEqual(collect("admissions_cta", { heading: "Places", text: "", button: "", link: "/pages/boarding/", session: "", open: false, closes: "" }),
    { heading: "Places", text: "", button: "", link: "/pages/boarding/", session: "", open: false, closes: "" });
  assert.equal(collect("contact_map", { latitude: "6.45", longitude: "" }).latitude, 6.45);
});

test("a form is drawn filled, with pictures said to be coming later", () => {
  const pages = [{ path: "/", label: "Home" }, { path: "/pages/boarding/", label: "Boarding" }];
  const hero = fields("hero", { heading: "Welcome", buttons: [{ label: "Boarding", link: "/pages/boarding/" }, { label: "Out", link: "https://x.example/" }] }, { pages });
  assert.match(hero, /value="Welcome"/);
  assert.match(hero, /<option value="\/pages\/boarding\/" selected>Boarding<\/option>/);
  assert.match(hero, /<option value="other" selected>Another address<\/option>/);
  assert.match(hero, /value="https:\/\/x.example\/"/);
  assert.match(hero, /Pictures and video come in a later update/);
  assert.match(fields("admissions_cta", { open: true }, { pages }), /type="checkbox" name="open" checked/);
  assert.doesNotMatch(fields("admissions_cta", {}, { pages }), /Another address/, "the admissions button stays on the site");
  assert.equal(summary("facts", { items: [{}, {}] }), "2 facts");
});

test("a form's values are read from its fields, a checkbox as ticked or not", () => {
  assert.deepEqual(valuesOf({ elements: [{ name: "a", value: "x" }, { name: "open", type: "checkbox", checked: true }, { value: "no name" }] }),
    { a: "x", open: true });
  assert.deepEqual(footerFrom({ address_line: "Ibadan", social_facebook: " https://facebook.com/s ", social_instagram: "" }, ["facebook", "instagram"]),
    { address_line: "Ibadan", social: [{ network: "facebook", url: "https://facebook.com/s" }] });
  assert.deepEqual(moved(["home", "about", "boarding"], 2, -1), ["home", "boarding", "about"]);
  assert.equal(moved(["home"], 0, -1), null);
});

// -- what the page does -------------------------------------------------------

test("switching a page on saves at once and redraws from the answer", async () => {
  const calls = [];
  const after = { ...OVERVIEW, pages: [OVERVIEW.pages[0], page("about", { enabled: true, version: 2 }), OVERVIEW.pages[2]] };
  const { root } = await opened([["/api/website/pages/about/", { method: "PUT", reply: (o) => { calls.push(JSON.parse(o.body)); return { status: 200, body: after }; } }]]);
  await root.change({ "data-action": "switch-page", "data-ref": "about" }, "", { checked: true });
  assert.deepEqual(calls, [{ version: 1, enabled: true }]);
  assert.match(root.innerHTML, /data-action="switch-page" data-ref="about" checked/);
});

test("leaving a form with unsaved edits asks first, and staying keeps the form", async () => {
  const asked = [];
  let answer = false;
  const { root, app } = await opened([], OVERVIEW, { ask: (q) => { asked.push(q); return answer; } });
  await root.click({ "data-action": "open-page", "data-ref": "home" });
  await root.click({ "data-action": "edit-section", "data-id": "12" });
  assert.equal(app.current().editing.id, 12);
  await root.input({ "data-tracked": "" }, "typed");
  assert.equal(app.isDirty(), true);
  await root.click({ "data-action": "cancel" });
  assert.deepEqual(asked, [states.UNSAVED]);
  assert.equal(app.current().editing.id, 12, "said stay: the form is still open");
  answer = true;
  await root.click({ "data-action": "cancel" });
  assert.equal(app.current().editing, null);
  assert.equal(app.isDirty(), false);
});

test("nothing asks when nothing was typed", async () => {
  const asked = [];
  const { root } = await opened([], OVERVIEW, { ask: (q) => { asked.push(q); return false; } });
  await root.click({ "data-action": "open-page", "data-ref": "home" });
  await root.click({ "data-action": "back" });
  assert.deepEqual(asked, []);
});

test("a section's Save sends its data and its version, and a refusal keeps the edits", async () => {
  const sent = [];
  const { root, app } = await opened([
    ["/api/website/sections/12/", { method: "PUT", reply: (o) => { sent.push(JSON.parse(o.body)); return { status: 422, body: { detail: "The text cannot be empty." } }; } }],
  ]);
  await root.click({ "data-action": "open-page", "data-ref": "home" });
  await root.click({ "data-action": "edit-section", "data-id": "12" });
  await root.submit({ heading: "", body: "" }, { form: "section", kind: "text" });
  assert.deepEqual(sent, [{ version: 1, data: { heading: "", body: "" } }]);
  assert.equal(app.current().editing.id, 12, "still on the form");
  assert.match(root.innerHTML, /The text cannot be empty/);
});

test("a stale save says so with a Reload", async () => {
  const { root } = await opened([
    ["/api/website/pages/", { method: "POST", status: 409, body: { detail: "Somebody else changed this since you opened it." } }],
  ]);
  await root.submit({ title: "Sports", slug: "" }, { form: "add-page" });
  assert.match(root.innerHTML, /Somebody else changed this[\s\S]*data-action="reload"/);
});

test("removing a section asks twice; the first tap sends nothing", async () => {
  const calls = [];
  const { root } = await opened([
    ["/api/website/sections/12/", { method: "DELETE", reply: (o, url) => { calls.push(url); return { status: 200, body: OVERVIEW }; } }],
  ]);
  await root.click({ "data-action": "open-page", "data-ref": "home" });
  await root.click({ "data-action": "remove-section", "data-id": "12" });
  assert.deepEqual(calls, []);
  assert.match(root.innerHTML, /Remove it/);
  await root.click({ "data-action": "remove-section", "data-id": "12", "data-sure": "1" });
  assert.deepEqual(calls, ["/api/website/sections/12/?version=1"]);
});

test("Publish has its own confirm screen and sends the draft the principal confirmed", async () => {
  const sent = [];
  const published = { ...OVERVIEW, state: { ...OVERVIEW.state, revision: 3, changes: false } };
  const { root, app } = await opened([
    ["/api/website/publish/", { method: "POST", reply: (o) => { sent.push(JSON.parse(o.body)); return { status: 200, body: published }; } }],
  ]);
  await root.click({ "data-action": "publish" });
  assert.match(root.innerHTML, /Publish the website\?/);
  assert.deepEqual(sent, [], "nothing is published by the first tap");
  await root.submit({ note: "Admissions open" }, { form: "publish" });
  assert.deepEqual(sent, [{ draft_version: 7, note: "Admissions open" }]);
  assert.equal(app.current().confirming, null);
  assert.match(root.innerHTML, /Version 3/);
});

test("going back to an earlier version has its own confirm screen", async () => {
  const sent = [];
  const { root } = await opened([
    ["/api/website/rollback/", { method: "POST", reply: (o) => { sent.push(JSON.parse(o.body)); return { status: 200, body: OVERVIEW }; } }],
  ]);
  await root.click({ "data-action": "rollback", "data-number": "1" });
  assert.match(root.innerHTML, /Go back to version 1\?/);
  await root.submit({ note: "Too soon" }, { form: "rollback", number: "1" });
  assert.deepEqual(sent, [{ number: 1, note: "Too soon" }]);
});

test("moving a page sends the whole order with Home still first", async () => {
  const sent = [];
  const { root } = await opened([
    ["/api/website/menu/", { method: "PUT", reply: (o) => { sent.push(JSON.parse(o.body)); return { status: 200, body: OVERVIEW }; } }],
  ]);
  await root.click({ "data-action": "page-up", "data-ref": "boarding" });
  assert.deepEqual(sent, [{ version: 3, order: ["home", "boarding", "about"] }]);
  await root.click({ "data-action": "page-up", "data-ref": "about" });
  assert.equal(sent.length, 1, "nothing goes above Home");
});

test("the delegated administrator's Ready says the principal was emailed, or was not", async () => {
  const marked = { ...ADMIN, state: { ...ADMIN.state, ready: true, ready_by: "Ade" } };
  const { root } = await opened([
    ["/api/website/ready/", { method: "POST", status: 200, body: { ...marked, told: 1 } }],
  ], ADMIN);
  await root.submit({ note: "Please look" }, { form: "ready" });
  assert.match(root.innerHTML, /We have emailed the principal a link to the preview/);
});
