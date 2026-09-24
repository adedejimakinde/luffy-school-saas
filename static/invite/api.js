/**
 * The two fetches the invitation page makes, and what each answer means.
 *
 * **Every refusal about the token is one state.** Unknown, already used,
 * replaced by a newer invitation, or out of time: the server answers all of
 * them alike, on purpose, so a guessed token and a spent one cannot be told
 * apart — and this module keeps that, mapping *any* refused answer to `DEAD`
 * without reading its status or its words. A page that said "expired" for one
 * and "not found" for another would hand back the difference the server
 * withholds.
 *
 * The one refusal that is not about the token is a password the server will
 * not take (422): that is the invitee's to fix, so its sentence is shown.
 */

import { getJson, postJson } from "../web/http.js";

export const DEAD = "dead";
export const BROKEN = "broken";

export function tokenFrom(pathname = "") {
  const found = /^\/invitations\/([^/]+)\/?$/.exec(pathname);
  if (!found) return "";
  try {
    return decodeURIComponent(found[1]);
  } catch {
    return "";
  }
}

export const previewUrl = (token) => `/api/invitations/${encodeURIComponent(token)}/`;
export const acceptUrl = (token) => `${previewUrl(token)}accept/`;

/** A server that failed says nothing about the token, so it is not `DEAD`. */
function refusal(status) {
  return status >= 500 ? BROKEN : DEAD;
}

export async function fetchPreview({ token, fetchImpl = fetch }) {
  let answer;
  try {
    answer = await getJson(previewUrl(token), { fetchImpl });
  } catch {
    return { ok: false, refusal: BROKEN };
  }
  if (answer.status === 200 && answer.body) return { ok: true, body: answer.body };
  return { ok: false, refusal: refusal(answer.status) };
}

export async function accept({ token, password = null, fetchImpl = fetch }) {
  let answer;
  try {
    answer = await postJson(acceptUrl(token), password ? { password } : {}, { fetchImpl });
  } catch {
    return { ok: false, refusal: BROKEN };
  }
  if (answer.status === 200 && answer.body) return { ok: true, body: answer.body };
  if (answer.status === 422) {
    return { ok: false, note: (answer.body && answer.body.detail) || "That password cannot be used." };
  }
  return { ok: false, refusal: refusal(answer.status) };
}
