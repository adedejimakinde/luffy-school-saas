/**
 * Exam slips: print a class's, or one student's for a lost one; and the principal names
 * and ends exam officers.
 *
 * Printing asks twice, because it cancels: the first tap says how many new slips and
 * how many old ones stop working, and only the second prints. The PDF is handed to the
 * browser to save and dropped; nothing on the page holds a PIN. After a print the page
 * reads the overview again, so the counts and the log are the school's own.
 */

import { REFUSAL, endOfficer, fetchClass, fetchOverview, nameOfficer, printSlips } from "./api.js";
import * as states from "./states.js";

/** The markup for one state. Pure, so every branch is testable. */
export function htmlFor(state, { portal = "" } = {}) {
  switch (state.step) {
    case "exam-slips":
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

export function fromOverview(answer, keep = {}) {
  if (!answer.ok) return { step: answer.refusal, ...answer.body };
  return { open: null, roster: null, ...keep, confirming: null, notes: {}, printed: {}, ...answer.body, step: "exam-slips" };
}

/** What the row says once the file is in the browser's hands. */
export function printedNote(filename) {
  return `Printed. Saved as ${filename}. Hand the slips out; any earlier slips for these students no longer work.`;
}

/** Saves the PDF, then lets go of it: the page keeps no copy of a PIN. */
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

export async function mount(root, { fetchImpl = fetch, save = saveFile } = {}) {
  const portal = root.dataset.portal || "";
  let state = fromOverview(await fetchOverview({ fetchImpl }));
  const draw = () => {
    root.innerHTML = htmlFor(state, { portal });
  };
  draw();

  /** Refused for the page, or a sentence under `key`. */
  const refused = (key, result) => {
    if (result.refusal) state = { step: result.refusal, ...result.body };
    else state = { ...state, confirming: null, notes: { [key]: { kind: "rejected", detail: result.detail || (result.body || {}).detail } } };
  };

  const loadRoster = async (classGroupId) => {
    const answer = await fetchClass({ classGroupId, fetchImpl });
    if (answer.ok) state = { ...state, roster: answer.body };
    else refused(`class${classGroupId}`, answer);
  };

  const print = async (key, classGroupId, studentId = null) => {
    const result = await printSlips({ classGroupId, studentId, fetchImpl });
    if (!result.ok) return refused(key, result);
    save(result.blob, result.filename);
    const keep = { open: state.open, roster: state.roster };
    state = fromOverview(await fetchOverview({ fetchImpl }), keep);
    if (state.step !== "exam-slips") return;
    state = { ...state, printed: { [key]: printedNote(result.filename) } };
    if (state.open != null) await loadRoster(state.open);
  };

  root.addEventListener("click", async (event) => {
    const hit = event.target.closest("[data-action]");
    if (!hit) return;
    const { action } = hit.dataset;
    const classId = Number(hit.dataset.class);
    if (action === "ask-print-class") state = { ...state, confirming: `class${classId}`, notes: {}, printed: {} };
    else if (action === "ask-print-student") state = { ...state, confirming: `student${hit.dataset.student}`, notes: {}, printed: {} };
    else if (action === "ask-end") state = { ...state, confirming: `end${hit.dataset.member}`, notes: {} };
    else if (action === "keep") state = { ...state, confirming: null };
    else if (action === "close-class") state = { ...state, open: null, roster: null };
    else if (action === "open-class") {
      state = { ...state, open: classId, roster: null, confirming: null, notes: {}, printed: {} };
      draw();
      await loadRoster(classId);
    } else if (action === "print-class") await print(`class${classId}`, classId);
    else if (action === "print-student") await print(`student${hit.dataset.student}`, classId, Number(hit.dataset.student));
    else if (action === "end") {
      const result = await endOfficer({ membershipId: Number(hit.dataset.member), fetchImpl });
      if (result.ok) state = fromOverview(result, { open: state.open, roster: state.roster });
      else refused(`end${hit.dataset.member}`, result);
    } else return;
    draw();
  });

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form || !form.dataset || form.dataset.form !== "name-officer") return;
    if (event.preventDefault) event.preventDefault();
    const result = await nameOfficer({ membershipId: Number(form.member.value), note: form.note.value, fetchImpl });
    if (result.ok) state = fromOverview(result, { open: state.open, roster: state.roster });
    else refused("name", result);
    draw();
  });

  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("exam-slips");
  if (root) {
    // An enhancement: if it cannot load, each select opens the system menu.
    import("../web/picker.js").then((picker) => picker.enhanceSelects(root), () => {});
    mount(root);
  }
}
