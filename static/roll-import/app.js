/**
 * Importing a roll from a spreadsheet: choose, check, admit.
 *
 * The chosen `File` is held for the life of the page, so "Admit" sends the
 * same file the preview was drawn from, and the server checks it again before
 * it writes anything. If the roll changed in between, the import answers with
 * problems and the page draws them as a preview again, by row.
 */

import { REFUSAL, checkFile, fetchDoor, importFile } from "./api.js";
import * as states from "./states.js";

/** The markup for one state. Pure, so every branch is testable. */
export function htmlFor(state, { portal = "" } = {}) {
  switch (state.step) {
    case "choose":
      return states.choose(state);
    case "preview":
      return states.preview(state);
    case "done":
      return states.done(state);
    case REFUSAL.NOT_THE_OFFICE:
      return states.notTheOffice(state);
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

/** A refusal that takes the whole page, from any answer. */
function pageRefusal(answer) {
  return answer.refusal ? { step: answer.refusal, ...answer.body } : null;
}

/**
 * What an import's answer does. A report with problems is a preview again,
 * the rows re-marked from the problems it names: the file is unchanged, so
 * the rows are the ones already on screen.
 */
export function afterImport(state, answer) {
  const refused = pageRefusal(answer);
  if (refused) return refused;
  if (answer.rejected) {
    return { ...state, busy: false, note: answer.body.detail || "That file could not be admitted." };
  }
  const report = answer.body;
  if (report.problems && report.problems.length) {
    const byLine = {};
    for (const p of report.problems) (byLine[p.line] ||= []).push(p);
    const rows = state.preview.rows.map((r) => ({ ...r, problems: byLine[r.line] || [] }));
    return {
      ...state,
      busy: false,
      note: "The roll changed since this file was checked. Nothing was admitted.",
      preview: { rows, problem_rows: Object.keys(byLine).length, admissible: false },
    };
  }
  return { step: "done", term: state.term, classes: state.classes, report, preview: state.preview };
}

/** What a check's answer does. */
export function afterCheck(state, answer, fileName) {
  const refused = pageRefusal(answer);
  if (refused) return refused;
  if (answer.rejected) {
    return { ...state, step: "choose", busy: false, note: answer.body.detail || "That file could not be read." };
  }
  return { step: "preview", term: state.term, classes: state.classes, fileName, preview: answer.body };
}

export async function mount(root, { fetchImpl = fetch } = {}) {
  const portal = root.dataset.portal || "";
  const door = await fetchDoor({ fetchImpl });
  let state = pageRefusal(door) || { step: "choose", term: door.body.term, classes: door.body.classes || [] };
  let file = null;

  const draw = () => {
    root.innerHTML = htmlFor(state, { portal });
  };
  draw();

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form || !form.file) return;
    if (event.preventDefault) event.preventDefault();
    const chosen = form.file && form.file.files && form.file.files[0];
    if (!chosen) return;
    file = chosen;
    state = { ...state, busy: true, note: null };
    draw();
    state = afterCheck(state, await checkFile({ file, fetchImpl }), file.name);
    draw();
  });

  root.addEventListener("click", async (event) => {
    const hit = event.target.closest("[data-action]");
    if (!hit) return;
    const action = hit.dataset.action;
    if (action === "again") {
      file = null;
      state = { step: "choose", term: state.term, classes: state.classes };
      draw();
      return;
    }
    if (action === "download-no-email" && state.step === "done") {
      // Built in the page from the report just shown; nothing is sent anywhere.
      const csv = states.noEmailCsv(state.report.no_email || []);
      const link = root.ownerDocument.createElement("a");
      link.href = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
      link.download = "students-without-guardian-email.csv";
      root.ownerDocument.body.append(link);
      link.click();
      link.remove();
      return;
    }
    if (action === "admit" && state.step === "preview" && state.preview.admissible && file && !state.busy) {
      state = { ...state, busy: true, note: null };
      draw();
      state = afterImport(state, await importFile({ file, fetchImpl }));
      draw();
    }
  });

  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("roll-import");
  if (root) mount(root);
}
