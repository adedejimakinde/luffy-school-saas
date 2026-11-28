/** The fetches a test's sitting page makes: `cbt/sitting_api.py`, CBT step 4, and the slip prints. */

import { csrfToken, getJson, postJson } from "../web/http.js";

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

/** The body, a sentence to say (403 on a write, 404 on a row, 409, 422), or a refusal. */
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
const write = (path, payload, fetchImpl) => send(() => postJson(`${BASE}${path}`, payload, { fetchImpl }), { write: true });

export const fetchSitting = ({ testId, fetchImpl = fetch }) => send(() => getJson(`${BASE}tests/${id(testId)}/sitting/`, { fetchImpl }), { write: true });
export const setCode = ({ testId, fetchImpl = fetch }) => write(`tests/${id(testId)}/code/`, {}, fetchImpl);
/** `kind` is open or close. */
export const controlSitting = ({ testId, classId, kind, reason, endAttempts = false, fetchImpl = fetch }) =>
  write(`tests/${id(testId)}/classes/${id(classId)}/${kind}/`, { reason, end_attempts: endAttempts }, fetchImpl);
export const giveExtraTime = ({ testId, studentId, minutes, reason, fetchImpl = fetch }) =>
  write(`tests/${id(testId)}/students/${id(studentId)}/extra-time/`, { minutes, reason }, fetchImpl);
export const allowRetake = ({ testId, studentId, reason, fetchImpl = fetch }) =>
  write(`tests/${id(testId)}/students/${id(studentId)}/retake/`, { reason }, fetchImpl);


/** A class's slips, or one student's: the PDF (the one place a PIN is written out), or a sentence. */
export async function printSlips({ classGroupId, studentId = null, replace = false, fetchImpl = fetch }) {
  const url = `${BASE}slips/classes/${id(classGroupId)}/${studentId == null ? "" : `students/${id(studentId)}/`}print/`;
  const post = async (csrf) =>
    fetchImpl(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/pdf, application/json", "X-CSRFToken": csrf },
      credentials: "same-origin",
      cache: "no-store",
      body: JSON.stringify(studentId == null ? { replace } : {}),
    });
  try {
    let response = await post(await csrfToken({ fetchImpl }));
    let body = response.status === 200 ? null : await jsonOf(response);
    if (response.status === 403 && body && body.code === "csrf_failed") {
      response = await post(await csrfToken({ fetchImpl, refresh: true }));
      body = response.status === 200 ? null : await jsonOf(response);
    }
    if (response.status !== 200) return classify({ status: response.status, body }, { write: true });
    const named = /filename="([^"]+)"/.exec(response.headers.get("Content-Disposition") || "");
    return { ok: true, blob: await response.blob(), filename: named ? named[1] : "exam-slips.pdf" };
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
}


async function jsonOf(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}
