/**
 * The principal's home: one read, drawn once. Nothing on it writes: every
 * row's button is a link to the screen that does the work. Sign out is the
 * menu's, not this page's.
 */

import { REFUSAL, fetchHome } from "./api.js";
import * as states from "./states.js";

/** The markup for one state. Pure, so every branch is testable. */
export function htmlFor(state, { portal = "" } = {}) {
  switch (state.step) {
    case "home":
      return states.home(state);
    case REFUSAL.NOT_YOURS:
      return states.notYours(state);
    case REFUSAL.WRONG_HOST:
      return states.wrongHost();
    case REFUSAL.EXPIRED:
      return states.signedOut({ portal, expired: true });
    case REFUSAL.SIGNED_OUT:
      return states.signedOut({ portal });
    default:
      return states.broken();
  }
}

export function fromHome(answer) {
  if (!answer.ok) return { step: answer.refusal, ...answer.body };
  return { step: "home", ...answer.body };
}

export async function mount(root, { fetchImpl = fetch } = {}) {
  const portal = root.dataset.portal || "";
  const state = fromHome(await fetchHome({ fetchImpl }));
  root.innerHTML = htmlFor(state, { portal });
  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("home");
  if (root) mount(root);
}
