/**
 * The fetches the OGSERA filler makes (`results/ogsera_api.py`).
 *
 * The workbook goes with every step and is never stored: headings, check and
 * fill each send it again, multipart, with the CSRF token.
 */

import { csrfToken, getJson, putJson } from "../web/http.js";

export const REFUSAL = {
  NOT_THE_OFFICE: "not-the-office",
  NOT_OGUN: "not-ogun",
  WRONG_HOST: "wrong-host",
  EXPIRED: "expired",
  SIGNED_OUT: "signed-out",
  BROKEN: "broken",
};

const BASE = "/api/results/ogsera/";
export const DOOR_URL = BASE;
export const HEADINGS_URL = `${BASE}headings/`;
export const MAPPING_URL = `${BASE}mapping/`;
export const CHECK_URL = `${BASE}check/`;
export const FILL_URL = `${BASE}fill/`;

export function refusalFor(status, body) {
  if (status === 403) return REFUSAL.NOT_THE_OFFICE;
  if (status === 409) return REFUSAL.NOT_OGUN;
  if (status === 404) return REFUSAL.WRONG_HOST;
  if (status === 401) return body && body.code === "session_expired" ? REFUSAL.EXPIRED : REFUSAL.SIGNED_OUT;
  return REFUSAL.BROKEN;
}

function answerFrom({ status, body }) {
  if (status === 200 && body) return { ok: true, body };
  if (status === 422) return { ok: false, rejected: true, body: body || {} };
  return { ok: false, refusal: refusalFor(status, body), body: body || {} };
}

function broken(error) {
  return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
}

export async function fetchDoor({ fetchImpl = fetch } = {}) {
  try {
    return answerFrom(await getJson(DOOR_URL, { fetchImpl }));
  } catch (error) {
    return broken(error);
  }
}

export async function saveMapping({ columns, fetchImpl = fetch }) {
  try {
    return answerFrom(await putJson(MAPPING_URL, { columns }, { fetchImpl }));
  } catch (error) {
    return broken(error);
  }
}

async function post(url, fields, fetchImpl, refresh) {
  const body = new FormData();
  for (const [name, value] of Object.entries(fields)) {
    if (value !== null && value !== undefined && value !== "") body.append(name, value);
  }
  return fetchImpl(url, {
    method: "POST",
    headers: { "X-CSRFToken": await csrfToken({ fetchImpl, refresh }) },
    credentials: "same-origin",
    body,
  });
}

async function send(url, fields, fetchImpl) {
  let response = await post(url, fields, fetchImpl, false);
  if (response.status === 403) {
    let body = null;
    try {
      body = await response.clone().json();
    } catch {
      body = null;
    }
    if (body && body.code === "csrf_failed") response = await post(url, fields, fetchImpl, true);
  }
  return response;
}

async function json(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

/** Step 1: the header row of `file`, with what each heading is mapped to now. */
export async function readHeadings({ file, fetchImpl = fetch }) {
  try {
    const response = await send(HEADINGS_URL, { file }, fetchImpl);
    return answerFrom({ status: response.status, body: await json(response) });
  } catch (error) {
    return broken(error);
  }
}

/** Step 2: what would be filled and what stands in the way. Writes nothing. */
export async function checkFile({ file, classGroupId, subjectId, replace, fetchImpl = fetch }) {
  try {
    const response = await send(
      CHECK_URL,
      { file, class_group_id: classGroupId, subject_id: subjectId, replace: replace ? "1" : "" },
      fetchImpl,
    );
    return answerFrom({ status: response.status, body: await json(response) });
  } catch (error) {
    return broken(error);
  }
}

/** Step 3: the filled workbook, as a Blob. */
export async function fillFile({ file, classGroupId, subjectId, replace, fetchImpl = fetch }) {
  try {
    const response = await send(
      FILL_URL,
      { file, class_group_id: classGroupId, subject_id: subjectId, replace: replace ? "1" : "" },
      fetchImpl,
    );
    if (response.status === 200) return { ok: true, blob: await response.blob() };
    return answerFrom({ status: response.status, body: await json(response) });
  } catch (error) {
    return broken(error);
  }
}
