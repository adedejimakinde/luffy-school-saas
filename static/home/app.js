/**
 * The principal's home: one read, drawn once. Nothing on it writes except
 * sign-out; every row's button is a link to the screen that does the work.
 */

import { failureNote, sessionEnded, signOut } from "../web/signout.js";
import { REFUSAL, fetchHome } from "./api.js";
import * as states from "./states.js";

/** The markup for one state. Pure, so every branch is testable. */
export function htmlFor(state, { portal = "", signOutFailed = false } = {}) {
  const after = signOutFailed ? failureNote() : "";
  switch (state.step) {
    case "home":
      return states.home(state) + after;
    case REFUSAL.NOT_YOURS:
      return states.notYours(state) + after;
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
  let signOutFailed = false;
  const state = fromHome(await fetchHome({ fetchImpl }));
  const draw = () => {
    root.innerHTML = htmlFor(state, { portal, signOutFailed });
  };
  draw();

  root.addEventListener("click", async (event) => {
    const hit = event.target.closest("[data-action]");
    if (!hit || hit.dataset.action !== "sign-out") return;
    if (sessionEnded(await signOut({ fetchImpl }))) {
      root.innerHTML = states.signedOut({ portal });
      return;
    }
    signOutFailed = true;
    draw();
  });

  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("home");
  if (root) mount(root);
}
