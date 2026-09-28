/**
 * The fetches the setup screen makes, and what each answer means.
 */

import { csrfToken, getJson, postJson, putJson } from "../web/http.js";

/** The states the whole page can be in, other than holding the school's shape. */
export const REFUSAL = {
  /** Signed in, and not somebody who shapes this school. */
  NOT_THE_OFFICE: "not-the-office",
  /** The portal, or a host that is not a school's. */
  WRONG_HOST: "wrong-host",
  EXPIRED: "expired",
  SIGNED_OUT: "signed-out",
  BROKEN: "broken",
};

/** What one write can come back as, beyond having worked. */
export const SAVE = {
  /** The calendar disagrees with itself, or the name is taken. Retypable. */
  REJECTED: "rejected",
  /** A standing they do not have. No retry helps. */
  NOT_ALLOWED: "not-allowed",
};

const SESSION_EXPIRED = "session_expired";

export function setupUrl() {
  return "/api/academics/setup/";
}

export function termsUrl() {
  return "/api/academics/terms/";
}

export function currentTermUrl(termId) {
  return `/api/academics/terms/${encodeURIComponent(termId)}/current/`;
}

export function classesUrl() {
  return "/api/academics/classes/";
}

export function colourUrl() {
  return "/api/academics/card/colour/";
}

export function crestUrl() {
  return "/api/academics/card/crest/";
}

export function contactEmailUrl() {
  return "/api/academics/contact-email/";
}

/**
 * Which page-level state an answer produces.
 *
 * **403 and 404 are different refusals.** A 403 is `can_set_up()`: signed in
 * at this school and not the office — a teacher, a bursar. A 404 is
 * `_school_of()`: this host is not a school's, so there is no calendar behind
 * the URL at all.
 */
export function refusalFor(status, body) {
  if (status === 403) return REFUSAL.NOT_THE_OFFICE;
  if (status === 404) return REFUSAL.WRONG_HOST;
  if (status === 401) {
    return body && body.code === SESSION_EXPIRED
      ? REFUSAL.EXPIRED
      : REFUSAL.SIGNED_OUT;
  }
  return REFUSAL.BROKEN;
}


/** The school's shape: every term and every class group. */
export async function fetchSetup({ fetchImpl = fetch } = {}) {
  let answer;
  try {
    answer = await getJson(setupUrl(), { fetchImpl });
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
  if (answer.status === 200 && answer.body) return { ok: true, body: answer.body };
  return {
    ok: false,
    refusal: refusalFor(answer.status, answer.body),
    body: answer.body || {},
  };
}

/**
 * Classify a write.
 *
 * **422 and 403 stay apart** because their remedies do: a calendar that
 * disagrees with itself is something the person can retype, and a standing
 * they do not have is not. Both arrive with a sentence the server wrote —
 * `full_clean()` turning a model constraint into words — and the page prints
 * it rather than inventing its own.
 */
function classify(answer, created = 201) {
  if (answer.status === created || answer.status === 200) {
    return { ok: true, row: answer.body || {} };
  }
  if (answer.status === 422) return { ok: false, outcome: SAVE.REJECTED, body: answer.body || {} };
  if (answer.status === 403) return { ok: false, outcome: SAVE.NOT_ALLOWED, body: answer.body || {} };
  return {
    ok: false,
    refusal: refusalFor(answer.status, answer.body),
    body: answer.body || {},
  };
}

/** Open a term's record. Does **not** make it current — that is a second act. */
export async function createTerm({ term, fetchImpl = fetch }) {
  try {
    return classify(await postJson(termsUrl(), term, { fetchImpl }));
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
}

/** Say which term the school is teaching now. The old one is cleared server-side. */
export async function makeCurrent({ termId, fetchImpl = fetch }) {
  try {
    return classify(await putJson(currentTermUrl(termId), {}, { fetchImpl }), 200);
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
}

/** Open a class group. */
export async function createClass({ group, fetchImpl = fetch }) {
  try {
    return classify(await postJson(classesUrl(), group, { fetchImpl }));
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
}

/** The card's one colour. A 422 is a colour too light to read, and says so. */
export async function saveColour({ colour, fetchImpl = fetch }) {
  let answer;
  try {
    answer = await putJson(colourUrl(), { colour }, { fetchImpl });
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
  return classify(answer, 200);
}

/**
 * This school's own contact email — where a reply to its outgoing mail
 * lands (`docs/messaging.md` D17). A 422 is an address that does not look
 * like one, and says so; blank clears it.
 */
export async function saveContactEmail({ contact_email, fetchImpl = fetch }) {
  let answer;
  try {
    answer = await putJson(contactEmailUrl(), { contact_email }, { fetchImpl });
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
  return classify(answer, 200);
}

/**
 * A new crest, as the file itself. Multipart, so the browser writes the body
 * and its boundary; the CSRF token goes in the header as it does for JSON.
 * Retried once on a stale token, as `postJson` does.
 */
export async function uploadCrest({ file, fetchImpl = fetch }) {
  const send = async (refresh) => {
    const body = new FormData();
    body.append("crest", file);
    const response = await fetchImpl(crestUrl(), {
      method: "POST",
      headers: { Accept: "application/json", "X-CSRFToken": await csrfToken({ fetchImpl, refresh }) },
      credentials: "same-origin",
      body,
    });
    let parsed = null;
    try {
      parsed = await response.json();
    } catch {
      parsed = null;
    }
    return { status: response.status, body: parsed };
  };
  let answer;
  try {
    answer = await send(false);
    if (answer.status === 403 && answer.body && answer.body.code === "csrf_failed") {
      answer = await send(true);
    }
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
  return classify(answer, 200);
}

/** No crest: the card goes back to the school's initials. */
export async function removeCrest({ fetchImpl = fetch }) {
  let answer;
  try {
    const response = await fetchImpl(crestUrl(), {
      method: "DELETE",
      headers: { Accept: "application/json", "X-CSRFToken": await csrfToken({ fetchImpl }) },
      credentials: "same-origin",
    });
    let parsed = null;
    try {
      parsed = await response.json();
    } catch {
      parsed = null;
    }
    answer = { status: response.status, body: parsed };
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
  return classify(answer, 200);
}
