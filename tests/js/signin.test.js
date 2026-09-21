/**
 * The sign-in flow, including the step a household sharing a handset needs.
 *
 * `advance()` is a pure (state, answer) -> state function, so the whole flow is
 * testable without a browser: the tests below walk a parent all the way in,
 * through the 202 and out the other side, and assert what is on the page at
 * each stop.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { advance, destination, htmlFor, initialState, mount } from "../../static/signin/app.js";
import * as steps from "../../static/signin/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const CODE_SENT = { status: 200, body: { detail: "If that number is on a guardian record, a code is on its way." } };
const ONE_SCHOOL = {
  status: 200,
  body: {
    full_name: "Mama Ada",
    schools: [{ slug: "st-marys", name: "St Mary's", host: "st-marys.example.test" }],
    csrf_token: "t",
  },
};
const TWO_SCHOOLS = {
  status: 200,
  body: {
    full_name: "Mama Ada",
    schools: [
      { slug: "st-marys", name: "St Mary's", host: "st-marys.example.test" },
      { slug: "grace", name: "Grace Academy", host: "grace.example.test" },
    ],
    csrf_token: "t",
  },
};
const SHARED_HANDSET = {
  status: 202,
  body: {
    detail: "This number is shared by more than one guardian.",
    choose: [
      { guardian: "3f1c-aaa", full_name: "Mama Ada" },
      { guardian: "9b2d-bbb", full_name: "Papa Ada" },
    ],
  },
};

/** A parent who has typed a number and asked for a code. */
function atTheCodeStep() {
  return advance({ ...initialState(), value: "08031234567" }, CODE_SENT);
}

test("asking for a code moves to the code step and never promises delivery", () => {
  const state = atTheCodeStep();
  assert.equal(state.step, "code");
  const html = htmlFor(state);
  // The API answers identically for every value typed so that a stranger
  // cannot learn whose number is on a guardian record. A page that said "we
  // have sent you a code" would put that oracle back.
  assert.doesNotMatch(html, /we have sent|we've sent|check your (phone|messages)/i);
  assert.match(html, /if that number is on a guardian record/i);
});

test("one school goes straight to that school's host", () => {
  const state = advance(atTheCodeStep(), ONE_SCHOOL);
  assert.equal(state.step, "leaving");
  assert.equal(destination(state), "//st-marys.example.test/cards/");
  // Protocol-relative, so a development deployment on http is not sent to an
  // https URL it cannot serve.
  assert.doesNotMatch(destination(state), /^https?:/);
});

test("more than one school asks which, on the portal", () => {
  const state = advance(atTheCodeStep(), TWO_SCHOOLS);
  assert.equal(state.step, "schools");
  assert.equal(destination(state), null, "nobody is redirected with two options");
  const html = htmlFor(state);
  assert.match(html, /St Mary&#39;s/);
  assert.match(html, /Grace Academy/);
  assert.match(html, /\/\/st-marys\.example\.test\/cards\//);
  assert.match(html, /\/\/grace\.example\.test\/cards\//);
});

test("a shared handset asks whose card this is, and keeps the code", () => {
  // The step this flow would be broken without: the code proved the handset,
  // not the person, and the pick goes back to the same route with the same
  // code. Dropping the code here is what leaves a household stuck half-way in.
  const state = advance(atTheCodeStep(), SHARED_HANDSET);

  assert.equal(state.step, "whose");
  assert.equal(state.value, "08031234567", "the number is still held");
  assert.equal(state.code, "", "the code typed at the previous step");
  const html = htmlFor(state);
  assert.match(html, /Mama Ada/);
  assert.match(html, /Papa Ada/);
  assert.match(html, /data-guardian="3f1c-aaa"/);
  assert.match(html, /data-guardian="9b2d-bbb"/);
});

test("the code survives the 202 when it was actually typed", () => {
  const typed = { ...atTheCodeStep(), code: "123456" };
  const state = advance(typed, SHARED_HANDSET);
  assert.equal(state.code, "123456", "the pick has no code to send without this");
});

test("picking a guardian on a shared handset signs that guardian in", () => {
  const picked = advance({ ...atTheCodeStep(), code: "123456", step: "whose" }, ONE_SCHOOL);
  assert.equal(picked.step, "leaving");
  assert.equal(destination(picked), "//st-marys.example.test/cards/");
});

test("a bad code leaves the parent on the code step with the sentence", () => {
  const state = advance(
    { ...atTheCodeStep(), code: "000000" },
    { status: 401, body: { detail: "That code is wrong or has expired.", code: "bad_code", retryable: false } },
  );
  assert.equal(state.step, "code");
  assert.equal(state.code, "", "the wrong code is cleared from the field");
  assert.match(htmlFor(state), /wrong or has expired/);
  // Never the programmer's string.
  assert.doesNotMatch(htmlFor(state), /bad_code/);
});

test("too many tries says how long to wait, in a unit a person reads", () => {
  const soon = advance(atTheCodeStep(), {
    status: 429,
    body: { detail: "Too many attempts.", code: "too_many_attempts", retry_after: 45 },
  });
  assert.equal(soon.step, "throttled");
  assert.match(htmlFor(soon), /about 45 seconds/);

  const later = advance(atTheCodeStep(), {
    status: 429,
    body: { detail: "Too many attempts.", retry_after: 900 },
  });
  assert.match(htmlFor(later), /about 15 minutes/);
});

test("signed in with no school says so without offering a link it cannot honour", () => {
  const state = advance(atTheCodeStep(), {
    status: 200,
    body: { full_name: "Mama Ada", schools: [], csrf_token: "t" },
  });
  assert.equal(state.step, "nowhere");
  const html = htmlFor(state);
  assert.match(html, /no schools on this account/i);
  assert.doesNotMatch(html, /<a /, "no link, because there is nowhere to send them");
});

test("a school with no host is named but not linked", () => {
  const html = steps.schools({
    full_name: "Mama Ada",
    schools: [
      { slug: "st-marys", name: "St Mary's", host: "st-marys.example.test" },
      { slug: "grace", name: "Grace Academy", host: null },
    ],
  });
  assert.match(html, /\/\/st-marys\.example\.test\/cards\//);
  assert.match(html, /Grace Academy/);
  assert.doesNotMatch(html, /href="\/\/null/, "a null host must not become a link");
  assert.match(html, /no web address/i);
});

test("a 500 or a dead transport is the broken page, not a blank one", () => {
  assert.equal(advance(atTheCodeStep(), { status: 500, body: {} }).step, "broken");
  assert.equal(advance(atTheCodeStep(), { status: 0, body: {} }).step, "broken");
  assert.match(htmlFor({ step: "broken" }), /not working/i);
});

test("a guardian's name cannot execute in another guardian's browser", () => {
  // `full_name` is typed by whoever created the account, and on a shared
  // handset one guardian's name is rendered into the other's page.
  const html = steps.whose({
    detail: "shared",
    choose: [{ guardian: "x", full_name: '<img src=x onerror="alert(1)">' }],
  });
  assert.doesNotMatch(html, /<img src=x/);
  assert.match(html, /&lt;img/);
});

test("every step renders something a reader can act on", () => {
  for (const step of ["ask", "code", "whose", "schools", "nowhere", "throttled", "broken"]) {
    const html = htmlFor({ step, body: { choose: [], schools: [] } });
    assert.match(html, /<h1>/, `${step} has no heading`);
    assert.ok(html.length > 80, `${step} renders almost nothing`);
  }
});

test("the two states that hold a live session offer a way to end it", () => {
  // The rule across the platform: the button is on every page where somebody is
  // signed in. These two are where this flow stops with a session open — the
  // `leaving` state does not need one because it is on its way elsewhere — and
  // a shared handset is exactly a page somebody else picks up next.
  assert.match(htmlFor(advance(atTheCodeStep(), TWO_SCHOOLS)), /data-action="sign-out"/);
  assert.match(
    htmlFor(
      advance(atTheCodeStep(), { status: 200, body: { full_name: "Mama Ada", schools: [] } }),
    ),
    /data-action="sign-out"/,
  );
});

test("a sign-out tap is not posted as a guardian pick", async () => {
  // The trap this guards. The click handler used to treat every button that
  // was not `restart` as a pick, so a `[data-action="sign-out"]` would have
  // gone to `/api/guardian/session/` carrying `guardian: undefined` — a spent
  // code answered with a 401, and a family dropped back to the code step for no
  // reason they could see.
  //
  // CONTROL, and the first aim of it was wrong in a way worth recording.
  // Removing `if (!button.dataset.guardian) return undefined;` alone leaves
  // this green, because the sign-out branch returns before ever reaching the
  // fallthrough — the guard is the second line, not the first. The control that
  // reddens this is dropping that branch's `return` *and* the guard, and
  // dropping the branch outright reddens this and the failure test below it.
  // Recorded rather than fixed silently: a control that changes nothing has
  // told you the claim you were about to ship is not the claim the test holds.
  forgetToken();
  const root = fakeRoot();
  const posted = [];
  const page = mount(root, {
    fetchImpl: async (url) => {
      posted.push(url);
      if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
      if (url === "/api/guardian/code/") return { status: 200, json: async () => CODE_SENT.body };
      if (url === "/api/logout/") return { status: 200, json: async () => ({ detail: "Signed out." }) };
      return { status: 200, json: async () => TWO_SCHOOLS.body };
    },
  });

  await root.submit({ value: "08031234567" });
  await root.submit({ code: "123456" });
  assert.equal(page.current().step, "schools");
  posted.length = 0;

  await root.click({ "data-action": "sign-out" });

  assert.ok(posted.includes("/api/logout/"), "the tap did not sign anybody out");
  assert.ok(
    !posted.includes("/api/guardian/session/"),
    "the tap was posted as a guardian pick as well",
  );
  assert.equal(page.current().step, "signed-out");
  assert.doesNotMatch(root.innerHTML, /St Mary/, "the schools outlived the session");
});

test("picking a guardian still reaches the session route", async () => {
  // The companion. Without it the test above passes just as well against a
  // handler that stopped sending picks altogether.
  forgetToken();
  const root = fakeRoot();
  const posted = [];
  const page = mount(root, {
    fetchImpl: async (url, options = {}) => {
      posted.push({ url, body: options.body ? JSON.parse(options.body) : null });
      if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
      if (url === "/api/guardian/code/") return { status: 200, json: async () => CODE_SENT.body };
      // The first answer from the session route is the 202; the pick that
      // follows it is what signs somebody in.
      return posted.filter((p) => p.url === "/api/guardian/session/").length > 1
        ? { status: 200, json: async () => ONE_SCHOOL.body }
        : { status: 202, json: async () => SHARED_HANDSET.body };
    },
  });

  await root.submit({ value: "08031234567" });
  await root.submit({ code: "123456" });
  assert.equal(page.current().step, "whose");

  await root.click({ "data-guardian": "3f1c-aaa" });

  const pick = posted.at(-1);
  assert.equal(pick.url, "/api/guardian/session/");
  assert.deepEqual(pick.body, { value: "08031234567", code: "123456", guardian: "3f1c-aaa" });
});

test("a guardian sign-out that was not confirmed does not claim it was", async () => {
  forgetToken();
  const root = fakeRoot();
  const page = mount(root, {
    fetchImpl: async (url) => {
      if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
      if (url === "/api/guardian/code/") return { status: 200, json: async () => CODE_SENT.body };
      if (url === "/api/logout/") return { status: 500, json: async () => ({}) };
      return { status: 200, json: async () => TWO_SCHOOLS.body };
    },
  });

  await root.submit({ value: "08031234567" });
  await root.submit({ code: "123456" });
  await root.click({ "data-action": "sign-out" });

  assert.equal(page.current().step, "schools");
  assert.match(root.innerHTML, /could not sign you out/i);
  assert.match(root.innerHTML, /St Mary/, "the chooser was thrown away on a failed sign-out");
});
