/**
 * The fetches the staff invitations screen makes, and what each answer means.
 *
 * The routes are `api.py`'s, addressed by the school's slug. Every refusal
 * there is an `HttpError`, so every failed answer carries `{"detail": ...}`.
 */

import { getJson, postJson } from "../web/http.js";

/** The states the whole page can be in, other than holding the list. */
export const REFUSAL = {
  /** Signed in, and not somebody who may invite staff here. */
  NOT_THE_OFFICE: "not-the-office",
  /** The portal, or a host that is not a school's. */
  WRONG_HOST: "wrong-host",
  EXPIRED: "expired",
  SIGNED_OUT: "signed-out",
  BROKEN: "broken",
};

const SESSION_EXPIRED = "session_expired";

export function listUrl(slug) {
  return `/api/schools/${encodeURIComponent(slug)}/invitations/`;
}

export function actionUrl(slug, invitationId, action) {
  return `${listUrl(slug)}${encodeURIComponent(invitationId)}/${action}/`;
}

/** Which page-level state an answer produces. */
export function refusalFor(status, body) {
  if (status === 403) return REFUSAL.NOT_THE_OFFICE;
  if (status === 404) return REFUSAL.WRONG_HOST;
  if (status === 401) {
    return body && body.code === SESSION_EXPIRED ? REFUSAL.EXPIRED : REFUSAL.SIGNED_OUT;
  }
  return REFUSAL.BROKEN;
}

/** Every invitation here that is still somebody's to act on. */
export async function fetchInvitations({ slug, fetchImpl = fetch }) {
  let answer;
  try {
    answer = await getJson(listUrl(slug), { fetchImpl });
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
  if (answer.status === 200 && answer.body) return { ok: true, body: answer.body };
  return { ok: false, refusal: refusalFor(answer.status, answer.body), body: answer.body || {} };
}

/**
 * Classify a write. **A refusal with a sentence is a note, not a page
 * state**: 400, 409, 502 and 503 each say something the office can read —
 * a missing address, somebody already on the staff, a mail server down — and
 * the list is still there behind them.
 */
function classify(answer, expected) {
  if (answer.status === expected || answer.status === 200) return { ok: true, row: answer.body || {} };
  if ([400, 403, 409, 422, 502, 503].includes(answer.status)) {
    return { ok: false, note: (answer.body && answer.body.detail) || "That did not work." };
  }
  return { ok: false, refusal: refusalFor(answer.status, answer.body), body: answer.body || {} };
}

async function write(url, payload, expected, fetchImpl) {
  try {
    return classify(await postJson(url, payload, { fetchImpl }), expected);
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
}

/**
 * Invite somebody. **One box for the address**, and which kind it is follows
 * from the `@`: an office has one thing in front of them for a new teacher,
 * and making them choose a field for it is a question they should not need
 * to answer.
 */
export function inviteePayload({ address = "", role = "", full_name = "" }) {
  const value = address.trim();
  const payload = { role, full_name: full_name.trim() };
  if (value.includes("@")) payload.email = value;
  else payload.phone = value;
  return payload;
}

export function invite({ slug, invitee, fetchImpl = fetch }) {
  return write(listUrl(slug), inviteePayload(invitee), 201, fetchImpl);
}

export function resend({ slug, invitationId, fetchImpl = fetch }) {
  return write(actionUrl(slug, invitationId, "resend"), {}, 201, fetchImpl);
}

export function revoke({ slug, invitationId, fetchImpl = fetch }) {
  return write(actionUrl(slug, invitationId, "revoke"), {}, 200, fetchImpl);
}
