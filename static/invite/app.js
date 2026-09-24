/**
 * Accepting an invitation: read the token from the address, show who invited
 * whom, take a password when one is needed, and point at the staff door.
 */

import { BROKEN, DEAD, accept, fetchPreview, tokenFrom } from "./api.js";
import * as states from "./states.js";

export function htmlFor(state) {
  switch (state.step) {
    case "offer":
      return states.offer(state);
    case "accepted":
      return states.accepted(state.accepted);
    case DEAD:
      return states.dead();
    default:
      return states.broken();
  }
}

export async function mount(root, { fetchImpl = fetch, pathname = "" } = {}) {
  const token = tokenFrom(pathname);
  let state = { step: DEAD };
  const draw = () => {
    root.innerHTML = htmlFor(state);
  };

  if (token) {
    const answer = await fetchPreview({ token, fetchImpl });
    state = answer.ok ? { step: "offer", preview: answer.body, note: "" } : { step: answer.refusal };
  }
  draw();

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form || state.step !== "offer") return;
    if (event.preventDefault) event.preventDefault();

    let password = null;
    if (state.preview.needs_password) {
      password = form.password ? form.password.value : "";
      const confirm = form.confirm ? form.confirm.value : "";
      if (password !== confirm) {
        state = { ...state, note: "The two passwords are not the same." };
        draw();
        return;
      }
    }

    const answer = await accept({ token, password, fetchImpl });
    if (answer.ok) state = { step: "accepted", accepted: answer.body };
    else if (answer.note) state = { ...state, note: answer.note };
    else state = { step: answer.refusal || BROKEN };
    draw();
  });

  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("invite");
  if (root) mount(root, { pathname: window.location.pathname });
}
