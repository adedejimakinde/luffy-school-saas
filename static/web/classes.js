/**
 * A list of classes as a select's options, shared by the pages that offer one
 * (the roll's, today). Apart from `web/html.js` because it is weight only
 * those pages should carry (`tests/test_budget.py`).
 */

import { esc } from "./html.js";

/** `web/picker.js`'s `SEARCH_ABOVE`: a list it searches is a list grouped. Not
 * imported, so a page still draws if the picker fails to load. */
export const GROUP_ABOVE = 8;

/**
 * `<option>`s for classes (`{ class_group_id, name, level }`, in level order).
 * A list long enough to search is grouped by level, each `<optgroup>` named by
 * what its arms share ("JSS 1" for JSS 1A and JSS 1B); flat if any level's do not.
 */
export function classOptions(classes, selected = "") {
  const option = (c) =>
    `<option value="${esc(c.class_group_id)}"${String(c.class_group_id) === String(selected) ? " selected" : ""}>${esc(c.name)}</option>`;
  const levels = new Map();
  for (const c of classes) levels.set(c.level, [...(levels.get(c.level) || []), c]);
  const stems = [...levels.values()].map((arms) => {
    const shared = new Set(arms.map((c) => (/^(.*\d)\s*[A-Za-z]?$/.exec(String(c.name).trim()) || [])[1]));
    return shared.size === 1 && !shared.has(undefined) ? [...shared][0] : null;
  });
  if (classes.length <= GROUP_ABOVE || levels.size < 2 || stems.includes(null)) return classes.map(option).join("");
  return [...levels.values()].map((arms, i) => `<optgroup label="${esc(stems[i])}">${arms.map(option).join("")}</optgroup>`).join("");
}
