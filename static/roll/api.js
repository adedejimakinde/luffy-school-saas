/**
 * The fetches the roll screen makes, and what each answer means.
 */

import { getJson, postJson, putJson } from "../web/http.js";

/** The states the whole page can be in, other than holding the roll. */
export const REFUSAL = {
  /** Signed in, and with no part in admitting or placing here. */
  NOT_THE_OFFICE: "not-the-office",
  /** The portal, or a host that is not a school's. */
  WRONG_HOST: "wrong-host",
  EXPIRED: "expired",
  SIGNED_OUT: "signed-out",
  BROKEN: "broken",
};

/** What one write can come back as, beyond having worked. */
export const SAVE = {
  /** That handle belongs to somebody already. Retypable. */
  HANDLE_TAKEN: "handle-taken",
  /** The request disagrees with the school's state. Retypable. */
  REJECTED: "rejected",
  /** A standing they do not have. No retry helps. */
  NOT_ALLOWED: "not-allowed",
};

const SESSION_EXPIRED = "session_expired";

export function rollUrl() {
  return "/api/enrolment/roll/";
}

export function classUrl(studentMembershipId) {
  return `${rollUrl()}${encodeURIComponent(studentMembershipId)}/class/`;
}

/**
 * Which page-level state an answer produces.
 *
 * **403 and 404 are different refusals.** A 403 is the authority check: signed
 * in at this school with no part in the roll — a teacher, a bursar. A 404 is
 * `_school_of()`: this host is not a school's, so there is no roll behind the
 * URL at all.
 */
export function refusalFor(status, body) {
  if (status === 403) return REFUSAL.NOT_THE_OFFICE;
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
  return answer.refusal === REFUSAL.NOT_THE_OFFICE;
}

/** Every child enrolled here, and where they sit this term. */
export async function fetchRoll({ fetchImpl = fetch } = {}) {
  let answer;
  try {
    answer = await getJson(rollUrl(), { fetchImpl });
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
 * Classify a write.
 *
 * **409 is kept apart from 422** because they are different sentences to a
 * person: a handle somebody else holds is a name to change, and a request that
 * disagrees with the school's state is something else entirely. Collapsing
 * them into "that did not work" would leave an administrator guessing which.
 */
function classify(answer, created) {
  if (answer.status === created || answer.status === 200) {
    return { ok: true, row: answer.body || {} };
  }
  if (answer.status === 409) return { ok: false, outcome: SAVE.HANDLE_TAKEN, body: answer.body || {} };
  if (answer.status === 422) return { ok: false, outcome: SAVE.REJECTED, body: answer.body || {} };
  if (answer.status === 403) return { ok: false, outcome: SAVE.NOT_ALLOWED, body: answer.body || {} };
  return {
    ok: false,
    refusal: refusalFor(answer.status, answer.body),
    body: answer.body || {},
  };
}

/** Create a child's login and enrol them. Optionally place them too. */
export async function admit({ child, fetchImpl = fetch }) {
  try {
    return classify(await postJson(rollUrl(), child, { fetchImpl }), 201);
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
}

/** Put a child in a class, or move them to another. The server decides which. */
export async function setClass({ studentMembershipId, classGroupId, fetchImpl = fetch }) {
  try {
    return classify(
      await putJson(classUrl(studentMembershipId), { class_group_id: classGroupId }, { fetchImpl }),
      200,
    );
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
}
