/**
 * The page-module halves of onboarding: where a staff sign-in lands, what an
 * accepted invitation says next, and a family's first-days welcome.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { advance, initialState, landingRedirect, mount } from "../../static/staff-signin/app.js";
import { landed } from "../../static/staff-signin/states.js";
import { accepted } from "../../static/invite/states.js";
import { welcome } from "../../static/index/states.js";
import { htmlFor as indexHtml } from "../../static/index/app.js";
import { fakeRoot } from "./fake_dom.js";

const school = (extra) => ({ slug: "sunrise", name: "Sunrise", host: "sunrise.classnode.test", ...extra });
const signedIn = (schools) => advance(initialState(), { status: 200, body: { full_name: "Folake Adebayo", schools } });

// -- the staff landing ------------------------------------------------------------

test("an administrator at one school that is not set up goes to Start here", () => {
  assert.equal(landingRedirect(signedIn([school({ start_here: true })])), "//sunrise.classnode.test/start/");
});

test("in the single-host demo it is the path alone", () => {
  assert.equal(landingRedirect(signedIn([school({ start_here: true, path_only: true })])), "/start/");
});

test("everybody else keeps the landing", () => {
  assert.equal(landingRedirect(signedIn([school({ may_take_a_register: true })])), null);
  assert.equal(landingRedirect(signedIn([])), null);
});

test("with several schools nobody is sent anywhere, and Start here is listed first", () => {
  const state = signedIn([school({ start_here: true, may_see_fees: true }), school({ slug: "grace", name: "Grace" })]);

  assert.equal(landingRedirect(state), null);
  const html = landed(state.body);
  assert.ok(html.indexOf("Start here: set up your school") < html.indexOf("Fees"));
});

test("a refused sign-in goes nowhere", () => {
  const state = advance(initialState(), { status: 401, body: { detail: "No." } });

  assert.equal(landingRedirect(state), null);
});

test("signing in really goes, once, after the landing is drawn", async () => {
  const went = [];
  const root = fakeRoot();
  const fetchImpl = async (url) => ({
    status: 200,
    ok: true,
    headers: { get: () => "application/json" },
    json: async () =>
      url.includes("/csrf/")
        ? { csrf_token: "t" }
        : { full_name: "Folake", schools: [school({ start_here: true })], csrf_token: "t" },
  });
  mount(root, { fetchImpl, go: (url) => went.push(url) });

  await root.submit({ identifier: "folake@example.com", password: "a-long-password" });

  assert.deepEqual(went, ["//sunrise.classnode.test/start/"]);
});

// -- an accepted invitation ----------------------------------------------------------

test("an accepted administrator is told step 1 in plain words", () => {
  const html = accepted({ school: "Sunrise", role: "admin" });

  assert.match(html, /Start here/);
  assert.match(html, /Step 1 is your school's contact email and crest/);
});

test("a teacher is told about registers and marks, and nothing about fees", () => {
  const html = accepted({ school: "Sunrise", role: "teacher" });

  assert.match(html, /take a register and enter marks/);
  assert.doesNotMatch(html, /fee/i);
});

// -- a family's first days -------------------------------------------------------------

const ADA = {
  student_membership_id: 5,
  student_name: "Ada Obi",
  cards: [
    { term_id: 9, term_label: "Third term", academic_session: "2025/2026", is_withheld: false, version: 1 },
  ],
};

test("the welcome names each child and links the released card", () => {
  const html = welcome({ name: "Tunde", children: [ADA] });

  assert.match(html, /Welcome, Tunde/);
  assert.match(html, /Ada Obi/);
  assert.match(html, /href="\/cards\/5\/9\/"/);
  assert.match(html, /is ready/);
});

test("a card held by the school is not called ready", () => {
  const held = { ...ADA, cards: [{ ...ADA.cards[0], is_withheld: true }] };
  const html = welcome({ children: [held] });

  assert.doesNotMatch(html, /is ready/);
  assert.match(html, /No report card has been released yet/);
});

test("fees appear only where the page already shows where to pay, never a balance", () => {
  const none = welcome({ children: [ADA] });
  const paying = welcome({
    children: [ADA],
    payInto: { 5: { bank_name: "Wema", account_number: "0123456789", account_name: "Sunrise / Ada Obi" } },
  });

  assert.doesNotMatch(none, /Fees/);
  assert.match(paying, /Fees: pay into Wema/);
  assert.doesNotMatch(paying, /owe|balance|&#8358;|₦/i);
});

test("the welcome shows only in a family's first days", () => {
  const body = { children: [ADA] };

  assert.match(indexHtml({ status: 200, body: { ...body, first_days: true, first_name: "Tunde" } }), /data-state="welcome"/);
  assert.doesNotMatch(indexHtml({ status: 200, body: { ...body, first_days: false } }), /data-state="welcome"/);
});

test("a failed fetch draws no welcome", () => {
  assert.doesNotMatch(indexHtml({ status: 500, body: null }), /data-state="welcome"/);
});
