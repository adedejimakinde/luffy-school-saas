/**
 * The exam page's calls to `/sit/api/`. `cbt/sit_views.py` says what each answers.
 *
 * No CSRF token: there is no account session to protect, and the one credential, the
 * `sit` cookie, is `SameSite=Strict` and scoped to `/sit/` (`sit_views` says why). Every
 * write is JSON, which a form on another site cannot send.
 *
 * Each call answers `{ status, body }`, or `{ status: 0 }` when the school could not be
 * reached at all, which is what the page reads as offline.
 */

const BASE = "/sit/api/";

async function call(path, { method = "POST", body = null, fetchImpl = fetch } = {}) {
  try {
    const response = await fetchImpl(`${BASE}${path}`, {
      method,
      credentials: "same-origin",
      cache: "no-store",
      headers: method === "POST" ? { "Content-Type": "application/json", Accept: "application/json" } : { Accept: "application/json" },
      body: method === "POST" ? JSON.stringify(body || {}) : undefined,
    });
    let answer = null;
    try {
      answer = await response.json();
    } catch {
      answer = null;
    }
    return { status: response.status, body: answer || {} };
  } catch {
    return { status: 0, body: {} };
  }
}

export const door = ({ code, number, pin, fetchImpl }) => call("door/", { body: { code, admission_number: number, pin }, fetchImpl });
export const notMe = ({ ticket, fetchImpl }) => call("not-me/", { body: { ticket }, fetchImpl });
export const start = ({ ticket, seat, syncOffsetMs, fetchImpl }) =>
  call("start/", { body: { ticket, seat, sync_offset_ms: syncOffsetMs }, fetchImpl });
export const attempt = ({ fetchImpl } = {}) => call("attempt/", { method: "GET", fetchImpl });
export const sync = ({ answers, events, fetchImpl }) => call("sync/", { body: { answers, events }, fetchImpl });
export const submit = ({ answers, events, byClock = false, fetchImpl }) =>
  call("submit/", { body: { answers, events, by_clock: byClock }, fetchImpl });
