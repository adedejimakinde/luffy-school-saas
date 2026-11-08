/**
 * The fetches a test's results page makes: `cbt/results_api.py`, CBT step 5.
 *
 * Every write answers with the results as they now stand (or, for a send to CA, its
 * lines), so the page redraws from the school's own answer. A refusal is one of
 * `REFUSAL` for the page, or a sentence (`rejected`) the view says beside itself.
 */

import { getJson, postJson } from "../web/http.js";

export const REFUSAL = {
  NOT_YOURS: "not-yours",
  WRONG_HOST: "wrong-host",
  EXPIRED: "expired",
  SIGNED_OUT: "signed-out",
  BROKEN: "broken",
};

const BASE = "/api/cbt/";

export function refusalFor(status, body) {
  if (status === 403) return REFUSAL.NOT_YOURS;
  if (status === 404) return REFUSAL.WRONG_HOST;
  if (status === 401) return body && body.code === "session_expired" ? REFUSAL.EXPIRED : REFUSAL.SIGNED_OUT;
  return REFUSAL.BROKEN;
}

/** The body, a sentence to say (403 or 404 on a write, 409, 422), or a refusal. */
export function classify(answer, { write = false } = {}) {
  if (answer.status === 200 && answer.body) return { ok: true, body: answer.body };
  const sayable = answer.status === 409 || answer.status === 422 || (write && (answer.status === 403 || answer.status === 404));
  if (sayable) return { ok: false, rejected: true, detail: (answer.body || {}).detail || "" };
  return { ok: false, refusal: refusalFor(answer.status, answer.body), body: answer.body || {} };
}

async function send(act, options) {
  try {
    return classify(await act(), options);
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
}

const id = encodeURIComponent;
const read = (path, fetchImpl) => send(() => getJson(`${BASE}${path}`, { fetchImpl }));
const write = (path, payload, fetchImpl) => send(() => postJson(`${BASE}${path}`, payload, { fetchImpl }), { write: true });

export const fetchResults = ({ testId, fetchImpl = fetch }) => read(`tests/${id(testId)}/results/`, fetchImpl);
export const correctKey = ({ testId, itemId, newIndex, reason, fetchImpl = fetch }) =>
  write(`tests/${id(testId)}/items/${id(itemId)}/key/`, { new_index: newIndex, reason }, fetchImpl);
export const closeTest = ({ testId, fetchImpl = fetch }) => write(`tests/${id(testId)}/close/`, {}, fetchImpl);
export const releaseClass = ({ testId, classId, fetchImpl = fetch }) => write(`tests/${id(testId)}/classes/${id(classId)}/release/`, {}, fetchImpl);
export const restoreRelease = ({ releaseId, reason, fetchImpl = fetch }) => write(`releases/${id(releaseId)}/restore/`, { reason }, fetchImpl);
/** The CA columns, or with `assessment` the preview of a send. Writes nothing. */
export const previewCa = ({ testId, assessment = 0, existing = "keep", fetchImpl = fetch }) =>
  read(`tests/${id(testId)}/ca/?assessment=${id(assessment)}&existing=${id(existing)}`, fetchImpl);
export const sendCa = ({ testId, assessmentId, existing, shown, confirmReplace = false, fetchImpl = fetch }) =>
  write(`tests/${id(testId)}/ca/`, { assessment_id: assessmentId, existing, shown, confirm_replace: confirmReplace }, fetchImpl);

/** What the preview showed, per student, which the send carries back. */
export function shownOf(preview) {
  const out = {};
  for (const line of preview.lines) {
    out[String(line.student_id)] = { score: line.test_score, mark: line.mark, current: line.current, version: line.version };
  }
  return out;
}
