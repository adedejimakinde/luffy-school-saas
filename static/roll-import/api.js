/**
 * The fetches the roll import makes, and what each answer means.
 *
 * Three calls, in the order the page makes them: what the school's import
 * door says (its term and classes), a check of the chosen file that writes
 * nothing, and the import of the same file. The file is sent twice rather than
 * trusting the first verdict, because the import runs the same check again on
 * the server: a file that passed a minute ago can meet an admission number
 * somebody else has just given out.
 */

import { csrfToken, getJson } from "../web/http.js";

/** The states the whole page can be in, other than working. */
export const REFUSAL = {
  /** Signed in, and not somebody who may admit children here. */
  NOT_THE_OFFICE: "not-the-office",
  /** The portal, or a host that is not a school's. */
  WRONG_HOST: "wrong-host",
  EXPIRED: "expired",
  SIGNED_OUT: "signed-out",
  BROKEN: "broken",
};

const SESSION_EXPIRED = "session_expired";

const BASE = "/api/enrolment/roll/import/";

export const DOOR_URL = `${BASE}door/`;
export const CHECK_URL = `${BASE}check/`;
export const IMPORT_URL = `${BASE}file/`;
export const TEMPLATE_URL = `${BASE}template/`;

/**
 * Which page-level state an answer produces.
 *
 * A 422 is not one of them: it is the file that disagrees, and the page says
 * why beside the file chooser rather than giving up the page.
 */
export function refusalFor(status, body) {
  if (status === 403) return REFUSAL.NOT_THE_OFFICE;
  if (status === 404) return REFUSAL.WRONG_HOST;
  if (status === 401) {
    return body && body.code === SESSION_EXPIRED ? REFUSAL.EXPIRED : REFUSAL.SIGNED_OUT;
  }
  return REFUSAL.BROKEN;
}

function answerFrom({ status, body }) {
  if (status === 200 && body) return { ok: true, body };
  if (status === 422) return { ok: false, rejected: true, body: body || {} };
  return { ok: false, refusal: refusalFor(status, body), body: body || {} };
}

/** This school's term and classes, or the refusal that replaces the page. */
export async function fetchDoor({ fetchImpl = fetch } = {}) {
  try {
    return answerFrom(await getJson(DOOR_URL, { fetchImpl }));
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
}

async function readBody(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

/**
 * One file, posted as multipart with the CSRF token, retried once on a stale
 * token: the rule `web/http.js` keeps for JSON, kept here for a file.
 */
async function postFile(url, file, { fetchImpl = fetch } = {}) {
  const send = async (refresh) => {
    const body = new FormData();
    body.append("file", file);
    const response = await fetchImpl(url, {
      method: "POST",
      headers: { Accept: "application/json", "X-CSRFToken": await csrfToken({ fetchImpl, refresh }) },
      credentials: "same-origin",
      body,
    });
    return { status: response.status, body: await readBody(response) };
  };
  try {
    let answer = await send(false);
    if (answer.status === 403 && answer.body && answer.body.code === "csrf_failed") {
      answer = await send(true);
    }
    return answerFrom(answer);
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
}

/** Every row's verdict. Writes nothing. */
export function checkFile({ file, fetchImpl = fetch }) {
  return postFile(CHECK_URL, file, { fetchImpl });
}

/** The whole file admitted, or none of it. */
export function importFile({ file, fetchImpl = fetch }) {
  return postFile(IMPORT_URL, file, { fetchImpl });
}
