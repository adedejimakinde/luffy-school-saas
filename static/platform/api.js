/**
 * The two calls the platform screen makes (`schools/platform_api.py`): the list
 * of schools with their student counts, and the one that adds a school.
 *
 * A 403 is "not platform staff"; a 404 is a school's host, where this screen
 * does not exist. On the add, a 422 or 502 carries a sentence for the person.
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

export const schoolsUrl = () => "/api/platform/schools/";

export function refusalFor(status, body) {
  if (status === 403) return REFUSAL.NOT_ALLOWED;
  if (status === 404) return REFUSAL.WRONG_HOST;
  if (status === 401) {
    return body && body.code === SESSION_EXPIRED ? REFUSAL.EXPIRED : REFUSAL.SIGNED_OUT;
  }
  return REFUSAL.BROKEN;
}

export async function fetchSchools({ fetchImpl = fetch } = {}) {
  let answer;
  try {
    answer = await getJson(schoolsUrl(), { fetchImpl });
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
  if (answer.status === 200 && answer.body) return { ok: true, body: answer.body };
  return { ok: false, refusal: refusalFor(answer.status, answer.body), body: answer.body || {} };
}

/** `{ok: true, body}`; `{ok: false, note}` for a sentence to show; else a page-wide `refusal`. */
export async function addSchool(fields, { fetchImpl = fetch } = {}) {
  let answer;
  try {
    answer = await postJson(schoolsUrl(), fields, { fetchImpl });
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
  if (answer.status === 201 && answer.body) return { ok: true, body: answer.body };
  if (answer.status === 422 || answer.status === 502) {
    return { ok: false, note: (answer.body && answer.body.detail) || "That did not work." };
  }
  return { ok: false, refusal: refusalFor(answer.status, answer.body), body: answer.body || {} };
}
