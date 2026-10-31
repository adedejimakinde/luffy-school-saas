/**
 * Every screen the website editor can show, as a pure function of the school's overview.
 *
 * Strings rather than DOM, for `card/states.js`' reason: a refusal is the path nobody demos,
 * and a string can be asserted in `node --test` with no browser.
 */

import { esc } from "../web/html.js";
import { BLANK, fields, summary } from "./forms.js";

const KIND_LABELS = {
  hero: "Hero", crest_motto: "Crest and motto", principal_message: "Principal's message", facts: "Facts",
  news: "News", gallery: "Gallery", admissions_cta: "Admissions panel", contact_map: "Contact and map", text: "Text",
};
export const kindLabel = (kind) => KIND_LABELS[kind] || kind;

const NETWORK_LABELS = { facebook: "Facebook", instagram: "Instagram", x: "X", youtube: "YouTube", tiktok: "TikTok", linkedin: "LinkedIn" };

export const UNSAVED = "You have unsaved changes. Leave anyway?";

function note(n) {
  if (!n) return "";
  const reload = n.stale ? ' <button type="button" class="again" data-action="reload">Reload</button>' : "";
  return `<p class="note" role="alert">${esc(n.detail)}${reload}</p>`;
}

function day(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

/** Draft or published, and whether the draft holds changes: said at the top of every screen. */
export function status(body) {
  const s = body.state || {};
  const lines = [];
  if (!s.published) lines.push('<strong class="label label-warn">Draft</strong> Not published yet: the public sees the school&#39;s old page.');
  else {
    lines.push(
      `<strong class="label label-ok">Published</strong> Version ${esc(s.revision)}, ${esc(day(s.published_at))}, by ${esc(s.published_by)}.`,
    );
    lines.push(s.changes ? " <strong>Changes not yet published.</strong>" : " The draft is what is live.");
  }
  if (s.ready) lines.push(`<br>Marked ready for the principal by ${esc(s.ready_by)}.`);
  return `<p class="site-status" role="status">${lines.join("")}</p>`;
}

function actions(body, { told = null } = {}) {
  const s = body.state || {};
  const out = [`<a class="btn" href="${esc(body.preview)}" target="_blank" rel="noopener">Preview the draft</a>`];
  if (body.can_publish && s.changes) out.push('<button type="button" class="btn-primary" data-action="publish">Publish</button>');
  let ready = "";
  if (body.can_edit && !body.can_publish) {
    if (s.ready) ready = '<p class="hint">The principal has been told the draft is ready.</p>';
    else if (s.changes) {
      ready = [
        '<form class="ready" data-form="ready">',
        '<label for="ready-note">A note for the principal (optional)</label>',
        '<input id="ready-note" name="note" maxlength="200">',
        '<button type="submit">Ready for the principal</button>',
        "</form>",
      ].join("");
    }
  }
  const toldLine =
    told === null ? "" : told > 0
      ? `<p class="done" role="status">Marked ready. We have emailed the principal a link to the preview.</p>`
      : `<p class="note" role="alert">Marked ready, but the principal has no email address on file. Please tell them yourself that the draft is ready to check.</p>`;
  return `<div class="site-actions">${out.join("")}</div>${ready}${toldLine}`;
}

function pageRow(p, i, pages, version) {
  const home = p.key === "home";
  const move = home ? "" : [
    `<button type="button" class="icon-button" data-action="page-up" data-ref="${esc(p.ref)}"${i <= 1 ? " disabled" : ""} aria-label="Move ${esc(p.label)} up">&uarr;</button>`,
    `<button type="button" class="icon-button" data-action="page-down" data-ref="${esc(p.ref)}"${i === pages.length - 1 ? " disabled" : ""} aria-label="Move ${esc(p.label)} down">&darr;</button>`,
  ].join("");
  const toggle = home
    ? '<span class="standing">Always on</span>'
    : [
        `<label class="switch"><input type="checkbox" data-action="switch-page" data-ref="${esc(p.ref)}"${p.enabled ? " checked" : ""}>`,
        '<span class="track" aria-hidden="true"></span>',
        `<span class="switch-text">${p.enabled ? "On" : "Off"}<span class="visually-hidden">: ${esc(p.label)}</span></span></label>`,
      ].join("");
  return [
    `<li class="group page-row${p.enabled ? "" : " inactive"}">`,
    `<span class="name">${esc(p.label)}</span>`,
    `<span class="level">${esc(p.path)} &middot; ${p.sections.length} ${p.sections.length === 1 ? "section" : "sections"}</span>`,
    `<span class="row-actions">${toggle}${move}`,
    `<button type="button" data-action="open-page" data-ref="${esc(p.ref)}">Edit<span class="visually-hidden"> ${esc(p.label)}</span></button></span>`,
    "</li>",
  ].join("");
}

/** The first screen: status, the pages in menu order, a new page, and the site-wide settings. */
export function site(body, { notes = {}, told = null } = {}) {
  const pages = body.pages || [];
  const parts = [
    '<section class="state state-site" data-state="site">',
    "<h1>Website</h1>",
    status(body),
    actions(body, { told }),
    note(notes.top),
  ];
  if (!body.can_edit) {
    parts.push(
      '<p class="hint">The principal has not let you edit the website. They can switch that on here, under &ldquo;Who edits&rdquo;.</p>',
    );
  } else {
    parts.push(
      "<h2>Pages</h2>",
      '<p class="hint">In the order the menu shows them. Home is always first and always on.</p>',
      `<ul class="classes pages-list">${pages.map((p, i) => pageRow(p, i, pages, body.version)).join("")}</ul>`,
      `<form class="add-page" data-form="add-page" data-tracked>`,
      "<h3>Add a page</h3>",
      '<label for="page-title">Name</label>',
      '<input id="page-title" name="title" maxlength="70" required placeholder="Boarding">',
      '<label for="page-slug">Web address (optional)</label>',
      '<span class="hint" id="page-slug-hint">/pages/ and then lowercase letters, numbers and hyphens. Made from the name if left blank.</span>',
      '<input id="page-slug" name="slug" maxlength="40" aria-describedby="page-slug-hint" autocapitalize="none">',
      '<button type="submit">Add the page</button>',
      note(notes["add-page"]),
      "</form>",
      footerForm(body, notes.footer),
    );
  }
  if (body.can_publish) parts.push(colourForm(body, notes.colour), delegation(body, notes.delegation));
  parts.push(log(body), "</section>");
  return parts.join("");
}

function footerForm(body, n) {
  const footer = body.footer || {};
  const social = Object.fromEntries((footer.social || []).map((s) => [s.network, s.url]));
  return [
    '<form class="footer-form" data-form="footer" data-tracked>',
    "<h2>Footer</h2>",
    '<label for="footer-address">Address line</label>',
    `<input id="footer-address" name="address_line" maxlength="200" value="${esc(footer.address_line || "")}">`,
    ...(body.networks || []).map((network) => [
      `<label for="footer-${esc(network)}">${esc(NETWORK_LABELS[network] || network)} page</label>`,
      `<input id="footer-${esc(network)}" name="social_${esc(network)}" maxlength="300" inputmode="url" autocapitalize="none" value="${esc(social[network] || "")}">`,
    ].join("")),
    '<button type="submit">Save the footer</button>',
    note(n),
    "</form>",
  ].join("");
}

function colourForm(body, n) {
  const current = body.colour || body.card_colour || "#143D8C";
  return [
    '<form class="colour-form" data-form="colour">',
    "<h2>The school&#39;s colour</h2>",
    `<p class="hint">${body.colour ? "The website&#39;s own colour." : "The report card&#39;s colour, until you choose another."} White writing must read on it.</p>`,
    '<label for="site-colour">Colour</label>',
    `<input type="color" id="site-colour" name="colour" value="${esc(current.toLowerCase())}">`,
    '<button type="submit">Save the colour</button>',
    body.colour ? '<button type="button" class="again" data-action="colour-reset">Use the report card&#39;s colour</button>' : "",
    note(n),
    "</form>",
  ].join("");
}

function delegation(body, n) {
  return [
    '<div class="delegation">',
    "<h2>Who edits</h2>",
    '<label class="switch"><input type="checkbox" data-action="delegation"',
    body.delegated ? " checked" : "",
    '><span class="track" aria-hidden="true"></span><span class="switch-text"><strong>Let the administrator edit the draft</strong>',
    '<span class="hint">They can change pages and mark the draft ready for you. Only you publish.</span></span></label>',
    note(n),
    "</div>",
  ].join("");
}

function log(body) {
  const events = body.log || [];
  const live = body.state && body.state.revision;
  const rows = events.map((e) => {
    const what = e.kind === "marked_ready" ? "Marked ready" : e.kind === "rolled_back" ? `Rolled back to version ${esc(e.rollback_of)} as version ${esc(e.revision)}` : `Published version ${esc(e.revision)}`;
    const back = body.can_publish && e.revision && e.revision !== live && e.kind !== "marked_ready"
      ? ` <button type="button" class="again" data-action="rollback" data-number="${esc(e.revision)}">Go back to version ${esc(e.revision)}</button>`
      : "";
    return `<li><span class="when">${esc(day(e.at))}</span> ${what} by ${esc(e.by)}${e.note ? `: &ldquo;${esc(e.note)}&rdquo;` : ""}${back}</li>`;
  });
  return [
    "<h2>History</h2>",
    rows.length ? `<ul class="site-log">${rows.join("")}</ul>` : '<p class="blank">Nothing published yet.</p>',
  ].join("");
}

/** One page: its name and address, its sections in order, and a section to add. */
export function page(body, ref, { confirming = null, notes = {} } = {}) {
  const p = (body.pages || []).find((x) => x.ref === ref);
  if (!p) return site(body, { notes });
  const custom = p.kind === "custom";
  const sections = p.sections || [];
  const options = (p.kinds || []).map((k) =>
    `<option value="${esc(k.kind)}"${k.available ? "" : " disabled"}${k.hint ? ` data-description="${esc(k.hint)}"` : ""}>${esc(k.label)}${k.available ? "" : " (coming soon)"}</option>`,
  ).join("");
  return [
    '<section class="state state-page" data-state="page">',
    '<button type="button" class="again" data-action="back">All pages</button>',
    `<h1>${esc(p.label)}</h1>`,
    status(body),
    `<p class="level">${esc(p.path)}${p.enabled ? "" : " &middot; Switched off: the public cannot see it"}</p>`,
    `<p><a class="btn" href="${esc(p.preview)}" target="_blank" rel="noopener">Preview this page</a></p>`,
    '<form class="page-form" data-form="page" data-tracked>',
    `<label for="page-name">${custom ? "Name" : "Title in the browser tab (optional)"}</label>`,
    `<input id="page-name" name="title" maxlength="70" value="${esc(p.title)}"${custom ? " required" : ""}>`,
    '<label for="page-description">Description for search engines (optional)</label>',
    `<textarea id="page-description" name="description" maxlength="160" rows="2">${esc(p.description)}</textarea>`,
    custom && !p.address_fixed
      ? `<label for="page-address">Web address</label><span class="hint" id="page-address-hint">/pages/ and then this. It is fixed once the page is published.</span><input id="page-address" name="slug" maxlength="40" value="${esc(p.slug)}" aria-describedby="page-address-hint" autocapitalize="none">`
      : "",
    '<button type="submit">Save</button>',
    note(notes.page),
    "</form>",
    "<h2>Sections</h2>",
    sections.length
      ? `<ol class="sections-list">${sections.map((s, i) => sectionRow(s, i, sections.length, confirming)).join("")}</ol>`
      : '<p class="blank">No sections yet. Add the first below.</p>',
    note(notes.sections),
    '<form class="add-section" data-form="add-section">',
    '<label for="add-kind">Add a section</label>',
    `<select id="add-kind" name="kind">${options}</select>`,
    `<button type="submit"${sections.length >= 15 ? " disabled" : ""}>Add</button>`,
    sections.length >= 15 ? '<p class="hint">A page holds at most 15 sections.</p>' : "",
    "</form>",
    custom ? removePage(p, confirming, notes.remove) : "",
    "</section>",
  ].join("");
}

function sectionRow(s, i, count, confirming) {
  const asked = confirming && confirming.what === "remove-section" && confirming.id === s.id;
  const soon = s.kind === "news" || s.kind === "gallery";
  return [
    '<li class="group section-row">',
    `<span class="name">${esc(kindLabel(s.kind))}</span>`,
    `<span class="level">${esc(summary(s.kind, s.data))}</span>`,
    '<span class="row-actions">',
    soon ? "" : `<button type="button" data-action="edit-section" data-id="${esc(s.id)}">Edit<span class="visually-hidden"> ${esc(kindLabel(s.kind))}</span></button>`,
    `<button type="button" class="icon-button" data-action="section-up" data-id="${esc(s.id)}"${i === 0 ? " disabled" : ""} aria-label="Move up">&uarr;</button>`,
    `<button type="button" class="icon-button" data-action="section-down" data-id="${esc(s.id)}"${i === count - 1 ? " disabled" : ""} aria-label="Move down">&darr;</button>`,
    asked
      ? `<button type="button" class="danger" data-action="remove-section" data-id="${esc(s.id)}" data-sure="1">Remove it</button><button type="button" data-action="keep">Keep it</button>`
      : `<button type="button" data-action="remove-section" data-id="${esc(s.id)}">Remove</button>`,
    "</span></li>",
  ].join("");
}

function removePage(p, confirming, n) {
  const asked = confirming && confirming.what === "remove-page";
  return [
    '<div class="remove-page">',
    "<h2>Delete this page</h2>",
    asked
      ? `<p>Delete ${esc(p.label)} and its sections from the draft?</p><button type="button" class="danger" data-action="remove-page" data-sure="1">Delete it</button> <button type="button" data-action="keep">Keep it</button>`
      : '<button type="button" data-action="remove-page">Delete this page</button>',
    note(n),
    "</div>",
  ].join("");
}

/** A section's form: one being added (`id` null) or one being changed. */
export function section(body, ref, { id = null, kind = null, notes = {} } = {}) {
  const p = (body.pages || []).find((x) => x.ref === ref);
  const s = p && id !== null ? (p.sections || []).find((x) => x.id === id) : null;
  const k = s ? s.kind : kind;
  const pages = (body.pages || []).map((x) => ({ path: x.path, label: x.label }));
  return [
    '<section class="state state-section" data-state="section">',
    `<button type="button" class="again" data-action="cancel">Back to ${esc(p ? p.label : "the page")}</button>`,
    `<h1>${s ? "" : "New: "}${esc(kindLabel(k))}</h1>`,
    `<form class="section-form" data-form="section" data-kind="${esc(k)}" data-tracked>`,
    fields(k, s ? s.data : BLANK[k] || {}, { pages }),
    `<button type="submit">${s ? "Save" : "Add to the page"}</button>`,
    note(notes.section),
    "</form>",
    "</section>",
  ].join("");
}

/** Publish, asked once more, with what it will do and room for a note. */
export function confirmPublish(body, { notes = {} } = {}) {
  return [
    '<section class="state state-confirm" data-state="confirm-publish">',
    "<h1>Publish the website?</h1>",
    `<p>Everyone who visits ${esc(body.school)}&#39;s website will see the draft as it is now, straight away.</p>`,
    `<p><a href="${esc(body.preview)}" target="_blank" rel="noopener">Look at the preview first</a></p>`,
    '<form data-form="publish">',
    '<label for="publish-note">A note for the history (optional)</label>',
    '<input id="publish-note" name="note" maxlength="200" placeholder="Admissions open for 2027/2028">',
    '<button type="submit" class="btn-primary">Publish now</button>',
    "</form>",
    '<button type="button" class="again" data-action="back">Not now</button>',
    note(notes.publish),
    "</section>",
  ].join("");
}

/** Going back to an earlier version, asked once more. */
export function confirmRollback(body, number, { notes = {} } = {}) {
  return [
    '<section class="state state-confirm" data-state="confirm-rollback">',
    `<h1>Go back to version ${esc(number)}?</h1>`,
    `<p>The website will show version ${esc(number)} again, straight away. The draft is not changed: fix it there and publish again when it is ready.</p>`,
    `<form data-form="rollback" data-number="${esc(number)}">`,
    '<label for="rollback-note">Why (optional)</label>',
    '<input id="rollback-note" name="note" maxlength="200">',
    `<button type="submit" class="btn-primary">Go back to version ${esc(number)}</button>`,
    "</form>",
    '<button type="button" class="again" data-action="back">Not now</button>',
    note(notes.rollback),
    "</section>",
  ].join("");
}

export const notYours = () =>
  '<section class="state state-refused" data-state="not-yours"><h1>Website</h1><p>The school&#39;s website is looked after by its principal, and by the administrator when the principal allows it.</p></section>';

export const wrongHost = () =>
  '<section class="state state-refused" data-state="wrong-host"><h1>Website</h1><p>Open the website editor on your school&#39;s own address.</p></section>';

export function signedOut({ portal = "", expired = false } = {}) {
  const door = portal ? `//${esc(portal)}/staff-sign-in/` : "/staff-sign-in/";
  return [
    '<section class="state state-signed-out" data-state="signed-out">',
    "<h1>Website</h1>",
    `<p>${expired ? "You were signed out after a while away." : "Please sign in to edit the school&#39;s website."}</p>`,
    `<a class="btn btn-primary" href="${door}">Sign in</a>`,
    "</section>",
  ].join("");
}

export const broken = () =>
  '<section class="state state-broken" data-state="broken"><h1>Website</h1><p>Something went wrong loading the website editor. Please try again.</p><button type="button" data-action="reload">Try again</button></section>';
