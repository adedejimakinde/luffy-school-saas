/**
 * The sign-in flow: four steps, one route each way, and no state on the server.
 *
 * Everything the flow remembers — the number typed and the code that proved the
 * handset — lives in this module for the life of the page. It is deliberately
 * not in `sessionStorage`: a shared handset is the case this flow exists for,
 * and a code left in a browser's storage is a code the next person to pick up
 * the phone can replay. Closing the tab is meant to lose it.
 *
 * `advance()` is a pure function of (state, answer) -> next state, so the whole
 * flow can be tested without a DOM. `mount()` is the only part that touches the
 * document or the network.
 */

import { postJson } from "../web/http.js";
import { failureNote, sessionEnded, signOut } from "../web/signout.js";
import * as steps from "./states.js";

const CODE_URL = "/api/guardian/code/";
const SESSION_URL = "/api/guardian/session/";

export function initialState() {
  return { step: "ask", value: "", code: "", error: "", detail: "" };
}

/**
 * What one answer does to the flow. Pure, and the whole flow's logic.
 *
 * The 202 case is the one worth reading twice: it keeps `value` **and** `code`,
 * because the pick is sent back to the same route with the same code. Dropping
 * the code there is the bug that makes a shared handset a dead end — the parent
 * picks a name and is told the code is wrong.
 */
export function advance(state, { status, body }) {
  const it = { ...state, error: "" };

  if (status === 429) return { ...it, step: "throttled", body };
  if (status >= 500 || status === 0) return { ...it, step: "broken" };

  if (it.step === "ask") {
    if (status === 200) return { ...it, step: "code", detail: body.detail || "" };
    if (status === 403) return { ...it, step: "broken" };
    return { ...it, step: "ask", error: body.detail || "That did not work." };
  }

  // Both the code step and the pick send to the same route, so they read the
  // same answers. Keeping them in one branch is what stops the two drifting.
  if (status === 200) {
    const schools = body.schools || [];
    if (schools.length === 1) return { ...it, step: "leaving", body };
    if (schools.length === 0) return { ...it, step: "nowhere", body };
    return { ...it, step: "schools", body };
  }
  if (status === 202) {
    return { ...it, step: "whose", body, detail: body.detail || "" };
  }
  if (status === 401) {
    // A bad or expired code leaves the parent on the code step with the
    // sentence; a replayed pick is the same answer and the same recovery.
    return {
      ...it,
      step: "code",
      error: body.detail || "That code did not work.",
      code: "",
    };
  }
  return { ...it, step: "broken" };
}

/** The markup for a state. Pure, so the dispatch itself is testable. */
export function htmlFor(state) {
  switch (state.step) {
    case "ask":
      return steps.ask(state);
    case "code":
      return steps.code(state);
    case "whose":
      return steps.whose(state.body || {});
    case "schools":
      return steps.schools(state.body || {}) + note(state);
    case "nowhere":
      return steps.nowhere(state.body || {}) + note(state);
    case "throttled":
      return steps.throttled(state.body || {});
    case "leaving":
      return leaving(state.body || {});
    case "signed-out":
      return signedOut();
    default:
      return steps.broken();
  }
}

/**
 * The sign-out failure sentence, appended to whichever state was on screen.
 *
 * Appended rather than passed in, so `schools()` and `nowhere()` stay pure
 * functions of an API body and do not grow a parameter for a failure that has
 * nothing to do with what they render.
 */
function note(state) {
  return state.signOutFailed ? failureNote() : "";
}

/**
 * Signed out from one of the two states that hold a live session.
 *
 * The way back is this same page, which is where this reader already is, so the
 * link is relative — unlike the family pages on a school's host, whose way back
 * crosses to the portal and needs the hostname rendered into the frame.
 */
function signedOut() {
  return [
    '<section class="step step-signed-out" data-step="signed-out">',
    "<h1>Signed out</h1>",
    "<p>Your session has ended on this browser and on your school's pages.</p>",
    '<p><a href="/sign-in/">Sign in again</a></p>',
    "</section>",
  ].join("");
}

/** The one-school case: say where they are going, then go. */
function leaving(body) {
  const school = (body.schools || [])[0] || {};
  return [
    '<section class="step step-leaving" data-step="leaving">',
    "<h1>Taking you to your child's cards&hellip;</h1>",
    `<p>${school.name ? `${school.name}. ` : ""}`,
    "If nothing happens, use the link below.</p>",
    school.host ? `<p><a href="//${school.host}/cards/">Continue</a></p>` : "",
    "</section>",
  ].join("");
}

/**
 * Where a signed-in guardian goes next, or `null` to stay put.
 *
 * Protocol-relative to `location`, so a development deployment on plain HTTP
 * does not get an `https://` link it cannot serve, and a production one is
 * never downgraded.
 */
export function destination(state) {
  if (state.step !== "leaving") return null;
  const school = (state.body.schools || [])[0];
  return school && school.host ? `//${school.host}/cards/` : null;
}

export function mount(root, { fetchImpl = fetch, navigate = null } = {}) {
  let state = initialState();

  const draw = () => {
    root.innerHTML = htmlFor(state);
    root.dataset.step = state.step;
  };

  const send = async (url, payload) => {
    let answer;
    try {
      answer = await postJson(url, payload, { fetchImpl });
    } catch {
      answer = { status: 0, body: {} };
    }
    state = advance(state, answer);
    draw();
    const going = destination(state);
    if (going && navigate) navigate(going);
    return state;
  };

  root.addEventListener("submit", (event) => {
    event.preventDefault();
    const form = event.target;
    if (state.step === "ask") {
      state = { ...state, value: form.value.value.trim() };
      return send(CODE_URL, { value: state.value });
    }
    if (state.step === "code") {
      state = { ...state, code: form.code.value.trim() };
      return send(SESSION_URL, { value: state.value, code: state.code });
    }
    return undefined;
  });

  root.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-guardian],[data-action]");
    if (!button) return;
    if (button.dataset.action === "restart") {
      state = initialState();
      return draw();
    }
    if (button.dataset.action === "sign-out") {
      const answer = await signOut({ fetchImpl });
      state = sessionEnded(answer)
        ? { ...initialState(), step: "signed-out" }
        : { ...state, signOutFailed: true };
      return draw();
    }
    // The pick carries the code that is already spent on proving the handset,
    // and it is guarded on the attribute rather than reached by falling through
    // every other button.
    //
    // **The branches above return first, so this guard is the second line and
    // not the first** — stated precisely because the first version of this
    // comment claimed otherwise and a control proved it wrong. What the guard
    // is worth was measured: dropping the `return` from the sign-out branch
    // above leaves the suite green *because of this line*, and dropping both
    // turns `a sign-out tap is not posted as a guardian pick` red. What it
    // stops is a `[data-action]` reaching here at all — a sign-out posted as a
    // pick with an undefined guardian is a spent code answered with a 401 and
    // a family back at the code step for no reason they could see.
    if (!button.dataset.guardian) return undefined;
    return send(SESSION_URL, {
      value: state.value,
      code: state.code,
      guardian: button.dataset.guardian,
    });
  });

  draw();
  return { current: () => state };
}

if (typeof document !== "undefined") {
  const root = document.getElementById("signin");
  if (root) mount(root, { navigate: (url) => window.location.assign(url) });
}
