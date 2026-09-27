/**
 * The one fetch the home page makes, and what each answer means.
 *
 * A 403 is "this page is not yours" and carries a sentence written for the
 * person refused. A 404 is the portal, where no school's figures exist.
 */

import { getJson } from "../web/http.js";

export const REFUSAL = {
  NOT_YOURS: "not-yours",
  WRONG_HOST: "wrong-host",
  EXPIRED: "expired",
  SIGNED_OUT: "signed-out",
  BROKEN: "broken",
};

const SESSION_EXPIRED = "session_expired";

export const homeUrl = () => "/api/home/";

export function refusalFor(status, body) {
  if (status === 403) return REFUSAL.NOT_YOURS;
  if (status === 404) return REFUSAL.WRONG_HOST;
  if (status === 401) {
    return body && body.code === SESSION_EXPIRED ? REFUSAL.EXPIRED : REFUSAL.SIGNED_OUT;
  }
  return REFUSAL.BROKEN;
}

export async function fetchHome({ fetchImpl = fetch } = {}) {
  let answer;
  try {
    answer = await getJson(homeUrl(), { fetchImpl });
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
  if (answer.status === 200 && answer.body) return { ok: true, body: answer.body };
  return { ok: false, refusal: refusalFor(answer.status, answer.body), body: answer.body || {} };
}
