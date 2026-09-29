/**
 * The calls the bank screen makes (`fees/bank_api.py`): the state, the bank
 * list, the name Paystack's bank resolve gives, and the one write.
 *
 * A 403 is "not the bursar or an administrator"; a 404 is the portal or a login
 * that may not read the books. On the write, 409/422 carry a sentence and 503
 * says Paystack is not there: each keeps the page up behind it.
 */

import { getJson, postJson } from "../web/http.js";

export const REFUSAL = {
  NOT_ALLOWED: "not-allowed",
  WRONG_HOST: "wrong-host",
  EXPIRED: "expired",
  SIGNED_OUT: "signed-out",
  BROKEN: "broken",
};

const SESSION_EXPIRED = "session_expired";
const BASE = "/api/fees/bank/";

export function refusalFor(status, body) {
  if (status === 403) return REFUSAL.NOT_ALLOWED;
  if (status === 404) return REFUSAL.WRONG_HOST;
  if (status === 401) {
    return body && body.code === SESSION_EXPIRED ? REFUSAL.EXPIRED : REFUSAL.SIGNED_OUT;
  }
  return REFUSAL.BROKEN;
}

async function call(run, { note = [409, 422, 503] } = {}) {
  let answer;
  try {
    answer = await run();
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
  if ((answer.status === 200 || answer.status === 201) && answer.body) return { ok: true, body: answer.body };
  if (note.includes(answer.status)) {
    return { ok: false, note: (answer.body && answer.body.detail) || "That did not work." };
  }
  return { ok: false, refusal: refusalFor(answer.status, answer.body), body: answer.body || {} };
}

export const fetchState = ({ fetchImpl = fetch } = {}) =>
  call(() => getJson(BASE, { fetchImpl }), { note: [] });

export const fetchBanks = ({ fetchImpl = fetch } = {}) =>
  call(() => getJson(`${BASE}banks/`, { fetchImpl }));

export const resolveAccount = (account, { fetchImpl = fetch } = {}) =>
  call(() => postJson(`${BASE}resolve/`, account, { fetchImpl }));

export const connectAccount = (account, { fetchImpl = fetch } = {}) =>
  call(() => postJson(BASE, account, { fetchImpl }));
