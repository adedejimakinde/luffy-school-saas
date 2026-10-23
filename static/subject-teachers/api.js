/**
 * The fetches the subject teachers screen makes: the overview, give one, take one away.
 *
 * Every write answers with the whole overview, so the page redraws from the school's own
 * answer. A 422 carries a sentence the school wrote, which the page prints under the form.
 */

import { deleteJson, getJson, postJson } from "../web/http.js";

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
const BASE = "/api/subject-teachers/";

export function refusalFor(status, body) {
  if (status === 403) return REFUSAL.NOT_YOURS;
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

export const assign = ({ classGroupId, subjectId, membershipId, fetchImpl = fetch }) =>
  send(() =>
    postJson(BASE, { class_group_id: classGroupId, subject_id: subjectId, membership_id: membershipId }, { fetchImpl }),
  );

export const unassign = ({ id, fetchImpl = fetch }) =>
  send(() => deleteJson(`${BASE}${encodeURIComponent(id)}/`, { fetchImpl }));
