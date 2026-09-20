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
import * as states from "./states.js";

const INDEX_URL = "/api/results/cards/";

/** The markup for one answer. Pure, so every branch is testable. */
export function htmlFor({ status, body }, { portal = "" } = {}) {
  if (status === 401) {
    return states.signedOut({ portal, expired: body && body.code === "session_expired" });
  }
  if (status !== 200 || !body) return states.broken();

  const children = body.children || [];
  const cards = children.reduce((n, child) => n + (child.cards || []).length, 0);
  if (!cards) return states.nothing({ hasChildren: children.length > 0 });

  return [
    '<section class="index" data-state="cards">',
    "<h1>Report cards</h1>",
    children.map(child).join(""),
    "</section>",
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
  root.innerHTML = '<p class="state state-loading">Fetching your cards&hellip;</p>';
  let answer;
  try {
    answer = await getJson(INDEX_URL, { fetchImpl });
  } catch {
    answer = { status: 0, body: null };
  }
  root.innerHTML = htmlFor(answer, { portal: root.dataset.portal || "" });
  return answer;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("index");
  if (root) mount(root);
}
