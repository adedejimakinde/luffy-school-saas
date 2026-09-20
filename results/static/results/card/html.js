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
