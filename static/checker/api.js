/**
 * The result checker's one request, and what each answer means.
 *
 * `POST /api/results/check/` with the admission number and the PIN from the
 * slip (docs/messaging.md D11). Five answers, and the page says something
 * different for each:
 *
 * | status | what it is |
 * | --- | --- |
 * | 200 | the card, `card_api.card_payload()` exactly as a signed-in family gets it |
 * | 403 | the right PIN, and the school is holding the card: `WithheldOut` |
 * | 404 | the one refusal, whichever half was wrong |
 * | 429 | too many wrong tries: a wait, with `retry_after` in seconds |
 * | anything else | something broke, on our side or on the way |
 *
 * **The 404 is one answer on purpose.** An unknown admission number, a wrong
 * PIN, a replaced PIN and another child's PIN all come back the same, so the
 * page cannot tell them apart and must not try: guessing "check the admission
 * number" would be telling somebody which half they got right.
 */

/** What an answer is. */
export const ANSWER = {
  CARD: "card",
  WITHHELD: "withheld",
  NOT_OPENED: "not-opened",
  WAIT: "wait",
  BROKEN: "broken",
};

export function checkUrl() {
  return "/api/results/check/";
}

/** Which answer a status is. Exported so a test can name each one. */
export function answerFor(status, body) {
  if (status === 200 && body) return ANSWER.CARD;
  if (status === 403) return ANSWER.WITHHELD;
  if (status === 404) return ANSWER.NOT_OPENED;
  if (status === 429) return ANSWER.WAIT;
  return ANSWER.BROKEN;
}

/**
 * Ask. Resolves to `{kind, body}`, and never throws: a wrong PIN and a wait
 * are answers the page has a sentence for, and a dead transport is `BROKEN`.
 *
 * **The PIN goes in the body and nowhere else.** Not in the URL, where it would
 * sit in the browser's history and in every access log between here and the
 * server.
 *
 * **`credentials: "omit"`**, the opposite of what `card/api.js` warns against,
 * and for the opposite reason: the card route's whole authentication is the
 * cookie, and this route's is the PIN. It asks no question of a session, so
 * none is sent: a check
 * made from a browser somebody happens to be signed in on has to answer exactly
 * as it would from any other, and a cookie the route never reads is one more
 * thing a reader would have to rule out. It is also why no CSRF token is
 * fetched: with no cookie there is no ambient authority for another site to
 * borrow.
 */
export async function check({ admissionNumber = "", pin = "", fetchImpl = fetch }) {
  let response;
  try {
    response = await fetchImpl(checkUrl(), {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      credentials: "omit",
      body: JSON.stringify({ admission_number: admissionNumber, pin }),
    });
  } catch {
    return { kind: ANSWER.BROKEN, body: {} };
  }
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  return { kind: answerFor(response.status, body), body: body || {} };
}
