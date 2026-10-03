/**
 * The platform admin screen: the schools with their student counts, and a form
 * that adds one and invites its first administrator.
 *
 * Nothing is decided here. Whether the person is platform staff, whether the
 * subdomain is free and what happens to the invitation are the server's; this
 * shows the answer, and a refusal keeps the form and what was typed.
 */

import { REFUSAL, addSchool, fetchSchools, fetchUnrouted } from "./api.js";
import * as states from "./states.js";

export function htmlFor(state) {
  switch (state.step) {
    case "main":
      return states.main(state);
    case REFUSAL.NOT_ALLOWED:
      return states.notAllowed();
    case REFUSAL.WRONG_HOST:
      return states.wrongHost();
    case REFUSAL.EXPIRED:
      return states.signedOut({ expired: true });
    case REFUSAL.SIGNED_OUT:
      return states.signedOut();
    default:
      return states.broken();
  }
}

export function fromList(answer) {
  if (!answer.ok) return { step: answer.refusal };
  return { step: "main", schools: answer.body.schools || [], made: null, note: null, values: {} };
}

const FIELDS = ["name", "subdomain", "admin_name", "admin_email", "admin_phone"];

/** What the form's fields say, as the body the server takes. */
export function fieldsFrom(form) {
  return Object.fromEntries(FIELDS.map((f) => [f, form[f] ? String(form[f].value).trim() : ""]));
}

export async function mount(root, { fetchImpl = fetch } = {}) {
  // A school's host answers the list with a 404, which is the wrong-host state.
  let state = fromList(await fetchSchools({ fetchImpl }));
  // Payments no school owns: read only, and only where the schools were readable.
  let unrouted = state.step === "main" ? await fetchUnrouted({ fetchImpl }) : [];
  if (state.step === "main") state = { ...state, unrouted };
  const draw = () => {
    root.innerHTML = htmlFor(state);
  };
  draw();

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (event.preventDefault) event.preventDefault();
    if (state.step !== "main") return;

    const fields = fieldsFrom(form);
    if (!fields.name || !fields.subdomain) {
      state = { ...state, values: fields, note: "A school needs a name and a subdomain." };
    } else if (!fields.admin_email && !fields.admin_phone) {
      state = { ...state, values: fields, note: "Give the first administrator's email or phone." };
    } else {
      const result = await addSchool(fields, { fetchImpl });
      if (result.ok) {
        const list = fromList(await fetchSchools({ fetchImpl }));
        state = list.step === "main" ? { ...list, made: result.body, unrouted } : list;
      } else if (result.refusal) {
        state = { step: result.refusal };
      } else {
        state = { ...state, values: fields, note: result.note };
      }
    }
    draw();
  });

  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("platform");
  if (root) mount(root);
}
