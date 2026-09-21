/**
 * School setup: the calendar, and the groups children sit in.
 *
 * The office's own screen. Two forms and one button, and everything it writes
 * is a thing every other tenant table hangs off — a placement, a register, a
 * result sheet, a card.
 *
 * **Every write reloads the shape rather than patching one row.** The other
 * screens redraw a row from the answer, and this one deliberately does not:
 * making a term current *changes another row* — the one that stops being
 * current — and a page that patched only the row it POSTed would show two
 * terms as current until somebody refreshed. Reloading is one extra request on
 * a screen used a handful of times a year.
 */

import { failureNote, sessionEnded, signOut } from "../web/signout.js";
import { REFUSAL, SAVE, createClass, createTerm, fetchSetup, makeCurrent } from "./api.js";
import * as states from "./states.js";

/** The markup for one state. Pure, so every branch is testable. */
export function htmlFor(state, { portal = "", signOutFailed = false } = {}) {
  const after = signOutFailed ? failureNote() : "";
  switch (state.step) {
    case "setup":
      return states.shape(state) + after;
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

export function fromSetup(answer) {
  if (!answer.ok) return { step: answer.refusal, ...answer.body };
  return { step: "setup", ...answer.body, notes: {} };
}

/**
 * What one write did to the screen.
 *
 * A rejection keeps the form open with the server's sentence under it — the
 * calendar disagreeing with itself is something the person retypes, and
 * clearing the form would make them type all of it again to fix one date.
 */
export function applyWrite(state, key, result) {
  const notes = { ...state.notes };
  if (result.ok) {
    delete notes[key];
    return { state: { ...state, notes }, reload: true };
  }
  if (result.refusal) return { state: { step: result.refusal, ...result.body }, reload: false };
  notes[key] = {
    kind: result.outcome === SAVE.REJECTED ? "rejected" : "not-allowed",
    detail: result.body.detail,
  };
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
    state = fromSetup(await fetchSetup({ fetchImpl }));
    if (state.step === "setup") state = { ...state, notes };
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
    if (!hit) return;
    if (hit.dataset.action === "sign-out") {
      const ended = sessionEnded(await signOut({ fetchImpl }));
      if (ended) {
        root.innerHTML = states.signedOut({ portal });
        return;
      }
      signOutFailed = true;
      draw();
      return;
    }
    if (hit.dataset.action === "make-current") {
      await after(
        "term",
        await makeCurrent({ termId: Number(hit.dataset.term), fetchImpl }),
      );
    }
  });

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form) return;
    if (event.preventDefault) event.preventDefault();

    if (form.session) {
      // Sent as typed. The server's `full_clean()` is what turns the model's
      // constraints into sentences, and a page that validated dates first
      // would be a second rule to keep in step with them.
      await after("term", await createTerm({
        term: {
          session: form.session.value,
          name: form.name.value,
          starts_on: form.starts_on.value,
          ends_on: form.ends_on.value,
        },
        fetchImpl,
      }));
      return;
    }
    if (form.name) {
      await after("class", await createClass({
        group: { name: form.name.value, level: Number(form.level.value || 0) },
        fetchImpl,
      }));
    }
  });

  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("setup");
  if (root) mount(root);
}
