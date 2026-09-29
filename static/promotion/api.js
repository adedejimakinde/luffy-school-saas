/**
 * The two calls the promotion screen makes: one read that writes nothing, and
 * one confirm that moves every child or none (`academics/promotion_api.py`).
 *
 * A 403 is "not the office"; a 404 is the portal. On the confirm, a 409 or a
 * 422 carries a sentence for the person and keeps the page up behind it.
 */

import { getJson, postJson } from "../web/http.js";

export const REFUSAL = {
  NOT_ALLOWED: "not-allowed",
  WRONG_HOST: "wrong-host",
  EXPIRED: "expired",
  SIGNED_OUT: "signed-out",
  BROKEN: "broken",
};

const SESSION_EXPIRED = "session_expired";

export const promotionUrl = () => "/api/academics/promotion/";

export function refusalFor(status, body) {
  if (status === 403) return REFUSAL.NOT_ALLOWED;
  if (status === 404) return REFUSAL.WRONG_HOST;
  if (status === 401) {
    return body && body.code === SESSION_EXPIRED ? REFUSAL.EXPIRED : REFUSAL.SIGNED_OUT;
  }
  return REFUSAL.BROKEN;
}

export async function fetchReview({ fetchImpl = fetch } = {}) {
  let answer;
  try {
    answer = await getJson(promotionUrl(), { fetchImpl });
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
  if (answer.status === 200 && answer.body) return { ok: true, body: answer.body };
  return { ok: false, refusal: refusalFor(answer.status, answer.body), body: answer.body || {} };
}

/**
 * Confirm a plan. `{ok: true, body}` when everybody moved; `{ok: false, note}`
 * when the school said no with a sentence (nothing moved, and the page stays
 * up behind it); a `refusal` for the states a whole page can be in.
 */
export async function confirmPlan(plan, { fetchImpl = fetch } = {}) {
  let answer;
  try {
    answer = await postJson(promotionUrl(), { classes: plan }, { fetchImpl });
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
  if (answer.status === 200 && answer.body) return { ok: true, body: answer.body };
  if (answer.status === 409 || answer.status === 422) {
    return { ok: false, note: (answer.body && answer.body.detail) || "That did not work." };
  }
  return { ok: false, refusal: refusalFor(answer.status, answer.body), body: answer.body || {} };
}
