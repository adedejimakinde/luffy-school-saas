/**
 * The editor's pure parts: no DOM, so `tests/js/blog_editor.test.js` runs them
 * with `node --test` and nothing installed.
 *
 * Each formatting command takes the text, the selection and returns the new
 * text with the new selection, so the page only has to put them back.
 */

/** "12 / 60", and whether it is over. */
export function counter(length, max) {
  return { text: `${length} / ${max}`, over: length > max };
}

/** The whole lines the selection touches. */
function lineSpan(text, start, end) {
  const from = text.lastIndexOf("\n", start - 1) + 1;
  const newline = text.indexOf("\n", end > start ? end - 1 : end);
  const to = newline === -1 ? text.length : newline;
  return [from, to];
}

/** Put `prefix` at the start of every line the selection touches. */
function prefixLines(text, start, end, prefix) {
  const [from, to] = lineSpan(text, start, end);
  const lines = text.slice(from, to).split("\n").map((line) => prefix + line.replace(/^(#{1,6} |- |> )/, ""));
  const block = lines.join("\n");
  return {
    text: text.slice(0, from) + block + text.slice(to),
    start: from,
    end: from + block.length,
  };
}

/** Wrap the selection, or a placeholder word selected for typing over. */
function wrap(text, start, end, before, after, placeholder) {
  const chosen = text.slice(start, end) || placeholder;
  const out = text.slice(0, start) + before + chosen + after + text.slice(end);
  return { text: out, start: start + before.length, end: start + before.length + chosen.length };
}

/**
 * Apply one toolbar command. `h2`, `bold`, `link`, `list` or `quote`.
 * Returns `{text, start, end}`.
 */
export function format(command, text, start, end) {
  switch (command) {
    case "h2":
      return prefixLines(text, start, end, "## ");
    case "list":
      return prefixLines(text, start, end, "- ");
    case "quote":
      return prefixLines(text, start, end, "> ");
    case "bold":
      return wrap(text, start, end, "**", "**", "bold words");
    case "link": {
      const label = text.slice(start, end) || "words";
      const out = `${text.slice(0, start)}[${label}](https://)${text.slice(end)}`;
      const urlAt = start + label.length + 3;
      return { text: out, start: urlAt, end: urlAt + "https://".length };
    }
    default:
      return { text, start, end };
  }
}

/** A picture as the post writes it, on lines of its own. Brackets in the description are dropped. */
export function pictureMarkdown(alt, key) {
  const clean = String(alt).replace(/[[\]\n]/g, " ").replace(/\s+/g, " ").trim();
  return `![${clean}](image:${key})`;
}

/** Insert `block` at `at`, on a line of its own. Returns `{text, start, end}` with the cursor after it. */
export function insertBlock(text, at, block) {
  const before = text.slice(0, at);
  const after = text.slice(at);
  const lead = before === "" || before.endsWith("\n\n") ? "" : before.endsWith("\n") ? "\n" : "\n\n";
  const tail = after.startsWith("\n\n") ? "" : after.startsWith("\n") ? "\n" : "\n\n";
  const out = before + lead + block + tail + after;
  const cursor = before.length + lead.length + block.length + tail.length;
  return { text: out, start: cursor, end: cursor };
}

/** How far the on-screen keyboard covers the page, from the visual viewport. 0 where the page already shrinks. */
export function keyboardHeight(innerHeight, viewportHeight, offsetTop) {
  return Math.max(0, Math.round(innerHeight - viewportHeight - offsetTop));
}

/** What a search result shows: the SEO field, or the field it falls back to. */
export function serpText(seo, fallback, placeholder) {
  return (seo || "").trim() || (fallback || "").trim() || placeholder;
}
