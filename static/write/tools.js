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

/* -- pasted HTML, turned into Markdown ------------------------------------ */

const HTML_TAG = /<\/?(p|div|h[1-6]|ul|ol|li|strong|b|em|i|a|blockquote|hr|br|pre|code|script|style|span|table)\b[^>]*>/i;
const VOID = new Set(["br", "hr", "img", "meta", "link", "input", "wbr"]);
const SKIP = new Set(["script", "style", "head", "noscript", "iframe", "svg", "template", "object", "form", "img"]);
const BLOCK = new Set(["p", "div", "section", "article", "main", "header", "footer", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "blockquote", "hr", "pre", "table", "tr"]);
const ENTITIES = { amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " ", ndash: "–", mdash: "—", hellip: "…", lsquo: "‘", rsquo: "’", ldquo: "“", rdquo: "”" };

/** Does this text hold HTML tags worth converting? */
export function looksLikeHtml(text) {
  return HTML_TAG.test(text || "");
}

function parse(html) {
  const root = { tag: "#root", kids: [] };
  const stack = [root];
  const top = () => stack[stack.length - 1];
  const re = /<!--[\s\S]*?-->|<(\/?)([a-zA-Z][a-zA-Z0-9]*)((?:"[^"]*"|'[^']*'|[^>"'])*)>|<[^>]*>|[^<]+|</g;
  let m;
  while ((m = re.exec(html))) {
    if (m[2] === undefined) {
      if (m[0][0] !== "<") top().kids.push(m[0]);
      continue;
    }
    const tag = m[2].toLowerCase();
    if (m[1]) {
      const at = stack.map((n) => n.tag).lastIndexOf(tag);
      if (at > 0) stack.length = at;
      continue;
    }
    // A new <p> or <li> ends the one still open.
    if (tag === "p" && top().tag === "p") stack.pop();
    if (tag === "li") {
      const open = stack.map((n) => n.tag).lastIndexOf("li");
      const list = Math.max(stack.map((n) => n.tag).lastIndexOf("ul"), stack.map((n) => n.tag).lastIndexOf("ol"));
      if (open > list) stack.length = open;
    }
    const node = { tag, attrs: m[3], kids: [] };
    top().kids.push(node);
    if (SKIP.has(tag)) {
      // Take everything up to the closing tag as nothing.
      if (!VOID.has(tag)) {
        const close = new RegExp(`</${tag}\\s*>`, "ig");
        close.lastIndex = re.lastIndex;
        const end = close.exec(html);
        re.lastIndex = end ? close.lastIndex : html.length;
      }
    } else if (!VOID.has(tag) && !/\/\s*$/.test(m[3])) stack.push(node);
  }
  return root;
}

const decode = (s) =>
  s.replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (all, e) => {
    if (e[0] === "#") {
      const code = e[1].toLowerCase() === "x" ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10);
      return code > 0 && code < 0x110000 ? String.fromCodePoint(code) : "";
    }
    return ENTITIES[e.toLowerCase()] ?? all;
  });

function href(attrs) {
  const m = /\bhref\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/i.exec(attrs || "");
  const url = decode(m ? m[1] ?? m[2] ?? m[3] : "").trim();
  return /^(https?:\/\/|mailto:)/i.test(url) ? url.replace(/ /g, "%20").replace(/\)/g, "%29") : "";
}

function inline(nodes) {
  let out = "";
  for (const n of nodes) {
    if (typeof n === "string") {
      out += decode(n).replace(/\s+/g, " ").replace(/([\\*_`[\]])/g, "\\$1");
      continue;
    }
    if (SKIP.has(n.tag)) continue;
    const inner = inline(n.kids);
    const text = inner.trim();
    const pad = (s) => (text ? inner.slice(0, inner.length - inner.trimStart().length) + s + inner.slice(inner.trimEnd().length) : inner);
    if (n.tag === "br") out += "  \n";
    else if (n.tag === "strong" || n.tag === "b") out += pad(`**${text}**`);
    else if (n.tag === "em" || n.tag === "i") out += pad(`*${text}*`);
    else if (n.tag === "code") out += text ? `\`${n.kids.map((k) => (typeof k === "string" ? decode(k) : "")).join("")}\`` : "";
    else if (n.tag === "a") out += href(n.attrs) && text ? pad(`[${text}](${href(n.attrs)})`) : inner;
    else out += inner;
  }
  return out;
}

function blocks(nodes, depth = 0) {
  const out = [];
  let run = [];
  const flush = () => {
    const text = inline(run).replace(/[ \t]*\n[ \t]*/g, "\n").trim();
    if (text) out.push(text);
    run = [];
  };
  for (const n of nodes) {
    if (typeof n === "string" || !BLOCK.has(n.tag)) {
      if (typeof n === "string" || !SKIP.has(n.tag)) run.push(n);
      continue;
    }
    flush();
    const tag = n.tag;
    if (tag === "hr") out.push("---");
    else if (/^h[1-6]$/.test(tag)) {
      const text = inline(n.kids).replace(/\s+/g, " ").trim();
      if (text) out.push(`${"#".repeat(Math.min(4, Math.max(2, Number(tag[1]))))} ${text}`);
    } else if (tag === "ul" || tag === "ol") {
      const items = n.kids.filter((k) => typeof k !== "string" && k.tag === "li");
      const lines = items.map((li, i) => {
        const mark = tag === "ol" ? `${i + 1}. ` : "- ";
        const [first = "", ...rest] = blocks(li.kids, depth + 1);
        const pad = " ".repeat(mark.length);
        return mark + [first, ...rest].join("\n").replace(/\n/g, `\n${pad}`);
      });
      if (lines.length) out.push(lines.join("\n"));
    } else if (tag === "blockquote") {
      const inner = blocks(n.kids, depth).join("\n\n");
      if (inner) out.push(inner.replace(/^/gm, "> "));
    } else if (tag === "pre") {
      const code = n.kids.map(function raw(k) { return typeof k === "string" ? decode(k) : k.kids.map(raw).join(""); }).join("").replace(/^\n|\n$/g, "");
      if (code.trim()) out.push("```\n" + code + "\n```");
    } else out.push(...blocks(n.kids, depth));
  }
  flush();
  return out;
}

/** Clean Markdown from pasted HTML: headings, bold, italic, lists, links,
 * quotes and rules kept; scripts, styles, classes, spans and pictures dropped. */
export function htmlToMarkdown(html) {
  return blocks(parse(String(html)).kids).join("\n\n").replace(/\n{3,}/g, "\n\n").trim();
}

const STRUCTURE = /<\/?(h[1-6]|ul|ol|li|p|blockquote|a|strong|b|em|i|hr|pre)\b/i;

/** What a paste becomes, or null to let the browser paste as it would.
 * Clipboard HTML counts only when it has structure (a code editor's coloured
 * spans do not); plain text counts when it holds HTML tags. */
export function pasteAsMarkdown(html, text) {
  const fromClipboard = STRUCTURE.test(html || "");
  const source = fromClipboard ? html : looksLikeHtml(text) ? text : "";
  if (!source) return null;
  const markdown = htmlToMarkdown(source);
  return markdown || null;
}
