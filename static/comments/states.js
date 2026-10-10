/**
 * Every screen the remarks flow can show, as a pure function of an API body.
 *
 * **The editable box is drawn from the payload's own `may_edit`, never from a
 * role this module works out.** `comments_api` computes it from the same rule
 * `comments.write_as()` enforces, and the service asks again against the
 * placement it writes with. A page deciding for itself who signs what would be
 * a third opinion on one rule.
 */

import { esc } from "../web/html.js";

/**
 * Which class to open. Issue #180: the frame never named one, so this always
 * had nowhere to send a caller — every class the school has, on the reasoning
 * `marking.choose()` gives for the same shape: who may actually sign a class's
 * remarks is a question the class list answers, once one is picked, not a
 * scope this screen narrows in advance.
 */
export function choose({ term = "", classes = [] } = {}) {
  return [
    '<section class="state state-choose" data-state="choose">',
    "<h1>Remarks</h1>",
    term ? `<p class="term">${esc(term)}</p>` : "",
    classes.length
      ? [
          "<p>Which class?</p>",
          '<ul class="classes">',
          classes
            .map(
              (g) =>
                `<li><button type="button" data-action="pick-class" ` +
                `data-class="${esc(g.class_group_id)}">${esc(g.class_group)}` +
                `</button></li>`,
            )
            .join(""),
          "</ul>",
        ].join("")
      : '<p class="blank">Your school has no classes set up yet.</p>',
    "</section>",
  ].join("");
}

/** Who in this class still needs which remark. */
export function classList({ class_group = "", term = "", rows = [] } = {}) {
  return [
    '<section class="state state-class" data-state="class">',
    `<h1>Remarks: ${esc(class_group)}</h1>`,
    `<p class="term">${esc(term)}</p>`,
    '<ul class="children">',
    rows
      .map(
        (row) =>
          `<li class="child${row.outstanding.length ? " outstanding" : " done"}">` +
          `<button type="button" data-action="open" ` +
          `data-child="${esc(row.student_membership_id)}">` +
          `${esc(row.student) || "(no name on record)"}</button>` +
          `<span class="left">${
            row.outstanding.length
              ? `${row.outstanding.length} still to write`
              : "Both written"
          }</span></li>`,
      )
      .join(""),
    "</ul>",
    '<button type="button" class="back" data-action="back-to-classes">',
    "Choose a different class</button>",
    "</section>",
  ].join("");
}

/**
 * One child: both remarks, the bank, and the conduct grid where there is one.
 *
 * `locked` disables every box up front — the marking sheet's lesson. A screen
 * that let a teacher write a paragraph and learned from the refusal afterwards
 * tells her it is gone at the worst possible moment.
 */
export function child({
  student = "",
  class_group = "",
  term = "",
  locked = false,
  locked_reason = "",
  remarks = [],
  phrases = {},
  may_rate = false,
  sections = [],
  scale = [],
  notes = {},
  health = null,
  healthNote = null,
} = {}) {
  return [
    '<section class="state state-child" data-state="child">',
    `<h1>${esc(student) || "(no name on record)"}</h1>`,
    `<p class="when">${esc(class_group)} &middot; ${esc(term)}</p>`,
    locked
      ? `<p class="locked" role="status">${esc(locked_reason) ||
          "This card has left draft, so its remarks cannot be changed here."}</p>`
      : "",
    remarks.map((r) => remark(r, { locked, bank: phrases[r.author], note: notes[r.author] })).join(""),
    conduct({ may_rate, sections, scale, locked, note: notes.rating }),
    health && health.printed ? healthSection(health, healthNote) : "",
    '<button type="button" class="back" data-action="back">Back to the class</button>',
    "</section>",
  ].join("");
}

/**
 * One signatory's remark. Always shown; editable only where `may_edit` says.
 *
 * A remark this login cannot sign is rendered as **text, not a disabled box**.
 * A greyed-out textarea invites a reader to try typing in it; a paragraph does
 * not, and what they actually need is to read what the other signatory wrote.
 */
function remark(r, { locked, bank, note }) {
  const editable = r.may_edit && !locked;
  const body = [
    `<section class="remark remark-${esc(r.author)}${note ? ` ${esc(note.kind)}` : ""}">`,
    `<h2>${esc(r.author_label)}</h2>`,
  ];
  if (editable) {
    body.push(
      `<label class="sr" for="body-${esc(r.author)}">${esc(r.author_label)}</label>`,
      `<textarea id="body-${esc(r.author)}" data-author="${esc(r.author)}" rows="3">`,
      esc(r.body),
      "</textarea>",
      bank && bank.length ? phraseBank(r.author, bank) : "",
      `<button type="button" data-action="save" data-author="${esc(r.author)}">Save</button>`,
    );
  } else if (r.body) {
    body.push(`<p class="written">${esc(r.body)}</p>`);
  } else {
    body.push(
      `<p class="blank">Not written yet.${
        r.may_edit ? "" : ` This remark is ${esc(r.author_label).toLowerCase()}'s.`
      }</p>`,
    );
  }
  if (note) body.push(`<p class="note" role="alert">${esc(note.detail)}</p>`);
  body.push("</section>");
  return body.join("");
}

/** The stock remarks this signatory may pick from. One tap fills, still editable. */
function phraseBank(author, bank) {
  return [
    '<ul class="phrases">',
    bank
      .map(
        (text) =>
          `<li><button type="button" data-action="phrase" ` +
          `data-author="${esc(author)}" data-text="${esc(text)}">${esc(text)}</button></li>`,
      )
      .join(""),
    "</ul>",
  ].join("");
}

/**
 * The conduct grid, and the two different reasons it may be absent.
 *
 * No enabled group means the school does not print conduct at all — nothing to
 * say beyond that. `may_rate` false means the school does print it and this
 * login is not the class teacher, which is a different sentence: the principal
 * signs her own remark for any child and rates nobody.
 */
function conduct({ may_rate, sections, scale, locked, note }) {
  if (!sections.length) return "";
  return [
    '<section class="conduct">',
    "<h2>Conduct</h2>",
    may_rate
      ? ""
      : '<p class="quiet">Conduct is rated by the teacher answerable for the class.</p>',
    sections
      .map((s) =>
        [
          `<h3>${esc(s.group_label)}</h3>`,
          '<ul class="traits">',
          s.traits
            .map((t) => trait(t, { may_rate: may_rate && !locked, scale }))
            .join(""),
          "</ul>",
        ].join(""),
      )
      .join(""),
    note ? `<p class="note" role="alert">${esc(note.detail)}</p>` : "",
    "</section>",
  ].join("");
}

function trait(t, { may_rate, scale }) {
  const current = t.score === null || t.score === undefined ? "" : String(t.score);
  if (!may_rate) {
    return (
      `<li class="trait"><span class="name">${esc(t.name)}</span>` +
      `<span class="score">${current || "-"}</span></li>`
    );
  }
  return [
    `<li class="trait"><label for="trait-${esc(t.trait_id)}">${esc(t.name)}</label>`,
    `<select id="trait-${esc(t.trait_id)}" data-trait="${esc(t.trait_id)}">`,
    `<option value=""${current === "" ? " selected" : ""}>-</option>`,
    scale
      .map(
        (p) =>
          `<option value="${esc(p.value)}"${
            current === String(p.value) ? " selected" : ""
          }>${esc(p.value)}: ${esc(p.label)}</option>`,
      )
      .join(""),
    "</select></li>",
  ].join("");
}

/** Signed in, and not somebody who signs a card here. */
export function notASignatory({ detail = "" } = {}) {
  return [
    '<section class="state state-not-a-signatory" data-state="not-a-signatory">',
    "<h1>You cannot write remarks here</h1>",
    `<p>${esc(detail) ||
      "A card is signed by the class teacher and the principal of the school " +
        "the child attends."}</p>`,
    "<p>If that should be you, the school office is who can arrange it.</p>",
    "</section>",
  ].join("");
}

/** This host is not a school's. */
export function wrongHost() {
  return [
    '<section class="state state-wrong-host" data-state="wrong-host">',
    "<h1>Remarks live on your school's own web address</h1>",
    "<p>This page is open on the sign-in site. Open it again from your ",
    "school's own address, the link on the page you signed in on.</p>",
    "</section>",
  ].join("");
}

/** Signed out, or never signed in. The way back is on another host. */
export function signedOut({ portal = "", expired = false } = {}) {
  return [
    '<section class="state state-signed-out" data-state="signed-out">',
    `<h1>${expired ? "Your session has ended" : "Please sign in"}</h1>`,
    expired
      ? "<p>You were signed out after a period of inactivity. Remarks you had " +
        "already saved were saved as you wrote them.</p>"
      : "<p>Sign in with your password to write remarks.</p>",
    wayBack(portal),
    "</section>",
  ].join("");
}

function wayBack(portal) {
  // No portal domain configured means no link, only the sentence — a dead link
  // is worse than being told to go back the way you came.
  if (!portal) return "<p>Go back to the sign-in page you came from.</p>";
  return `<p><a href="//${esc(portal)}/staff-sign-in/">Sign in again</a></p>`;
}

/** Anything the page cannot explain. */
export function broken() {
  return [
    '<section class="state state-broken" data-state="broken">',
    "<h1>This page is not working</h1>",
    "<p>Something went wrong on our side. Please try again in a few minutes, ",
    "and tell your school if it keeps happening.</p>",
    "</section>",
  ].join("");
}

/**
 * Physical development and health, on the Ogun State card. Served only to the
 * class teacher, the principal and an administrator (`results/health.py`), so
 * a teacher of another class never gets here with anything to draw. The class
 * teacher edits it until the card goes home; anyone else reads it.
 */
export function healthSection(h, note = null) {
  const typed = (note && note.typed) || {};
  const value = (name) => (typed[name] !== undefined ? typed[name] : h[name]);
  const box = (name, label, attrs) =>
    `<label for="health-${name}">${label}</label>` +
    `<input id="health-${name}" name="${name}" value="${esc(value(name) ?? "")}" ${attrs}>`;
  const shown = (v, unit) => (v === null || v === undefined || v === "" ? "-" : `${esc(v)}${unit}`);
  const head = '<section class="health"><h2>Physical development and health</h2>' +
    '<p class="hint">Seen only by the class teacher, the principal, the school&#39;s administrators and this child&#39;s parents.</p>';
  if (!h.may_edit) {
    return [
      head,
      '<dl class="facts">',
      `<dt>Height, beginning of term</dt><dd>${shown(h.height_start_m, " m")}</dd>`,
      `<dt>Height, end of term</dt><dd>${shown(h.height_end_m, " m")}</dd>`,
      `<dt>Weight, beginning of term</dt><dd>${shown(h.weight_start_kg, " kg")}</dd>`,
      `<dt>Weight, end of term</dt><dd>${shown(h.weight_end_kg, " kg")}</dd>`,
      `<dt>Days absent through illness</dt><dd>${shown(h.days_absent_ill, "")}</dd>`,
      `<dt>Nature of illness</dt><dd>${shown(h.illness, "")}</dd>`,
      "</dl>",
      note ? `<p class="note" role="alert">${esc(note.detail)}</p>` : "",
      "</section>",
    ].join("");
  }
  return [
    head,
    `<form class="health-form${note ? ` ${esc(note.kind)}` : ""}" data-form="health">`,
    box("height_start_m", "Height at the beginning of term (m)", 'inputmode="decimal" placeholder="1.42"'),
    box("height_end_m", "Height at the end of term (m)", 'inputmode="decimal" placeholder="1.44"'),
    box("weight_start_kg", "Weight at the beginning of term (kg)", 'inputmode="decimal" placeholder="38.5"'),
    box("weight_end_kg", "Weight at the end of term (kg)", 'inputmode="decimal" placeholder="39.0"'),
    box("days_absent_ill", "Days absent through illness", 'inputmode="numeric"'),
    box("illness", "Nature of illness", 'maxlength="120"'),
    '<button type="submit">Save health record</button>',
    note ? `<p class="note" role="alert">${esc(note.detail)}</p>` : "",
    "</form>",
    "</section>",
  ].join("");
}
