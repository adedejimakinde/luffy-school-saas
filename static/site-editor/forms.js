/**
 * One form per section kind: what each field is, drawn as HTML, and read back as the data the
 * school's rules check (`schoolsite/sections.py`). Pure, so every kind is testable with no browser.
 *
 * The server is the judge of every value: lengths here are only `maxlength`, to stop a phone
 * keyboard early, and a refusal comes back as the school's own sentence.
 *
 * Pictures (PR 5): a hero's photos (a slideshow of one to five) or its video, and the principal's
 * portrait, are chosen from the school's pictures, uploaded at Photos and albums
 * (`/website/photos/`), where each photo's description and focal point are set; a gallery shows
 * one album. A picture is named by its id, which the server checks is this school's and the right sort.
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
    { name: "slides", label: "Photos", type: "slides", count: 5 },
    { name: "media", label: "Or a video instead", type: "picture", use: "hero", video: true },
  ],
  crest_motto: [
    { name: "motto", label: "Motto", type: "text", max: 120 },
    { name: "language", label: "The motto's language", type: "select", options: MOTTO_LANGUAGES },
    { name: "translation", label: "Translation", type: "text", max: 160 },
    { name: "founded", label: "Year founded", type: "number" },
  ],
  principal_message: [
    { name: "portrait", label: "Portrait", type: "picture", use: "portrait" },
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
  gallery: [
    { name: "album", label: "Album", type: "album" },
    { name: "count", label: "How many photos to show", type: "number", hint: "From 1 to 12. The rest are on the album's own page." },
  ],
};

/** Fields of the data a form does not show, kept as they are when it is saved. */
const KEPT = { gallery: ["photos"] };

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

/** A picture field's value: `image:12` or `video:13` for a hero, `12` for a portrait. */
export const pictureValue = (use, p) => (!p ? "" : use === "hero" ? `${p.video ? "video" : "image"}:${p.id}` : String(p.id));

const PHOTOS = "/website/photos/";

function pictureField(prefix, f, data, ctx) {
  const pictures = (ctx.pictures || []).filter((p) => p.use === f.use && (!f.video || p.video));
  const chosen = f.use === "hero" ? (data.video ? `video:${data.video}` : "") : String(data[f.name] || "");
  const picked = pictures.find((p) => pictureValue(f.use, p) === chosen);
  const state = (p) => (p.state === "processing" ? " \u2013 Processing\u2026" : p.state === "ready" ? "" : " \u2013 Could not be used");
  const options = [["", "None"], ...pictures.map((p) => [pictureValue(f.use, p), `${p.alt || "No description yet"}${p.video ? " (video)" : ""}${state(p)}`])];
  // A picture the list does not hold stays chosen rather than being dropped on Save.
  if (chosen && !picked) options.push([chosen, "The current picture"]);
  const thumb = picked && picked.thumb ? `<img class="thumb" src="${esc(picked.thumb)}" alt="${esc(picked.alt)}" width="96" height="96">` : "";
  const upload = f.use === "hero" ? `${PHOTOS}#upload-hero-video">Upload a video` : `${PHOTOS}#upload-portrait">Upload a portrait`;
  return [
    `<fieldset class="row-group picture-field"><legend>${esc(f.label)}</legend>${thumb}`,
    select(prefix, f.name, "Choose one", options, chosen),
    `<p><a class="btn" href="${upload}</a>${picked ? ` <a class="btn" href="${PHOTOS}#picture-${esc(picked.id)}">Edit this picture</a>` : ""}</p>`,
    "</fieldset>",
  ].join("");
}

/** A hero's slideshow: up to five of the school's hero photos, in order. Each photo's description
 * and focal point are its own, edited at Photos and albums, so it reads and crops the same everywhere. */
function slidesField(prefix, f, data, ctx) {
  const photos = (ctx.pictures || []).filter((p) => p.use === "hero" && !p.video);
  const ids = (data.slides || []).map((s) => s.picture).concat(data.image ? [data.image] : []);
  const state = (p) => (p.state === "processing" ? " \u2013 Processing\u2026" : p.state === "ready" ? "" : " \u2013 Could not be used");
  const rows = Array.from({ length: f.count }, (_, i) => {
    const chosen = ids[i] ? String(ids[i]) : "";
    const picked = photos.find((p) => String(p.id) === chosen);
    const options = [["", "None"], ...photos.map((p) => [String(p.id), `${p.alt || "No description yet"}${state(p)}`])];
    if (chosen && !picked) options.push([chosen, "The current photo"]);
    const thumb = picked && picked.thumb ? `<img class="thumb" src="${esc(picked.thumb)}" alt="${esc(picked.alt)}" width="96" height="96">` : "";
    const edit = picked ? `<p><a class="btn" href="${PHOTOS}#picture-${esc(picked.id)}">Description and focal point</a></p>` : "";
    return `<div class="slide-row">${thumb}${select(prefix, `slide${i + 1}`, `Photo ${i + 1}${i ? "" : ", shown first"}`, options, chosen)}${edit}</div>`;
  });
  return [
    `<fieldset class="row-group picture-field"><legend>${esc(f.label)}</legend>`,
    '<p class="hint">One to five photos. They fade from one to the next every 4 seconds; the first loads with the page.</p>',
    ...rows,
    `<p><a class="btn" href="${PHOTOS}#upload-hero">Upload a photo</a></p></fieldset>`,
  ].join("");
}

function albumField(prefix, f, data, ctx) {
  const options = [["", "Choose an album"], ...(ctx.albums || []).map((a) => [String(a.id), `${a.title}${a.live ? "" : " (not published)"}`])];
  return `${select(prefix, f.name, f.label, options, data.album ? String(data.album) : "")}<p class="hint">It shows only what is published in the album. <a href="${PHOTOS}">Photos and albums</a></p>`;
}

function field(prefix, f, data, pages, ctx = {}) {
  switch (f.type) {
    case "picture":
      return pictureField(prefix, f, data, ctx);
    case "slides":
      return slidesField(prefix, f, data, ctx);
    case "album":
      return albumField(prefix, f, data, ctx);
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

/**
 * The fields of one kind's form, filled from `data`. `pages` are the site's pages a link may name;
 * `pictures` and `albums` what a picture or album field offers.
 */
export function fields(kind, data = {}, { pages = [], prefix = "f", pictures = [], albums = [] } = {}) {
  return (FORMS[kind] || []).map((f) => field(prefix, f, data || {}, pages, { pictures, albums })).join("");
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
    } else if (f.type === "slides") {
      if (!("slide1" in values)) {
        // A form that does not show the field keeps what the data holds.
        if (existing && existing.slides) data.slides = existing.slides;
        continue;
      }
      const seen = new Set();
      data.slides = [];
      for (let n = 1; n <= f.count; n += 1) {
        const pid = Number(values[`slide${n}`] || 0);
        if (pid && !seen.has(pid)) data.slides.push({ picture: pid });
        seen.add(pid);
      }
    } else if (f.type === "picture") {
      if (!(f.name in values)) {
        // A form that does not show the field keeps what the data holds.
        const name = f.use === "hero" ? "video" : f.name;
        if (existing && existing[name] !== undefined && existing[name] !== null) data[name] = existing[name];
        continue;
      }
      const raw = String(values[f.name] || "");
      if (f.use === "hero") {
        const [what, id] = raw.split(":");
        data.video = what === "video" && id ? Number(id) : null;
        // A video chosen takes the hero's place of its photos.
        if (data.video) data.slides = [];
      } else {
        data[f.name] = raw ? Number(raw) : null;
      }
    } else if (f.type === "album") {
      if (values[f.name]) data.album = Number(values[f.name]);
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
  // A gallery shows an album or photos chosen one by one, never both: an album chosen wins.
  if (kind === "gallery" && data.album) {
    delete data.photos;
  } else if (kind === "gallery") {
    delete data.count;
  }
  return data;
}

/** One line saying what a section holds, for the list of a page's sections. */
export function summary(kind, data = {}, { albums = [] } = {}) {
  switch (kind) {
    case "gallery": {
      const album = albums.find((a) => a.id === data.album);
      return album ? `${album.title}${album.live ? "" : " (not published)"}` : data.photos ? `${data.photos.length} photos` : "No album chosen";
    }
    case "facts":
      return `${(data.items || []).length} facts`;
    case "principal_message":
      return data.name || "The principal's message";
    case "contact_map":
      return data.hours ? data.hours.split("\n")[0] : "Address, phone and map";
    case "crest_motto":
      return data.motto || "The crest";
    case "news":
      return "Coming soon";
    default:
      return data.heading || (data.body ? data.body.split("\n")[0] : "");
  }
}
