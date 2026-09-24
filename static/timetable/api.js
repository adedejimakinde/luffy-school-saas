/**
 * The fetches the timetable page makes, and what each answer means.
 *
 * **A 404 is one answer here, on purpose.** The routes refuse somebody who may
 * not read a timetable with a flat 404 — the same as for a class or term that
 * does not exist — so "you may not" and "there is no such thing" read alike.
 * Which *host* the page is on, it is told by the frame instead.
 *
 * **A 403, a 409 and a 422 on a write are sentences for a person**: the
 * principal told they read and do not set, a clash naming the lesson the
 * teacher is already in, a period that overlaps another. Each keeps its
 * `detail`, because it was written to be read.
 */

import { deleteJson, getJson, postJson, putJson } from "../web/http.js";

export const REFUSAL = {
  /** Refused, or no such class or term — deliberately the same answer. */
  NOT_YOURS: "not-yours",
  WRONG_HOST: "wrong-host",
  EXPIRED: "expired",
  SIGNED_OUT: "signed-out",
  BROKEN: "broken",
};

const SESSION_EXPIRED = "session_expired";

const q = encodeURIComponent;

export const indexUrl = (termId) =>
  termId === undefined || termId === null
    ? "/api/timetable/"
    : `/api/timetable/?term_id=${q(termId)}`;
export const weekUrl = (classId, termId) =>
  `/api/timetable/classes/${q(classId)}/?term_id=${q(termId)}`;
export const lessonsUrl = (classId) => `/api/timetable/classes/${q(classId)}/lessons/`;
export const slotUrl = (classId, termId, weekday, periodId) =>
  `${lessonsUrl(classId)}?term_id=${q(termId)}&weekday=${q(weekday)}&period_id=${q(periodId)}`;
export const copyUrl = (termId) => `/api/timetable/terms/${q(termId)}/copy/`;
export const periodsUrl = () => "/api/timetable/periods/";
export const periodUrl = (periodId) => `/api/timetable/periods/${q(periodId)}/`;

export function refusalFor(status, body) {
  if (status === 404) return REFUSAL.NOT_YOURS;
  if (status === 401) {
    return body && body.code === SESSION_EXPIRED ? REFUSAL.EXPIRED : REFUSAL.SIGNED_OUT;
  }
  return REFUSAL.BROKEN;
}

/** Statuses a write answers with a sentence for a person, not a state. */
const SENTENCES = [403, 409, 422];

async function ask(request, okStatuses, sentences = []) {
  let answer;
  try {
    answer = await request();
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
  const body = answer.body || {};
  if (okStatuses.includes(answer.status)) return { ok: true, status: answer.status, body };
  if (sentences.includes(answer.status) && body.detail) return { ok: false, refusal: null, body };
  return { ok: false, refusal: refusalFor(answer.status, answer.body), body };
}

const write = (request, okStatuses) => ask(request, okStatuses, SENTENCES);

export function fetchIndex({ termId = null, fetchImpl = fetch } = {}) {
  return ask(() => getJson(indexUrl(termId), { fetchImpl }), [200]);
}

export function fetchWeek({ classId, termId, fetchImpl = fetch }) {
  return ask(() => getJson(weekUrl(classId, termId), { fetchImpl }), [200]);
}

export function putLesson({ classId, lesson, fetchImpl = fetch }) {
  return write(() => putJson(lessonsUrl(classId), lesson, { fetchImpl }), [200, 201]);
}

export function clearLesson({ classId, termId, weekday, periodId, fetchImpl = fetch }) {
  return write(() => deleteJson(slotUrl(classId, termId, weekday, periodId), { fetchImpl }), [204]);
}

export function copyLastTerm({ termId, fetchImpl = fetch }) {
  return write(() => postJson(copyUrl(termId), {}, { fetchImpl }), [201]);
}

export function addPeriod({ startsAt, endsAt, label = "", fetchImpl = fetch }) {
  return write(
    () => postJson(periodsUrl(), { starts_at: startsAt, ends_at: endsAt, label }, { fetchImpl }),
    [201],
  );
}

export function removePeriod({ periodId, fetchImpl = fetch }) {
  return write(() => deleteJson(periodUrl(periodId), { fetchImpl }), [204]);
}
