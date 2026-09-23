/**
 * The fetches the broadsheet page makes, and what each answer means.
 *
 * **A 404 is one answer here, on purpose.** The routes refuse a reader who may
 * not see positions with a flat 404 — the same as for a class or term that
 * does not exist — so that nobody can map the school by probing ids. The page
 * keeps that: "not a broadsheet you can open" covers both, and never guesses
 * which. Which *host* it is on, it is told by the frame instead.
 */

import { getJson } from "../web/http.js";

export const REFUSAL = {
  /** Refused, or no such class or term — deliberately the same answer. */
  NOT_YOURS: "not-yours",
  WRONG_HOST: "wrong-host",
  EXPIRED: "expired",
  SIGNED_OUT: "signed-out",
  BROKEN: "broken",
};

const SESSION_EXPIRED = "session_expired";

export const termsUrl = () => "/api/results/broadsheets/";
export const overviewUrl = (termId) =>
  `/api/results/overview/?term_id=${encodeURIComponent(termId)}`;
export const broadsheetUrl = (classId, termId) =>
  `/api/results/classes/${encodeURIComponent(classId)}/broadsheet/?term_id=${encodeURIComponent(termId)}`;

export function refusalFor(status, body) {
  if (status === 404) return REFUSAL.NOT_YOURS;
  if (status === 401) {
    return body && body.code === SESSION_EXPIRED ? REFUSAL.EXPIRED : REFUSAL.SIGNED_OUT;
  }
  return REFUSAL.BROKEN;
}

async function read(url, fetchImpl) {
  let answer;
  try {
    answer = await getJson(url, { fetchImpl });
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
  if (answer.status === 200 && answer.body) return { ok: true, body: answer.body };
  return { ok: false, refusal: refusalFor(answer.status, answer.body), body: answer.body || {} };
}

export const fetchTerms = ({ fetchImpl = fetch } = {}) => read(termsUrl(), fetchImpl);
export const fetchOverview = ({ termId, fetchImpl = fetch }) => read(overviewUrl(termId), fetchImpl);
export const fetchBroadsheet = ({ classId, termId, fetchImpl = fetch }) =>
  read(broadsheetUrl(classId, termId), fetchImpl);
