/**
 * Student ID cards: choose a term, press Print on a class, choose the children
 * (or none for the whole class), and watch the file being made.
 *
 * The file is made by a worker. The page asks how the job is getting on every
 * couple of seconds while it is being made, and stops when it is ready, has
 * failed, or the panel is closed. Nothing here is a person's data beyond a name
 * and an admission number, drawn from the API and never kept.
 */

import { REFUSAL, fetchJob, fetchOverview, fetchRoster, startPrint } from "./api.js";
import * as states from "./states.js";

const POLL_MS = 2000;

/** The markup for one state. Pure, so every branch is testable. */
export function htmlFor(state, { portal = "" } = {}) {
  switch (state.step) {
    case "id-cards":
      return states.overview(state);
    case REFUSAL.NOT_YOURS:
      return states.notYours(state);
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

export function fromOverview(answer) {
  if (!answer.ok) return { step: answer.refusal, ...answer.body };
  return { printing: null, notes: {}, ...answer.body, step: "id-cards" };
}

/** A job still being made is one the page keeps asking about. */
export const stillMaking = (job) => job.state === "pending" || job.state === "building";

export async function mount(root, { fetchImpl = fetch, wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms)) } = {}) {
  const portal = root.dataset.portal || "";
  let state = fromOverview(await fetchOverview({ fetchImpl }));
  const draw = () => {
    root.innerHTML = htmlFor(state, { portal });
  };
  draw();

  const refusedForPage = (result) => {
    state = { step: result.refusal, ...(result.body || {}) };
    draw();
  };
  const sameJob = (jobId) => state.printing && state.printing.job && state.printing.job.id === jobId;

  const watch = async (jobId) => {
    while (sameJob(jobId) && stillMaking(state.printing.job)) {
      await wait(POLL_MS);
      if (!sameJob(jobId)) return;
      const result = await fetchJob({ jobId, fetchImpl });
      if (result.refusal) return refusedForPage(result);
      if (!sameJob(jobId)) return;
      if (!result.ok) {
        const classId = state.printing.class_group_id;
        state = { ...state, printing: null, notes: { [classId]: (result.body || {}).detail || "The cards could not be made." } };
        draw();
        return;
      }
      state = { ...state, printing: { ...state.printing, job: result.body } };
      draw();
    }
  };

  const ask = async (classGroupId) => {
    state = { ...state, notes: {}, printing: { class_group_id: classGroupId, children: null, chosen: [], job: null } };
    draw();
    const result = await fetchRoster({ classGroupId, termId: state.term.id, fetchImpl });
    if (result.refusal) return refusedForPage(result);
    if (!result.ok) {
      state = { ...state, printing: null, notes: { [classGroupId]: (result.body || {}).detail || "" } };
    } else if (state.printing && state.printing.class_group_id === classGroupId) {
      state = { ...state, printing: { ...state.printing, children: result.body.children } };
    }
    draw();
  };

  const start = async (classGroupId) => {
    const chosen = (state.printing && state.printing.chosen) || [];
    const result = await startPrint({ classGroupId, termId: state.term.id, studentIds: chosen, fetchImpl });
    if (result.refusal) return refusedForPage(result);
    if (!result.ok) {
      state = { ...state, printing: null, notes: { [classGroupId]: (result.body || {}).detail || "" } };
      draw();
      return;
    }
    state = { ...state, printing: { ...state.printing, job: result.body } };
    draw();
    await watch(result.body.id);
  };

  // A box ticked or unticked: remembered, not redrawn, so focus stays put.
  root.addEventListener("change", async (event) => {
    const target = event.target;
    if (target && target.closest && target.closest("[data-term-select]")) {
      state = fromOverview(await fetchOverview({ termId: Number(target.value), fetchImpl }));
      draw();
      return;
    }
    const box = target && target.closest ? target.closest("[data-print-child]") : null;
    if (!box || !state.printing) return;
    const id = Number(box.dataset.printChild);
    const chosen = new Set(state.printing.chosen || []);
    if (target.checked) chosen.add(id);
    else chosen.delete(id);
    state = { ...state, printing: { ...state.printing, chosen: [...chosen].sort((a, b) => a - b) } };
  });

  root.addEventListener("click", async (event) => {
    const hit = event.target.closest("[data-action]");
    if (!hit) return;
    const { action } = hit.dataset;
    if (action === "ask-print") await ask(Number(hit.dataset.class));
    else if (action === "cancel-print") {
      state = { ...state, printing: null };
      draw();
      // A finished print is in the log now: read it again.
      const fresh = await fetchOverview({ termId: state.term ? state.term.id : null, fetchImpl });
      if (fresh.ok && !state.printing) {
        state = { ...fromOverview(fresh), notes: state.notes };
        draw();
      }
    }
  });

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form || !form.dataset || !form.dataset.print) return;
    if (event.preventDefault) event.preventDefault();
    await start(Number(form.dataset.print));
  });

  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("id-cards");
  if (root) {
    // An enhancement: if it cannot load, each select opens the system menu.
    import("../web/picker.js").then((picker) => picker.enhanceSelects(root), () => {});
    mount(root);
  }
}
