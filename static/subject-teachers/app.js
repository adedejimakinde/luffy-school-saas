/**
 * Who teaches which subject to which class: the principal's screen, read by the office.
 *
 * Every write answers with the whole overview and the page redraws from it. A refusal
 * keeps the form open with the school's sentence under it. Taking one away asks twice:
 * the first tap names what will go. So does the switch: the first tap says what opening
 * or restricting marking will do, and only the second does it.
 */

import { REFUSAL, assign, fetchOverview, setMarking, unassign } from "./api.js";
import * as states from "./states.js";

/** The markup for one state. Pure, so every branch is testable. */
export function htmlFor(state, { portal = "" } = {}) {
  switch (state.step) {
    case "subject-teachers":
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
  return { confirming: null, switching: false, ...answer.body, step: "subject-teachers", notes: {} };
}

export async function mount(root, { fetchImpl = fetch } = {}) {
  const portal = root.dataset.portal || "";
  let state = fromOverview(await fetchOverview({ fetchImpl }));
  const draw = () => {
    root.innerHTML = htmlFor(state, { portal });
  };
  draw();

  /** A write's answer: the new overview, the sentence under `key`, or a refusal. */
  const after = (key, result) => {
    if (result.ok) state = fromOverview(result);
    else if (result.refusal) state = { step: result.refusal, ...result.body };
    else state = { ...state, confirming: null, switching: false, notes: { [key]: { kind: "rejected", detail: result.body.detail } } };
    draw();
  };

  root.addEventListener("click", async (event) => {
    const hit = event.target.closest("[data-action]");
    if (!hit) return;
    const { action, assignment } = hit.dataset;
    if (action === "ask-unassign") state = { ...state, confirming: Number(assignment), notes: {} };
    else if (action === "keep") state = { ...state, confirming: null, switching: false };
    else if (action === "ask-switch") state = { ...state, switching: true, notes: {} };
    else if (action === "switch") {
      return after("switch", await setMarking({ open: hit.dataset.open === "true", fetchImpl }));
    } else if (action === "unassign") {
      return after("remove" + assignment, await unassign({ id: Number(assignment), fetchImpl }));
    } else return;
    draw();
  });

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form || !form.dataset || form.dataset.form !== "assign") return;
    if (event.preventDefault) event.preventDefault();
    await after(
      "assign",
      await assign({
        membershipId: Number(form.teacher.value),
        subjectId: Number(form.subject.value),
        classGroupId: Number(form.class_group.value),
        fetchImpl,
      }),
    );
  });

  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("subject-teachers");
  if (root) mount(root);
}
