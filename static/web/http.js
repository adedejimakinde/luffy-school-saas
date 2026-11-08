/**
 * Talking to the API: one GET, one POST, and the CSRF token the POST needs.
 *
 * The token comes from `GET /api/csrf/`, not from `document.cookie`: reading the cookie
 * depends on `CSRF_COOKIE_HTTPONLY` staying false and puts the cookie's name in the
 * browser. It is fetched once and reused; a 403 with `code: "csrf_failed"` means it is
 * stale, so the write fetches a fresh one and retries **once**, not until it works.
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
 * One JSON POST, with the token, retried once on a stale-token 403. `same-origin`
 * credentials send the session cookie and keep every POST on its own host, so
 * `CSRF_TRUSTED_ORIGINS` is never widened.
 */
export async function postJson(url, payload, options = {}) {
  return sendJson("POST", url, payload, options);
}

/**
 * The same request and CSRF story, spelled PUT: the register write, which is a PUT
 * because there is one register per group per day (`attendance/api.py`). It shares
 * `sendJson()` so the retry-once rule has one copy.
 */
export async function putJson(url, payload, options = {}) {
  return sendJson("PUT", url, payload, options);
}

/** The same again, spelled DELETE, with no body: the URL names what is removed. */
export async function deleteJson(url, options = {}) {
  return sendJson("DELETE", url, undefined, options);
}

async function sendJson(method, url, payload, { fetchImpl = fetch } = {}) {
  const send = async (csrf) =>
    fetchImpl(url, {
      method,
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
