/**
 * Every screen the setup page can show, as a pure function of an API body.
 *
 * Strings rather than DOM, for `card/states.js`' reason: a refusal is the path
 * nobody demos, and a string can be asserted in `node --test` with no browser.
 */

import { esc, numberOrBlank } from "../web/html.js";

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
  lga = "", lga_choices = [], notes = {},
} = {}) {
  return [
    '<section class="state state-setup" data-state="setup">',
    "<h1>School setup</h1>",

    "<h2>Terms</h2>",
    terms.length
      ? `<ul class="terms">${terms.map((t) => termRow(t)).join("")}</ul>`
      : '<p class="blank">No terms yet. The first one opens the school\'s calendar.</p>',
    newTermForm(notes.term),

    "<h2>Classes</h2>",
    classes.length
      ? `<ul class="classes">${classes.map(classRow).join("")}</ul>`
      : '<p class="blank">No class groups yet.</p>',
    newClassForm(notes.class),

    card ? cardLook(card, notes) : "",

    localGovernment(lga, lga_choices, notes),

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
function localGovernment(lga, choices, notes) {
  return [
    '<h2 id="lga">Local government area</h2>',
    '<p class="hint">Printed beside your school&#39;s name on the Ogun State report card.</p>',
    `<form class="lga-form${notes.lga ? ` ${esc(notes.lga.kind)}` : ""}" data-form="lga">`,
    '<label for="lga_input">Local government area</label>',
    `<input id="lga_input" name="lga" value="${esc(lga)}" maxlength="60" list="lga_choices" autocomplete="off">`,
    `<datalist id="lga_choices">${choices.map((c) => `<option value="${esc(c)}">`).join("")}</datalist>`,
    '<button type="submit">Save local government area</button>',
    notes.lga ? `<p class="note" role="alert">${esc(notes.lga.detail)}</p>` : "",
    "</form>",
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
  return [
    '<section class="state state-broken" data-state="broken">',
    "<h1>This page is not working</h1>",
    "<p>Something went wrong on our side. Please try again in a few minutes, ",
    "and tell whoever runs this system for your school.</p>",
    "</section>",
  ].join("");
}
