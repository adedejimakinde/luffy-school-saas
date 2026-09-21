/**
 * The fetches the marking screen makes, and what each answer means.
 *
 * Nothing here interprets a sheet. The payloads arrive assembled — rows in
 * order, each with its version and running total — and `states.js` renders
 * them.
 */

import { getJson, putJson } from "../web/http.js";

/** The states this page can be in, other than holding a sheet. */
export const REFUSAL = {
  /** Signed in, and not somebody who marks here. */
  NOT_A_MARKER: "not-a-marker",
  /** The portal, or a host that is not a school's. No gradebook behind it. */
  WRONG_HOST: "wrong-host",
  EXPIRED: "expired",
  SIGNED_OUT: "signed-out",
  BROKEN: "broken",
};

/** What a save can come back as, beyond having worked. */
export const SAVE = {
  /** Somebody else moved this mark while it was being typed. Carries theirs. */
  CONFLICT: "conflict",
  /** The term left draft. The cell cannot be written now, and may never be. */
  LOCKED: "locked",
  /** The number is the problem, and it is one the teacher can retype. */
  INVALID: "invalid",
};

const SESSION_EXPIRED = "session_expired";

export function whereUrl() {
  return "/api/gradebook/where/";
}

export function sheetUrl(assessmentId, classGroupId) {
  return (
    `/api/gradebook/assessments/${encodeURIComponent(assessmentId)}/sheet/` +
    `?class_group_id=${encodeURIComponent(classGroupId)}`
  );
}

export function scoreUrl(assessmentId, studentMembershipId) {
  return (
    `/api/gradebook/assessments/${encodeURIComponent(assessmentId)}` +
    `/scores/${encodeURIComponent(studentMembershipId)}/`
  );
}

/**
 * Which state a *page-level* answer puts the page in.
 *
 * **403 and 404 are not the same refusal.** A 403 is `can_enter_marks()`:
 * signed in at this school, not somebody who marks — a bursar, a parent. A 404
 * is `_school_of()`: this host is not a school's, so there is no gradebook
 * anywhere behind the URL. The remedies differ completely.
 *
 * The 401 splits the way `accounts/session.py` splits it: a session that
 * lapsed is recoverable and says so; no session at all is a different sentence.
 */
export function refusalFor(status, body) {
  if (status === 403) return REFUSAL.NOT_A_MARKER;
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
  return answer.refusal === REFUSAL.NOT_A_MARKER;
}

async function read(url, fetchImpl) {
  let answer;
  try {
    answer = await getJson(url, { fetchImpl });
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

/** Which assessments, which classes, which term. */
export function fetchWhere({ fetchImpl = fetch } = {}) {
  return read(whereUrl(), fetchImpl);
}

/** One class group's rows for one assessment. */
export function fetchSheet({ assessmentId, classGroupId, fetchImpl = fetch }) {
  return read(sheetUrl(assessmentId, classGroupId), fetchImpl);
}

/**
 * Save one mark. This is what a blur calls.
 *
 * **`expectedVersion` is sent even when it is null**, and null is meaningful:
 * it says "I was shown no mark", which `set_score()` reads as an insert. A
 * client that omitted the field would get a 409 the moment a row already
 * existed, rather than an overwrite — the safe default, and the reason the
 * field is spelled out here rather than left off.
 *
 * The three non-200 answers a teacher can act on are kept apart, because their
 * remedies are not the same: a **409** carries the other person's value and is
 * fixed by looking at it; a **423** means the term left draft and no amount of
 * retrying will help; a **422** is a number to retype.
 *
 * A 409 whose `current` is null is a real outcome — the mark was *cleared*
 * while this one was being typed — and is not the same as "it now reads 17".
 */
export async function saveScore({
  assessmentId,
  studentMembershipId,
  value,
  expectedVersion,
  fetchImpl = fetch,
}) {
  let answer;
  try {
    answer = await putJson(
      scoreUrl(assessmentId, studentMembershipId),
      { value, expected_version: expectedVersion },
      { fetchImpl },
    );
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }

  if (answer.status === 200 && answer.body) return { ok: true, cell: answer.body };
  if (answer.status === 409) {
    return { ok: false, outcome: SAVE.CONFLICT, body: answer.body || {} };
  }
  if (answer.status === 423) {
    return { ok: false, outcome: SAVE.LOCKED, body: answer.body || {} };
  }
  if (answer.status === 422) {
    return { ok: false, outcome: SAVE.INVALID, body: answer.body || {} };
  }
  return {
    ok: false,
    refusal: refusalFor(answer.status, answer.body),
    body: answer.body || {},
  };
}
