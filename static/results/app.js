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

import {
  REFUSAL,
  STEP,
  fetchChain,
  previewFamilies,
  printSlips,
  takeStep,
  tellFamilies,
} from "./api.js";
import * as states from "./states.js";

/** The markup for one state. Pure, so every branch is testable. */
export function htmlFor(state, { portal = "" } = {}) {
  switch (state.step) {
    case "chain":
      return states.chain(state);
    case "no-term":
      return states.noTerm();
    case REFUSAL.NOT_ON_THE_CHAIN:
      return states.notOnTheChain(state);
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
export function fromChain(answer, { focus = null } = {}) {
  if (!answer.ok) return { step: answer.refusal, ...answer.body };
  if (!answer.body.term_id) return { step: "no-term" };
  return {
    step: "chain",
    ...answer.body,
    notes: {},
    asking: null,
    telling: null,
    confirming: null,
    focus,
  };
}

/**
 * The class the page was opened for, from `?class=`: the home page's
 * "Waiting for you" links here, and the row it named is the one to show.
 */
export function focusFrom(search = "") {
  const id = Number(new URLSearchParams(search).get("class"));
  return Number.isInteger(id) && id > 0 ? id : null;
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
      state: { ...state, notes, asking: null, confirming: null, rows: replace(state.rows, result.row) },
      reload: false,
    };
  }
  if (result.refusal) return { state: { step: result.refusal, ...result.body }, reload: false };

  if (result.outcome === STEP.ALREADY_SIGNED) {
    notes[classGroupId] = { kind: "already-signed", detail: result.body.detail };
    return { state: { ...state, notes, asking: null, confirming: null }, reload: false };
  }
  if (result.outcome === STEP.MOVED) {
    notes[classGroupId] = { kind: "moved", detail: result.body.detail };
    return { state: { ...state, notes, asking: null, confirming: null }, reload: true };
  }
  if (result.outcome === STEP.NEEDS_A_REASON) {
    // The box stays open: what is missing is the sentence, and closing the
    // form would make them find the class again to type it.
    notes[classGroupId] = { kind: "needs-a-reason", detail: result.body.detail };
    return { state: { ...state, notes, asking: classGroupId, confirming: null }, reload: false };
  }
  if (result.outcome === STEP.NOT_CHECKED) {
    // No reload: the row is as it was, approved, and its Release button is
    // the recovery. The note says why the class is not released.
    notes[classGroupId] = { kind: "not-checked", detail: result.body.detail };
    return { state: { ...state, notes, asking: null, confirming: null }, reload: false };
  }
  notes[classGroupId] = { kind: "not-allowed", detail: result.body.detail };
  return { state: { ...state, notes, asking: null, confirming: null }, reload: false };
}

/**
 * Hand the browser a file to save, from a `Blob` already in memory.
 *
 * The slips PDF is the only place the PINs are ever written out, so it is
 * handed over and let go: the object URL is revoked once the download has had
 * time to start, rather than kept for the life of the page.
 */
export function saveFile(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

/** What the row says after a press, from `printSlips()`'s answer. */
export function slipsNote(result) {
  if (result.ok) {
    return {
      kind: "slips-printed",
      detail: `The slips are downloading as ${result.filename}. Print them, and give each child theirs with the report card.`,
    };
  }
  return { kind: "not-printed", detail: result.detail || "No slips were printed." };
}

export async function mount(root, { fetchImpl = fetch, download = saveFile, search = "" } = {}) {
  const portal = root.dataset.portal || "";
  const focus = focusFrom(search);
  let state = { step: "loading" };

  const draw = () => {
    root.innerHTML = htmlFor(state, { portal });
  };
  const load = async () => {
    state = fromChain(await fetchChain({ fetchImpl }), { focus });
    draw();
  };

  await load();
  if (focus && typeof root.querySelector === "function") {
    const row = root.querySelector(`#class-${focus}`);
    if (row && typeof row.scrollIntoView === "function") row.scrollIntoView({ block: "center" });
  }

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

  // Result-checker slips (docs/messaging.md D11). A PDF on success, which is
  // saved and then the rows fetched again for the count; a refusal is a
  // sentence on the row.
  const printing = async (classGroupId, admissionNumber) => {
    const result = await printSlips({ classGroupId, admissionNumber, fetchImpl });
    if (result.refusal) {
      state = { step: result.refusal, ...(result.body || {}) };
      draw();
      return;
    }
    const notes = { ...state.notes, [classGroupId]: slipsNote(result) };
    if (result.ok) {
      download(result.blob, result.filename);
      await load();
      if (state.step === "chain") state = { ...state, notes };
    } else {
      state = { ...state, notes };
    }
    draw();
  };

  // Delegated from the root: every state is redrawn wholesale, so a listener
  // bound to a button would be bound to a node about to be replaced.
  root.addEventListener("click", async (event) => {
    const hit = event.target.closest("[data-action]");
    if (!hit) return;
    const action = hit.dataset.action;

    if (action === "ask-send-back") {
      state = { ...state, asking: Number(hit.dataset.class), confirming: null };
      draw();
      return;
    }
    if (action === "ask-release") {
      // Asks first: a release cannot be taken back. Nothing is sent until the
      // question's own button, which is a `step` like any other.
      state = { ...state, confirming: Number(hit.dataset.class), asking: null };
      draw();
      return;
    }
    if (action === "cancel-release") {
      state = { ...state, confirming: null };
      draw();
      return;
    }
    if (action === "step") {
      await step(Number(hit.dataset.class), hit.dataset.step);
      return;
    }
    if (action === "tell-families") {
      // Asks first (docs/messaging.md D9): the preview writes nothing, and
      // nothing is sent until "Send them".
      const classGroupId = Number(hit.dataset.class);
      const result = await previewFamilies({ classGroupId, fetchImpl });
      if (result.refusal) {
        state = { step: result.refusal, ...result.body };
      } else if (!result.ok) {
        const notes = { ...state.notes, [classGroupId]: { kind: "not-told", detail: result.body.detail } };
        state = { ...state, notes, telling: null };
      } else {
        const notes = { ...state.notes };
        delete notes[classGroupId];
        state = { ...state, notes, telling: { class_group_id: classGroupId, ...result.body } };
      }
      draw();
      return;
    }
    if (action === "print-slips") {
      await printing(Number(hit.dataset.class), "");
      return;
    }
    if (action === "cancel-telling") {
      state = { ...state, telling: null };
      draw();
      return;
    }
    if (action === "send-to-families") {
      const classGroupId = Number(hit.dataset.class);
      const result = await tellFamilies({ classGroupId, fetchImpl });
      if (result.refusal) {
        state = { step: result.refusal, ...result.body };
        draw();
        return;
      }
      const notes = { ...state.notes, [classGroupId]: { kind: result.ok ? "told" : "not-told", detail: result.body.detail } };
      await load();
      if (state.step === "chain") state = { ...state, notes };
      draw();
    }
  });

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (form && form.admission_number && form.class_group_id) {
      // A lost slip. Sent as typed: the server trims it, and says so if no
      // child in the class has that number.
      if (event.preventDefault) event.preventDefault();
      await printing(Number(form.class_group_id.value), form.admission_number.value);
      return;
    }
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
  if (root) mount(root, { search: window.location.search });
}
