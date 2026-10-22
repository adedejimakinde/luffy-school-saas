/**
 * Every screen the setup page can show, as a pure function of an API body.
 *
 * Strings rather than DOM, for `card/states.js`' reason: a refusal is the path
 * nobody demos, and a string can be asserted in `node --test` with no browser.
 */

import { emptyState, esc, numberOrBlank, brokenState } from "../web/html.js";
import { connectionDropped } from "../web/http.js";

/**
 * The school's shape: its terms and its class groups.
 *
 * **Exactly one term is marked current, and the others offer to become it.**
 * The constraint behind that is `one_current_term`, and the server clears the
 * old one in the same transaction — so the screen never has to ask anybody to
 * unset a term first, and never shows two as current.
 */
export function shape({
  terms = [], classes = [], card = null, contact_email = "", about = "", address = "", phone = "",
  lga = "", lga_choices = [], school_code = "", subjects = [], departments = [], conduct = null, notes = {},
} = {}) {
  return [
    '<section class="state state-setup" data-state="setup">',
    "<h1>School setup</h1>",

    '<h2 id="terms">Terms</h2>',
    terms.length
      ? `<ul class="terms">${terms.map((t) => termRow(t)).join("")}</ul>`
      : '<p class="blank">No terms yet. The first one opens the school\'s calendar.</p>',
    newTermForm(notes.term),

    '<h2 id="classes">Classes</h2>',
    classes.length
      ? `<ul class="classes">${classes.map(classRow).join("")}</ul>`
      : emptyState({
          key: "classes",
          icon: "i-sheet",
          title: "No classes yet",
          text: "Add JSS 1 to SS 3, one class for each arm. Registers, marks and report cards all belong to a class.",
          action: { href: "#class_name", label: "Add your first class" },
        }),
    newClassForm(notes.class),

    card ? cardLook(card, notes) : "",

    conduct ? conductSettings(conduct, notes) : "",

    localGovernment(lga, lga_choices, notes, school_code),
    card && card.template === "ogun" ? subjectDepartments(subjects, departments, notes) : "",

    contactEmail(contact_email, notes),

    publicPage({ about, address, phone }, notes),

    "</section>",
  ].join("");
}

/**
 * This school's own contact email (`docs/messaging.md` D17). Every email the
 * platform sends on the school's behalf carries this as `Reply-To`, so a
 * family or a provider who replies reaches the school, not this platform.
 */
function contactEmail(address, notes) {
  return [
    '<h2 id="contact-email">Contact email</h2>',
    "<p class=\"hint\">Where a reply to an email from this school should land. ",
    "Shown to nobody but used as the reply-to address on payment receipts, ",
    "absence alerts and every other email this school sends.</p>",
    `<form class="contact-email-form${notes.contact_email ? ` ${esc(notes.contact_email.kind)}` : ""}" data-form="contact-email">`,
    '<label for="contact_email">Contact email</label>',
    `<input id="contact_email" name="contact_email" type="email" value="${esc(address)}" placeholder="office@yourschool.example">`,
    '<button type="submit">Save contact email</button>',
    notes.contact_email ? `<p class="note" role="alert">${esc(notes.contact_email.detail)}</p>` : "",
    "</form>",
  ].join("");
}

/**
 * The local government area the school sits in, which the Ogun State report
 * card prints beside the school's name. Ogun's twenty are offered as the
 * person types; a school elsewhere types its own.
 */
function localGovernment(lga, choices, notes, schoolCode = "") {
  return [
    '<h2 id="lga">Local government area and school code</h2>',
    '<p class="hint">Printed beside your school&#39;s name on the Ogun State report card: ' +
      '&quot;(Abeokuta South LGA) [B13003]&quot;. Both are optional.</p>',
    `<form class="lga-form${notes.lga ? ` ${esc(notes.lga.kind)}` : ""}" data-form="lga">`,
    '<label for="lga_input">Local government area</label>',
    `<input id="lga_input" name="lga" value="${esc(lga)}" maxlength="60" list="lga_choices" autocomplete="off">`,
    `<datalist id="lga_choices">${choices.map((c) => `<option value="${esc(c)}">`).join("")}</datalist>`,
    '<label for="school_code">School code</label>',
    `<input id="school_code" name="school_code" value="${esc(schoolCode)}" maxlength="20" autocomplete="off" placeholder="B13003">`,
    '<button type="submit">Save</button>',
    notes.lga ? `<p class="note" role="alert">${esc(notes.lga.detail)}</p>` : "",
    "</form>",
  ].join("");
}

/**
 * Which department each subject sits under on a senior (SSS) Ogun State
 * card, whose subject columns are grouped under department headings. A junior
 * card prints its subjects in one run and ignores this. Saved as it is chosen.
 */
function subjectDepartments(subjects, departments, notes) {
  if (!subjects.length) return "";
  return [
    '<h2 id="departments">Subject departments</h2>',
    '<p class="hint">On a senior (SSS) Ogun State card, subjects are grouped under these headings. ' +
      "A subject with none is printed under Other.</p>",
    '<ul class="subjects">',
    subjects
      .map(
        (s) =>
          `<li><label for="department_${esc(s.subject_id)}">${esc(s.name)}</label>` +
          `<select id="department_${esc(s.subject_id)}" data-subject="${esc(s.subject_id)}">` +
          `<option value="">None</option>` +
          departments
            .map((d) => `<option value="${esc(d.value)}"${d.value === s.department ? " selected" : ""}>${esc(d.label)}</option>`)
            .join("") +
          "</select></li>",
      )
      .join(""),
    "</ul>",
    notes.department ? `<p class="note" role="alert">${esc(notes.department.detail)}</p>` : "",
  ].join("");
}

/**
 * What the school's public page says, beside the crest and colour set above.
 * Its contact email, above, is shown there too.
 */
function publicPage({ about, address, phone }, notes) {
  return [
    '<h2 id="public-page">Your school\'s web page</h2>',
    '<p class="hint">Families see this on your school\'s own address, with your crest, ',
    "colour and contact email. Leave a box empty to leave it off the page.</p>",
    `<form class="public-page-form${notes.public_page ? ` ${esc(notes.public_page.kind)}` : ""}" data-form="public-page">`,
    '<label for="about">About the school</label>',
    `<textarea id="about" name="about" rows="4" maxlength="600">${esc(about)}</textarea>`,
    '<label for="address">Address</label>',
    `<input id="address" name="address" value="${esc(address)}" maxlength="300" autocomplete="off">`,
    '<label for="phone">Phone</label>',
    `<input id="phone" name="phone" type="tel" value="${esc(phone)}" maxlength="30" autocomplete="off">`,
    '<button type="submit">Save web page</button>',
    notes.public_page ? `<p class="note" role="alert">${esc(notes.public_page.detail)}</p>` : "",
    "</form>",
  ].join("");
}

/**
 * One term.
 *
 * `school_days` is `numberOrBlank()` and not `|| "—"`: a term declared as
 * having nought teaching days is a real (if odd) statement, and one nobody has
 * declared yet is a different one. Truthiness cannot tell them apart, which is
 * the same care the card page takes with attendance.
 */
function termRow(t) {
  return [
    `<li class="term${t.is_current ? " current" : ""}">`,
    `<span class="name">${esc(t.session)} &middot; ${esc(t.name_label)}</span>`,
    `<span class="dates">${esc(t.starts_on)} to ${esc(t.ends_on)}</span>`,
    `<span class="days">${numberOrBlank(t.school_days)} school days</span>`,
    t.is_current
      ? '<span class="standing">Current</span>'
      : `<button type="button" data-action="make-current" ` +
        `data-term="${esc(t.term_id)}">Make current</button>`,
    "</li>",
  ].join("");
}

function classRow(c) {
  return [
    `<li class="group${c.is_active ? "" : " inactive"}">`,
    `<span class="name">${esc(c.name)}</span>`,
    `<span class="level">level ${esc(c.level)}</span>`,
    c.is_active ? "" : '<span class="standing">No longer taught</span>',
    "</li>",
  ].join("");
}

/**
 * Opening a term's record.
 *
 * It does **not** offer "and make it current" as a checkbox. Those are two
 * decisions, and a school opening next term's record while this one is still
 * being taught is the ordinary case — a checkbox defaulting either way would
 * be wrong for somebody.
 */
function newTermForm(note) {
  return [
    `<form class="new-term${note ? ` ${esc(note.kind)}` : ""}" data-form="term">`,
    "<h3>Open a term</h3>",
    '<label for="session">Session</label>',
    '<input id="session" name="session" placeholder="2026/2027" required>',
    '<label for="name">Term</label>',
    '<select id="name" name="name">',
    '<option value="first">First term</option>',
    '<option value="second">Second term</option>',
    '<option value="third">Third term</option>',
    "</select>",
    '<label for="starts_on">Starts</label>',
    '<input id="starts_on" name="starts_on" type="date" required>',
    '<label for="ends_on">Ends</label>',
    '<input id="ends_on" name="ends_on" type="date" required>',
    '<button type="submit">Open the term</button>',
    note ? `<p class="note" role="alert">${esc(note.detail)}</p>` : "",
    "</form>",
  ].join("");
}

function newClassForm(note) {
  return [
    `<form class="new-class${note ? ` ${esc(note.kind)}` : ""}" data-form="class">`,
    "<h3>Open a class group</h3>",
    '<label for="class_name">Name</label>',
    '<input id="class_name" name="name" placeholder="JSS 1A" required>',
    // Not derived from the name: "JSS 1A" sorts before "JSS 10A" as text, and
    // no string rule survives a school running Nursery, Primary and Senior.
    '<label for="level">Where it sits in your order</label>',
    '<input id="level" name="level" type="number" min="0" value="0">',
    '<button type="submit">Open the group</button>',
    note ? `<p class="note" role="alert">${esc(note.detail)}</p>` : "",
    "</form>",
  ].join("");
}

/**
 * The report card's look: the school's crest and its one colour. Both optional.
 *
 * The preview is the card's own header in miniature: on white, the crest or,
 * with none, the initials in a circle of the colour, the name in the colour,
 * and the colour's rule under it. The colour is the school's, from the API,
 * which is why it may be written into a `style`: it is data here, not a
 * design choice.
 */
function cardLook(card, notes) {
  const colour = card.colour || card.default_colour;
  const mark = card.has_crest
    ? `<img class="crest-mark" src="/api/academics/card/crest/?v=${esc(card.crest_version || "")}" alt="Your crest">`
    : `<span class="initials" aria-hidden="true" style="background: ${esc(colour)}">${esc(card.initials || "")}</span>`;
  return [
    '<h2 id="report-card">Report card</h2>',
    "<p class=\"hint\">Your crest and one colour lead every report card. Both are optional.</p>",
    templateForm(card.template || "standard", notes.template),
    positionForm(Boolean(card.show_position), notes.position),
    card.template === "ogun" ? ministryForm(Boolean(card.show_ministry), notes.ministry) : "",
    '<div class="look-preview">',
    '<div class="look-head">',
    `<span class="mark">${mark}</span>`,
    `<span class="look-name" style="color: ${esc(colour)}">Your school&#39;s name</span>`,
    "</div>",
    `<div class="look-rule" style="background: ${esc(colour)}"></div>`,
    "</div>",

    `<form class="colour-form${notes.colour ? ` ${esc(notes.colour.kind)}` : ""}" data-form="colour">`,
    '<label for="colour">School colour</label>',
    `<input id="colour" name="colour" type="color" value="${esc(colour)}">`,
    '<span class="hint">Used for the school&#39;s name and the rules on the card. It has to ',
    "read clearly on white paper, so a colour too light to read is refused.</span>",
    '<button type="submit">Save colour</button>',
    notes.colour ? `<p class="note" role="alert">${esc(notes.colour.detail)}</p>` : "",
    "</form>",

    `<form class="crest-form${notes.crest ? ` ${esc(notes.crest.kind)}` : ""}" data-form="crest" enctype="multipart/form-data">`,
    '<label for="crest">Crest</label>',
    '<input id="crest" name="crest" type="file" accept="image/png,image/jpeg" required>',
    '<span class="hint">PNG or JPG, up to 1 MB. It is resized to a small square. ',
    "With no crest, the card shows your school&#39;s initials in a circle.</span>",
    '<span class="actions">',
    '<button type="submit">Upload crest</button>',
    card.has_crest ? '<button type="button" data-action="remove-crest">Remove crest</button>' : "",
    "</span>",
    notes.crest ? `<p class="note" role="alert">${esc(notes.crest.detail)}</p>` : "",
    "</form>",
  ].join("");
}

/**
 * The affective and psychomotor sections: a switch, a trait list and the 1 to 5
 * scale's words. The principal's and the administrator's, and only theirs: the
 * server sends this block to nobody else.
 *
 * **Off hides, it does not delete.** The switch's sentence says so, because the
 * question a principal has is whether the ratings are gone. And every sentence
 * about a card already sent says it keeps what it showed: that is the promise
 * the whole section is built on, and the screen is where it is made.
 *
 * A trait is never deleted, only hidden: a hidden one stays in the list, muted,
 * with a button to show it again, because ratings and released cards still name it.
 */
function conductSettings(conduct, notes) {
  return [
    '<h2 id="conduct">Affective and psychomotor</h2>',
    '<p class="hint">The conduct and skills lines under the marks. Teachers rate each child ',
    "from 1 to 5. Changes apply to cards released from now on; a card already sent home ",
    "keeps the lines, ratings and words it was sent with.</p>",
    ...conduct.sections.map((section) => conductSection(section, notes)),
    scaleForm(conduct.scale, notes.conduct_scale),
    changeLog(conduct.changes),
  ].join("");
}

function conductSection(section, notes) {
  const note = notes[`conduct_${section.group}`];
  const id = `conduct-${esc(section.group)}`;
  return [
    `<section class="conduct-section${section.enabled ? " on" : ""}" data-group="${esc(section.group)}" aria-labelledby="${id}">`,
    `<label class="switch"><input type="checkbox" role="switch" data-switch="${esc(section.group)}"` +
      `${section.enabled ? " checked" : ""}>` +
      `<span class="track" aria-hidden="true"></span>` +
      `<span class="switch-text"><strong id="${id}">${esc(section.label)}</strong>` +
      `<span class="hint">${
        section.enabled
          ? "On. Teachers rate it and new cards print it."
          : "Off. No rating grid for teachers and no section on new cards. Ratings already entered are kept."
      }</span></span></label>`,
    section.traits.length
      ? `<ol class="trait-list">${section.traits.map((t, i) => traitRow(section, t, i)).join("")}</ol>`
      : '<p class="blank">No traits yet.</p>',
    `<form class="trait-add" data-form="add-trait" data-group="${esc(section.group)}">`,
    `<label for="new-${esc(section.group)}">Add a trait</label>`,
    `<span class="row"><input id="new-${esc(section.group)}" name="name" maxlength="64" autocomplete="off" placeholder="Respect for school property">`,
    '<button type="submit">Add</button></span>',
    "</form>",
    note ? `<p class="note" role="alert">${esc(note.detail)}</p>` : "",
    "</section>",
  ].join("");
}

function traitRow(section, t, index) {
  const last = index === section.traits.length - 1;
  const g = esc(section.group);
  return [
    `<li class="trait${t.is_hidden ? " hidden" : ""}">`,
    `<input class="trait-name" aria-label="Name of trait ${index + 1}" value="${esc(t.name)}" maxlength="64" ` +
      `data-trait-name="${esc(t.trait_id)}" autocomplete="off">`,
    '<span class="trait-actions">',
    `<button type="button" class="icon-btn" data-action="move-up" data-group="${g}" data-trait="${esc(t.trait_id)}" aria-label="Move ${esc(t.name)} up"${index === 0 ? " disabled" : ""}>&uarr;</button>`,
    `<button type="button" class="icon-btn" data-action="move-down" data-group="${g}" data-trait="${esc(t.trait_id)}" aria-label="Move ${esc(t.name)} down"${last ? " disabled" : ""}>&darr;</button>`,
    t.is_hidden
      ? `<button type="button" data-action="show-trait" data-trait="${esc(t.trait_id)}">Show</button>`
      : `<button type="button" data-action="hide-trait" data-trait="${esc(t.trait_id)}">Hide</button>`,
    "</span>",
    t.is_hidden ? '<span class="hint">Hidden. Off new cards; its ratings are kept.</span>' : "",
    "</li>",
  ].join("");
}

/** Five words for five fixed numbers. The numbers are not editable: ratings are stored as them. */
function scaleForm(scale, note) {
  return [
    '<section class="conduct-scale" aria-labelledby="conduct-scale">',
    '<h3 id="conduct-scale">Rating scale</h3>',
    '<p class="hint">Always 1 to 5. You can change the words, not the numbers.</p>',
    '<ul class="scale-list">',
    scale
      .map(
        (p) =>
          `<li><label for="scale-${esc(p.value)}"><span class="num">${esc(p.value)}</span></label>` +
          `<input id="scale-${esc(p.value)}" value="${esc(p.label)}" maxlength="32" data-scale="${esc(p.value)}" autocomplete="off"></li>`,
      )
      .join(""),
    "</ul>",
    note ? `<p class="note" role="alert">${esc(note.detail)}</p>` : "",
    "</section>",
  ].join("");
}

/** Who changed what, and when: the latest few, folded away until asked for. */
function changeLog(changes) {
  if (!changes || !changes.length) return "";
  return [
    '<details class="change-log"><summary>Recent changes</summary><ul>',
    changes
      .map((c) => `<li><span class="when">${esc(whenText(c.at))}</span> ${esc(c.summary)} <span class="hint">by ${esc(c.by)}</span></li>`)
      .join(""),
    "</ul></details>",
  ].join("");
}

/** "2026-10-20 14:05" from an ISO time, in the reader's own zone. */
export function whenText(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/**
 * Which card the school prints. Choosing the Ogun State card sets up its
 * papers, traits and scale on the server; the sentence under the choice says
 * what it did, and what it left alone because marks or ratings were in.
 */
function templateForm(template, note) {
  const option = (value, label, hint) =>
    `<label class="choice"><input type="radio" name="template" value="${value}"` +
    `${template === value ? " checked" : ""}> <span><strong>${label}</strong> ` +
    `<span class="hint">${hint}</span></span></label>`;
  return [
    `<form class="template-form${note && note.kind !== "applied" ? ` ${esc(note.kind)}` : ""}" data-form="template">`,
    '<fieldset><legend>Report card template</legend>',
    option("standard", "Standard", "The Classnode card."),
    option(
      "ogun",
      "Ogun State",
      "The MOEST/OGSERA report sheet. Sets up 1st Test 10, 2nd Test 10, Assignment 10 " +
        "and Exam 70, the sheet&#39;s affective and psychomotor traits, and its rating key. " +
        "Nothing already marked or rated is changed.",
    ),
    "</fieldset>",
    '<button type="submit">Use this template</button>',
    template === "ogun" ? '<p><a class="btn btn-quiet" href="/ogsera/">Fill an OGSERA template</a></p>' : "",
    note && note.kind === "applied" ? applied(note.applied) : "",
    note && note.kind !== "applied" ? `<p class="note" role="alert">${esc(note.detail)}</p>` : "",
    "</form>",
  ].join("");
}

/**
 * Whether the card prints the child's position in class. Off unless the
 * school turns it on; the Ogun State card turns it on. A card already
 * released keeps what it printed.
 */
function positionForm(on, note) {
  return [
    `<form class="position-form${note ? ` ${esc(note.kind)}` : ""}" data-form="position">`,
    '<label class="choice"><input type="checkbox" name="show_position"' + (on ? " checked" : "") + ">",
    " <span><strong>Print each child&#39;s position in class</strong> ",
    '<span class="hint">Cards released from now on show &quot;4th of 45&quot;. Cards already sent home keep what they showed.</span></span></label>',
    '<button type="submit">Save</button>',
    note ? `<p class="note" role="alert">${esc(note.detail)}</p>` : "",
    "</form>",
  ].join("");
}

/**
 * Whether the Ogun State card opens with the ministry's heading. Off unless
 * the school turns it on; without it the card leads with the school's name,
 * crest, LGA and code. Offered only while the school prints the Ogun card.
 */
function ministryForm(on, note) {
  return [
    `<form class="ministry-form${note ? ` ${esc(note.kind)}` : ""}" data-form="ministry">`,
    '<label class="choice"><input type="checkbox" name="show_ministry"' + (on ? " checked" : "") + ">",
    " <span><strong>Head the card with the Ogun State Government and its Ministry of Education</strong> ",
    '<span class="hint">Off, the card leads with your school&#39;s name, crest, LGA and code. ',
    "Cards already sent home keep what they showed.</span></span></label>",
    '<button type="submit">Save</button>',
    note ? `<p class="note" role="alert">${esc(note.detail)}</p>` : "",
    "</form>",
  ].join("");
}

function applied(a) {
  if (!a) return '<p class="done" role="status">Saved. Report cards use the Standard template.</p>';
  const list = (items) => items.map(esc).join(", ");
  const lines = ['<div class="done" role="status"><p>Saved. Report cards use the Ogun State template.</p><ul>'];
  if (a.assessments_set.length) lines.push(`<li>Papers set for ${list(a.assessments_set)}.</li>`);
  if (a.assessments_kept.length) {
    lines.push(`<li>Kept as they are, because marks are in: ${list(a.assessments_kept)}.</li>`);
  }
  if (a.traits_added.length) lines.push(`<li>Traits added: ${list(a.traits_added)}.</li>`);
  if (a.traits_renamed.length) lines.push(`<li>Traits renamed: ${list(a.traits_renamed)}.</li>`);
  if (a.traits_hidden.length) {
    lines.push(`<li>Traits the sheet does not print, hidden (any ratings are kept): ${list(a.traits_hidden)}.</li>`);
  }
  lines.push("</ul></div>");
  return lines.join("");
}

/** Signed in, and not somebody who shapes this school. */
export function notTheOffice({ detail = "" } = {}) {
  return [
    '<section class="state state-not-the-office" data-state="not-the-office">',
    "<h1>You cannot set this school up</h1>",
    `<p>${esc(detail) ||
      "The calendar and the class groups are set up by a principal or an " +
        "administrator of the school."}</p>`,
    "<p>If that should be you, whoever runs this system for your school can ",
    "arrange it.</p>",
    "</section>",
  ].join("");
}

/** This host is not a school's. */
export function wrongHost() {
  return [
    '<section class="state state-wrong-host" data-state="wrong-host">',
    "<h1>Setup lives on your school's own web address</h1>",
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
      ? "<p>You were signed out after a period of inactivity. Anything you had " +
        "already saved was saved.</p>"
      : "<p>Sign in with your password to set your school up.</p>",
    wayBack(portal),
    "</section>",
  ].join("");
}

function wayBack(portal) {
  // No portal domain configured means no link, only the sentence.
  if (!portal) return "<p>Go back to the sign-in page you came from.</p>";
  return `<p><a href="//${esc(portal)}/staff-sign-in/">Sign in again</a></p>`;
}

/** Anything the page cannot explain. */
export function broken() {
  return brokenState(connectionDropped(), "tell whoever runs this system for your school");
}
