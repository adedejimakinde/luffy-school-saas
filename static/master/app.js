/**
 * The master broadsheet: one class and term, as a table, and as a PDF or Excel file.
 *
 * The ids come from the frame (`data-class`, `data-term`). Who may read the
 * sheet is the server's question, asked by every route: a refusal is a state
 * here, never a hidden button.
 */

import { REFUSAL, fetchJob, fetchSheet, startFile } from "./api.js";
import * as states from "./states.js";

/** How often the page asks how a file is getting on, in milliseconds. */
export const POLL_MS = 2000;

export const stillMaking = (job) => Boolean(job) && (job.state === "pending" || job.state === "building");

export function htmlFor(state, { portal = "" } = {}) {
  switch (state.step) {
    case "sheet":
      return states.sheet(state);
    case REFUSAL.NOT_YOURS:
      return states.notYours();
    case REFUSAL.NOT_FOUND:
      return states.notFound();
    case "wrong-host":
      return states.wrongHost();
    case REFUSAL.EXPIRED:
      return states.signedOut({ portal, expired: true });
    case REFUSAL.SIGNED_OUT:
      return states.signedOut({ portal });
    default:
      return states.broken();
  }
}

export async function mount(root, { fetchImpl = fetch, wait = (ms) => new Promise((r) => setTimeout(r, ms)) } = {}) {
  const portal = root.dataset.portal || "";
  const classId = Number(root.dataset.class);
  const termId = Number(root.dataset.term);
  let state = { step: "loading" };
  const draw = () => {
    root.innerHTML = htmlFor(state, { portal });
  };

  if (root.dataset.onSchool !== "yes") {
    state = { step: "wrong-host" };
    draw();
    return state;
  }

  const loaded = await fetchSheet({ classId, termId, fetchImpl });
  if (!loaded.ok) {
    state = { step: loaded.refusal };
    draw();
    return state;
  }
  state = { step: "sheet", sheet: loaded.body, job: null, paper: "A4" };
  draw();

  const watch = async (jobId) => {
    while (state.job && state.job.id === jobId && stillMaking(state.job)) {
      await wait(POLL_MS);
      if (!state.job || state.job.id !== jobId) return;
      const answer = await fetchJob({ jobId, fetchImpl });
      if (!state.job || state.job.id !== jobId) return;
      if (!answer.ok) {
        state = { ...state, job: { id: jobId, state: "failed", detail: (answer.body && answer.body.detail) || "The file could not be made." } };
      } else {
        state = { ...state, job: answer.body };
      }
      draw();
    }
  };

  const make = async (format) => {
    const field = root.querySelector("[data-paper]");
    const paper = field ? field.value : state.paper;
    const answer = await startFile({ classId, termId, format, paper, fetchImpl });
    state = {
      ...state,
      paper,
      job: answer.ok
        ? answer.body
        : { id: 0, state: "failed", detail: (answer.body && answer.body.detail) || "The file could not be started." },
    };
    draw();
    if (answer.ok) await watch(answer.body.id);
  };

  root.addEventListener("click", async (event) => {
    const hit = event.target.closest && event.target.closest("[data-action]");
    if (!hit || state.step !== "sheet") return;
    if (hit.dataset.action === "make-pdf") await make("pdf");
    else if (hit.dataset.action === "make-xlsx") await make("xlsx");
    else if (hit.dataset.action === "close-file") {
      state = { ...state, job: null };
      draw();
    }
  });

  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("master");
  if (root) {
    // An enhancement: if it cannot load, the select opens the system menu.
    import("../web/picker.js").then((picker) => picker.enhanceSelects(root), () => {});
    mount(root);
  }
}
