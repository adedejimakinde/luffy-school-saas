/**
 * The result checker's entry point: a form, one request, and the answer drawn.
 *
 * The only module here that touches the DOM or the network, which is what lets
 * the rest be tested with `node --test` and no browser — `card/app.js`'s rule.
 * `htmlFor()` and `afterAnswer()` are pure and exported for the same reason.
 */

import { ANSWER, check } from "./api.js";
import * as states from "./states.js";

/** Where the page starts, and where "Check another card" returns it. */
export const EMPTY = { step: "form", admissionNumber: "", note: null };

/** The markup for one state. */
export function htmlFor(state, { portal = "" } = {}) {
  if (state.step === "card") return states.opened(state.card);
  if (state.step === "withheld") return states.withheld(state.body);
  return states.form({ admissionNumber: state.admissionNumber, note: state.note, portal });
}

/**
 * What one answer does to the page.
 *
 * A card or a withheld refusal replaces the form; every other answer redraws
 * the form with a note above it, the admission number kept and the PIN box
 * empty (`states.form()` says why).
 */
export function afterAnswer(admissionNumber, answer) {
  if (answer.kind === ANSWER.CARD) return { step: "card", card: answer.body };
  if (answer.kind === ANSWER.WITHHELD) return { step: "withheld", body: answer.body };
  if (answer.kind === ANSWER.NOT_OPENED) {
    return { ...EMPTY, admissionNumber, note: { kind: states.NOTE.NOT_OPENED, detail: answer.body.detail } };
  }
  if (answer.kind === ANSWER.WAIT) {
    return {
      ...EMPTY,
      admissionNumber,
      note: { kind: states.NOTE.WAIT, detail: answer.body.detail, retryAfter: answer.body.retry_after },
    };
  }
  return { ...EMPTY, admissionNumber, note: { kind: states.NOTE.BROKEN } };
}

export function mount(root, { fetchImpl = fetch } = {}) {
  const portal = root.dataset.portal || "";
  let state = EMPTY;

  const draw = () => {
    root.innerHTML = htmlFor(state, { portal });
    root.dataset.state = state.step;
  };
  draw();

  // Delegated from the root: every state is redrawn wholesale, so a listener
  // bound to the form would be bound to a node about to be replaced.
  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form || !form.pin) return;
    if (event.preventDefault) event.preventDefault();
    const admissionNumber = form.admission_number ? form.admission_number.value : "";
    const answer = await check({ admissionNumber, pin: form.pin.value, fetchImpl });
    state = afterAnswer(admissionNumber, answer);
    draw();
  });

  root.addEventListener("click", (event) => {
    if (!event.target.closest('[data-action="check-another"]')) return;
    state = EMPTY;
    draw();
  });

  return root;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("checker");
  if (root) mount(root);
}
