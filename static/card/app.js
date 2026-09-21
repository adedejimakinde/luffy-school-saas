/**
 * The entry point: read two integers out of the document, ask, mount the answer.
 *
 * Everything else in this directory is a pure function. This is the only module
 * that touches the DOM or the network, which is what lets the rest be tested
 * with `node --test` and no browser.
 *
 * The ids come from `data-` attributes rather than from parsing
 * `window.location`, so the page's URL shape is the Django URLconf's business
 * and changing it does not mean changing a regular expression in here.
 */

import { fetchCard, provesASession, REFUSAL } from "./api.js";
import { button as signOutButton, failureNote, sessionEnded, signOut } from "../web/signout.js";
import * as states from "./states.js";
import { card } from "./render.js";

const STATE_RENDERERS = {
  [REFUSAL.WITHHELD]: states.withheld,
  [REFUSAL.MISSING]: states.missing,
  [REFUSAL.EXPIRED]: states.expired,
  [REFUSAL.SIGNED_OUT]: states.signedOut,
  [REFUSAL.BROKEN]: states.broken,
};

/**
 * What to put in the page for one answer. Pure, so a test can cover the
 * dispatch itself rather than only the states it dispatches to.
 *
 * An unknown refusal falls to `broken()` instead of rendering nothing: a blank
 * page is the one outcome that tells a parent neither what happened nor what to
 * do about it.
 */
export function htmlFor(answer, { portal = "", signOutFailed = false } = {}) {
  const after =
    (signOutFailed ? failureNote() : "") +
    (provesASession(answer) ? signOutButton() : "");
  if (answer.ok) return card(answer.card) + after;
  const render = STATE_RENDERERS[answer.refusal] || states.broken;
  // Two arguments, and only two of the five renderers read the second: the
  // card page is on a school's host and sign-in is on the portal, so the way
  // back cannot be a relative link and cannot come from the API either.
  return render(answer.body || {}, { portal }) + after;
}

export async function mount(root, { fetchImpl = fetch } = {}) {
  const portal = root.dataset.portal || "";
  root.innerHTML = states.loading();
  const answer = await fetchCard({
    studentMembershipId: root.dataset.studentMembershipId,
    termId: root.dataset.termId,
    fetchImpl,
  });
  let signOutFailed = false;
  const draw = () => {
    root.innerHTML = htmlFor(answer, { portal, signOutFailed });
    // Said out loud for the print stylesheet and for anything watching: which
    // of the states the page settled in, on the element itself.
    root.dataset.state = answer.ok ? "card" : answer.refusal;
  };
  draw();

  root.addEventListener("click", async (event) => {
    if (!event.target.closest('[data-action="sign-out"]')) return;
    if (sessionEnded(await signOut({ fetchImpl }))) {
      // The card goes with the session. It was served to somebody who proved a
      // claim on it, and leaving it on screen after that claim has been given
      // up is the shared handset this platform is built for, holding a child's
      // marks for whoever picks it up next.
      root.innerHTML = states.signedOut({}, { portal });
      root.dataset.state = REFUSAL.SIGNED_OUT;
      return;
    }
    signOutFailed = true;
    draw();
  });

  return answer;
}

// `defer` on the script tag means the document is parsed by the time this runs,
// so there is no readiness dance.
//
// Both guards earn their place. `typeof document` is what lets `node --test`
// import this module to test `htmlFor()` — without it the import itself would
// throw in a runtime that has no DOM, and the dispatch would be the one part of
// the page with no test. The `root` guard means a page that loaded the module
// without the element does nothing rather than throwing into the console.
if (typeof document !== "undefined") {
  const root = document.getElementById("card");
  if (root) mount(root);
}
