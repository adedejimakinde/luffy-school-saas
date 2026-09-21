/**
 * The fetches the remarks screen makes, and what each answer means.
 */

import { getJson, putJson } from "../web/http.js";

/** The states the whole page can be in, other than holding a class or a child. */
export const REFUSAL = {
  /** Signed in, and not somebody who signs a card here. */
  NOT_A_SIGNATORY: "not-a-signatory",
  /** The portal, or a host that is not a school's. */
  WRONG_HOST: "wrong-host",
  EXPIRED: "expired",
  SIGNED_OUT: "signed-out",
  BROKEN: "broken",
};

/** What one save can come back as, beyond having worked. */
export const SAVE = {
  /** The term left draft. No reload reopens it. */
  LOCKED: "locked",
  /** The text is the problem — blank, or too long. Retypable. */
  REJECTED: "rejected",
  /** Not this login's remark to sign, or not their class. */
  NOT_ALLOWED: "not-allowed",
};

const SESSION_EXPIRED = "session_expired";

export function listUrl(classGroupId) {
  return `/api/results/comments/?class_group_id=${encodeURIComponent(classGroupId)}`;
}

export function childUrl(studentMembershipId) {
  return `/api/results/comments/${encodeURIComponent(studentMembershipId)}/`;
}

export function remarkUrl(studentMembershipId, author) {
  return `${childUrl(studentMembershipId)}${encodeURIComponent(author)}/`;
}

export function ratingUrl(studentMembershipId, traitId) {
  return (
    `/api/results/ratings/${encodeURIComponent(studentMembershipId)}` +
    `/${encodeURIComponent(traitId)}/`
  );
}

/**
 * Which page-level state an answer produces.
 *
 * **403 and 404 are different refusals.** A 403 is `_refuse_outsiders()`:
 * signed in at this school and not a signatory — a bursar, an administrator.
 * A 404 is `_school_of()`: this host is not a school's.
 */
export function refusalFor(status, body) {
  if (status === 403) return REFUSAL.NOT_A_SIGNATORY;
  if (status === 404) return REFUSAL.WRONG_HOST;
  if (status === 401) {
    return body && body.code === SESSION_EXPIRED
      ? REFUSAL.EXPIRED
      : REFUSAL.SIGNED_OUT;
  }
  return REFUSAL.BROKEN;
}

/** Whether this answer proves there is a session to end. */
export function provesASession(answer) {
  if (answer.ok) return true;
  return answer.refusal === REFUSAL.NOT_A_SIGNATORY;
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

/** Who in this class still needs which remark. */
export function fetchClass({ classGroupId, fetchImpl = fetch }) {
  return read(listUrl(classGroupId), fetchImpl);
}

/** One child: both remarks, the bank this login may use, the conduct grid. */
export function fetchChild({ studentMembershipId, fetchImpl = fetch }) {
  return read(childUrl(studentMembershipId), fetchImpl);
}

/**
 * Classify a write. The three refusals stay three because their remedies are:
 *
 * - **locked** (423) — the term left draft; nothing reloadable reopens it, so
 *   the whole screen goes read-only rather than the one box being retried;
 * - **rejected** (422) — the text is the problem and it is retypable, so what
 *   was typed is kept;
 * - **not allowed** (403) — a standing they do not have.
 */
function classify(answer) {
  if (answer.status === 200) return { ok: true, body: answer.body || {} };
  if (answer.status === 423) return { ok: false, outcome: SAVE.LOCKED, body: answer.body || {} };
  if (answer.status === 422) return { ok: false, outcome: SAVE.REJECTED, body: answer.body || {} };
  if (answer.status === 403) return { ok: false, outcome: SAVE.NOT_ALLOWED, body: answer.body || {} };
  return {
    ok: false,
    refusal: refusalFor(answer.status, answer.body),
    body: answer.body || {},
  };
}

/** Save one signatory's remark. An upsert — rewriting is a correction. */
export async function saveRemark({ studentMembershipId, author, body, fetchImpl = fetch }) {
  try {
    return classify(
      await putJson(remarkUrl(studentMembershipId, author), { body }, { fetchImpl }),
    );
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
}

/** Score one trait for one child. The class teacher's alone. */
export async function saveRating({ studentMembershipId, traitId, score, fetchImpl = fetch }) {
  try {
    return classify(
      await putJson(ratingUrl(studentMembershipId, traitId), { score }, { fetchImpl }),
    );
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
}
