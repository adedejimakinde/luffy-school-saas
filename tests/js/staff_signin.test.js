/**
 * The staff sign-in flow: one step, five answers, and a landing that links to
 * what each school actually offers this login.
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
      {
        slug: "st-marys",
        name: "St Mary's",
        host: "st-marys.example.test",
        may_take_a_register: true,
        has_children_here: false,
      },
      {
        slug: "grace",
        name: "Grace Academy",
        host: "grace.example.test",
        may_take_a_register: false,
        has_children_here: true,
      },
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

test("each school is linked to what it offers this login, and to nothing else", () => {
  // This replaces `the landing links nowhere at all`, which was the rule while
  // `/cards/` was the only page a school's host served — a *family* surface
  // even for staff, so a teacher sent there read "No children on this account".
  // Both halves that made it right have changed: the register is a staff
  // destination, and `SchoolOut` now carries the two booleans, each being the
  // same question the surface behind it asks rather than a role standing in.
  //
  // The fixture is deliberately asymmetric — a marker at one school and a
  // family at the other — so a renderer that drew both links on every school,
  // or keyed either on `host`, fails here.
  const html = htmlFor(advance(initialState(), TWO_SCHOOLS));

  assert.match(html, /<a href="\/\/st-marys\.example\.test\/register\/">/);
  assert.doesNotMatch(
    html,
    /<a href="\/\/st-marys\.example\.test\/cards\/">/,
    "a school where she guards nobody was linked to the family page",
  );
  assert.match(html, /<a href="\/\/grace\.example\.test\/cards\/">/);
  assert.doesNotMatch(
    html,
    /<a href="\/\/grace\.example\.test\/register\/">/,
    "a school where she may not mark was linked to the register",
  );
});

test("a school offering this login nothing is named and says so", () => {
  // Whoever lands here has nothing on this platform at this school yet.
  // Named without a sentence would read as a page that failed to load, and
  // they have done nothing wrong.
  const html = htmlFor(
    advance(initialState(), {
      status: 200,
      body: {
        full_name: "Bimpe Bursar",
        schools: [
          {
            slug: "grace",
            name: "Grace Academy",
            host: "grace.example.test",
            may_take_a_register: false,
            has_children_here: false,
          },
        ],
        csrf_token: "t",
      },
    }),
  );

  assert.match(html, /Grace Academy/);
  assert.doesNotMatch(html, /<a /, "a link was drawn for a login with nothing to open");
  assert.match(html, /nothing for you to open here yet/);
});

test("a school with no host is named but not linked, whatever it offers", () => {
  // `hostHref()`'s rule, on its second caller. The booleans say she may do
  // both things there; the deployment cannot say where. A `//null/register/`
  // is a broken link that looks like a working one.
  const html = htmlFor(
    advance(initialState(), {
      status: 200,
      body: {
        full_name: "Tayo",
        schools: [
          {
            slug: "grace",
            name: "Grace Academy",
            host: null,
            may_take_a_register: true,
            has_children_here: true,
          },
        ],
        csrf_token: "t",
      },
    }),
  );

  assert.doesNotMatch(html, /href="\/\/null/, "a null host became a link");
  assert.doesNotMatch(html, /<a /);
  assert.match(html, /no web address set up yet/);
});

test("one school is one row however many roles are held there", () => {
  // Multiple memberships per (user, school) are expected and correct. The
  // landing answers "where can I go", not "what am I called", so a teacher who
  // is also a parent at one school is one school with two links.
  const html = htmlFor(
    advance(initialState(), {
      status: 200,
      body: {
        full_name: "Tayo",
        schools: [
          {
            slug: "st-marys",
            name: "St Mary's",
            host: "st-marys.example.test",
            may_take_a_register: true,
            has_children_here: true,
          },
        ],
        csrf_token: "t",
      },
    }),
  );

  assert.equal(html.match(/St Mary&#39;s/g).length, 1, "the school was drawn twice");
  assert.match(html, /\/register\//);
  assert.match(html, /\/cards\//);
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

test("the absence list is linked iff the login may read it there", () => {
  // `may_see_absences` is `attendance.absences.may_see()`: principal, vice
  // principal (academic) and administrator. A vice principal who landed on
  // "nothing for you to open" before this now has somewhere to go, and a
  // teacher still has no link to a list that would answer her with a 404.
  const html = htmlFor(
    advance(initialState(), {
      status: 200,
      body: {
        full_name: "Vera",
        schools: [
          {
            slug: "grace",
            name: "Grace Academy",
            host: "grace.example.test",
            may_take_a_register: false,
            may_see_absences: true,
            has_children_here: false,
          },
          {
            slug: "st-marys",
            name: "St Mary's",
            host: "st-marys.example.test",
            may_take_a_register: true,
            may_see_absences: false,
            has_children_here: false,
          },
        ],
        csrf_token: "t",
      },
    }),
  );

  assert.match(html, /href="\/\/grace\.example\.test\/absences\/"/);
  assert.doesNotMatch(html, /st-marys\.example\.test\/absences\//);
  assert.equal(html.match(/\/absences\//g).length, 1);
});

test("the books are linked iff the login may read them there", () => {
  // `may_see_fees` is `fees.authority.may_read()`: bursar, administrator,
  // principal and vice principal (academic). A bursar had nothing to open
  // before this; a teacher still has no link to a page that would answer her
  // with a 404.
  const html = htmlFor(
    advance(initialState(), {
      status: 200,
      body: {
        full_name: "Bimpe Bursar",
        schools: [
          {
            slug: "grace",
            name: "Grace Academy",
            host: "grace.example.test",
            may_take_a_register: false,
            may_see_fees: true,
            has_children_here: false,
          },
          {
            slug: "st-marys",
            name: "St Mary's",
            host: "st-marys.example.test",
            may_take_a_register: true,
            may_see_fees: false,
            has_children_here: false,
          },
        ],
        csrf_token: "t",
      },
    }),
  );

  assert.match(html, /href="\/\/grace\.example\.test\/fees\/"/);
  assert.doesNotMatch(html, /st-marys\.example\.test\/fees\//);
  assert.equal(html.match(/\/fees\//g).length, 1);
});

test("the timetable is linked iff the login may read it there", () => {
  // `may_see_timetable` is `timetable.services.may_read()`: every teacher, the
  // principal, the vice principal (academic) and the administrator. A bursar
  // is not sent to a page that would answer with a 404.
  const html = htmlFor(
    advance(initialState(), {
      status: 200,
      body: {
        full_name: "Kemi Teacher",
        schools: [
          {
            slug: "grace",
            name: "Grace Academy",
            host: "grace.example.test",
            may_take_a_register: true,
            may_see_timetable: true,
            has_children_here: false,
          },
          {
            slug: "st-marys",
            name: "St Mary's",
            host: "st-marys.example.test",
            may_see_fees: true,
            may_see_timetable: false,
            has_children_here: false,
          },
        ],
        csrf_token: "t",
      },
    }),
  );

  assert.match(html, /href="\/\/grace\.example\.test\/timetable\/"/);
  assert.doesNotMatch(html, /st-marys\.example\.test\/timetable\//);
  assert.equal(html.match(/\/timetable\//g).length, 1);
});
