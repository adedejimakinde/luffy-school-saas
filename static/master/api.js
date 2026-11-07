/**
 * The fetches the master broadsheet page makes, and what each answer means.
 *
 * **A 403 is one answer.** The routes refuse somebody with no standing, and a
 * class teacher asking about a class that is not theirs, with the same
 * sentence, so the page says one thing for both and never guesses which. A 404
 * is a class or term that does not exist, or the portal.
 */

import { getJson, postJson } from "../web/http.js";

export const REFUSAL = {
  NOT_YOURS: "not-yours",
  NOT_FOUND: "not-found",
  EXPIRED: "expired",
  SIGNED_OUT: "signed-out",
  BROKEN: "broken",
};

const SESSION_EXPIRED = "session_expired";

export const sheetUrl = (classId, termId) =>
  `/api/results/master-broadsheet/${encodeURIComponent(classId)}/${encodeURIComponent(termId)}/`;
export const filesUrl = (classId, termId) => `${sheetUrl(classId, termId)}files/`;
export const jobUrl = (jobId) => `/api/results/print-jobs/${encodeURIComponent(jobId)}/`;

export function refusalFor(status, body) {
  if (status === 403) return REFUSAL.NOT_YOURS;
  if (status === 404) return REFUSAL.NOT_FOUND;
  if (status === 401) {
    return body && body.code === SESSION_EXPIRED ? REFUSAL.EXPIRED : REFUSAL.SIGNED_OUT;
  }
  return REFUSAL.BROKEN;
}

async function settle(call, okStatuses) {
  let answer;
  try {
    answer = await call();
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
  if (okStatuses.includes(answer.status) && answer.body) return { ok: true, body: answer.body };
  return { ok: false, status: answer.status, refusal: refusalFor(answer.status, answer.body), body: answer.body || {} };
}

export const fetchSheet = ({ classId, termId, fetchImpl = fetch }) =>
  settle(() => getJson(sheetUrl(classId, termId), { fetchImpl }), [200]);

/** `format` is "pdf" or "xlsx"; `paper` is "A3" or "A4" and matters for a PDF only. */
export const startFile = ({ classId, termId, format, paper = "", fetchImpl = fetch }) =>
  settle(() => postJson(filesUrl(classId, termId), { format, paper }, { fetchImpl }), [202]);

export const fetchJob = ({ jobId, fetchImpl = fetch }) =>
  settle(() => getJson(jobUrl(jobId), { fetchImpl }), [200]);
