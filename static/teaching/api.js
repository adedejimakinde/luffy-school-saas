/**
 * The fetches the teaching screen makes: subjects, this term's papers, class teachers.
 *
 * Every write answers with the whole overview, so the page redraws from the school's own
 * answer and never from a patch of its own. A 422 carries a sentence the school wrote, which
 * the page prints under the form it came from.
 */

import { csrfToken, deleteJson, getJson, postJson, putJson } from "../web/http.js";

/** The states the whole page can be in, other than holding the overview. */
export const REFUSAL = {
  /** Signed in, and not somebody who shapes this school. */
  NOT_THE_OFFICE: "not-the-office",
  /** The portal, or a host that is not a school's. */
  WRONG_HOST: "wrong-host",
  EXPIRED: "expired",
  SIGNED_OUT: "signed-out",
  BROKEN: "broken",
};

const SESSION_EXPIRED = "session_expired";
const BASE = "/api/teaching/";

export function refusalFor(status, body) {
  if (status === 403) return REFUSAL.NOT_THE_OFFICE;
  if (status === 404) return REFUSAL.WRONG_HOST;
  if (status === 401) {
    return body && body.code === SESSION_EXPIRED ? REFUSAL.EXPIRED : REFUSAL.SIGNED_OUT;
  }
  return REFUSAL.BROKEN;
}

/** What an answer is: the overview, a sentence to print (422), or a page-level refusal. */
function classify(answer) {
  if (answer.status === 200 && answer.body) return { ok: true, body: answer.body };
  if (answer.status === 422) return { ok: false, rejected: true, body: answer.body || {} };
  return { ok: false, refusal: refusalFor(answer.status, answer.body), body: answer.body || {} };
}

async function send(act) {
  try {
    return classify(await act());
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
}

export const fetchOverview = ({ fetchImpl = fetch } = {}) => send(() => getJson(BASE, { fetchImpl }));

export const addSubject = ({ name, code, fetchImpl = fetch }) =>
  send(() => postJson(`${BASE}subjects/`, { name, code }, { fetchImpl }));

export const changeSubject = ({ id, name, code, is_active, fetchImpl = fetch }) =>
  send(() => putJson(`${BASE}subjects/${encodeURIComponent(id)}/`, { name, code, is_active }, { fetchImpl }));

export const removeSubject = ({ id, fetchImpl = fetch }) =>
  send(() => deleteJson(`${BASE}subjects/${encodeURIComponent(id)}/`, { fetchImpl }));

export const addPaper = ({ subjectId, name, max_score, fetchImpl = fetch }) =>
  send(() => postJson(`${BASE}subjects/${encodeURIComponent(subjectId)}/papers/`, { name, max_score }, { fetchImpl }));

export const changePaper = ({ id, name, max_score, fetchImpl = fetch }) =>
  send(() => putJson(`${BASE}papers/${encodeURIComponent(id)}/`, { name, max_score }, { fetchImpl }));

export const removePaper = ({ id, fetchImpl = fetch }) =>
  send(() => deleteJson(`${BASE}papers/${encodeURIComponent(id)}/`, { fetchImpl }));

export const setClassTeacher = ({ classId, membershipId, fetchImpl = fetch }) =>
  send(() =>
    membershipId
      ? putJson(`${BASE}classes/${encodeURIComponent(classId)}/teacher/`, { membership_id: membershipId }, { fetchImpl })
      : deleteJson(`${BASE}classes/${encodeURIComponent(classId)}/teacher/`, { fetchImpl }),
  );

export { csrfToken };
