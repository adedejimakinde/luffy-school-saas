/**
 * The fetches the Tests page makes: banks and their questions, a question's picture,
 * tests and the chain that approves them, and the preview of a paper.
 *
 * Every write answers with the thing written, so the page redraws from the school's
 * own answer. A refusal is one of `REFUSAL` for the page, or a sentence (`rejected`)
 * the form says beside itself.
 */

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
const read = (path, fetchImpl) => send(() => getJson(`${BASE}${path}`, { fetchImpl }));
const write = (path, payload, fetchImpl) => send(() => postJson(`${BASE}${path}`, payload, { fetchImpl }), { write: true });

export const fetchTests = ({ fetchImpl = fetch } = {}) => read("tests/", fetchImpl);
export const fetchBanks = ({ fetchImpl = fetch } = {}) => read("banks/", fetchImpl);
export const fetchBank = ({ subjectId, level, fetchImpl = fetch }) => read(`banks/${id(subjectId)}/${id(level)}/`, fetchImpl);
export const fetchTest = ({ testId, fetchImpl = fetch }) => read(`tests/${id(testId)}/`, fetchImpl);
export const fetchPreview = ({ testId, fetchImpl = fetch }) => send(() => getJson(`${BASE}tests/${id(testId)}/preview/`, { fetchImpl }), { write: true });

export const addQuestion = ({ subjectId, level, question, fetchImpl = fetch }) =>
  write(`banks/${id(subjectId)}/${id(level)}/questions/`, question, fetchImpl);
export const editQuestion = ({ questionId, question, fetchImpl = fetch }) => write(`questions/${id(questionId)}/`, question, fetchImpl);
export const retireQuestion = ({ questionId, fetchImpl = fetch }) => write(`questions/${id(questionId)}/retire/`, {}, fetchImpl);
export const deleteQuestion = ({ questionId, fetchImpl = fetch }) => write(`questions/${id(questionId)}/delete/`, {}, fetchImpl);

export const createTest = ({ test, fetchImpl = fetch }) => write("tests/", test, fetchImpl);
export const updateTest = ({ testId, test, fetchImpl = fetch }) => write(`tests/${id(testId)}/`, test, fetchImpl);
export const deleteTest = ({ testId, fetchImpl = fetch }) => write(`tests/${id(testId)}/delete/`, {}, fetchImpl);
/** `act` is one of submit, withdraw, approve, send-back. */
export const moveTest = ({ testId, act, note = "", fetchImpl = fetch }) => write(`tests/${id(testId)}/${act}/`, { note }, fetchImpl);
export const changeClasses = ({ testId, classGroupIds, fetchImpl = fetch }) =>
  write(`tests/${id(testId)}/classes/`, { class_group_ids: classGroupIds }, fetchImpl);

// -- the sitting (CBT step 4) -------------------------------------------------------------

export const fetchSitting = ({ testId, fetchImpl = fetch }) => send(() => getJson(`${BASE}tests/${id(testId)}/sitting/`, { fetchImpl }), { write: true });
export const setCode = ({ testId, fetchImpl = fetch }) => write(`tests/${id(testId)}/code/`, {}, fetchImpl);
/** `kind` is open or close. */
export const controlSitting = ({ testId, classId, kind, reason, endAttempts = false, fetchImpl = fetch }) =>
  write(`tests/${id(testId)}/classes/${id(classId)}/${kind}/`, { reason, end_attempts: endAttempts }, fetchImpl);
export const giveExtraTime = ({ testId, studentId, minutes, reason, fetchImpl = fetch }) =>
  write(`tests/${id(testId)}/students/${id(studentId)}/extra-time/`, { minutes, reason }, fetchImpl);
export const allowRetake = ({ testId, studentId, reason, fetchImpl = fetch }) =>
  write(`tests/${id(testId)}/students/${id(studentId)}/retake/`, { reason }, fetchImpl);

/**
 * A picture for a question, as multipart. Not `postJson()`, because the body is a file;
 * the CSRF rule is `web/http.js`'s all the same, with one retry on a stale token.
 */
export async function uploadPicture({ subjectId, level, file, fetchImpl = fetch }) {
  const url = `${BASE}banks/${id(subjectId)}/${id(level)}/pictures/`;
  const post = async (token) => {
    const body = new FormData();
    body.append("picture", file);
    return fetchImpl(url, { method: "POST", headers: { "X-CSRFToken": token, Accept: "application/json" }, credentials: "same-origin", body });
  };
  try {
    let response = await post(await csrfToken({ fetchImpl }));
    let body = await jsonOf(response);
    if (response.status === 403 && body && body.code === "csrf_failed") {
      response = await post(await csrfToken({ fetchImpl, refresh: true }));
      body = await jsonOf(response);
    }
    return classify({ status: response.status, body }, { write: true });
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
