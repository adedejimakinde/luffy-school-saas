/**
 * The index: the page that makes a card reachable at all.
 *
 * `htmlFor()` is a pure function of one API answer, so every branch — cards,
 * two kinds of silence, an expired session, a failure — is asserted here
 * without a browser.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { htmlFor, mount } from "../../static/index/app.js";
import * as states from "../../static/index/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const FAMILY = {
  status: 200,
  body: {
    children: [
      {
        student_membership_id: 12,
        student_name: "Ada Obi",
        cards: [
          {
            term_id: 3,
            term_name: "third",
            term_label: "Third term",
            academic_session: "2025/2026",
            version: 1,
            is_revised: false,
            is_withheld: false,
          },
          {
            term_id: 2,
            term_name: "second",
            term_label: "Second term",
            academic_session: "2025/2026",
            version: 2,
            is_revised: true,
            is_withheld: true,
          },
        ],
      },
      { student_membership_id: 13, student_name: "Bola Obi", cards: [] },
    ],
  },
};

test("each card links to its own card page, keyed on the two ids", () => {
  const html = htmlFor(FAMILY);
  assert.match(html, /href="\/cards\/12\/3\/"/);
  assert.match(html, /href="\/cards\/12\/2\/"/);
  assert.match(html, /Third term/);
  assert.match(html, /2025\/2026/);
});

test("a withheld card is listed and marked, never hidden", () => {
  // Hiding it defeats what withholding is for: a school holds a card back to
  // start a conversation about fees, and a card that never appears starts none.
  const html = htmlFor(FAMILY);
  assert.match(html, /href="\/cards\/12\/2\/"/, "the held card still links");
  assert.match(html, /Being held by the school/);
  assert.match(html, /class="withheld"/);
});

test("the index carries no card content of any kind", () => {
  // `ListedCardOut` has no slot for a mark, an average, a remark or a rating,
  // and that is what makes listing a withheld card safe. This is the page's
  // half of the same claim.
  const html = htmlFor(FAMILY);
  for (const absent of [/\b\d{2}\.\d{2}%/, /Excellent|Very Good/, /Position|Rank/i]) {
    assert.doesNotMatch(html, absent);
  }
});

test("a revision is marked, and a version only when there is more than one", () => {
  const html = htmlFor(FAMILY);
  assert.match(html, /Revised/);
  assert.match(html, /Version 2/);
  assert.equal((html.match(/Version 1/g) || []).length, 0, "version 1 is not a mark");
});

test("a child with no cards is listed rather than dropped", () => {
  // A parent whose second child has no released card should see that child and
  // be told why there is nothing under them, not wonder where they went.
  const html = htmlFor(FAMILY);
  assert.match(html, /Bola Obi/);
  assert.match(html, /No cards released yet/);
});

test("two silences, told apart because they send a parent to different people", () => {
  const noCards = htmlFor({ status: 200, body: { children: [{ student_membership_id: 1, student_name: "Ada", cards: [] }] } });
  assert.match(noCards, /No report cards yet/);
  assert.doesNotMatch(noCards, /school office/, "nothing for the office to fix");

  const noChildren = htmlFor({ status: 200, body: { children: [] } });
  assert.match(noChildren, /No children on this account/);
  assert.match(noChildren, /school office/, "this one is the office's to fix");
});

test("an expired session links back to the portal it came from", () => {
  const html = htmlFor(
    { status: 401, body: { code: "session_expired", detail: "Your session has ended." } },
    { portal: "portal.example.test" },
  );
  assert.match(html, /session has ended/i);
  assert.match(html, /href="\/\/portal\.example\.test\/sign-in\/"/);
});

test("never signed in is a different sentence from signed out", () => {
  const fresh = states.signedOut({ portal: "portal.example.test", expired: false });
  const lapsed = states.signedOut({ portal: "portal.example.test", expired: true });
  assert.match(fresh, /Please sign in/);
  assert.match(lapsed, /session has ended/i);
  assert.notEqual(fresh, lapsed);
});

test("no portal host means a sentence, never a dead link", () => {
  // A deployment with no `Domain` row for the public schema. A link to
  // `//undefined/sign-in/` is worse than telling somebody to go back.
  const html = states.signedOut({ portal: "", expired: true });
  assert.doesNotMatch(html, /<a /);
  assert.match(html, /go back to the sign-in page/i);
});

test("a 500 or an unparseable body is the broken page", () => {
  assert.match(htmlFor({ status: 500, body: {} }), /could not load/i);
  assert.match(htmlFor({ status: 200, body: null }), /could not load/i);
  assert.match(htmlFor({ status: 0, body: null }), /could not load/i);
});

test("a child's name cannot execute in a parent's browser", () => {
  const html = htmlFor({
    status: 200,
    body: {
      children: [
        {
          student_membership_id: 1,
          student_name: '<script>alert("x")</script>',
          cards: [{ term_id: 1, term_label: "First term", academic_session: "2025/2026", version: 1 }],
        },
      ],
    },
  });
  assert.doesNotMatch(html, /<script>alert/);
  assert.match(html, /&lt;script&gt;/);
});

test("the sign-out button is on the answer that proves a session, and no other", () => {
  // A 200 is the API having answered this caller about their own children,
  // which it does for nobody who is not signed in. A 401 already says the
  // opposite; a 500 or a dead transport says nothing either way, and a button
  // that posts a logout from a page that cannot reach the server is a control
  // that does nothing while looking like it did.
  const shown = (answer) => htmlFor(answer, { portal: "p.test" }).includes('data-action="sign-out"');

  assert.equal(shown(FAMILY), true);
  // Both silences are still a signed-in reader.
  assert.equal(shown({ status: 200, body: { children: [] } }), true);
  assert.equal(
    shown({ status: 200, body: { children: [{ student_name: "Ada", cards: [] }] } }),
    true,
  );

  assert.equal(shown({ status: 401, body: {} }), false);
  assert.equal(shown({ status: 500, body: {} }), false);
  assert.equal(shown({ status: 0, body: null }), false);
});

test("a sign-out that did not work leaves the cards on the page and says why", () => {
  // The list is still there and still readable; what changed is only that the
  // session is still open. Replacing the page would punish a parent for a
  // failure on our side.
  const html = htmlFor(FAMILY, { portal: "p.test", signOutFailed: true });

  assert.match(html, /Ada Obi/);
  assert.match(html, /could not sign you out/i);
  assert.match(html, /close this browser/i);
});

test("mount signs out and the children's names go with the session", async () => {
  forgetToken();
  const root = fakeRoot({ portal: "portal.example.test" });
  const calls = [];
  await mount(root, {
    fetchImpl: async (url) => {
      calls.push(url);
      if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
      if (url === "/api/logout/") return { status: 200, json: async () => ({ detail: "Signed out." }) };
      return { status: 200, json: async () => FAMILY.body };
    },
  });
  assert.match(root.innerHTML, /Ada Obi/);

  await root.click({ "data-action": "sign-out" });

  assert.ok(calls.includes("/api/logout/"), "the button never posted");
  assert.doesNotMatch(root.innerHTML, /Ada Obi/, "a child's name outlived the session");
  // **Not the expired state.** Signing out on purpose deletes the cookie as
  // well as the session, so nothing lapsed and there is nothing to recover by
  // trying again — `docs/membership.md` draws exactly that line.
  assert.doesNotMatch(root.innerHTML, /session has ended/i);
  assert.match(root.innerHTML, /please sign in/i);
  assert.match(root.innerHTML, /\/\/portal\.example\.test\/sign-in\//);
});

test("a sign-out the server would not confirm does not empty the page", async () => {
  forgetToken();
  const root = fakeRoot({ portal: "portal.example.test" });
  await mount(root, {
    fetchImpl: async (url) => {
      if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
      if (url === "/api/logout/") return { status: 502, json: async () => ({}) };
      return { status: 200, json: async () => FAMILY.body };
    },
  });

  await root.click({ "data-action": "sign-out" });

  // The dangerous direction. A page that cleared itself here would tell a
  // parent on a shared handset that they were signed out while the cookie was
  // still live and the cards still one refresh away.
  assert.match(root.innerHTML, /Ada Obi/);
  assert.match(root.innerHTML, /could not sign you out/i);
});
