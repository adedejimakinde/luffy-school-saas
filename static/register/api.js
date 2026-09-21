/**
 * The three fetches the register screen makes, and what each answer means.
 *
 * Nothing here interprets a register. `states.js` renders what arrives, and the
 * payloads arrive assembled: `RegisterOut.rows` is already the roster in order
 * with each child's status, and `RegisterTakenOut` is already the four lists
 * the write actually wrote.
 */

import { getJson, putJson } from "../web/http.js";

/** The states this page can be in, other than holding a register. */
export const REFUSAL = {
  /** Signed in, and not somebody who may mark here. */
  NOT_A_MARKER: "not-a-marker",
  /** The portal, or a host that is not a school's. There is no register here. */
  WRONG_HOST: "wrong-host",
  EXPIRED: "expired",
  SIGNED_OUT: "signed-out",
  BROKEN: "broken",
};

/** The API's own marker for a session that was presented and is no longer good. */
const SESSION_EXPIRED = "session_expired";

export function whereUrl() {
  return "/api/attendance/where/";
}

export function registerUrl(classGroupId, termId, on) {
  return (
    `/api/attendance/classes/${encodeURIComponent(classGroupId)}` +
    `/terms/${encodeURIComponent(termId)}/${encodeURIComponent(on)}/`
  );
}

/**
 * Which state an answer puts the page in. Exported so a test can name it.
 *
 * **403 and 404 are not the same refusal and must not collapse.** A 403 is
 * `_refuse_non_markers()`: signed in at this school, not somebody who marks —
 * a bursar, a vice principal, a parent. A 404 is `_school_of()`: this host is
 * not a school's, so there is no register anywhere behind this URL. The
 * remedies differ completely, and a page that showed one sentence for both
 * would be wrong for whichever reader it was not written for.
 *
 * The 401 splits the same way `card/api.js` splits it, and for the same reason:
 * `accounts/session.py` distinguishes a session that lapsed — recoverable, and
 * worth saying so — from no session at all.
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
 * The sign-out button is drawn on the answers that could only have come back to
 * somebody signed in, and on no others — the platform-wide rule, and a control
 * that posts a logout for a browser holding no cookie is one that does nothing
 * while looking like it did.
 *
 * The 403 qualifies and is the one worth arguing: `_refuse_non_markers()` is
 * reached only after `session_auth` has already identified the caller, so a
 * bursar reading this refusal is signed in. `SchoolAccessMiddleware`'s own 403
 * never gets here — it refuses the *frame* on the way in, and this module is
 * never loaded.
 *
 * `wrong-host` does not qualify: a 404 from `_school_of()` says nothing about
 * the cookie, because it is raised before any authority question is asked.
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

/** Which classes, and which term. `{ok: true, body}` or a refusal. */
export function fetchWhere({ fetchImpl = fetch } = {}) {
  return read(whereUrl(), fetchImpl);
}

/** One register, taken or not. `RegisterOut.taken` is what tells those apart. */
export function fetchRegister({ classGroupId, termId, on, fetchImpl = fetch }) {
  return read(registerUrl(classGroupId, termId, on), fetchImpl);
}

/**
 * Submit one register. `absentIds` is what the teacher tapped; everyone else
 * the screen showed is present.
 *
 * **`shownIds` is sent and is not optional here.** The schema allows omitting
 * it and means "whatever the roster is now" — correct for an import, wrong for
 * a phone, which knows exactly which names it drew. Sending it is what makes
 * the two reports possible at all: a child who joined the group after the
 * screen loaded comes back in `appeared` and is *not* marked, and an absentee
 * moved out of the group comes back in `not_on_the_roster`. Neither fails the
 * request, because a teacher in front of a class should not lose a register
 * over one child the office moved while they were marking.
 */
export async function takeRegister({
  classGroupId,
  termId,
  on,
  absentIds,
  shownIds,
  fetchImpl = fetch,
}) {
  let answer;
  try {
    answer = await putJson(
      registerUrl(classGroupId, termId, on),
      { absent_ids: absentIds, shown_ids: shownIds },
      { fetchImpl },
    );
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
  if (answer.status === 200 && answer.body) return { ok: true, body: answer.body };
  // 409 (nobody in the group) and 422 (a date outside the term) are answers a
  // teacher can act on, so they keep their own body and are not flattened into
  // `broken`. `states.js` prints `detail`, which the API wrote for a person.
  if (answer.status === 409 || answer.status === 422) {
    return { ok: false, refusal: null, body: answer.body || {} };
  }
  return {
    ok: false,
    refusal: refusalFor(answer.status, answer.body),
    body: answer.body || {},
  };
}
