/**
 * Staff invitations: who this school has invited, and sending or cancelling.
 *
 * **Every write re-reads the list**, like the roll. A resend is a second row
 * that revokes the first, and the list shows the newest per person, so
 * patching only what came back would leave the page showing a row the server
 * no longer lists.
 */

import { REFUSAL, fetchInvitations, invite, resend, revoke } from "./api.js";
import * as states from "./states.js";

export function htmlFor(state, { portal = "" } = {}) {
  switch (state.step) {
    case "list":
      return states.list(state);
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

export function fromList(answer) {
  if (!answer.ok) return { step: answer.refusal, ...answer.body };
  return { step: "list", ...answer.body, note: null, typed: null };
}

export async function mount(root, { fetchImpl = fetch } = {}) {
  const portal = root.dataset.portal || "";
  const slug = root.dataset.school || "";
  let state = { step: "loading" };

  const draw = () => {
    root.innerHTML = htmlFor(state, { portal });
  };
  const load = async () => {
    // No slug means this frame was served on a host that is not a school's;
    // there is no list to ask for.
    state = slug ? fromList(await fetchInvitations({ slug, fetchImpl })) : { step: REFUSAL.WRONG_HOST };
    draw();
  };
  const after = async (result, typed = null) => {
    if (result.ok) return load();
    if (result.refusal) {
      state = { step: result.refusal, ...result.body };
    } else {
      state = { ...state, note: result.note, typed };
    }
    draw();
  };

  await load();

  root.addEventListener("click", async (event) => {
    const hit = event.target.closest("[data-action]");
    if (!hit) return;
    const action = hit.dataset.action;
    if (action === "resend" || action === "revoke") {
      const call = action === "resend" ? resend : revoke;
      await after(await call({ slug, invitationId: Number(hit.dataset.invitation), fetchImpl }));
      return;
    }
  });

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form || !form.address) return;
    if (event.preventDefault) event.preventDefault();
    const invitee = {
      address: form.address.value,
      role: form.role ? form.role.value : "",
      full_name: form.full_name ? form.full_name.value : "",
    };
    await after(await invite({ slug, invitee, fetchImpl }), invitee);
  });

  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("staff");
  if (root) mount(root);
}
