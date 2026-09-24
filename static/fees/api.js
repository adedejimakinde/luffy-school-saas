/**
 * The fetches the fees page makes, and what each answer means.
 *
 * **A 404 is one answer here, on purpose.** Every read refuses a reader who
 * may not see the books with a flat 404 — the same as for a child or an entry
 * that does not exist — so the page says "not something you can open" for
 * both and never guesses which. A 403 is different: it goes only to somebody
 * who reads the books and may not write to them, and its sentence is shown.
 */

import { deleteJson, getJson, postJson, putJson } from "../web/http.js";

export const REFUSAL = {
  NOT_YOURS: "not-yours",
  WRONG_HOST: "wrong-host",
  EXPIRED: "expired",
  SIGNED_OUT: "signed-out",
  BROKEN: "broken",
};

const SESSION_EXPIRED = "session_expired";
const q = encodeURIComponent;

export const booksUrl = (termId) =>
  termId == null ? "/api/fees/classes/" : `/api/fees/classes/?term_id=${q(termId)}`;
export const classUrl = (classId, termId) => `/api/fees/classes/${q(classId)}/?term_id=${q(termId)}`;
export const accountUrl = (studentId) => `/api/fees/students/${q(studentId)}/`;
export const paymentUrl = (studentId) => `/api/fees/students/${q(studentId)}/payments/`;
export const discountUrl = (studentId) => `/api/fees/students/${q(studentId)}/discounts/`;
export const reversalUrl = (entryId) => `/api/fees/entries/${q(entryId)}/reversal/`;
export const receiptUrl = (entryId) => `/api/fees/entries/${q(entryId)}/receipt/`;
export const billsUrl = (termId) =>
  termId == null ? "/api/fees/bills/" : `/api/fees/bills/?term_id=${q(termId)}`;
export const billUrl = (classId, termId) => `/api/fees/classes/${q(classId)}/bill/?term_id=${q(termId)}`;
export const billLinesUrl = (classId) => `/api/fees/classes/${q(classId)}/bill/lines/`;
export const billLineUrl = (lineId) => `/api/fees/bill-lines/${q(lineId)}/`;
export const chargesUrl = (classId) => `/api/fees/classes/${q(classId)}/bill/charges/`;
export const concessionsUrl = (studentId) => `/api/fees/students/${q(studentId)}/concessions/`;
export const revocationUrl = (concessionId) => `/api/fees/concessions/${q(concessionId)}/revocation/`;

export function refusalFor(status, body) {
  if (status === 404) return REFUSAL.NOT_YOURS;
  if (status === 401) {
    return body && body.code === SESSION_EXPIRED ? REFUSAL.EXPIRED : REFUSAL.SIGNED_OUT;
  }
  return REFUSAL.BROKEN;
}

async function read(url, fetchImpl) {
  let answer;
  try {
    answer = await getJson(url, { fetchImpl });
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
  if (answer.status === 200 && answer.body) return { ok: true, body: answer.body };
  return { ok: false, refusal: refusalFor(answer.status, answer.body), body: answer.body || {} };
}

/**
 * A write. 201 is posted; **200 is "this form had already posted"**, which is
 * success too — the payment is in the books once. 403, 409 and 422 carry a
 * sentence for the person and keep the page where it is.
 */
async function write(url, payload, fetchImpl, send = postJson) {
  let answer;
  try {
    answer = await send(url, payload, { fetchImpl });
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
  if ((answer.status === 201 || answer.status === 200) && answer.body) {
    return { ok: true, body: answer.body };
  }
  if ([403, 409, 422].includes(answer.status)) {
    return { ok: false, refusal: null, body: answer.body || {} };
  }
  return { ok: false, refusal: refusalFor(answer.status, answer.body), body: answer.body || {} };
}

export const fetchBooks = ({ termId = null, fetchImpl = fetch } = {}) => read(booksUrl(termId), fetchImpl);
export const fetchClass = ({ classId, termId, fetchImpl = fetch }) => read(classUrl(classId, termId), fetchImpl);
export const fetchAccount = ({ studentId, fetchImpl = fetch }) => read(accountUrl(studentId), fetchImpl);
export const fetchReceipt = ({ entryId, fetchImpl = fetch }) => read(receiptUrl(entryId), fetchImpl);
export const postPayment = ({ studentId, payment, fetchImpl = fetch }) =>
  write(paymentUrl(studentId), payment, fetchImpl);
export const postDiscount = ({ studentId, discount, fetchImpl = fetch }) =>
  write(discountUrl(studentId), discount, fetchImpl);
export const postReversal = ({ entryId, reason, fetchImpl = fetch }) =>
  write(reversalUrl(entryId), { reason }, fetchImpl);

// -- B2: bills and concessions. Every bill write answers with the bill as it
// now stands, so the page draws what the server holds rather than patching.

export const fetchBills = ({ termId = null, fetchImpl = fetch } = {}) => read(billsUrl(termId), fetchImpl);
export const fetchBill = ({ classId, termId, fetchImpl = fetch }) => read(billUrl(classId, termId), fetchImpl);
export const fetchConcessions = ({ studentId, fetchImpl = fetch }) => read(concessionsUrl(studentId), fetchImpl);
export const postBillLine = ({ classId, line, fetchImpl = fetch }) => write(billLinesUrl(classId), line, fetchImpl);
export const putBillLine = ({ lineId, line, fetchImpl = fetch }) =>
  write(billLineUrl(lineId), line, fetchImpl, putJson);
export const removeBillLine = ({ lineId, fetchImpl = fetch }) =>
  write(billLineUrl(lineId), undefined, fetchImpl, (url, _payload, options) => deleteJson(url, options));
export const postCharges = ({ classId, termId, fetchImpl = fetch }) =>
  write(chargesUrl(classId), { term_id: termId }, fetchImpl);
export const postConcession = ({ studentId, concession, fetchImpl = fetch }) =>
  write(concessionsUrl(studentId), concession, fetchImpl);
export const postRevocation = ({ concessionId, reason, fetchImpl = fetch }) =>
  write(revocationUrl(concessionId), { reason }, fetchImpl);
