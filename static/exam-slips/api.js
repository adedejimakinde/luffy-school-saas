/**
 * The fetches the exam slips screen makes: the overview, one class's students, a
 * class's slips or one student's, and the principal naming and ending exam officers.
 *
 * Every officer write answers with the whole overview, so the page redraws from the
 * school's own answer. A print answers with the PDF itself, which is the only place the
 * PINs are ever written out; the page hands it to the browser to save and keeps nothing.
 */

import { csrfToken, getJson, postJson } from "../web/http.js";

/** The states the whole page can be in, other than holding the overview. */
export const REFUSAL = {
  /** Signed in, and not the principal, the administrator or an exam officer. */
  NOT_YOURS: "not-yours",
  /** The portal, or a host that is not a school's. */
  WRONG_HOST: "wrong-host",
  EXPIRED: "expired",
  SIGNED_OUT: "signed-out",
  BROKEN: "broken",
};

const SESSION_EXPIRED = "session_expired";
const BASE = "/api/cbt/";

export function refusalFor(status, body) {
  if (status === 403) return REFUSAL.NOT_YOURS;
  if (status === 404) return REFUSAL.WRONG_HOST;
  if (status === 401) {
    return body && body.code === SESSION_EXPIRED ? REFUSAL.EXPIRED : REFUSAL.SIGNED_OUT;
  }
  return REFUSAL.BROKEN;
}

/** What an answer is: the body, a sentence to print (409, 422), or a page-level refusal. */
function classify(answer) {
  if (answer.status === 200 && answer.body) return { ok: true, body: answer.body };
  if (answer.status === 409 || answer.status === 422) return { ok: false, rejected: true, body: answer.body || {} };
  return { ok: false, refusal: refusalFor(answer.status, answer.body), body: answer.body || {} };
}

async function send(act) {
  try {
    return classify(await act());
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
}

export const fetchOverview = ({ fetchImpl = fetch } = {}) => send(() => getJson(`${BASE}slips/`, { fetchImpl }));

export const fetchClass = ({ classGroupId, fetchImpl = fetch }) =>
  send(() => getJson(`${BASE}slips/classes/${encodeURIComponent(classGroupId)}/`, { fetchImpl }));

export const nameOfficer = ({ membershipId, note = "", fetchImpl = fetch }) =>
  send(() => postJson(`${BASE}officers/`, { membership_id: membershipId, note }, { fetchImpl }));

export const endOfficer = ({ membershipId, fetchImpl = fetch }) =>
  send(() => postJson(`${BASE}officers/${encodeURIComponent(membershipId)}/end/`, {}, { fetchImpl }));

export function printUrl(classGroupId, studentId = null) {
  const base = `${BASE}slips/classes/${encodeURIComponent(classGroupId)}/`;
  return studentId == null ? `${base}print/` : `${base}students/${encodeURIComponent(studentId)}/print/`;
}

/**
 * Print a class's slips, or one student's. Resolves to `{ok: true, blob, filename}` or
 * `{ok: false, detail}` for a sentence the row can say, or with `refusal` for the page.
 *
 * Not `postJson()`, because a 200 here is a file, not JSON. The CSRF rule is
 * `web/http.js`'s all the same: the token from the API, and one retry on a stale one.
 */
export async function printSlips({ classGroupId, studentId = null, fetchImpl = fetch }) {
  const send = async (csrf) =>
    fetchImpl(printUrl(classGroupId, studentId), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/pdf, application/json",
        "X-CSRFToken": csrf,
      },
      credentials: "same-origin",
      cache: "no-store",
      body: "{}",
    });

  let response;
  let body = null;
  try {
    response = await send(await csrfToken({ fetchImpl }));
    if (response.status !== 200) {
      body = await jsonOf(response);
      if (response.status === 403 && body && body.code === "csrf_failed") {
        response = await send(await csrfToken({ fetchImpl, refresh: true }));
        body = response.status === 200 ? null : await jsonOf(response);
      }
    }
    if (response.status === 200) {
      return { ok: true, blob: await response.blob(), filename: filenameOf(response.headers.get("Content-Disposition")) };
    }
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
  body = body || {};
  if (response.status === 422) return { ok: false, detail: body.detail || "" };
  return { ok: false, refusal: refusalFor(response.status, body), body };
}

/** The server's name for the file, or a plain one if it gave none. */
export function filenameOf(disposition) {
  const named = /filename="([^"]+)"/.exec(disposition || "");
  return named ? named[1] : "exam-slips.pdf";
}

async function jsonOf(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}
