/**
 * Who is absent too often: one term's list, and what "too often" means here.
 *
 * `?term=` opens a term directly; otherwise the server picks the school's
 * current one. The principal and an administrator can change the threshold
 * from the page; the list is fetched again after a save, so what it shows was
 * drawn by the rule it prints.
 */

import { failureNote, sessionEnded, signOut } from "../web/signout.js";
import { REFUSAL, fetchAbsences, saveThreshold } from "./api.js";
import * as states from "./states.js";

export function htmlFor(state, { portal = "", signOutFailed = false } = {}) {
  const after = signOutFailed ? failureNote() : "";
  switch (state.step) {
    case "list":
      return states.list(state) + after;
    case "no-term":
      return states.noTerm(state) + after;
    case REFUSAL.NOT_YOURS:
      return states.notYours() + after;
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

export async function mount(root, { fetchImpl = fetch, search = "" } = {}) {
  const portal = root.dataset.portal || "";
  const asked = new URLSearchParams(search).get("term");
  let state = { step: "loading" };
  let signOutFailed = false;
  const draw = () => {
    root.innerHTML = htmlFor(state, { portal, signOutFailed });
  };

  if (root.dataset.onSchool !== "yes") {
    state = { step: REFUSAL.WRONG_HOST };
    draw();
    return state;
  }

  const show = async (termId, note = "") => {
    const answer = await fetchAbsences({ termId, fetchImpl });
    if (!answer.ok) {
      state = { step: answer.refusal };
    } else if (answer.body.term_id === null) {
      state = { step: "no-term", absences: answer.body };
    } else {
      state = { step: "list", absences: answer.body, note };
    }
    draw();
  };

  await show(asked ? Number(asked) : null);

  root.addEventListener("change", async (event) => {
    const field = event.target;
    if (!field || !field.dataset || field.dataset.term === undefined) return;
    await show(Number(field.value));
  });

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form || !form.threshold_percent) return;
    if (event.preventDefault) event.preventDefault();
    if (state.step !== "list") return;
    // Sent as typed. The route's bounds are what turn a bad number into a
    // sentence, and a page that checked first would be a second rule to keep
    // in step with them.
    const saved = await saveThreshold({
      thresholdPercent: Number(form.threshold_percent.value),
      minMarkedDays: Number(form.min_marked_days.value),
      fetchImpl,
    });
    if (saved.ok) {
      await show(state.absences.term_id, "Saved. The list below uses the new rule.");
      return;
    }
    if (saved.refusal) {
      state = { step: saved.refusal };
      draw();
      return;
    }
    state = { ...state, note: saved.body.detail || "That could not be saved." };
    draw();
  });

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

  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("absences");
  if (root) mount(root, { search: window.location.search });
}
