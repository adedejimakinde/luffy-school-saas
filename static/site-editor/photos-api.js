/**
 * The fetches the photos and albums screen makes (`schoolsite/api.py`, PR 5): uploads, a picture's
 * description and focal point, deleting and taking down, and albums. Every write answers with the
 * school's overview (and the album, where one is open), as `api.js`'s do, and is classified the same way.
 */

import { csrfToken, deleteJson, getJson, postJson, putJson } from "../web/http.js";
import { classify, REFUSAL } from "./api.js";

const BASE = "/api/website/";
const at = (path, ...parts) => BASE + path + parts.map((p) => `${encodeURIComponent(p)}/`).join("");

async function send(act) {
  try {
    return classify(await act());
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
}

export const fetchOverview = ({ fetchImpl = fetch } = {}) => send(() => getJson(BASE, { fetchImpl }));


/**
 * Pictures as the files themselves: multipart, so the browser writes the body and its boundary;
 * the CSRF token goes in the header as it does for JSON, and is fetched again once if stale.
 * `fields` are `use`, `alt`, `consent`, and `album` or `video`; `files` are one to five File objects.
 */
export async function uploadPictures({ fields, files, fetchImpl = fetch }) {
  const sendOnce = async (refresh) => {
    const body = new FormData();
    for (const [name, value] of Object.entries(fields)) {
      if (value !== undefined && value !== null) body.append(name, String(value));
    }
    for (const file of files) body.append("photo", file);
    const response = await fetchImpl(at("pictures/"), {
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
  return send(async () => {
    const answer = await sendOnce(false);
    if (answer.status === 403 && answer.body && answer.body.code === "csrf_failed") return sendOnce(true);
    return answer;
  });
}

/** `change` holds any of alt, caption, focal ({x, y}, each 0 to 1). */
export const changePicture = ({ id, version, change, fetchImpl = fetch }) =>
  send(() => putJson(at("pictures/", id), { version, ...change }, { fetchImpl }));

export const removePicture = ({ id, version, fetchImpl = fetch }) =>
  send(() => deleteJson(`${at("pictures/", id)}?version=${encodeURIComponent(version)}`, { fetchImpl }));

export const takeDown = ({ id, reason, fetchImpl = fetch }) =>
  send(() => postJson(`${at("pictures/", id)}take-down/`, { reason }, { fetchImpl }));

export const addAlbum = ({ title, slug, fetchImpl = fetch }) =>
  send(() => postJson(at("albums/"), { title, slug: slug || null }, { fetchImpl }));

export const fetchAlbum = ({ id, fetchImpl = fetch }) => send(() => getJson(at("albums/", id), { fetchImpl }));

/** `change` holds any of title, description, slug. */
export const changeAlbum = ({ id, version, change, fetchImpl = fetch }) =>
  send(() => putJson(at("albums/", id), { version, ...change }, { fetchImpl }));

export const orderPhotos = ({ id, version, order, fetchImpl = fetch }) =>
  send(() => putJson(`${at("albums/", id)}photos/`, { version, order }, { fetchImpl }));

export const removePhoto = ({ id, photo, version, fetchImpl = fetch }) =>
  send(() => deleteJson(`${at("albums/", id)}photos/${encodeURIComponent(photo)}/?version=${encodeURIComponent(version)}`, { fetchImpl }));

export const removeAlbum = ({ id, version, fetchImpl = fetch }) =>
  send(() => deleteJson(`${at("albums/", id)}?version=${encodeURIComponent(version)}`, { fetchImpl }));

export const publishAlbum = ({ id, version, note = "", fetchImpl = fetch }) =>
  send(() => postJson(`${at("albums/", id)}publish/`, { version, note }, { fetchImpl }));

export const unpublishAlbum = ({ id, version, note = "", fetchImpl = fetch }) =>
  send(() => postJson(`${at("albums/", id)}unpublish/`, { version, note }, { fetchImpl }));
