/**
 * The fetches the website editor makes (`schoolsite/api.py`).
 *
 * Every write answers with the whole overview, so the page redraws from the school's own
 * answer. A 422 carries a sentence to print under the form it came from; a 409 is a save based
 * on something somebody else changed since, printed the same way with a way to reload.
 */

import { deleteJson, getJson, postJson, putJson } from "../web/http.js";

/** The states the whole page can be in, other than holding the overview. */
export const REFUSAL = {
  /** Signed in, and not the principal or the administrator here. */
  NOT_YOURS: "not-yours",
  /** The portal, or a host that is not a school's. */
  WRONG_HOST: "wrong-host",
  EXPIRED: "expired",
  SIGNED_OUT: "signed-out",
  BROKEN: "broken",
};

const SESSION_EXPIRED = "session_expired";
const BASE = "/api/website/";

export function refusalFor(status, body) {
  if (status === 403) return REFUSAL.NOT_YOURS;
  if (status === 404) return REFUSAL.WRONG_HOST;
  if (status === 401) return body && body.code === SESSION_EXPIRED ? REFUSAL.EXPIRED : REFUSAL.SIGNED_OUT;
  return REFUSAL.BROKEN;
}

/** What an answer is: the overview, a sentence to print (422, or 409 to reload), or a refusal. */
export function classify(answer) {
  if (answer.status === 200 && answer.body) return { ok: true, body: answer.body };
  if (answer.status === 422 || answer.status === 409) {
    return { ok: false, rejected: true, stale: answer.status === 409, body: answer.body || {} };
  }
  return { ok: false, refusal: refusalFor(answer.status, answer.body), body: answer.body || {} };
}

async function send(act) {
  try {
    return classify(await act());
  } catch (error) {
    return { ok: false, refusal: REFUSAL.BROKEN, body: { detail: String(error) } };
  }
}

const at = (path, ...parts) => BASE + path + parts.map((p) => `${encodeURIComponent(p)}/`).join("");

export const fetchOverview = ({ fetchImpl = fetch } = {}) => send(() => getJson(BASE, { fetchImpl }));

export const addPage = ({ version, title, slug, fetchImpl = fetch }) =>
  send(() => postJson(at("pages/"), { version, title, slug: slug || null }, { fetchImpl }));

/** `change` holds any of title, description, enabled, or slug (a custom page's address). */
export const changePage = ({ ref, version, change, fetchImpl = fetch }) =>
  send(() => putJson(at("pages/", ref), { version, ...change }, { fetchImpl }));

export const removePage = ({ ref, version, fetchImpl = fetch }) =>
  send(() => deleteJson(`${at("pages/", ref)}?version=${encodeURIComponent(version)}`, { fetchImpl }));

export const orderMenu = ({ version, order, fetchImpl = fetch }) =>
  send(() => putJson(at("menu/"), { version, order }, { fetchImpl }));

export const addSection = ({ ref, version, kind, data, fetchImpl = fetch }) =>
  send(() => postJson(`${at("pages/", ref)}sections/`, { version, kind, data }, { fetchImpl }));

export const orderSections = ({ ref, version, order, fetchImpl = fetch }) =>
  send(() => putJson(`${at("pages/", ref)}sections/`, { version, order }, { fetchImpl }));

export const changeSection = ({ id, version, data, fetchImpl = fetch }) =>
  send(() => putJson(at("sections/", id), { version, data }, { fetchImpl }));

export const removeSection = ({ id, version, fetchImpl = fetch }) =>
  send(() => deleteJson(`${at("sections/", id)}?version=${encodeURIComponent(version)}`, { fetchImpl }));

export const changeFooter = ({ version, footer, fetchImpl = fetch }) =>
  send(() => putJson(at("footer/"), { version, footer }, { fetchImpl }));

export const changeColour = ({ version, colour, fetchImpl = fetch }) =>
  send(() => putJson(at("colour/"), { version, colour }, { fetchImpl }));

export const changeDelegation = ({ on, fetchImpl = fetch }) =>
  send(() => putJson(at("delegation/"), { on }, { fetchImpl }));

export const markReady = ({ note = "", fetchImpl = fetch }) => send(() => postJson(at("ready/"), { note }, { fetchImpl }));

export const publish = ({ draftVersion, note = "", fetchImpl = fetch }) =>
  send(() => postJson(at("publish/"), { draft_version: draftVersion, note }, { fetchImpl }));

export const rollback = ({ number, note = "", fetchImpl = fetch }) =>
  send(() => postJson(at("rollback/"), { number, note }, { fetchImpl }));
