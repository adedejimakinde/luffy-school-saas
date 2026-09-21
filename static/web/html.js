/**
 * Escaping, and the one rule every renderer in this directory obeys.
 *
 * These modules build strings and the page assigns them to `innerHTML`, so
 * **every interpolated value goes through `esc()`**. That is not belt-and-
 * braces: `school_name`, `student_name`, `class_group_name`, a subject name and
 * every remark on the card are typed by a school into the admin, and a remark
 * reading `<img src=x onerror=...>` would otherwise execute in the browser of
 * the parent reading it. Django escapes by default in a template; a string
 * built by hand has no default, so the escape has to be a named rule with a
 * test on it rather than a habit.
 *
 * Building DOM nodes and assigning `textContent` would escape by construction
 * and was the alternative. It was not taken because it makes every renderer
 * need a DOM to run, and there is no DOM in `node --test` without adding a
 * dependency and a build step to a page whose whole premise is having neither.
 * Strings keep the renderers pure functions of their data, which is what the
 * tests in `results/tests/js/` assert.
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
 * A number that may legitimately be nought, rendered without lying about it.
 *
 * `0` and `null` are different answers and truthiness cannot tell them apart:
 * attendance is nullable until Phase 2 *and* legitimately nought, so a child
 * present on none of the days the school opened must read "0", while a school
 * that kept no register must read blank. A `value || fallback` here would print
 * the fallback for both, which is a parent being told nobody kept a register
 * when in fact their child was never there. The PDF template makes the same
 * distinction with `default_if_none`.
 */
export function numberOrBlank(value, blank = "&mdash;") {
  return value === null || value === undefined ? blank : esc(value);
}

/**
 * Seconds to wait, in the unit a person reading it would use.
 *
 * Shared because the threshold is a rule rather than a sentence: both sign-in
 * doors answer 429 with the same `retry_after` — `guardian_signin` raises
 * `TooManyAttempts` carrying `signin.THROTTLED`, the password door's own
 * constant — so two pages print the same number and must round it the same way.
 * A copy per page is two places to change the threshold and one of them gets
 * missed.
 *
 * Whole minutes once seconds would read as precision nobody needs, and `""` for
 * an answer that carried no `retry_after` at all: the caller then says "too many
 * attempts" without inventing a wait it was not told.
 */
export function waitInWords(seconds) {
  if (seconds === null || seconds === undefined) return "";
  if (seconds >= 120) return `about ${Math.ceil(seconds / 60)} minutes`;
  return `about ${seconds} seconds`;
}

/**
 * A page on a school's own host, as a link this page can actually draw.
 *
 * **Scheme-relative on purpose.** `//host/path` keeps whatever scheme the
 * deployment is served over, where a hard-coded `https://` is wrong in
 * development and a bare `/path` is wrong everywhere that matters here: every
 * caller is on a *different* host from the one it is linking to, so a path
 * would resolve against the page's own host and 404. That is the dead
 * `<a href="/">` the card page shipped, and the reason
 * `accounts/templates/403.html` names the portal by host too.
 *
 * **`""` for a school with no host, and every caller must branch on it.** A
 * deployment with no primary `Domain` for that school has nothing to link to,
 * and a school named without a link is honest where `//null/cards/` is a
 * broken link that looks like a working one. Returning the empty string rather
 * than throwing keeps the decision — what to say instead — with the page that
 * knows what it is offering, because the two callers say different things: the
 * guardian chooser explains the missing web address, and the staff landing has
 * its own reasons a school may not be linked.
 *
 * The host is escaped here rather than by each caller. It is a value a school
 * typed into the admin, it lands inside a quoted attribute, and an escape that
 * every caller has to remember is an escape one of them will not.
 */
export function hostHref(host, path) {
  if (!host) return "";
  return `//${esc(host)}${path}`;
}
