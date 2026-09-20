/**
 * One fetch, and the classification of every answer it can give.
 *
 * The page has four states beyond the card itself, and they are not four HTTP
 * statuses — 401 is two of them. `code` on the 401 body says which, and the
 * distinction is the whole of `accounts/session.py`: a session that lapsed is
 * recoverable and says so, while no session at all is a caller who never
 * signed in. Branching on the status alone would collapse them.
 *
 * Nothing here interprets the card. The payload arrives assembled —
 * `columns` in print order, each line's `cells` already aligned to it — and
 * `render.js` walks it. That is why this module returns the body untouched.
 */

/** The states this page can be in, other than holding a card. */
export const REFUSAL = {
  WITHHELD: "withheld",
  MISSING: "missing",
  EXPIRED: "expired",
  SIGNED_OUT: "signed-out",
  BROKEN: "broken",
};

/** The API's own marker for a session that was presented and is no longer good. */
const SESSION_EXPIRED = "session_expired";

export function cardUrl(studentMembershipId, termId) {
  return `/api/results/cards/${encodeURIComponent(
    studentMembershipId,
  )}/${encodeURIComponent(termId)}/`;
}

/**
 * Fetch one card. Resolves to `{ok: true, card}` or `{ok: false, refusal, body}`.
 *
 * It does not throw for a refusal, because a withheld card and an expired
 * session are answers rather than faults — the page has something to say for
 * each. A transport failure or an unreadable body is `BROKEN`, which is the
 * only state the page cannot explain to a parent and says so honestly.
 *
 * `credentials: "same-origin"` is the default in every browser this targets and
 * is stated anyway: the session cookie is the entire authentication story here,
 * and a future edit adding `credentials: "omit"` would turn every card into a
 * 401 with no other symptom.
 */
export async function fetchCard({ studentMembershipId, termId, fetchImpl = fetch }) {
  let response;
  try {
    response = await fetchImpl(cardUrl(studentMembershipId, termId), {
      headers: { Accept: "application/json" },
      credentials: "same-origin",
    });
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }

  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (response.status === 200 && body) return { ok: true, card: body };

  return { ok: false, refusal: refusalFor(response.status, body), body: body || {} };
}

/** Which state an answer puts the page in. Exported so a test can name it. */
export function refusalFor(status, body) {
  if (status === 403) return REFUSAL.WITHHELD;
  if (status === 404) return REFUSAL.MISSING;
  if (status === 401) {
    return body && body.code === SESSION_EXPIRED
      ? REFUSAL.EXPIRED
      : REFUSAL.SIGNED_OUT;
  }
  return REFUSAL.BROKEN;
}
