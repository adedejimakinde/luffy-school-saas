/**
 * The roll: who is enrolled, and which class each child is in.
 *
 * **Every write re-reads the roll**, like the setup screen and unlike the
 * marking sheet. Admitting a child adds a row; moving one changes a row and
 * can change what the class chooser should say next to it. Patching only what
 * was POSTed would leave the page telling a half-truth on a screen an office
 * works down a list on.
 *
 * The handle is typed, never generated — see `states.js`.
 */

import { failureNote, sessionEnded, signOut } from "../web/signout.js";
import { REFUSAL, SAVE, admit, fetchRoll, setClass } from "./api.js";
import * as states from "./states.js";

/** The markup for one state. Pure, so every branch is testable. */
export function htmlFor(state, { portal = "", signOutFailed = false } = {}) {
  const after = signOutFailed ? failureNote() : "";
  switch (state.step) {
    case "roll":
      return states.roll(state) + after;
    case REFUSAL.NOT_THE_OFFICE:
      return states.notTheOffice(state) + after;
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

export function fromRoll(answer) {
  if (!answer.ok) return { step: answer.refusal, ...answer.body };
  return { step: "roll", ...answer.body, notes: {} };
}

/**
 * What one write did to the screen.
 *
 * A **handle already taken** and a **rejected request** are different notes,
 * because they are different sentences to an administrator: one is a name to
 * change and the other is the school's state disagreeing with what was asked.
 * The form stays open with what was typed either way — retyping a name and
 * address to fix one field is the failure the refusal exists to prevent.
 */
export function applyWrite(state, key, result) {
  const notes = { ...state.notes };
  if (result.ok) {
    delete notes[key];
    return { state: { ...state, notes }, reload: true };
  }
  if (result.refusal) return { state: { step: result.refusal, ...result.body }, reload: false };
  const kind =
    result.outcome === SAVE.HANDLE_TAKEN
      ? "handle-taken"
      : result.outcome === SAVE.REJECTED
        ? "rejected"
        : "not-allowed";
  notes[key] = { kind, detail: result.body.detail };
  return { state: { ...state, notes }, reload: false };
}

export async function mount(root, { fetchImpl = fetch } = {}) {
  const portal = root.dataset.portal || "";
  let state = { step: "loading" };
  let signOutFailed = false;

  const draw = () => {
    root.innerHTML = htmlFor(state, { portal, signOutFailed });
  };
  const load = async (notes = {}) => {
    state = fromRoll(await fetchRoll({ fetchImpl }));
    if (state.step === "roll") state = { ...state, notes };
    draw();
  };

  await load();

  const after = async (key, result) => {
    const applied = applyWrite(state, key, result);
    state = applied.state;
    if (applied.reload) await load(state.notes);
    else draw();
  };

  root.addEventListener("click", async (event) => {
    const hit = event.target.closest("[data-action]");
    if (!hit || hit.dataset.action !== "sign-out") return;
    const ended = sessionEnded(await signOut({ fetchImpl }));
    if (ended) {
      root.innerHTML = states.signedOut({ portal });
      return;
    }
    signOutFailed = true;
    draw();
  });

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form || !form.username) return;
    if (event.preventDefault) event.preventDefault();

    const child = {
      full_name: form.full_name.value,
      username: form.username.value,
      reference: form.reference ? form.reference.value : "",
    };
    // Absent rather than null when no class was chosen: the field is optional
    // and "not yet" is a real answer, not an empty one.
    const chosen = form.class_group_id ? form.class_group_id.value : "";
    if (chosen !== "") child.class_group_id = Number(chosen);

    await after("admit", await admit({ child, fetchImpl }));
  });

  root.addEventListener("change", async (event) => {
    const field = event.target;
    if (!field || !field.dataset || field.dataset.child === undefined) return;
    if (state.step !== "roll") return;
    const chosen = String(field.value).trim();
    // Choosing "Not in a class yet" is not a move. Taking a child *out* of a
    // class is `remove_placement()`, a different act with a different service,
    // and doing it silently from a dropdown would be a removal nobody asked
    // for.
    if (chosen === "") return;

    await after(
      "place",
      await setClass({
        studentMembershipId: Number(field.dataset.child),
        classGroupId: Number(chosen),
        fetchImpl,
      }),
    );
  });

  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("roll");
  if (root) mount(root);
}
