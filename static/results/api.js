/**
 * The fetches the approval-chain page makes, and what each answer means.
 *
 * Every step is a POST that returns the row as it now stands — state, label
 * and the actions this login may take next — so the page redraws one row from
 * the answer rather than re-fetching the list or guessing what the transition
 * did. A page that computed the next state itself would be a second
 * implementation of the chain, free to disagree with the one in `services`.
 */

import { getJson, postJson } from "../web/http.js";

/** The states the whole page can be in, other than holding the chain. */
export const REFUSAL = {
  /** Signed in, and not somebody who takes steps on results here. */
  NOT_ON_THE_CHAIN: "not-on-the-chain",
  /** The portal, or a host that is not a school's. No results behind it. */
  WRONG_HOST: "wrong-host",
  EXPIRED: "expired",
  SIGNED_OUT: "signed-out",
  BROKEN: "broken",
};

/** What one step can come back as, beyond having worked. */
export const STEP = {
  /** This person already signed this pass. Carries the step they took. */
  ALREADY_SIGNED: "already-signed",
  /** The sheet moved under them, or the release is final. */
  MOVED: "moved",
  /** A send-back with nothing in it. */
  NEEDS_A_REASON: "needs-a-reason",
  /** Not theirs to take — the class-teacher scope, or the wrong role. */
  NOT_ALLOWED: "not-allowed",
  /**
   * A release that could not check who it was leaving out, so it did not
   * happen. Nothing went home, and releasing again is the recovery.
   */
  NOT_CHECKED: "not-checked",
};

const SESSION_EXPIRED = "session_expired";
const LEFT_OUT_NOT_CHECKED = "left_out_not_checked";

export function chainUrl() {
  return "/api/results/chain/";
}

export function stepUrl(classGroupId, step) {
  return `/api/results/chain/${encodeURIComponent(classGroupId)}/${step}/`;
}

/**
 * Which page-level state an answer produces.
 *
 * **403 and 404 are different refusals.** A 403 is `_refuse_outsiders()`:
 * signed in at this school, with no part in the chain — a bursar, a parent. A
 * 404 is `_school_of()`: this host is not a school's, so there are no results
 * anywhere behind the URL.
 */
export function refusalFor(status, body) {
  if (status === 403) return REFUSAL.NOT_ON_THE_CHAIN;
  if (status === 404) return REFUSAL.WRONG_HOST;
  if (status === 401) {
    return body && body.code === SESSION_EXPIRED
      ? REFUSAL.EXPIRED
      : REFUSAL.SIGNED_OUT;
  }
  return REFUSAL.BROKEN;
}

/**
 * Whether this answer proves there is a session to end.
 *
 * The 403 qualifies — it is reached only after `session_auth` identified the
 * caller. The 404 does not: `_school_of()` raises before any authority
 * question and says nothing about the cookie.
 */
export function provesASession(answer) {
  if (answer.ok) return true;
  return answer.refusal === REFUSAL.NOT_ON_THE_CHAIN;
}

/** Where every class stands. `{ok: true, body}` or a page-level refusal. */
export async function fetchChain({ fetchImpl = fetch } = {}) {
  let answer;
  try {
    answer = await getJson(chainUrl(), { fetchImpl });
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
  if (answer.status === 200 && answer.body) return { ok: true, body: answer.body };
  return {
    ok: false,
    refusal: refusalFor(answer.status, answer.body),
    body: answer.body || {},
  };
}

/**
 * Take one step. Resolves to the new row, or to an outcome the page can say.
 *
 * The four refusals stay four because their remedies are four different
 * sentences: **already signed** names the step this person took and tells them
 * to ask somebody else; **moved** means somebody else advanced it and the page
 * should reload; **needs a reason** is a box to fill in; **not allowed** is a
 * standing they do not have. A fifth belongs to release alone: **not checked**
 * is a release that could not say who it left out and so did not happen, and
 * its remedy is the same button again.
 *
 * A 409 carrying `existing` is the same-signatory rule; a 409 without it is a
 * state that moved. They share a status because both are "this did not happen
 * because the world changed", and they are told apart by the body — which is
 * why `AlreadySignedThisCycle` was given one.
 */
export async function takeStep({ classGroupId, step, reason, fetchImpl = fetch }) {
  let answer;
  try {
    answer = await postJson(
      stepUrl(classGroupId, step),
      reason === undefined ? {} : { reason },
      { fetchImpl },
    );
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }

  if (answer.status === 200 && answer.body) return { ok: true, row: answer.body };
  if (answer.status === 409) {
    return {
      ok: false,
      outcome: answer.body && answer.body.existing ? STEP.ALREADY_SIGNED : STEP.MOVED,
      body: answer.body || {},
    };
  }
  if (answer.status === 422) {
    return { ok: false, outcome: STEP.NEEDS_A_REASON, body: answer.body || {} };
  }
  if (answer.status === 403) {
    return { ok: false, outcome: STEP.NOT_ALLOWED, body: answer.body || {} };
  }
  // The code, not the status alone: a 503 can come from a proxy in front of
  // the server, and that one is the page-level "broken" below.
  if (answer.status === 503 && answer.body && answer.body.code === LEFT_OUT_NOT_CHECKED) {
    return { ok: false, outcome: STEP.NOT_CHECKED, body: answer.body };
  }
  return {
    ok: false,
    refusal: refusalFor(answer.status, answer.body),
    body: answer.body || {},
  };
}
