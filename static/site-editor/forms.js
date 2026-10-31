/**
 * One form per section kind: what each field is, drawn as HTML, and read back as the data the
 * school's rules check (`schoolsite/sections.py`). Pure, so every kind is testable with no browser.
 *
 * The server is the judge of every value: lengths here are only `maxlength`, to stop a phone
 * keyboard early, and a refusal comes back as the school's own sentence. Pictures and videos
 * arrive in a later update: their fields show a "coming soon" line, and whatever the data
 * already holds for them is kept as it is.
 */

import { esc } from "../web/html.js";

const MOTTO_LANGUAGES = [
  ["", "Not set"], ["en", "English"], ["la", "Latin"], ["yo", "Yoruba"], ["ig", "Igbo"], ["ha", "Hausa"], ["ar", "Arabic"],
];

/** What each kind's form asks for, in order. */
export const FORMS = {
  hero: [
    { name: "heading", label: "Heading", type: "text", max: 120, required: true },
    { name: "subheading", label: "The line under the heading", type: "text", max: 240 },
    { name: "buttons", label: "Buttons", type: "buttons", count: 2 },
    { type: "soon", label: "Picture or video", text: "Pictures and video come in a later update." },
  ],
  crest_motto: [
    { name: "motto", label: "Motto", type: "text", max: 120 },
    { name: "language", label: "The motto's language", type: "select", options: MOTTO_LANGUAGES },
    { name: "translation", label: "Translation", type: "text", max: 160 },
    { name: "founded", label: "Year founded", type: "number" },
  ],
  principal_message: [
    { type: "soon", label: "Portrait", text: "Pictures come in a later update." },
    { name: "name", label: "Name", type: "text", max: 120 },
    { name: "title", label: "Title", type: "text", max: 80, hint: "For example Rev. Sr. or Dr (Mrs)" },
    { name: "message", label: "Message", type: "textarea", max: 4000, required: true },
    { name: "signature", label: "Signature line", type: "text", max: 120 },
  ],
  facts: [{ name: "items", label: "Facts", type: "facts", count: 6 }],
  admissions_cta: [
    { name: "heading", label: "Heading", type: "text", max: 120, required: true },
    { name: "text", label: "Words", type: "textarea", max: 600 },
    { name: "button", label: "The button's words", type: "text", max: 40, hint: "Blank: Find out how to apply" },
    { name: "link", label: "Where the button goes", type: "page" },
    { name: "session", label: "Session", type: "text", max: 9, hint: "Like 2027/2028" },
    { name: "open", label: "Admissions are open", type: "checkbox" },
    { name: "closes", label: "Closing date", type: "date" },
  ],
  contact_map: [
    { name: "whatsapp", label: "WhatsApp number", type: "text", max: 30 },
    { name: "hours", label: "Office hours", type: "textarea", max: 200 },
    { name: "latitude", label: "Latitude", type: "number", step: "any" },
    { name: "longitude", label: "Longitude", type: "number", step: "any" },
    { name: "maps_link", label: "Google Maps link", type: "text", max: 300, hint: "Or leave blank to use the address" },
  ],
  text: [
    { name: "heading", label: "Heading", type: "text", max: 120 },
    { name: "body", label: "Text", type: "textarea", max: 6000, required: true },
  ],
  news: [{ type: "soon", label: "News", text: "News arrives in a later update." }],
  gallery: [{ type: "soon", label: "Photo albums", text: "Photo albums arrive in a later update." }],
};

/** Fields of the data a form does not show yet, kept as they are when it is saved. */
const KEPT = { hero: ["image", "focal", "video"], principal_message: ["portrait"] };

/** Data a new section of each kind starts with. */
export const BLANK = { admissions_cta: { open: true } };

const id = (prefix, name) => `${prefix}-${name}`;

function text(prefix, f, value) {
  const max = f.max ? ` maxlength="${f.max}"` : "";
  const req = f.required ? " required" : "";
  const hint = f.hint ? `<span class="hint" id="${id(prefix, f.name)}-hint">${esc(f.hint)}</span>` : "";
  const described = f.hint ? ` aria-describedby="${id(prefix, f.name)}-hint"` : "";
  const label = `<label for="${id(prefix, f.name)}">${esc(f.label)}</label>`;
  const v = value === null || value === undefined ? "" : value;
  if (f.type === "textarea") {
    return `${label}${hint}<textarea id="${id(prefix, f.name)}" name="${f.name}" rows="5"${max}${req}${described}>${esc(v)}</textarea>`;
  }
  const kind = f.type === "number" ? `type="number" inputmode="decimal"${f.step ? ` step="${f.step}"` : ""}` : f.type === "date" ? 'type="date"' : 'type="text"';
  return `${label}${hint}<input ${kind} id="${id(prefix, f.name)}" name="${f.name}" value="${esc(v)}"${max}${req}${described}>`;
}

function select(prefix, name, label, options, value) {
  return [
    `<label for="${id(prefix, name)}">${esc(label)}</label>`,
    `<select id="${id(prefix, name)}" name="${name}">`,
    options.map(([v, l]) => `<option value="${esc(v)}"${v === (value || "") ? " selected" : ""}>${esc(l)}</option>`).join(""),
    "</select>",
  ].join("");
}

/** The site's own pages a link may name, then "Another address". */
function linkChoice(prefix, name, label, value, pages) {
  const own = pages.map((p) => [p.path, p.label]);
  const known = own.some(([path]) => path === value);
  const other = Boolean(value) && !known;
  const options = [["", "Choose"], ...own, ["other", "Another address"]];
  return [
    select(prefix, name, label, options, other ? "other" : value),
    `<label for="${id(prefix, `${name}_other`)}">Another address</label>`,
    `<span class="hint">https:// web address, tel: or mailto:</span>`,
    `<input type="text" id="${id(prefix, `${name}_other`)}" name="${name}_other" value="${esc(other ? value : "")}" maxlength="300">`,
  ].join("");
}

function field(prefix, f, data, pages) {
  switch (f.type) {
    case "soon":
      return `<p class="soon"><strong>${esc(f.label)}.</strong> ${esc(f.text)}</p>`;
    case "select":
      return select(prefix, f.name, f.label, f.options, data[f.name]);
    case "checkbox":
      return `<label class="check"><input type="checkbox" name="${f.name}"${data[f.name] ? " checked" : ""}> ${esc(f.label)}</label>`;
    case "page": {
      // One of the school's own pages only: the admissions button never leaves the site.
      const own = pages.filter((p) => p.path !== "/").map((p) => [p.path, p.label]);
      return select(prefix, f.name, f.label, [["", "The Admissions page, or Contact"], ...own], data[f.name] || "");
    }
    case "buttons": {
      const buttons = data.buttons || [];
      return Array.from({ length: f.count }, (_, i) => {
        const b = buttons[i] || {};
        const n = i + 1;
        return [
          `<fieldset class="row-group"><legend>Button ${n}</legend>`,
          text(prefix, { name: `button${n}_label`, label: "Words", type: "text", max: 40 }, b.label || ""),
          linkChoice(prefix, `button${n}_link`, "Where it goes", b.link || "", pages),
          "</fieldset>",
        ].join("");
      }).join("");
    }
    case "facts": {
      const items = data.items || [];
      return [
        '<p class="hint">From 2 to 6. Leave a row blank to leave it out.</p>',
        ...Array.from({ length: f.count }, (_, i) => {
          const item = items[i] || {};
          const n = i + 1;
          return [
            `<fieldset class="row-group"><legend>Fact ${n}</legend>`,
            text(prefix, { name: `fact${n}_figure`, label: "Figure", type: "text", max: 16, hint: "Like 98%" }, item.figure || ""),
            text(prefix, { name: `fact${n}_label`, label: "What it is", type: "text", max: 120 }, item.label || ""),
            text(prefix, { name: `fact${n}_source`, label: "Source", type: "text", max: 160 }, item.source || ""),
            "</fieldset>",
          ].join("");
        }),
      ].join("");
    }
    default:
      return text(prefix, f, data[f.name]);
  }
}

/** The fields of one kind's form, filled from `data`. `pages` are the site's pages a link may name. */
export function fields(kind, data = {}, { pages = [], prefix = "f" } = {}) {
  return (FORMS[kind] || []).map((f) => field(prefix, f, data || {}, pages)).join("");
}

const linkOf = (values, name) => (values[name] === "other" ? String(values[`${name}_other`] || "").trim() : values[name] || "");

/**
 * The data a form's `values` (name to value; a checkbox's is true or false) say, for the server
 * to check. Blank number fields are left out; blank rows of buttons and facts are left out.
 */
export function collect(kind, values, existing = {}) {
  const data = {};
  for (const f of FORMS[kind] || []) {
    if (f.type === "soon") continue;
    if (f.type === "buttons") {
      data.buttons = [];
      for (let n = 1; n <= f.count; n += 1) {
        const label = String(values[`button${n}_label`] || "").trim();
        const link = linkOf(values, `button${n}_link`);
        if (label || link) data.buttons.push({ label, link });
      }
    } else if (f.type === "facts") {
      data.items = [];
      for (let n = 1; n <= f.count; n += 1) {
        const item = {
          figure: String(values[`fact${n}_figure`] || "").trim(),
          label: String(values[`fact${n}_label`] || "").trim(),
          source: String(values[`fact${n}_source`] || "").trim(),
        };
        if (item.figure || item.label || item.source) data.items.push(item);
      }
    } else if (f.type === "checkbox") {
      data[f.name] = Boolean(values[f.name]);
    } else if (f.type === "number") {
      const raw = String(values[f.name] ?? "").trim();
      if (raw !== "") data[f.name] = Number(raw);
    } else if (f.type === "page") {
      data[f.name] = values[f.name] || "";
    } else {
      data[f.name] = values[f.name] ?? "";
    }
  }
  for (const name of KEPT[kind] || []) {
    if (existing && existing[name] !== undefined && existing[name] !== null) data[name] = existing[name];
  }
  return data;
}

/** One line saying what a section holds, for the list of a page's sections. */
export function summary(kind, data = {}) {
  switch (kind) {
    case "facts":
      return `${(data.items || []).length} facts`;
    case "principal_message":
      return data.name || "The principal's message";
    case "contact_map":
      return data.hours ? data.hours.split("\n")[0] : "Address, phone and map";
    case "crest_motto":
      return data.motto || "The crest";
    case "news":
    case "gallery":
      return "Coming soon";
    default:
      return data.heading || (data.body ? data.body.split("\n")[0] : "");
  }
}
