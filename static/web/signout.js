/**
 * Ending a session, from whichever page the reader is looking at.
 *
 * Shared by every page that can have somebody signed in on it — the two family
 * pages on a school's host and the staff landing on the portal — because all
 * three do the same three things and the third one is a judgement rather than a
 * call.
 *
 * ## It posts to the host the page is already on
 *
 * `/api/logout/` is mounted in `urls.py`, which both urlconfs serve, so the
 * portal's own route answers the staff page and a school's own route answers
 * the pages on that school's host. Nothing here crosses hosts, which is what
 * keeps `CSRF_TRUSTED_ORIGINS` untouched — `docs/sign-in-page.md` predicted
 * exactly this POST and said it would need no setting, and it does not.
 *
 * The route is authenticated on purpose (`auth=session_auth`), which is what
 * puts it behind ninja's CSRF check: an unauthenticated logout is a route any
 * other origin can aim at a signed-in teacher's browser to throw away the
 * session they are marking with. `postJson` carries the token, so that costs
 * this module nothing.
 *
 * ## One session, both hosts
 *
 * `logout()` flushes the session rather than forgetting the user, and the
 * cookie is scoped to a domain covering the portal and every school host —
 * `accounts.checks.session_cookie_spans_every_host` refuses a deployment where
 * it is not. So signing out on a school's host ends the portal session too.
 * That is the behaviour a shared handset needs and it is worth knowing it is
 * not per-host, because a button that ended one of several sessions would be
 * worse than no button.
 */

import { postJson } from "./http.js";

export const SIGN_OUT_URL = "/api/logout/";

/**
 * The control itself.
 *
 * A `button` and not a link: this is a POST, and a link that performed one
 * would be a link a prefetcher could follow. `data-action` rather than an id,
 * because more than one page mounts it and each delegates from its own root.
 */
export function button(label = "Sign out") {
  return `<button type="button" class="signout" data-action="sign-out">${label}</button>`;
}

/** Ask. Resolves to `{status, body}`; a transport failure is status 0. */
export async function signOut({ fetchImpl = fetch } = {}) {
  try {
    return await postJson(SIGN_OUT_URL, {}, { fetchImpl });
  } catch {
    return { status: 0, body: {} };
  }
}

/**
 * Whether that answer means there is no session left. The judgement.
 *
 * **401 counts.** A caller whose session had already gone asks to be signed out
 * and is told nobody is signed in, which is a true answer to the question —
 * `api.sign_out()` says so in as many words. Treating it as a failure would
 * leave a reader staring at "could not sign you out" on a browser holding
 * nothing.
 *
 * **Everything else does not**, including a 500 and a dead transport. The two
 * wrong answers here are not symmetrical: telling somebody they are still
 * signed in when they are not is a wasted tap, and telling somebody they are
 * signed out when the session is still live is the shared handset this platform
 * is built for, handed to the next person with the cards still open. So the
 * uncertain cases read as "not ended" and the page says what to do instead.
 */
export function sessionEnded({ status }) {
  return status === 200 || status === 401;
}

/**
 * What to say when `sessionEnded()` said no, and the page it says it on.
 *
 * Here rather than in each page's states, because it is the other half of the
 * judgement above: the reason three pages must not claim a session ended when
 * they cannot show it did is the reason they must all tell the reader the same
 * thing to do instead. Closing the browser is advice a person can act on
 * without us; "try again" is not, because the failure that got here is a server
 * that is not answering.
 *
 * No `esc()` call and no exception to the rule it belongs to: there is nothing
 * interpolated into this string. It is a literal with no markup in it, which is
 * what `esc()` exists to guarantee of values that are *not* literals.
 */
export const COULD_NOT_END =
  "We could not sign you out. Close this browser to be sure your session is " +
  "not left open.";

export function failureNote() {
  return `<p class="problem" role="alert">${COULD_NOT_END}</p>`;
}
