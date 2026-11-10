/** Escaping: every interpolated value goes through `esc()` (docs/module-notes.md, "web/html.js"). */

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

const MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(" ");

/** A stored day (`2026-11-08`) as "8 Nov 2026", day first; anything else as it was. */
export function dayFirst(iso) {
  const [y, m, d] = String(iso ?? "").slice(0, 10).split("-").map(Number);
  return y && d && MONTHS[m - 1] ? `${d} ${MONTHS[m - 1]} ${y}` : String(iso ?? "");
}

/** A number that may be nought: `0` and `null` are different answers. */
export function numberOrBlank(value, blank = "-") {
  return value === null || value === undefined ? blank : esc(value);
}

/** Seconds to wait in a person's unit; `""` when none was sent. */
export function waitInWords(seconds) {
  if (seconds === null || seconds === undefined) return "";
  if (seconds >= 120) return `about ${Math.ceil(seconds / 60)} minutes`;
  return `about ${seconds} seconds`;
}

/** A page on a school's own host as a scheme-relative link; `pathOnly` is the path alone; `""` with no host. */
export function hostHref(host, path, { pathOnly = false } = {}) {
  // The single-host demo: the school is the host this page is on (`path_only`).
  if (pathOnly) return path;
  if (!host) return "";
  return `//${esc(host)}${path}`;
}

/** An empty list's state: what is missing and one button (`{ href, label }` or `{ data, label }`). */
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
