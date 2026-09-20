/**
 * The staff sign-in flow: one step, five answers, and a landing that links
 * nowhere.
 *
 * `advance()` is a pure (state, answer) -> state function and every state is a
 * pure function of an API body, so the whole flow is walked here without a
 * browser. What it walks is `POST /api/login/`'s answer set, not a design: a
 * 200 with schools, a 200 with none, a 401, a 429 and everything else.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  advance,
  afterSignOut,
  htmlFor,
  initialState,
  mount,
} from "../../static/staff-signin/app.js";
import * as steps from "../../static/staff-signin/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const TWO_SCHOOLS = {
  status: 200,
  body: {
    full_name: "Adaeze Bello",
    schools: [
      { slug: "st-marys", name: "St Mary's", host: "st-marys.example.test" },
      { slug: "grace", name: "Grace Academy", host: "grace.example.test" },
    ],
    csrf_token: "t",
  },
};
const NO_SCHOOL = {
  status: 200,
  body: { full_name: "Adaeze Bello", schools: [], csrf_token: "t" },
};
const REFUSED = {
  status: 401,
  body: {
    detail: "That identifier and password do not match an account.",
    code: "bad_credentials",
    retryable: false,
  },
};

test("a password signs a member of staff in and names the account that answered", () => {
  const state = advance({ ...initialState(), identifier: "ada@stmarys.test" }, TWO_SCHOOLS);

  assert.equal(state.step, "landed");
  const html = htmlFor(state);
  // The receipt. A staff-parent may hold two accounts on this platform, and
  // this is how she knows which one the password opened.
  assert.match(html, /Signed in as Adaeze Bello/);
  assert.match(html, /St Mary&#39;s/);
  assert.match(html, /Grace Academy/);
});

test("the landing links nowhere at all", () => {
  // The decision this page turns on. `/cards/` is the only page a school's host
  // serves and `_children_of()` makes it a family surface even for staff, so a
  // teacher sent there reads "No children on this account… ask the school
  // office to add you as a guardian" — the school's answer to somebody else's
  // question. Auto-redirecting is wrong for that reason; a link labelled
  // "Report cards" is the same wrong answer with a tap in between.
  //
  // CONTROL: putting `<a href="//${host}/cards/">` back into `landed()` reddens
  // this and nothing else, which is what says this assertion is the rule rather
  // than a description of markup that happens not to have a link in it.
  const html = htmlFor(advance(initialState(), TWO_SCHOOLS));

  assert.doesNotMatch(html, /<a /, "the landing offers a link it cannot justify");
  assert.doesNotMatch(html, /\/cards\//, "the family page is not a staff destination");
});

test("the flow never redirects, even for a member of staff at one school", () => {
  // The guardian flow does redirect on one school, and the difference is not an
  // inconsistency: a guardian has exactly one destination and jumping to it
  // saves a tap. This module exports no `destination()` because there is
  // nothing for it to return.
  const one = advance(initialState(), {
    status: 200,
    body: { full_name: "A", schools: [{ slug: "s", name: "S", host: "s.test" }] },
  });

  assert.equal(one.step, "landed");
  assert.match(htmlFor(one), /this school:/);
});

test("signed in with no school is a success, not a refusal", () => {
  // Reachable and not rare: `user.schools()` is scoped to ACTIVE memberships
  // alone, so a suspended teacher and an invited one who never accepted both
  // authenticate perfectly and land here. Reading an empty list as a failure
  // would tell them their password was wrong.
  const state = advance(initialState(), NO_SCHOOL);

  assert.equal(state.step, "nowhere");
  const html = htmlFor(state);
  assert.match(html, /Signed in as Adaeze Bello/);
  assert.doesNotMatch(html, /do not match|did not work|wrong/i);
  // The one of the two causes the reader can act on alone.
  assert.match(html, /invitation/i);
});

test("a refusal keeps the identifier and says one sentence about neither field", () => {
  const typed = { ...initialState(), identifier: "ada@stmarys.test" };
  const state = advance(typed, REFUSED);

  assert.equal(state.step, "ask");
  assert.equal(state.identifier, "ada@stmarys.test", "retyping the field that was right");
  const html = htmlFor(state);
  assert.match(html, /do not match an account/);
  // `signin.REFUSED` is one sentence for no account, a wrong password, a
  // deactivated account and two accounts matching one identifier. A page that
  // guessed which would hand back the account-existence oracle the API gives up.
  assert.doesNotMatch(html, /bad_credentials/, "never the programmer's string");
  assert.doesNotMatch(html, /no such|does not exist|wrong password/i);
});

test("the password is never in the state and never back in the markup", () => {
  // There is no second request, so there is nothing to keep. The field is
  // rendered empty after a refusal while the identifier is rendered back.
  const state = advance({ ...initialState(), identifier: "ada@stmarys.test" }, REFUSED);

  assert.equal(Object.values(state).includes("hunter2"), false);
  assert.doesNotMatch(htmlFor(state), /hunter2/);
  assert.match(htmlFor(state), /type="password"[^>]*>/);
  assert.doesNotMatch(htmlFor(state), /type="password"[^>]*value=/);
});

test("too many tries says how long to wait, in a unit a person reads", () => {
  const soon = advance(initialState(), {
    status: 429,
    body: { detail: "Too many attempts.", code: "too_many_attempts", retry_after: 45 },
  });
  assert.equal(soon.step, "throttled");
  assert.match(htmlFor(soon), /about 45 seconds/);

  const later = advance(initialState(), {
    status: 429,
    body: { detail: "Too many attempts.", retry_after: 900 },
  });
  assert.match(htmlFor(later), /about 15 minutes/);

  // The same arithmetic as the guardian door, because it is the same throttle:
  // `guardian_signin.TooManyAttempts` carries `signin.THROTTLED`. It lives in
  // `web/html.js` so the threshold cannot drift between two pages.
  const silent = steps.throttled({ detail: "Too many." });
  assert.doesNotMatch(silent, /try again in/i, "no wait was sent, so none is invented");
});

test("a 500, a dead transport and a surviving 403 are all the broken page", () => {
  assert.equal(advance(initialState(), { status: 500, body: {} }).step, "broken");
  assert.equal(advance(initialState(), { status: 0, body: {} }).step, "broken");
  // `postJson` has already refetched the token and retried once, so a 403 that
  // survives is a door refusing everything rather than a stale token.
  assert.equal(
    advance(initialState(), { status: 403, body: { code: "csrf_failed" } }).step,
    "broken",
  );
  assert.match(htmlFor({ step: "broken" }), /not working/i);
});

test("a school's name cannot execute in a teacher's browser", () => {
  // `name` is typed by whoever created the school, in the admin.
  const html = steps.landed({
    full_name: '<img src=x onerror="alert(1)">',
    schools: [{ name: '<script>alert(2)</script>' }],
  });
  assert.doesNotMatch(html, /<img src=x/);
  assert.doesNotMatch(html, /<script>/);
  assert.match(html, /&lt;img/);
});

test("every state renders something a reader can act on", () => {
  for (const step of ["ask", "landed", "nowhere", "throttled", "signed-out", "broken"]) {
    const html = htmlFor({ step, body: { schools: [] } });
    assert.match(html, /<h1>/, `${step} has no heading`);
    assert.ok(html.length > 80, `${step} renders almost nothing`);
  }
});

test("signing out from the landing ends the session and says so", async () => {
  assert.equal(afterSignOut({ step: "landed" }, { status: 200 }).step, "signed-out");
  // A session that had already gone is a true answer to "sign me out".
  assert.equal(afterSignOut({ step: "landed" }, { status: 401 }).step, "signed-out");
  assert.match(htmlFor({ step: "signed-out" }), /Signed out/);
  // Same host, so the way back is relative — unlike the family pages, whose
  // way back crosses to the portal.
  assert.match(htmlFor({ step: "signed-out" }), /href="\/staff-sign-in\/"/);
});

test("a sign-out that did not work does not claim it did", async () => {
  // The dangerous direction: telling somebody they are signed out while the
  // session is live hands the next person the pages still open.
  const failed = afterSignOut({ step: "landed", body: NO_SCHOOL.body }, { status: 500 });

  assert.notEqual(failed.step, "signed-out");
  assert.match(htmlFor(failed), /could not sign you out/i);
  assert.match(htmlFor(failed), /close this browser/i);
});

test("mount posts what was typed and redraws, without trimming the password", async () => {
  forgetToken();
  const root = fakeRoot();
  const sent = [];
  const page = mount(root, {
    fetchImpl: async (url, options) => {
      if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
      sent.push(JSON.parse(options.body));
      return { status: 200, json: async () => TWO_SCHOOLS.body };
    },
  });

  await root.submit({ identifier: "  ada@stmarys.test  ", password: " sp ace " });

  assert.deepEqual(sent, [{ identifier: "ada@stmarys.test", password: " sp ace " }]);
  assert.equal(page.current().step, "landed");
  assert.equal(root.dataset.step, "landed");
  assert.match(root.innerHTML, /Signed in as Adaeze Bello/);
});

test("mount signs out and the page stops naming the schools", async () => {
  forgetToken();
  const root = fakeRoot();
  const calls = [];
  const page = mount(root, {
    fetchImpl: async (url) => {
      calls.push(url);
      if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
      if (url === "/api/logout/") return { status: 200, json: async () => ({ detail: "Signed out." }) };
      return { status: 200, json: async () => TWO_SCHOOLS.body };
    },
  });

  await root.submit({ identifier: "ada@stmarys.test", password: "x" });
  await root.click({ "data-action": "sign-out" });

  assert.ok(calls.includes("/api/logout/"), "the button never posted");
  assert.equal(page.current().step, "signed-out");
  assert.doesNotMatch(root.innerHTML, /St Mary/, "the schools outlived the session");
});
