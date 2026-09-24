/**
 * The fetches the absence page makes, and what each answer means.
 *
 * **A 404 is one answer here, on purpose.** The list refuses a reader who may
 * not see it with a flat 404 — the same as for a term that does not exist — so
 * that "you may not" and "there is no such thing" read alike. The page keeps
 * that: "not a list you can open" covers both, and never guesses which. Which
 * *host* it is on, it is told by the frame instead.
 */

import { getJson, putJson } from "../web/http.js";

export const REFUSAL = {
  /** Refused, or no such term — deliberately the same answer. */
  NOT_YOURS: "not-yours",
  WRONG_HOST: "wrong-host",
  EXPIRED: "expired",
  SIGNED_OUT: "signed-out",
  BROKEN: "broken",
};

const SESSION_EXPIRED = "session_expired";

export const absencesUrl = (termId) =>
  termId === undefined || termId === null
    ? "/api/attendance/absences/"
    : `/api/attendance/absences/?term_id=${encodeURIComponent(termId)}`;
export const thresholdUrl = () => "/api/attendance/absences/threshold/";

export function refusalFor(status, body) {
  if (status === 404) return REFUSAL.NOT_YOURS;
  if (status === 401) {
    return body && body.code === SESSION_EXPIRED ? REFUSAL.EXPIRED : REFUSAL.SIGNED_OUT;
  }
  return REFUSAL.BROKEN;
}

export async function fetchAbsences({ termId = null, fetchImpl = fetch } = {}) {
  let answer;
  try {
    answer = await getJson(absencesUrl(termId), { fetchImpl });
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
  if (answer.status === 200 && answer.body) return { ok: true, body: answer.body };
  return { ok: false, refusal: refusalFor(answer.status, answer.body), body: answer.body || {} };
}

/**
 * Set what "too often" means. A 403 (a vice principal, who reads the list but
 * may not change it) and a 422 (a number out of range) keep their sentence:
 * both are answers a person can act on, and `detail` was written for one.
 */
export async function saveThreshold({ thresholdPercent, minMarkedDays, fetchImpl = fetch }) {
  let answer;
  try {
    answer = await putJson(
      thresholdUrl(),
      { threshold_percent: thresholdPercent, min_marked_days: minMarkedDays },
      { fetchImpl },
    );
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
  if (answer.status === 200 && answer.body) return { ok: true, body: answer.body };
  if (answer.status === 403 || answer.status === 422) {
    return { ok: false, refusal: null, body: answer.body || {} };
  }
  return { ok: false, refusal: refusalFor(answer.status, answer.body), body: answer.body || {} };
}
