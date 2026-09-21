/**
 * The register screen: choose a class, tap who is absent, submit once.
 *
 * Every state is a pure function of an API body and `mount()` touches only
 * `innerHTML`, `dataset` and `addEventListener`, so the whole flow is walked
 * here without a browser. What it walks is the `attendance` routes' actual
 * answer set — a 200, a 403, a 404, a 409, a 422 and a 401 that is two states.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { fromRegister, fromWhere, htmlFor, mount, today } from "../../static/register/app.js";
import { REFUSAL, refusalFor, provesASession } from "../../static/register/api.js";
import * as states from "../../static/register/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const WHERE = {
  term_id: 7,
  term: "2025/2026 First term",
  classes: [
    { id: 11, name: "JSS 1A", level: 1 },
    { id: 12, name: "JSS 1B", level: 1 },
  ],
};

const REGISTER = {
  class_group_id: 11,
  class_group: "JSS 1A",
  term_id: 7,
  term: "2025/2026 First term",
  taken_on: "2025-09-17",
  taken: false,
  rows: [
    { student_membership_id: 1, student: "Ada Obi", status: null },
    { student_membership_id: 2, student: "Emeka Nwosu", status: null },
    { student_membership_id: 3, student: "Bisi Ade", status: null },
  ],
};

function serve(routes) {
  return async (url, options = {}) => {
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    for (const [match, answer] of routes) {
      if (url.includes(match)) {
        const value = typeof answer === "function" ? answer(options) : answer;
        return { status: value.status, json: async () => value.body };
      }
    }
    throw new Error(`no stub for ${url}`);
  };
}

// -- the refusals are not one refusal ---------------------------------------

test("403 and 404 are different answers with different remedies", () => {
  // A 403 is `_refuse_non_markers()`: signed in at this school, not somebody
  // who marks. A 404 is `_school_of()`: this host is not a school's, so there
  // is no register anywhere behind the URL. One sentence for both would be
  // wrong for whichever reader it was not written for.
  assert.equal(refusalFor(403, {}), REFUSAL.NOT_A_MARKER);
  assert.equal(refusalFor(404, {}), REFUSAL.WRONG_HOST);
});

test("the two 401s are told apart by code, not by status", () => {
  assert.equal(refusalFor(401, { code: "session_expired" }), REFUSAL.EXPIRED);
  assert.equal(refusalFor(401, { code: "not_authenticated" }), REFUSAL.SIGNED_OUT);
});

test("only answers that prove a session carry a sign-out button", () => {
  // A 403 qualifies: `_refuse_non_markers()` is reached only after
  // `session_auth` has identified the caller. A 404 does not: `_school_of()`
  // raises before any authority question, so it says nothing about the cookie.
  assert.ok(provesASession({ ok: true }));
  assert.ok(provesASession({ ok: false, refusal: REFUSAL.NOT_A_MARKER }));
  assert.ok(!provesASession({ ok: false, refusal: REFUSAL.WRONG_HOST }));
  assert.ok(!provesASession({ ok: false, refusal: REFUSAL.BROKEN }));
});

test("the refusal a bursar reads does not offer her the staff door", () => {
  // She is already signed in with a password. What she lacks is a role only
  // the school can give her — the false-remedy rule `accounts/refusals.py`
  // turns on, in a second place.
  const html = states.notAMarker({ detail: "A register is taken by a teacher." });

  assert.doesNotMatch(html, /staff-sign-in/);
  assert.match(html, /school office/i);
});

// -- no current term ---------------------------------------------------------

test("no current term is its own screen, not a refusal and not a guess", () => {
  // `Term.is_current` is a column the school sets. A term inferred from the
  // calendar would disagree with the school the first time a term ran late,
  // and nothing on the resulting register row would say it was a guess.
  const state = fromWhere({ ok: true, body: { term_id: null, term: null, classes: [] } });

  assert.equal(state.step, "no-term");
  assert.match(htmlFor(state), /No term is open/);
  assert.match(htmlFor(state), /school office/i);
});

// -- the chooser -------------------------------------------------------------

test("every class the school teaches is offered, not only her own", () => {
  // `can_mark_attendance()` is school-wide and carries no reference to
  // `ClassTeacher`. A shorter list here would be a scope the platform does not
  // enforce, drawn as though it did. Issue #125.
  const html = htmlFor(fromWhere({ ok: true, body: WHERE }, { on: "2025-09-17" }));

  assert.match(html, /JSS 1A/);
  assert.match(html, /JSS 1B/);
});

test("today is the default day and it is still editable", () => {
  // A register entered from paper on Friday for Wednesday is ordinary office
  // work — the case `MARKING_ROLES` admits principals and administrators for.
  assert.equal(today(new Date("2025-09-17T09:30:00Z")), "2025-09-17");
  const html = htmlFor(fromWhere({ ok: true, body: WHERE }, { on: "2025-09-17" }));
  assert.match(html, /<input id="on" name="on" type="date" value="2025-09-17">/);
});

// -- marking -----------------------------------------------------------------

test("an existing register opens pre-marked rather than blank", () => {
  // A teacher correcting one child must not have to re-mark the other
  // twenty-nine. `taken` is what says this register already exists.
  const state = fromRegister({
    ok: true,
    body: {
      ...REGISTER,
      taken: true,
      rows: [
        { student_membership_id: 1, student: "Ada Obi", status: "absent" },
        { student_membership_id: 2, student: "Emeka Nwosu", status: "present" },
        { student_membership_id: 3, student: "Bisi Ade", status: null },
      ],
    },
  });

  assert.deepEqual(state.absent, [1]);
  const html = htmlFor(state);
  assert.match(html, /already been taken/);
  assert.match(html, /1 marked absent of 3/);
});

test("an unmarked child is not a present child", () => {
  // `status: null` means **not marked**, which is a third answer. A register
  // that exists with a child unmarked differs from one where they were marked
  // present, and truthiness cannot tell those apart.
  const state = fromRegister({ ok: true, body: REGISTER });

  assert.deepEqual(state.absent, [], "a null status was read as absent");
  assert.match(htmlFor(state), /0 marked absent of 3/);
});

test("a child with no name on record still gets a row to be marked in", () => {
  // `_names_for()` falls back to the empty string rather than to a username: a
  // username on a register is a hint the teacher cannot act on, and the child
  // still has to be markable.
  const html = states.marking({
    ...REGISTER,
    rows: [{ student_membership_id: 9, student: "", status: null }],
  });

  assert.match(html, /data-child="9"/);
  assert.match(html, /no name on record/);
});

test("a school name typed into the admin cannot execute in a teacher's browser", () => {
  const html = states.marking({
    ...REGISTER,
    class_group: '<img src=x onerror="alert(1)">',
  });

  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
});

// -- the write ---------------------------------------------------------------

test("submitting sends absences and the roster the screen actually drew", async () => {
  forgetToken();
  const sent = [];
  const root = fakeRoot({ portal: "portal.example.test" });
  await mount(root, {
    now: new Date("2025-09-17T09:00:00Z"),
    fetchImpl: serve([
      ["/api/attendance/where/", { status: 200, body: WHERE }],
      [
        "/api/attendance/classes/",
        (options) => {
          if (options.method === "PUT") {
            sent.push(JSON.parse(options.body));
            return {
              status: 200,
              body: {
                class_group_id: 11,
                taken_on: "2025-09-17",
                present: [2, 3],
                absent: [1],
                appeared: [],
                not_on_the_roster: [],
              },
            };
          }
          return { status: 200, body: REGISTER };
        },
      ],
    ]),
  });

  await root.click({ "data-action": "open", "data-class": "11" });
  await root.click({ "data-action": "toggle", "data-child": "1" });
  await root.click({ "data-action": "submit" });

  assert.deepEqual(sent, [{ absent_ids: [1], shown_ids: [1, 2, 3] }]);
  assert.match(root.innerHTML, /Register taken/);
  assert.match(root.innerHTML, /2 present, 1 absent/);
});

test("a child who joined while the screen was open is named, not silently marked", async () => {
  // This is what `shown_ids` exists for. Marking somebody present on a screen
  // that never showed them is the failure the field prevents, and a teacher who
  // is not told cannot fix it.
  forgetToken();
  const root = fakeRoot({});
  await mount(root, {
    now: new Date("2025-09-17T09:00:00Z"),
    fetchImpl: serve([
      ["/api/attendance/where/", { status: 200, body: WHERE }],
      [
        "/api/attendance/classes/",
        (options) =>
          options.method === "PUT"
            ? {
                status: 200,
                body: {
                  class_group_id: 11,
                  taken_on: "2025-09-17",
                  present: [2, 3],
                  absent: [1],
                  appeared: [4],
                  not_on_the_roster: [],
                },
              }
            : {
                status: 200,
                body: {
                  ...REGISTER,
                  rows: [...REGISTER.rows, { student_membership_id: 4, student: "Tunde Cole", status: null }],
                },
              },
      ],
    ]),
  });

  await root.click({ "data-action": "open", "data-class": "11" });
  await root.click({ "data-action": "toggle", "data-child": "1" });
  await root.click({ "data-action": "submit" });

  assert.match(root.innerHTML, /Not marked/);
  assert.match(root.innerHTML, /Tunde Cole/, "the child was reported as an id");
  assert.match(root.innerHTML, /Take the register again/);
});

test("a 409 and a 422 keep their own sentence instead of becoming 'broken'", async () => {
  // Both are answers a teacher can act on — nobody in the group, or a date
  // outside the term — and the API wrote `detail` for a person to read.
  for (const status of [409, 422]) {
    forgetToken();
    const root = fakeRoot({});
    await mount(root, {
      now: new Date("2025-09-17T09:00:00Z"),
      fetchImpl: serve([
        ["/api/attendance/where/", { status: 200, body: WHERE }],
        [
          "/api/attendance/classes/",
          (options) =>
            options.method === "PUT"
              ? { status, body: { detail: "That day is outside the term." } }
              : { status: 200, body: REGISTER },
        ],
      ]),
    });

    await root.click({ "data-action": "open", "data-class": "11" });
    await root.click({ "data-action": "submit" });

    assert.match(root.innerHTML, /That day is outside the term/, `status ${status}`);
    assert.doesNotMatch(root.innerHTML, /not working/i, `status ${status} became broken`);
  }
});

// -- the hosts and the session ----------------------------------------------

test("on the portal the page says where the work is", async () => {
  // `urls_public.py` splats the tenant patterns in, so the frame resolves
  // there; every route it calls 404s because there is no register in the
  // public schema.
  const root = fakeRoot({ portal: "portal.example.test" });
  await mount(root, {
    fetchImpl: serve([["/api/attendance/where/", { status: 404, body: { detail: "No register on this host." } }]]),
  });

  assert.match(root.innerHTML, /school's own web address/i);
  assert.doesNotMatch(root.innerHTML, /data-action="sign-out"/, "a 404 proved a session it cannot prove");
});

test("an expired session and no session are different sentences", () => {
  const expired = htmlFor({ step: REFUSAL.EXPIRED }, { portal: "portal.example.test" });
  const never = htmlFor({ step: REFUSAL.SIGNED_OUT }, { portal: "portal.example.test" });

  assert.match(expired, /session has ended/i);
  assert.match(never, /Please sign in/i);
  for (const html of [expired, never]) {
    assert.match(html, /\/\/portal\.example\.test\/staff-sign-in\//);
  }
});

test("with no portal domain there is a sentence and no link", () => {
  // A dead link is worse than being told to go back the way you came — the
  // rule `schools.hosts.portal_host()` states, on its third caller.
  const html = htmlFor({ step: REFUSAL.SIGNED_OUT }, { portal: "" });

  assert.doesNotMatch(html, /<a /);
  assert.match(html, /go back to the sign-in page/i);
});

test("a sign-out that did not work does not empty the register", async () => {
  forgetToken();
  const root = fakeRoot({ portal: "portal.example.test" });
  await mount(root, {
    fetchImpl: serve([
      ["/api/attendance/where/", { status: 200, body: WHERE }],
      ["/api/logout/", { status: 502, body: {} }],
    ]),
  });

  await root.click({ "data-action": "sign-out" });

  // The dangerous direction: telling a teacher she is signed out while the
  // cookie is live is a handset passed on with the roll still open.
  assert.match(root.innerHTML, /JSS 1A/);
  assert.match(root.innerHTML, /could not sign you out/i);
});
