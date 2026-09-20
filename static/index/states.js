/**
 * What the index says when it has no cards to list, or cannot list them.
 *
 * The card page's states are about **one** card; these are about the family.
 * They are separate modules because they answer to different routes: this page
 * reads `GET /api/results/cards/`, which never 403s and never 404s — it answers
 * only about children the caller already stands for.
 */

import { esc } from "../web/html.js";

/**
 * Signed in, and nothing to show.
 *
 * Two different silences, told apart because they send a parent to different
 * people. No children at all is the school office's business — a guardianship
 * that was never recorded. Children with no released cards is nobody's fault
 * and needs no action, so it does not read like a problem.
 */
export function nothing({ hasChildren = false } = {}) {
  if (hasChildren) {
    return [
      '<section class="state state-empty" data-state="empty">',
      "<h1>No report cards yet</h1>",
      "<p>No cards have been released for this term. They appear here as soon ",
      "as the school releases them.</p>",
      "</section>",
    ].join("");
  }
  return [
    '<section class="state state-nobody" data-state="nobody">',
    "<h1>No children on this account</h1>",
    "<p>This school has no children linked to you. If that is wrong, the ",
    "school office can add you as a guardian.</p>",
    "</section>",
  ].join("");
}

/**
 * 401. Sign-in is on the portal and this page is on a school's host, so the
 * link out has to be absolute — and the portal's address is **not** something
 * the API will tell this page. `api._portal_only()` settles that: the client
 * knows where it signed in, and having the server answer it would put the same
 * fact in two places.
 *
 * So the server renders it into the frame from the one authority there is — the
 * `Domain` row for the public schema — and passes it here. Where a deployment
 * has no such row the sentence stands without a link, because a dead link is
 * worse than a sentence that tells you to go back the way you came.
 */
export function signedOut({ portal = "", expired = false } = {}) {
  const heading = expired ? "Your session has ended" : "Please sign in";
  const sentence = expired
    ? "Sign in again to see your children's report cards."
    : "Sign in to see your children's report cards.";
  const link = portal
    ? `<p><a href="//${esc(portal)}/sign-in/">Sign in</a></p>`
    : "<p>Go back to the sign-in page you came from.</p>";
  return [
    `<section class="state state-signed-out" data-state="signed-out">`,
    `<h1>${heading}</h1>`,
    `<p>${sentence}</p>`,
    link,
    "</section>",
  ].join("");
}

/** A 500, a transport failure, a body that would not parse. */
export function broken() {
  return [
    '<section class="state state-broken" data-state="broken">',
    "<h1>This page could not load your cards</h1>",
    "<p>Something went wrong on our side. Please try again in a few minutes, ",
    "and tell the school office if it keeps happening.</p>",
    "</section>",
  ].join("");
}
