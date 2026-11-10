/** Talking to the API: GET, POST, PUT, DELETE and the CSRF token (docs/module-notes.md, "web/http.js"). */

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

/** One JSON GET: `{status, body}`; throws only if the transport does. */
export async function getJson(url, { fetchImpl = fetch } = {}) {
  const response = await fetchImpl(url, {
    headers: { Accept: "application/json" },
    credentials: "same-origin",
  });
  return { status: response.status, body: await readBody(response) };
}

/** One JSON POST, with the token, retried once on a stale-token 403. */
export async function postJson(url, payload, options = {}) {
  return sendJson("POST", url, payload, options);
}

/** The same, spelled PUT (the register write: one register per group per day). */
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
