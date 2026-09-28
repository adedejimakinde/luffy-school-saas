/**
 * Notices settings: the three switches, and who gets the daily money summary.
 *
 * **Every save re-reads the whole form and posts the whole state**, the way
 * `staff/app.js` reposts the whole invitee rather than a diff: a checkbox
 * left unchecked in a payload is indistinguishable from "leave this alone",
 * so the switches and the recipient list are read off the form and sent
 * together every time, and the answer redraws the page from what the server
 * actually holds afterward.
 */

import { REFUSAL, fetchSettings, saveSettings } from "./api.js";
import * as states from "./states.js";

export function htmlFor(state, { portal = "" } = {}) {
  switch (state.step) {
    case "settings":
      return states.settings(state);
    case REFUSAL.NOT_ALLOWED:
      return states.notAllowed(state);
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

export function fromSettings(answer) {
  if (!answer.ok) return { step: answer.refusal, ...answer.body };
  return { step: "settings", ...answer.body, note: null };
}

/**
 * What the form's own fields say, as the save payload. `staff` is the list
 * the page drew the recipient checkboxes from — each one named
 * `recipient_<membership_id>`, since the fake-free form this page posts
 * through (`web/http.js`) has no `querySelectorAll` of its own to walk.
 */
export function payloadFrom(form, staff = []) {
  const isChecked = (name) => !!(form[name] && form[name].checked);
  return {
    payment_receipts: isChecked("payment_receipts"),
    absence_alerts: isChecked("absence_alerts"),
    daily_money_summary: isChecked("daily_money_summary"),
    money_summary_recipient_ids: staff
      .filter((m) => isChecked(`recipient_${m.membership_id}`))
      .map((m) => m.membership_id),
  };
}

export async function mount(root, { fetchImpl = fetch } = {}) {
  const portal = root.dataset.portal || "";
  const onSchool = root.dataset.onSchool === "yes";
  let state = { step: "loading" };

  const draw = () => {
    root.innerHTML = htmlFor(state, { portal });
  };
  const load = async () => {
    state = onSchool ? fromSettings(await fetchSettings({ fetchImpl })) : { step: REFUSAL.WRONG_HOST };
    draw();
  };

  await load();

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form || form.payment_receipts === undefined) return;
    if (event.preventDefault) event.preventDefault();
    const result = await saveSettings(payloadFrom(form, state.staff || []), { fetchImpl });
    if (result.ok) {
      state = { step: "settings", ...result.body, note: null };
    } else if (result.refusal) {
      state = { step: result.refusal, ...result.body };
    } else {
      state = { ...state, note: result.note };
    }
    draw();
  });

  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("notices-settings");
  if (root) mount(root);
}
