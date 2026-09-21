/**
 * The index: every child this caller stands for at this school, and their cards.
 *
 * Without this page a parent cannot reach a card at all. Both card routes are
 * keyed on `(student_membership_id, term_id)` and nothing this API says to a
 * family carried either number until `GET /api/results/cards/` — so the card
 * page shipped reachable only by typing two integers into a URL. This is the
 * page that closes that.
 *
 * A renderer, like the card page: the API sends the children in order and each
 * child's cards newest first, and this walks them.
 *
 * ## A withheld card is listed and marked, never hidden
 *
 * `is_withheld` comes back true for a card the school is holding over fees, and
 * the row is rendered with a mark on it and a link that still goes to the card
 * page — where the 403 explains itself and names who to contact. Hiding the row
 * would defeat what withholding is *for*: a school holds a card back to start a
 * conversation, and a card that never appears starts none. The index carries no
 * card content, which is what makes listing it safe — `ListedCardOut` has no
 * slot for a mark, an average, a remark or a rating.
 */

import { getJson } from "../web/http.js";
import { esc } from "../web/html.js";
import { button as signOutButton, failureNote, sessionEnded, signOut } from "../web/signout.js";
import * as states from "./states.js";

const INDEX_URL = "/api/results/cards/";

/**
 * The markup for one answer. Pure, so every branch is testable.
 *
 * **The sign-out button is shown on a 200 and on nothing else.** A 200 is the
 * API having answered this caller about their own children, which it does for
 * nobody who is not signed in — so it is the one status that proves there is a
 * session to end. A 401 is the opposite and already says so. A 500 or a dead
 * transport proves nothing either way, and a button that posts a logout from a
 * page that cannot reach the server is a control that does nothing while
 * looking like it did.
 *
 * `signOutFailed` is the answer to a tap that did not work, and it is rendered
 * below the list rather than in place of it: the cards are still there and
 * still readable, and what changed is only that the session is still open.
 */
export function htmlFor({ status, body }, { portal = "", signOutFailed = false } = {}) {
  if (status === 401) {
    return states.signedOut({ portal, expired: body && body.code === "session_expired" });
  }
  if (status !== 200 || !body) return states.broken();

  const children = body.children || [];
  const cards = children.reduce((n, child) => n + (child.cards || []).length, 0);
  const after = (signOutFailed ? failureNote() : "") + signOutButton();
  if (!cards) return states.nothing({ hasChildren: children.length > 0 }) + after;

  return [
    '<section class="index" data-state="cards">',
    "<h1>Report cards</h1>",
    children.map(child).join(""),
    "</section>",
    after,
  ].join("");
}

function child(record) {
  const cards = record.cards || [];
  return [
    '<section class="child">',
    `<h2>${esc(record.student_name)}</h2>`,
    cards.length
      ? `<ul class="cards">${cards.map((c) => card(record, c)).join("")}</ul>`
      : '<p class="blank">No cards released yet.</p>',
    "</section>",
  ].join("");
}

/**
 * One card in the list.
 *
 * The version appears only when there is more than one, which is exactly the
 * case where two cards for one child and one term can sit in a parent's hand
 * and the superseded one must not be mistaken for the card that stands. Same
 * rule as the stored PDF's filename.
 */
function card(record, entry) {
  const href = `/cards/${encodeURIComponent(record.student_membership_id)}/${encodeURIComponent(entry.term_id)}/`;
  const marks = [
    entry.is_revised ? '<span class="tag revised">Revised</span>' : "",
    entry.is_withheld ? '<span class="tag held">Being held by the school</span>' : "",
    entry.version > 1 ? `<span class="tag">Version ${esc(entry.version)}</span>` : "",
  ].join("");
  return [
    `<li${entry.is_withheld ? ' class="withheld"' : ""}>`,
    `<a href="${href}">${esc(entry.term_label)} &middot; ${esc(entry.academic_session)}</a>`,
    marks,
    "</li>",
  ].join("");
}

export async function mount(root, { fetchImpl = fetch } = {}) {
  const portal = root.dataset.portal || "";
  root.innerHTML = '<p class="state state-loading">Fetching your cards&hellip;</p>';
  let answer;
  try {
    answer = await getJson(INDEX_URL, { fetchImpl });
  } catch {
    answer = { status: 0, body: null };
  }
  let signOutFailed = false;
  const draw = () => {
    root.innerHTML = htmlFor(answer, { portal, signOutFailed });
  };
  draw();

  // Delegated from the root, because the button is redrawn on every state and
  // a listener bound to the element itself would be bound to a node that is
  // about to be replaced.
  root.addEventListener("click", async (event) => {
    if (!event.target.closest('[data-action="sign-out"]')) return;
    const ended = sessionEnded(await signOut({ fetchImpl }));
    if (ended) {
      // Not `signedOut({expired: true})`. Signing out on purpose deletes the
      // cookie as well as the session, so nothing lapsed and nothing is
      // recoverable by trying again — `docs/membership.md` draws exactly that
      // line, and telling somebody who chose to sign out that their session
      // "ended" would invite them to expect their place back.
      root.innerHTML = states.signedOut({ portal });
      return;
    }
    signOutFailed = true;
    draw();
  });

  return answer;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("index");
  if (root) mount(root);
}
