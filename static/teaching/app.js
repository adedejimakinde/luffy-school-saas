/**
 * Subjects, this term's papers and class teachers: the office's screen for what a school teaches.
 *
 * Every write answers with the whole overview and the page redraws from it. A refusal keeps the
 * form it came from open with the school's sentence under it, because it is something to retype.
 * Removing anything asks twice: the first tap names what will go.
 */

import {
  REFUSAL,
  addPaper,
  addSubject,
  changePaper,
  changeSubject,
  fetchOverview,
  removePaper,
  removeSubject,
  setClassTeacher,
} from "./api.js";
import * as states from "./states.js";

/** The markup for one state. Pure, so every branch is testable. */
export function htmlFor(state, { portal = "" } = {}) {
  switch (state.step) {
    case "teaching": {
      const open = state.open && (state.subjects || []).find((s) => s.subject_id === state.open);
      return open ? states.subject(open, state) : states.overview(state);
    }
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

/** The overview the school sent, with this page's own state (what is open) kept. */
export function fromOverview(answer, kept = {}) {
  if (!answer.ok) return { step: answer.refusal, ...answer.body };
  return { open: null, editing: null, confirming: null, ...kept, ...answer.body, step: "teaching", notes: {} };
}

export async function mount(root, { fetchImpl = fetch } = {}) {
  const portal = root.dataset.portal || "";
  let state = fromOverview(await fetchOverview({ fetchImpl }));
  const draw = () => {
    root.innerHTML = htmlFor(state, { portal });
  };
  draw();

  const keep = () => ({ open: state.open, editing: null, confirming: null });

  /** A write's answer: the new overview, or the sentence under the form `key`, or a refusal. */
  const after = (key, result, then = {}) => {
    if (result.ok) state = fromOverview(result, { ...keep(), ...then });
    else if (result.refusal) state = { step: result.refusal, ...result.body };
    else state = { ...state, confirming: null, notes: { ...state.notes, [key]: { kind: "rejected", detail: result.body.detail } } };
    draw();
  };

  root.addEventListener("click", async (event) => {
    const hit = event.target.closest("[data-action]");
    if (!hit) return;
    const { action, subject, paper } = hit.dataset;
    if (action === "open-subject") state = { ...state, open: Number(subject), notes: {} };
    else if (action === "back") state = { ...state, open: null, editing: null, confirming: null, notes: {} };
    else if (action === "edit-paper") state = { ...state, editing: Number(paper), confirming: null, notes: {} };
    else if (action === "cancel-edit" || action === "keep") state = { ...state, editing: null, confirming: null };
    else if (action === "ask-remove-paper") state = { ...state, confirming: { paper: Number(paper) } };
    else if (action === "ask-remove-subject") state = { ...state, confirming: { subject: Number(subject) } };
    else if (action === "remove-paper") return after("paper" + paper, await removePaper({ id: Number(paper), fetchImpl }));
    else if (action === "remove-subject") {
      return after("remove", await removeSubject({ id: Number(subject), fetchImpl }), { open: null });
    } else return;
    draw();
  });

  // A class teacher is saved as it is chosen: one select per class, no button.
  root.addEventListener("change", async (event) => {
    const field = event.target;
    if (!field || !field.dataset || field.dataset.class === undefined) return;
    const classId = Number(field.dataset.class);
    await after("class" + classId, await setClassTeacher({ classId, membershipId: Number(field.value) || null, fetchImpl }));
  });

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form || !form.dataset) return;
    if (event.preventDefault) event.preventDefault();
    const which = form.dataset.form;
    if (which === "subject") {
      await after("subject", await addSubject({ name: form.name.value, code: form.code.value, fetchImpl }));
    } else if (which === "subject-edit") {
      await after(
        "subject",
        await changeSubject({
          id: Number(form.dataset.subject),
          name: form.name.value,
          code: form.code.value,
          is_active: !form.retired.checked,
          fetchImpl,
        }),
      );
    } else if (which === "paper") {
      await after(
        "paper",
        await addPaper({ subjectId: Number(form.dataset.subject), name: form.name.value, max_score: Number(form.max_score.value), fetchImpl }),
      );
    } else if (which === "paper-edit") {
      const id = Number(form.dataset.paper);
      const result = await changePaper({ id, name: form.name.value, max_score: Number(form.max_score.value), fetchImpl });
      if (result.ok) await after("paper" + id, result);
      else {
        // The form stays open, with the sentence under it.
        state = { ...state, notes: { ...state.notes, ["paper" + id]: { kind: "rejected", detail: (result.body || {}).detail } } };
        if (result.refusal) state = { step: result.refusal, ...result.body };
        draw();
      }
    }
  });

  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("teaching");
  if (root) mount(root);
}
