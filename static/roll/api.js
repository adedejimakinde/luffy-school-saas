/**
 * The fetches the roll screen makes, and what each answer means.
 */

import { getJson, postJson, putJson } from "../web/http.js";

/** The states the whole page can be in, other than holding the roll. */
export const REFUSAL = {
  /** Signed in, and with no part in admitting or placing here. */
  NOT_THE_OFFICE: "not-the-office",
  /** The portal, or a host that is not a school's. */
  WRONG_HOST: "wrong-host",
  EXPIRED: "expired",
  SIGNED_OUT: "signed-out",
  BROKEN: "broken",
};

/** What one write can come back as, beyond having worked. */
export const SAVE = {
  /** That handle belongs to somebody already. Retypable. */
  HANDLE_TAKEN: "handle-taken",
  /** The request disagrees with the school's state. Retypable. */
  REJECTED: "rejected",
  /** A standing they do not have. No retry helps. */
  NOT_ALLOWED: "not-allowed",
};

const SESSION_EXPIRED = "session_expired";

export function rollUrl() {
  return "/api/enrolment/roll/";
}

export function classUrl(studentMembershipId) {
  return `${rollUrl()}${encodeURIComponent(studentMembershipId)}/class/`;
}

export function guardiansUrl(studentMembershipId) {
  return `${rollUrl()}${encodeURIComponent(studentMembershipId)}/guardians/`;
}

export function removeUrl(studentMembershipId, linkId) {
  return `${guardiansUrl(studentMembershipId)}${encodeURIComponent(linkId)}/remove/`;
}

/**
 * Which page-level state an answer produces.
 *
 * **403 and 404 are different refusals.** A 403 is the authority check: signed
 * in at this school with no part in the roll — a teacher, a bursar. A 404 is
 * `_school_of()`: this host is not a school's, so there is no roll behind the
 * URL at all.
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

/** Whether this answer proves there is a session to end. */
export function provesASession(answer) {
  if (answer.ok) return true;
  return answer.refusal === REFUSAL.NOT_THE_OFFICE;
}

/** Every child enrolled here, and where they sit this term. */
export async function fetchRoll({ fetchImpl = fetch } = {}) {
  let answer;
  try {
    answer = await getJson(rollUrl(), { fetchImpl });
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
 * **409 is kept apart from 422** because they are different sentences to a
 * person: a handle somebody else holds is a name to change, and a request that
 * disagrees with the school's state is something else entirely. Collapsing
 * them into "that did not work" would leave an administrator guessing which.
 */
function classify(answer, created) {
  if (answer.status === created || answer.status === 200) {
    return { ok: true, row: answer.body || {} };
  }
  if (answer.status === 409) return { ok: false, outcome: SAVE.HANDLE_TAKEN, body: answer.body || {} };
  if (answer.status === 422) return { ok: false, outcome: SAVE.REJECTED, body: answer.body || {} };
  if (answer.status === 403) return { ok: false, outcome: SAVE.NOT_ALLOWED, body: answer.body || {} };
  return {
    ok: false,
    refusal: refusalFor(answer.status, answer.body),
    body: answer.body || {},
  };
}

/** Create a child's login and enrol them. Optionally place them too. */
export async function admit({ child, fetchImpl = fetch }) {
  try {
    return classify(await postJson(rollUrl(), child, { fetchImpl }), 201);
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
}

/** Put a child in a class, or move them to another. The server decides which. */
export async function setClass({ studentMembershipId, classGroupId, fetchImpl = fetch }) {
  try {
    return classify(
      await putJson(classUrl(studentMembershipId), { class_group_id: classGroupId }, { fetchImpl }),
      200,
    );
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
}

/**
 * One child's guardians. **A 404 here is the child, not the host**: the roll
 * itself loaded on this host, so a missing child is a panel note rather than
 * the whole page turning into "wrong address".
 */
export async function fetchGuardians({ studentMembershipId, fetchImpl = fetch }) {
  try {
    return panelAnswer(await getJson(guardiansUrl(studentMembershipId), { fetchImpl }), 200);
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
}

/** Link a guardian by name and contact. Answers with the whole panel. */
export async function linkGuardian({ studentMembershipId, guardian, fetchImpl = fetch }) {
  try {
    return panelAnswer(
      await postJson(guardiansUrl(studentMembershipId), guardian, { fetchImpl }),
      201,
    );
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
}

/**
 * Send a guardian this school's code (`enrolment_api.send_code`). Which code is
 * the server's decision, from the channel's state; the page only says which of
 * a live guardian's channels. Answers with the whole panel.
 */
export async function sendCode({ studentMembershipId, linkId, channelType, fetchImpl = fetch }) {
  try {
    return panelAnswer(
      await postJson(
        `${guardiansUrl(studentMembershipId)}${encodeURIComponent(linkId)}/send-code/`,
        channelType ? { channel_type: channelType } : {},
        { fetchImpl },
      ),
      200,
    );
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
}

/** Give a live guardian their other channel, an email or a phone (#111). */
export async function addContact({ studentMembershipId, linkId, contact, fetchImpl = fetch }) {
  try {
    return panelAnswer(
      await postJson(
        `${guardiansUrl(studentMembershipId)}${encodeURIComponent(linkId)}/contacts/`,
        { contact },
        { fetchImpl },
      ),
      201,
    );
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
}

/** Remove one guardian from one child. Answers with the whole panel. */
export async function removeGuardian({ studentMembershipId, linkId, fetchImpl = fetch }) {
  try {
    return panelAnswer(
      await postJson(removeUrl(studentMembershipId, linkId), {}, { fetchImpl }),
      200,
    );
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
}

function panelAnswer(answer, expected) {
  if (answer.status === expected && answer.body) return { ok: true, body: answer.body };
  // A 429 is "too many codes just now": a sentence on the panel with a time in
  // it, not a page that has stopped working.
  if (answer.status === 422 || answer.status === 429) {
    return { ok: false, outcome: SAVE.REJECTED, body: answer.body || {} };
  }
  if (answer.status === 403) return { ok: false, outcome: SAVE.NOT_ALLOWED, body: answer.body || {} };
  if (answer.status === 404) return { ok: false, outcome: SAVE.REJECTED, body: answer.body || {} };
  return {
    ok: false,
    refusal: refusalFor(answer.status, answer.body),
    body: answer.body || {},
  };
}
