/**
 * The fetches the ID cards screen makes: the overview, one class's roll to choose
 * from, starting a print, and watching it. The file itself is a plain link to the
 * server's route, so nothing here holds a PDF.
 */

import { getJson, postJson } from "../web/http.js";

/** The states the whole page can be in, other than holding the overview. */
export const REFUSAL = {
  /** Signed in, and not the principal, the vice principal or the administrator. */
  NOT_YOURS: "not-yours",
  /** The portal, or a host that is not a school's. */
  WRONG_HOST: "wrong-host",
  EXPIRED: "expired",
  SIGNED_OUT: "signed-out",
  BROKEN: "broken",
};

const SESSION_EXPIRED = "session_expired";
const BASE = "/api/id-cards/";

export function refusalFor(status, body) {
  if (status === 403) return REFUSAL.NOT_YOURS;
  if (status === 404) return REFUSAL.WRONG_HOST;
  if (status === 401) {
    return body && body.code === SESSION_EXPIRED ? REFUSAL.EXPIRED : REFUSAL.SIGNED_OUT;
  }
  return REFUSAL.BROKEN;
}

/**
 * What an answer is: the body when it is the status asked for, a sentence the
 * panel can say (409, 422), or a refusal for the whole page.
 */
function classify(answer, expected) {
  if (answer.status === expected && answer.body) return { ok: true, body: answer.body };
  if (answer.status === 409 || answer.status === 422) return { ok: false, rejected: true, body: answer.body || {} };
  return { ok: false, refusal: refusalFor(answer.status, answer.body), body: answer.body || {} };
}

async function send(act, expected) {
  try {
    return classify(await act(), expected);
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
}

export const overviewUrl = (termId = null) => (termId == null ? BASE : `${BASE}?term_id=${encodeURIComponent(termId)}`);
export const rosterUrl = (classGroupId, termId) =>
  `${BASE}classes/${encodeURIComponent(classGroupId)}/${encodeURIComponent(termId)}/`;
export const printUrl = (classGroupId, termId) => `${rosterUrl(classGroupId, termId)}print/`;
export const jobUrl = (jobId) => `${BASE}jobs/${encodeURIComponent(jobId)}/`;

export const fetchOverview = ({ termId = null, fetchImpl = fetch } = {}) =>
  send(() => getJson(overviewUrl(termId), { fetchImpl }), 200);

export const fetchRoster = ({ classGroupId, termId, fetchImpl = fetch }) =>
  send(() => getJson(rosterUrl(classGroupId, termId), { fetchImpl }), 200);

/** Start making the file: every child when `studentIds` is empty, else those. A 202 carries the job. */
export const startPrint = ({ classGroupId, termId, studentIds = [], fetchImpl = fetch }) =>
  send(() => postJson(printUrl(classGroupId, termId), { student_ids: studentIds }, { fetchImpl }), 202);

/** How far the job has got. The server asks for a lost job again itself. */
export const fetchJob = ({ jobId, fetchImpl = fetch }) => send(() => getJson(jobUrl(jobId), { fetchImpl }), 200);
