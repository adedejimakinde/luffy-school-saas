/**
 * The staff sign-in flow: one step, one route, and nothing kept anywhere.
 *
 * `advance()` is a pure function of (state, answer) -> next state and
 * `htmlFor()` is a pure function of state, so the whole flow is testable
 * without a DOM. `mount()` is the only part that touches the document or the
 * network — the shape `signin/app.js` established next door.
 *
 * ## The password is never in the state
 *
 * The guardian flow holds the number and the code in module memory because its
 * second request needs both. This one has no second request: the password goes
 * from the field into the POST body and is not copied anywhere, so there is
 * nothing for a later screen to leak and nothing to clear. The identifier is
 * kept, only so a refusal does not make somebody retype the field that was not
 * wrong.
 *
 * ## Where this page is, and why it is not on a school's host
 *
 * The portal, mounted in `urls_public.py` alone, because `api.sign_in()` begins
 * with `_portal_only()`: a school's host refuses anybody without an active
 * membership *there*, so the same credentials would work on one hostname and
 * not another, and a teacher who is also a parent elsewhere would need two
 * sessions. A form mounted where its route is not is a form that submits into a
 * 404.
 */

import { failureNote, sessionEnded, signOut } from "../web/signout.js";
import { postJson } from "../web/http.js";
import * as steps from "./states.js";

const LOGIN_URL = "/api/login/";

export function initialState() {
  return { step: "ask", identifier: "", error: "", body: {} };
}

/**
 * What one answer does to the flow. Pure, and the whole of the flow's logic.
 *
 * The 200 split is the part worth reading twice: `schools: []` is a **success**
 * and not a refusal. `user.schools()` is scoped to ACTIVE memberships alone, so
 * a suspended teacher and an invited one who never accepted both authenticate
 * perfectly and reach it, and a page that treated an empty list as a failure
 * would tell them their password was wrong.
 *
 * A 403 here is not a refusal to explain either: `postJson` has already
 * refetched the token and retried once, so a 403 that survives is a door
 * refusing everything, which is `broken` rather than something to advise on.
 */
export function advance(state, { status, body }) {
  const it = { ...state, error: "", body: body || {} };

  if (status === 429) return { ...it, step: "throttled" };
  if (status >= 500 || status === 0) return { ...it, step: "broken" };

  if (status === 200) {
    const schools = it.body.schools || [];
    return { ...it, step: schools.length ? "landed" : "nowhere" };
  }
  if (status === 401) {
    // One sentence for all four failures, straight from `signin.REFUSED`. The
    // page does not improve on it: splitting "no such account" from "wrong
    // password" is how a sign-in route becomes an account-existence oracle.
    return {
      ...it,
      step: "ask",
      error: it.body.detail || "That identifier and password do not match an account.",
    };
  }
  return { ...it, step: "broken" };
}

/**
 * What a sign-out answer does. Pure, and separate from `advance()` on purpose.
 *
 * Sign-out is not an answer from the sign-in route and folding it into
 * `advance()` would mean one function reading two routes' statuses, where a
 * 401 means "wrong password" for one and "there was nothing to end" for the
 * other. `sessionEnded()` holds that judgement for every page that has the
 * button.
 */
export function afterSignOut(state, answer) {
  if (sessionEnded(answer)) return { ...initialState(), step: "signed-out" };
  return { ...state, signOutFailed: true };
}

/** The markup for a state. Pure, so the dispatch itself is testable. */
export function htmlFor(state) {
  const body = state.body || {};
  switch (state.step) {
    case "ask":
      return steps.ask(state);
    case "landed":
      return steps.landed(body) + note(state);
    case "nowhere":
      return steps.nowhere(body) + note(state);
    case "throttled":
      return steps.throttled(body);
    case "signed-out":
      return steps.signedOut();
    default:
      return steps.broken();
  }
}

/**
 * The one sentence a signed-in state can carry: a sign-out that did not work.
 *
 * Appended rather than passed in, so `landed()` and `nowhere()` stay pure
 * functions of an API body and do not grow a parameter for a failure that has
 * nothing to do with what they render. The sentence itself lives in
 * `web/signout.js`, beside the judgement that decides when to show it.
 */
function note(state) {
  return state.signOutFailed ? failureNote() : "";
}

export function mount(root, { fetchImpl = fetch } = {}) {
  let state = initialState();

  const draw = () => {
    root.innerHTML = htmlFor(state);
    root.dataset.step = state.step;
  };

  root.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    const identifier = form.identifier.value.trim();
    // Not trimmed: a password's leading and trailing spaces are part of it.
    const password = form.password.value;
    state = { ...state, identifier };

    let answer;
    try {
      answer = await postJson(LOGIN_URL, { identifier, password }, { fetchImpl });
    } catch {
      answer = { status: 0, body: {} };
    }
    state = advance(state, answer);
    draw();
  });

  root.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    if (button.dataset.action === "restart") {
      state = initialState();
      return draw();
    }
    if (button.dataset.action === "sign-out") {
      state = afterSignOut(state, await signOut({ fetchImpl }));
      return draw();
    }
    return undefined;
  });

  draw();
  return { current: () => state };
}

if (typeof document !== "undefined") {
  const root = document.getElementById("staff-signin");
  if (root) mount(root);
}
