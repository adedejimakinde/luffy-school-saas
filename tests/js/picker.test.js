/**
 * The picker's pure parts: what it lists, what a search keeps, where a typed
 * letter jumps, and how a long list of classes is grouped. What it does in a
 * browser (the sheet, the keys, focus, what the form sends) is
 * `tests/ui/picker.test.js`'s.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { GROUP_ABOVE, classOptions } from "../../static/web/classes.js";
import { SEARCH_ABOVE, SHORT_UP_TO, filterRows, fold, nextMatch, rowsOf } from "../../static/web/picker.js";

/** Just enough of a `<select>` for `rowsOf()`: options, some in an optgroup. */
function fakeSelect(spec) {
  const options = [];
  for (const item of spec) {
    const group = item.group ? { tagName: "OPTGROUP", label: item.group, disabled: Boolean(item.groupDisabled) } : { tagName: "SELECT" };
    options.push({ label: item.label, textContent: item.label, hidden: Boolean(item.hidden), disabled: Boolean(item.disabled), parentElement: group });
  }
  return { options };
}

const rows = (labels) => rowsOf(fakeSelect(labels.map((label) => ({ label }))));

test("a long list is more than eight, and a list long enough to search is grouped", () => {
  assert.equal(SEARCH_ABOVE, 8);
  assert.equal(GROUP_ABOVE, SEARCH_ABOVE);
  assert.equal(SHORT_UP_TO, 6, "six or fewer open as a menu under the field on a phone");
});

test("rows keep each option's index, its group and whether it can be chosen, and leave hidden ones out", () => {
  const listed = rowsOf(
    fakeSelect([
      { label: "Choose a class" },
      { label: "JSS 1A", group: "JSS 1" },
      { label: "  JSS   1B ", group: "JSS 1", disabled: true },
      { label: "Old class", hidden: true },
      { label: "SS 1A", group: "SS 1", groupDisabled: true },
    ]),
  );

  assert.deepEqual(
    listed.map(({ index, label, group, disabled }) => [index, label, group, disabled]),
    [
      [0, "Choose a class", "", false],
      [1, "JSS 1A", "JSS 1", false],
      [2, "JSS 1B", "JSS 1", true],
      [4, "SS 1A", "SS 1", true],
    ],
  );
});

test("an option's data-description is the line under it", () => {
  const select = fakeSelect([{ label: "Teacher" }, { label: "Bursar" }]);
  select.options[0].getAttribute = (name) => (name === "data-description" ? "  Takes registers " : null);

  assert.deepEqual(rowsOf(select).map((r) => [r.label, r.hint]), [["Teacher", "Takes registers"], ["Bursar", ""]]);
});

test("a search ignores case, accents, spaces and punctuation, and wants every word", () => {
  const listed = rows(["Ìfé Bello", "Ife Adeyemi", "Kemi Bello", "JSS 1A", "JSS 10A", "SS 1A", "Vice principal (academic)"]);

  assert.deepEqual(filterRows(listed, "  IFE ").map((r) => r.label), ["Ìfé Bello", "Ife Adeyemi"]);
  assert.deepEqual(filterRows(listed, "bello ife").map((r) => r.label), ["Ìfé Bello"]);
  assert.deepEqual(filterRows(listed, "jss 1").map((r) => r.label), ["JSS 1A", "JSS 10A"]);
  assert.deepEqual(filterRows(listed, "academic").map((r) => r.label), ["Vice principal (academic)"]);
  assert.deepEqual(filterRows(listed, "nobody"), []);
  assert.equal(filterRows(listed, "").length, 7);
  assert.equal(fold("  Ìfé   Bello "), "ife bello");
  assert.equal(fold("St Mary's (JSS 1)"), "st mary s jss 1");
});

test("a word is found from its start, so a level is not found inside another", () => {
  const listed = rows(["JSS 2A", "SS 2A", "SS 2B", "Adeyemi"]);

  assert.deepEqual(filterRows(listed, "ss 2").map((r) => r.label), ["SS 2A", "SS 2B"]);
  assert.deepEqual(filterRows(listed, "2a").map((r) => r.label), ["JSS 2A", "SS 2A"]);
  assert.deepEqual(filterRows(listed, "yemi"), []);
});

test("a search finds a row by its group's name too", () => {
  const listed = rowsOf(fakeSelect([{ label: "A", group: "JSS 2" }, { label: "B", group: "JSS 3" }]));

  assert.deepEqual(filterRows(listed, "jss 2").map((r) => r.label), ["A"]);
});

test("typing jumps to the next row starting with it, and a letter again moves on", () => {
  const listed = rows(["Bursar", "Principal", "Teacher", "Tutor", "Vice principal (academic)"]);

  assert.equal(nextMatch(listed, "t", -1), 2);
  assert.equal(nextMatch(listed, "t", 2), 3);
  assert.equal(nextMatch(listed, "tt", 3), 2, "round again");
  assert.equal(nextMatch(listed, "tu", 2), 3, "a word goes to the row it spells");
  assert.equal(nextMatch(listed, "te", 2), 2, "and stays on one it already spells");
  assert.equal(nextMatch(listed, "vice", 0), 4);
  assert.equal(nextMatch(listed, "x", 0), -1);
});

test("typing never lands on a row that cannot be chosen", () => {
  const listed = rowsOf(fakeSelect([{ label: "Teacher", disabled: true }, { label: "Tutor" }]));

  assert.equal(nextMatch(listed, "t", -1), 1);
});

const CLASS = (id, name, level) => ({ class_group_id: id, name, level });
const MANY = [
  CLASS(1, "JSS 1A", 1), CLASS(2, "JSS 1B", 1), CLASS(3, "JSS 2A", 2), CLASS(4, "JSS 2B", 2),
  CLASS(5, "JSS 3A", 3), CLASS(6, "JSS 3B", 3), CLASS(7, "SS 1A", 4), CLASS(8, "SS 1B", 4), CLASS(9, "SS 2", 5),
];

test("a long list of classes is grouped by level, each named by what its arms share", () => {
  const html = classOptions(MANY, 4);

  assert.match(html, /^<optgroup label="JSS 1"><option value="1">JSS 1A<\/option><option value="2">JSS 1B<\/option><\/optgroup>/);
  assert.match(html, /<optgroup label="JSS 2"><option value="3">JSS 2A<\/option><option value="4" selected>JSS 2B<\/option><\/optgroup>/);
  assert.match(html, /<optgroup label="SS 2"><option value="9">SS 2<\/option><\/optgroup>$/);
  assert.equal(html.match(/<optgroup/g).length, 5);
});

test("a short list, one level, or a level whose arms share no name stays flat", () => {
  assert.doesNotMatch(classOptions(MANY.slice(0, 8)), /optgroup/);
  assert.doesNotMatch(classOptions(MANY.map((c) => ({ ...c, level: 1 }))), /optgroup/);
  assert.doesNotMatch(classOptions([...MANY, CLASS(10, "Science", 5)]), /optgroup/);
});

test("a class's name is escaped like everything else drawn", () => {
  const html = classOptions([CLASS(1, '<img src=x onerror="1">', 1)]);

  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img src=x onerror=&quot;1&quot;&gt;/);
});
