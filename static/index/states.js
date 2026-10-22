/**
 * What the index says when it has no cards to list, or cannot list them.
 *
 * The card page's states are about **one** card; these are about the family.
 * They are separate modules because they answer to different routes: this page
 * reads `GET /api/results/cards/`, which never 403s and never 404s — it answers
 * only about children the caller already stands for.
 */

import { esc, brokenState } from "../web/html.js";
import { connectionDropped } from "../web/http.js";

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
 * A family's first fourteen days (`first_days` from the API): what they can
 * see here, child by child, in two short lines. Only this caller's own
 * children reach this page (`card_api._children_of()`).
 *
 * "Report card ready" only for a card released to families and not being
 * held: the API lists nothing else, and a held card says so in the list
 * below instead. Fees only where the existing page would show them, which is
 * where to pay (`payInto`, from `GET /api/fees/virtual/mine/`), never a
 * balance.
 */
export function welcome({ name = "", children = [], payInto = {} } = {}) {
  if (!children.length) return "";
  const lines = children.map((c) => {
    const ready = (c.cards || []).filter((card) => !card.is_withheld);
    const latest = ready[0]; // newest first (`card_api._cards_of()`)
    const cardLine = latest
      ? `<a href="/cards/${encodeURIComponent(c.student_membership_id)}/${encodeURIComponent(latest.term_id)}/">` +
        `See the report card</a>: ${esc(latest.term_label)} ${esc(latest.academic_session)} is ready`
      : "No report card has been released yet. It shows here as soon as the school releases it.";
    const pay = payInto[c.student_membership_id];
    const feeLine = pay
      ? `Fees: pay into ${esc(pay.bank_name)} <strong>${esc(pay.account_number)}</strong>, ${esc(pay.account_name)}`
      : "";
    return [
      `<li data-welcome-child="${esc(c.student_membership_id)}">`,
      `<strong>${esc(c.student_name)}</strong>`,
      `<span>${cardLine}</span>`,
      feeLine ? `<span>${feeLine}</span>` : "",
      "</li>",
    ].join("");
  });
  return [
    '<section class="welcome" data-state="welcome">',
    `<h2>Welcome${name ? `, ${esc(name)}` : ""}</h2>`,
    "<p>Here is what you can see for your children on Classnode.</p>",
    `<ul>${lines.join("")}</ul>`,
    "<p class=\"blank\">A child missing? Call the school office and they will add them to your account.</p>",
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
  return brokenState(connectionDropped(), "tell the school office if it keeps happening", { title: "This page could not load your cards" });
}
