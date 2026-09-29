/**
 * The platform admin screen: the list, the add form, and its refusals.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { fieldsFrom, fromList, htmlFor, mount } from "../../static/platform/app.js";
import { REFUSAL, refusalFor } from "../../static/platform/api.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const SCHOOLS = {
  schools: [
    { name: "St Mary's", subdomain: "st-marys", host: "st-marys.example.org", students: 412, is_active: true, created_on: "2026-01-01" },
    { name: "Grace <b>Academy</b>", subdomain: "grace", host: "grace.example.org", students: 1, is_active: true, created_on: "2026-02-01" },
  ],
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

const FORM = { name: "Hope Academy", subdomain: "hope", admin_name: "", admin_email: "head@hope.example", admin_phone: "" };

test("each school is listed with its student count, and names are escaped", () => {
  const html = htmlFor(fromList({ ok: true, body: SCHOOLS }));

  assert.match(html, /412 students/);
  assert.match(html, /1 student</);
  assert.match(html, /Grace &lt;b&gt;Academy&lt;\/b&gt;/);
  assert.doesNotMatch(html, /<b>Academy/);
  assert.match(html, /name="admin_email"/);
  assert.match(html, /name="admin_phone"/);
});

test("refusals are told apart", () => {
  assert.equal(refusalFor(403, {}), REFUSAL.NOT_ALLOWED);
  assert.equal(refusalFor(404, {}), REFUSAL.WRONG_HOST);
  assert.equal(refusalFor(401, { code: "session_expired" }), REFUSAL.EXPIRED);
  assert.equal(refusalFor(401, {}), REFUSAL.SIGNED_OUT);
  assert.equal(refusalFor(500, {}), REFUSAL.BROKEN);
  assert.match(htmlFor({ step: REFUSAL.NOT_ALLOWED }), /data-state="not-allowed"/);
  assert.match(htmlFor({ step: REFUSAL.WRONG_HOST }), /data-state="wrong-host"/);
  assert.match(htmlFor({ step: REFUSAL.EXPIRED }), /Your session has ended/);
  assert.match(htmlFor({ step: REFUSAL.BROKEN }), /data-state="broken"/);
});

test("a non-platform-staff caller sees the refusal and no list", async () => {
  forgetToken();
  const root = fakeRoot();
  await mount(root, { fetchImpl: serve([["/api/platform/schools/", { status: 403, body: { detail: "no" } }]]) });

  assert.match(root.innerHTML, /data-state="not-allowed"/);
  assert.doesNotMatch(root.innerHTML, /name="subdomain"/);
});

test("fieldsFrom trims what was typed", () => {
  assert.equal(fieldsFrom({ name: { value: "  Hope " } }).name, "Hope");
  assert.equal(fieldsFrom({}).admin_phone, "");
});

test("nothing is posted for a form missing its name, subdomain or a way to reach the administrator", async () => {
  forgetToken();
  const root = fakeRoot();
  let posted = 0;
  const fetchImpl = serve([["/api/platform/schools/", (o) => { if (o.method === "POST") posted += 1; return { status: 200, body: SCHOOLS }; }]]);
  await mount(root, { fetchImpl });

  await root.submit({ ...FORM, name: "" });
  assert.match(root.innerHTML, /needs a name and a subdomain/);
  await root.submit({ ...FORM, admin_email: "", admin_phone: "" });
  assert.match(root.innerHTML, /email or phone/);
  assert.equal(posted, 0);
});

test("adding a school posts the fields, then shows it in the list", async () => {
  forgetToken();
  const root = fakeRoot();
  let listed = 0;
  let posted;
  const fetchImpl = serve([["/api/platform/schools/", (o) => {
    if (o.method === "POST") {
      posted = JSON.parse(o.body);
      return { status: 201, body: { school: { name: "Hope Academy", host: "hope.example.org" }, invited: "head@hope.example", emailed: true, link_to_hand_over: null } };
    }
    listed += 1;
    return { status: 200, body: listed === 1 ? SCHOOLS : { schools: [...SCHOOLS.schools, { name: "Hope Academy", subdomain: "hope", host: "hope.example.org", students: 0 }] } };
  }]]);
  await mount(root, { fetchImpl });

  await root.submit(FORM);

  assert.deepEqual(posted, FORM);
  assert.match(root.innerHTML, /invitation was sent to head@hope\.example/);
  assert.match(root.innerHTML, /0 students/);
  assert.match(root.innerHTML, /3 schools/);
});

test("with no email the link is shown to be handed over", async () => {
  forgetToken();
  const root = fakeRoot();
  const fetchImpl = serve([["/api/platform/schools/", (o) =>
    o.method === "POST"
      ? { status: 201, body: { school: { name: "Hope", host: "hope.example.org" }, invited: "+2348035550100", emailed: false, link_to_hand_over: "https://x/invitations/abc/" } }
      : { status: 200, body: SCHOOLS }]]);
  await mount(root, { fetchImpl });

  await root.submit({ ...FORM, admin_email: "", admin_phone: "08035550100" });

  assert.match(root.innerHTML, /Nothing was sent/);
  assert.match(root.innerHTML, /https:\/\/x\/invitations\/abc\//);
});

test("a refusal keeps the form and what was typed, with the server's sentence", async () => {
  forgetToken();
  const root = fakeRoot();
  const fetchImpl = serve([["/api/platform/schools/", (o) =>
    o.method === "POST"
      ? { status: 422, body: { detail: "'app' is reserved for the platform itself." } }
      : { status: 200, body: SCHOOLS }]]);
  await mount(root, { fetchImpl });

  await root.submit({ ...FORM, subdomain: "app" });

  assert.match(root.innerHTML, /reserved for the platform/);
  assert.match(root.innerHTML, /value="app"/);
  assert.match(root.innerHTML, /value="Hope Academy"/);
});
