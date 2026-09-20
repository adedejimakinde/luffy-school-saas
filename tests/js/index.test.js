/**
 * The index: the page that makes a card reachable at all.
 *
 * `htmlFor()` is a pure function of one API answer, so every branch — cards,
 * two kinds of silence, an expired session, a failure — is asserted here
 * without a browser.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { htmlFor } from "../../static/index/app.js";
import * as states from "../../static/index/states.js";

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
