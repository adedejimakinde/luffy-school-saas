/**
 * The one fetch the notices settings screen makes, and the one write it
 * offers: `notices/api.py`'s `/api/notices/settings/`.
 *
 * A 403 carries a sentence — signed in, but not the principal or an
 * administrator. A 404 is the portal, where there is no school's settings row.
 */

import { getJson, postJson } from "../web/http.js";

export const REFUSAL = {
  NOT_ALLOWED: "not-allowed",
  WRONG_HOST: "wrong-host",
  EXPIRED: "expired",
  SIGNED_OUT: "signed-out",
  BROKEN: "broken",
};

const SESSION_EXPIRED = "session_expired";

export const settingsUrl = () => "/api/notices/settings/";

export function refusalFor(status, body) {
  if (status === 403) return REFUSAL.NOT_ALLOWED;
  if (status === 404) return REFUSAL.WRONG_HOST;
  if (status === 401) {
    return body && body.code === SESSION_EXPIRED ? REFUSAL.EXPIRED : REFUSAL.SIGNED_OUT;
  }
  return REFUSAL.BROKEN;
}

export async function fetchSettings({ fetchImpl = fetch } = {}) {
  let answer;
  try {
    answer = await getJson(settingsUrl(), { fetchImpl });
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
  if (answer.status === 200 && answer.body) return { ok: true, body: answer.body };
  return { ok: false, refusal: refusalFor(answer.status, answer.body), body: answer.body || {} };
}

/**
 * Save a change. **A 403 with a sentence is a note, not a page state** —
 * signed in, but not the principal or an administrator — and the form stays
 * up behind it, exactly as `staff/api.js`'s `write()` keeps the invite form up
 * behind a refused invite.
 */
export async function saveSettings(payload, { fetchImpl = fetch } = {}) {
  let answer;
  try {
    answer = await postJson(settingsUrl(), payload, { fetchImpl });
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
  if (answer.status === 200 && answer.body) return { ok: true, body: answer.body };
  if (answer.status === 403) {
    return { ok: false, note: (answer.body && answer.body.detail) || "That did not work." };
  }
  return { ok: false, refusal: refusalFor(answer.status, answer.body), body: answer.body || {} };
}
