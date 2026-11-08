/**
 * `/test-scores/`: a parent's children's released scores, or a student's door to their own.
 *
 * A signed-in parent is shown their children (`GET /api/cbt/scores/`) and never the door
 * (`docs/parent-access.md` D2). Anybody else gets the door; what it opens is drawn and
 * kept only in this page's memory, and "Done" or closing the page forgets it.
 */

import * as api from "./api.js";
import * as states from "./states.js";

export function htmlFor(state) {
  switch (state.step) {
    case "family":
      return states.family(state.children, state);
    case "student":
      return states.student(state.scores, state);
    case "blank":
      return states.noChildren();
    case "door":
      return states.door(state);
    default:
      return states.broken();
  }
}

/** What the page shows first. */
export async function first({ guardian = false, fetchImpl = fetch } = {}) {
  const answer = await api.family({ fetchImpl });
  const children = answer.status === 200 ? answer.body.children || [] : [];
  if (children.length) return { step: "family", children, current: 0 };
  if (guardian) return answer.status === 200 ? { step: "blank" } : { step: "broken" };
  return { step: "door" };
}

/** The door's answer as a state. */
export function opened(answer, number) {
  if (answer.status === 200) return { step: "student", scores: answer.body, all: false };
  if (answer.status === 429) return { step: "door", number, wait: answer.body.retry_after || 60 };
  if (answer.status === 0) return { step: "door", number, note: "The school could not be reached. Check the connection and try again." };
  return { step: "door", number, note: answer.body.detail || "That did not open anything. Check the three and try again." };
}

export async function mount(root, { fetchImpl = fetch } = {}) {
  let state = await first({ guardian: root.dataset.guardian === "1", fetchImpl });
  const draw = () => {
    root.innerHTML = htmlFor(state);
  };
  draw();

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form || !form.dataset || form.dataset.form !== "door") return;
    if (event.preventDefault) event.preventDefault();
    const number = form.number.value;
    const answer = await api.open({ code: form.code.value, number, pin: form.pin.value, fetchImpl });
    state = opened(answer, number);
    draw();
  });

  root.addEventListener("click", (event) => {
    const hit = event.target.closest("[data-action]");
    if (!hit) return;
    const { action } = hit.dataset;
    if (action === "child") state = { ...state, current: Number(hit.dataset.index) };
    else if (action === "show-all") state = { ...state, all: true };
    else if (action === "wrong-only") state = { ...state, all: false };
    else if (action === "done") state = { step: "door" };
    else return;
    draw();
  });

  return { state: () => state };
}

if (typeof document !== "undefined") {
  const root = document.getElementById("test-scores");
  if (root) mount(root);
}
