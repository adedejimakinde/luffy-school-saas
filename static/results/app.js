/**
 * The approval chain: where every class stands, and one step at a time.
 *
 * Each step POSTs and gets **the row back as it now stands** — state, label
 * and the actions this login may take next — so one row is redrawn from the
 * answer. The page never works out the next state for itself: that would be a
 * second implementation of the chain, and the day it disagreed with
 * `results/services.py` the wrong one would be the one on screen.
 *
 * ## Four refusals, four sentences
 *
 * A step can fail in four ways whose remedies have nothing in common, so they
 * are not collapsed into "that did not work":
 *
 * - **already signed** — this person took a step on this pass. The body
 *   carries which one, so the page can say "you submitted this sheet" instead
 *   of "you may not check it". That is the whole reason
 *   `AlreadySignedThisCycle` carries the transition.
 * - **moved** — somebody else advanced it, or the release is final. The list
 *   is stale, so the page reloads it rather than leaving a button that will
 *   fail again.
 * - **needs a reason** — a send-back with an empty box.
 * - **not allowed** — a standing they do not have. No amount of retrying helps.
 */

import { failureNote, sessionEnded, signOut } from "../web/signout.js";
import { REFUSAL, STEP, fetchChain, takeStep } from "./api.js";
import * as states from "./states.js";

/** The markup for one state. Pure, so every branch is testable. */
export function htmlFor(state, { portal = "", signOutFailed = false } = {}) {
  const after = signOutFailed ? failureNote() : "";
  switch (state.step) {
    case "chain":
      return states.chain(state) + after;
    case "no-term":
      return states.noTerm() + after;
    case REFUSAL.NOT_ON_THE_CHAIN:
      return states.notOnTheChain(state) + after;
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

/**
 * Turn the chain answer into a state.
 *
 * A 200 with no current term is **not** a refusal: the password was right and
 * this person has a part in the chain. What is missing is a school setting.
 */
export function fromChain(answer) {
  if (!answer.ok) return { step: answer.refusal, ...answer.body };
  if (!answer.body.term_id) return { step: "no-term" };
  return { step: "chain", ...answer.body, notes: {}, asking: null };
}

/** Replace one row, keeping the rest of the list as it was. */
function replace(rows, row) {
  return (rows || []).map((r) =>
    r.class_group_id === row.class_group_id ? { ...r, ...row } : r,
  );
}

/**
 * What one step did to the list.
 *
 * `reload` comes back true when the answer says the page's copy is stale —
 * somebody else moved the sheet — because leaving the old buttons up offers a
 * step that will fail for the same reason a second time.
 */
export function applyStep(state, classGroupId, result) {
  const notes = { ...state.notes };
  if (result.ok) {
    delete notes[classGroupId];
    return {
      state: { ...state, notes, asking: null, rows: replace(state.rows, result.row) },
      reload: false,
    };
  }
  if (result.refusal) return { state: { step: result.refusal, ...result.body }, reload: false };

  if (result.outcome === STEP.ALREADY_SIGNED) {
    notes[classGroupId] = { kind: "already-signed", detail: result.body.detail };
    return { state: { ...state, notes, asking: null }, reload: false };
  }
  if (result.outcome === STEP.MOVED) {
    notes[classGroupId] = { kind: "moved", detail: result.body.detail };
    return { state: { ...state, notes, asking: null }, reload: true };
  }
  if (result.outcome === STEP.NEEDS_A_REASON) {
    // The box stays open: what is missing is the sentence, and closing the
    // form would make them find the class again to type it.
    notes[classGroupId] = { kind: "needs-a-reason", detail: result.body.detail };
    return { state: { ...state, notes, asking: classGroupId }, reload: false };
  }
  notes[classGroupId] = { kind: "not-allowed", detail: result.body.detail };
  return { state: { ...state, notes, asking: null }, reload: false };
}

export async function mount(root, { fetchImpl = fetch } = {}) {
  const portal = root.dataset.portal || "";
  let state = { step: "loading" };
  let signOutFailed = false;

  const draw = () => {
    root.innerHTML = htmlFor(state, { portal, signOutFailed });
  };
  const load = async () => {
    state = fromChain(await fetchChain({ fetchImpl }));
    draw();
  };

  await load();

  const step = async (classGroupId, name, reason) => {
    const result = await takeStep({ classGroupId, step: name, reason, fetchImpl });
    const applied = applyStep(state, classGroupId, result);
    state = applied.state;
    if (applied.reload) {
      // Keep the note that explains why, then refresh the rows under it.
      const notes = state.notes;
      await load();
      if (state.step === "chain") state = { ...state, notes };
    }
    draw();
  };

  // Delegated from the root: every state is redrawn wholesale, so a listener
  // bound to a button would be bound to a node about to be replaced.
  root.addEventListener("click", async (event) => {
    const hit = event.target.closest("[data-action]");
    if (!hit) return;
    const action = hit.dataset.action;

    if (action === "sign-out") {
      const ended = sessionEnded(await signOut({ fetchImpl }));
      if (ended) {
        root.innerHTML = states.signedOut({ portal });
        return;
      }
      signOutFailed = true;
      draw();
      return;
    }
    if (action === "ask-send-back") {
      state = { ...state, asking: Number(hit.dataset.class) };
      draw();
      return;
    }
    if (action === "step") {
      await step(Number(hit.dataset.class), hit.dataset.step);
    }
  });

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form || !form.reason) return;
    if (event.preventDefault) event.preventDefault();
    // Sent even when empty, deliberately: the server's refusal is the one that
    // names what is missing, and a page that refused first would be a second
    // rule to keep in step with `services.send_back()` and its constraint.
    await step(Number(form.dataset ? form.dataset.class : state.asking), "send-back", form.reason.value);
  });

  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("results");
  if (root) mount(root);
}
