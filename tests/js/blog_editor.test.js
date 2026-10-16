/**
 * The blog editor's pure parts (`static/write/tools.js`): the formatting
 * buttons, the picture's Markdown, the counters, the search preview's text and
 * how far a keyboard covers the page. No DOM and nothing installed.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { counter, format, insertBlock, keyboardHeight, pictureMarkdown, serpText } from "../../static/write/tools.js";

test("bold wraps the selection, or a placeholder selected for typing over", () => {
  assert.deepEqual(format("bold", "say this now", 4, 8), { text: "say **this** now", start: 6, end: 10 });
  const empty = format("bold", "ab", 1, 1);
  assert.equal(empty.text, "a**bold words**b");
  assert.equal(empty.text.slice(empty.start, empty.end), "bold words");
});

test("a heading, a list and a quote start every line the selection touches", () => {
  assert.equal(format("h2", "one\ntwo", 1, 1).text, "## one\ntwo");
  assert.equal(format("list", "one\ntwo\nthree", 1, 6).text, "- one\n- two\nthree");
  assert.equal(format("quote", "one", 0, 0).text, "> one");
  // Switching a line from one to another does not stack the two.
  assert.equal(format("h2", "- one", 0, 0).text, "## one");
});

test("a link keeps the words and selects the address to type", () => {
  const out = format("link", "see the fees", 8, 12);
  assert.equal(out.text, "see the [fees](https://)");
  assert.equal(out.text.slice(out.start, out.end), "https://");
});

test("a picture is written with its description, on lines of its own", () => {
  const key = "a".repeat(32);
  assert.equal(pictureMarkdown("The fee [screen]\nnow", key), `![The fee screen now](image:${key})`);
  const out = insertBlock("Before.\nAfter.", 7, "![x](image:k)");
  assert.equal(out.text, "Before.\n\n![x](image:k)\n\nAfter.");
  assert.equal(insertBlock("", 0, "B").text, "B\n\n");
});

test("a counter says the length and whether it is over", () => {
  assert.deepEqual(counter(43, 60), { text: "43 / 60", over: false });
  assert.deepEqual(counter(61, 60), { text: "61 / 60", over: true });
});

test("the search preview falls back to the title and the summary", () => {
  assert.equal(serpText("", "The title", "SEO title"), "The title");
  assert.equal(serpText("  ", "", "SEO title"), "SEO title");
  assert.equal(serpText("Own", "The title", "SEO title"), "Own");
});

test("the keyboard's height: none where the page shrinks for it, the gap where it does not", () => {
  // Chrome on Android with `interactive-widget=resizes-content`: the page shrinks too.
  assert.equal(keyboardHeight(420, 420, 0), 0);
  // Safari: the page keeps its height and the visual viewport shrinks.
  assert.equal(keyboardHeight(800, 460, 0), 340);
  assert.equal(keyboardHeight(800, 460, 40), 300);
  assert.equal(keyboardHeight(800, 900, 0), 0);
});
