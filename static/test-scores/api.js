/**
 * The calls `/test-scores/` makes. `cbt/score_views.py` and `cbt/results_api.py` say what
 * each answers.
 *
 * A parent's children's scores are read with the account session. A student's own are
 * opened with the test code, their admission number and exam PIN: no account, no CSRF
 * token (there is no session to ride on), JSON only, and no cookie comes back.
 *
 * Each call answers `{ status, body }`, or `{ status: 0 }` when the school could not be
 * reached.
 */

import { getJson } from "../web/http.js";

export async function family({ fetchImpl = fetch } = {}) {
  try {
    return await getJson("/api/cbt/scores/", { fetchImpl });
  } catch {
    return { status: 0, body: {} };
  }
}

export async function open({ code, number, pin, fetchImpl = fetch }) {
  try {
    const response = await fetchImpl("/test-scores/api/open/", {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ code, admission_number: number, pin }),
    });
    let body = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    return { status: response.status, body: body || {} };
  } catch {
    return { status: 0, body: {} };
  }
}
