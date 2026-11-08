/**
 * Escaping, and the one rule every renderer here obeys: these modules build
 * strings for `innerHTML`, so **every interpolated value goes through
 * `esc()`**. Names and remarks are typed by a school, and a remark reading
 * `<img src=x onerror=...>` would otherwise run in a parent's browser. Strings
 * rather than DOM nodes keep the renderers pure functions that `node --test`
 * can check with no DOM, no dependency and no build step.
 */

const ESCAPES = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

/** One value, safe to drop into markup or a quoted attribute. */
export function esc(value) {
  if (value === null || value === undefined) return "";
  return String(value).replace(/[&<>"']/g, (c) => ESCAPES[c]);
}

/**
 * A number that may legitimately be nought, rendered without lying about it: `0` and
 * `null` are different answers (present on no day, versus no register kept), and
 * `value || fallback` would print the fallback for both.
 */
export function numberOrBlank(value, blank = "-") {
  return value === null || value === undefined ? blank : esc(value);
}

/**
 * Seconds to wait, in the unit a person would use. Shared because both sign-in doors
 * answer 429 with the same `retry_after` and must round it the same way: whole minutes
 * once seconds read as false precision, and `""` when none was sent.
 */
export function waitInWords(seconds) {
  if (seconds === null || seconds === undefined) return "";
  if (seconds >= 120) return `about ${Math.ceil(seconds / 60)} minutes`;
  return `about ${seconds} seconds`;
}

/**
 * A page on a school's own host, as a link this page can draw.
 *
 * Scheme-relative (`//host/path`): every caller links to a host other than
 * its own, so a bare path would 404, and a fixed `https://` is wrong in
 * development. `""` for a school with no host, and each caller says what to
 * show instead. `pathOnly` (the API's `path_only`, the single-host demo) is
 * the path alone. The host is a school's typing, so it is escaped here.
 */
export function hostHref(host, path, { pathOnly = false } = {}) {
  // The single-host demo: the school is the host this page is on (`path_only`).
  if (pathOnly) return path;
  if (!host) return "";
  return `//${esc(host)}${path}`;
}

/**
 * An empty list's state: what is missing and one button (`{ href, label }`, or
 * `{ data, label }` for a `data-action`), else who does it. Drawn only from a
 * successful answer with no rows: a failed fetch has its own states.
 */
export function emptyState({ key = "", icon = "", title = "", text = "", action = null, who = "" } = {}) {
  const button = !action
    ? ""
    : action.href
      ? `<a class="btn btn-primary" href="${esc(action.href)}">${esc(action.label)}</a>`
      : `<button type="button" class="btn-primary" data-action="${esc(action.data)}">${esc(action.label)}</button>`;
  return (
    `<section class="empty-card" data-empty="${esc(key)}">` +
    (icon ? `<span class="empty-icon" aria-hidden="true"><svg class="icon"><use href="#${esc(icon)}"/></svg></span>` : "") +
    `<h2>${esc(title)}</h2><p>${esc(text)}</p>${button}` +
    (!button && who ? `<p class="quiet">${esc(who)}</p>` : "") +
    "</section>"
  );
}
