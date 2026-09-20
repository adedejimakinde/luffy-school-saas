/**
 * Talking to the API: one GET, one POST, and the CSRF token the POST needs.
 *
 * Shared by every page, because the rules here are the API's rather than any
 * one screen's. The card page only reads; the sign-in page writes, and writing
 * is where the two rules below come from.
 *
 * ## The token comes from the API, not from a cookie read by hand
 *
 * `GET /api/csrf/` exists for exactly this: the sign-in routes check CSRF by
 * hand — they are the routes a caller uses *before* it has a session — and they
 * want the token in `X-CSRFToken`. Reading `document.cookie` for `csrftoken`
 * would work today and is the wrong shape: it depends on `CSRF_COOKIE_HTTPONLY`
 * staying false, which is a setting somebody can harden on a Friday, and it
 * puts knowledge of the cookie's name in the browser.
 *
 * The token is fetched once and reused. A 403 with `code: "csrf_failed"` means
 * the one we hold is stale — a rotated session, a long-open tab — so `postJson`
 * fetches a fresh one and retries **once**. Once, not until it works: a loop
 * against a route that refuses everything is a page that hammers the server
 * while telling the reader nothing.
 */

/** Remembered for the life of the page; `null` until first asked for. */
let token = null;

export async function csrfToken({ fetchImpl = fetch, refresh = false } = {}) {
  if (token !== null && !refresh) return token;
  const response = await fetchImpl("/api/csrf/", {
    headers: { Accept: "application/json" },
    credentials: "same-origin",
  });
  const body = await response.json();
  token = body.csrf_token;
  return token;
}

/** Exported for tests, which must not inherit a token from each other. */
export function forgetToken() {
  token = null;
}

/**
 * One JSON GET. Resolves to `{status, body}` and throws only if the transport
 * does — an HTTP refusal is an answer the caller has something to say about.
 */
export async function getJson(url, { fetchImpl = fetch } = {}) {
  const response = await fetchImpl(url, {
    headers: { Accept: "application/json" },
    credentials: "same-origin",
  });
  return { status: response.status, body: await readBody(response) };
}

/**
 * One JSON POST, with the token, retried once on a stale-token 403.
 *
 * `credentials: "same-origin"` is stated rather than left to the default
 * because it is load-bearing twice over: it sends the session cookie that
 * authenticates the caller, and it is what keeps this from ever being a
 * cross-site request. Every POST this platform makes is aimed at its own host —
 * the sign-in page posts to the portal's own routes, and a page on a school's
 * host posts to that school's — so nothing here needs `CSRF_TRUSTED_ORIGINS`
 * widened. A future POST that crossed hosts would need that, and would deserve
 * an argument rather than a setting.
 */
export async function postJson(url, payload, { fetchImpl = fetch } = {}) {
  const send = async (csrf) =>
    fetchImpl(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-CSRFToken": csrf,
      },
      credentials: "same-origin",
      body: JSON.stringify(payload),
    });

  let response = await send(await csrfToken({ fetchImpl }));
  let body = await readBody(response);

  if (response.status === 403 && body && body.code === "csrf_failed") {
    response = await send(await csrfToken({ fetchImpl, refresh: true }));
    body = await readBody(response);
  }

  return { status: response.status, body: body || {} };
}

async function readBody(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}
