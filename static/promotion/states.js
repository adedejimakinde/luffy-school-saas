/**
 * Every screen the promotion page can show, as a pure function of an API body.
 *
 * Three steps and one rule. The review lists every class with every child:
 * the year's average off the released third-term card, what Classnode suggests
 * from it and the pass mark, and the principal's decision. Only the principal
 * is offered the controls that record a decision, and nothing is assumed for a
 * child nobody has decided about (audit finding G-04). "Review" moves nothing;
 * it shows what confirming would do, and only the second button, on the
 * summary, writes, moving every child or none, as decided.
 */

import { esc } from "../web/html.js";

const GRADUATE = "graduate";

function destinationSelect(row, targets) {
  const chosen = row.graduate ? GRADUATE : row.destination_id;
  const options = [
    `<option value=""${chosen ? "" : " selected"}>Choose a class…</option>`,
    ...targets
      .filter((t) => t.class_group_id !== row.class_group_id)
      .map(
        (t) =>
          `<option value="${esc(t.class_group_id)}"${t.class_group_id === chosen ? " selected" : ""}>${esc(t.name)}</option>`,
      ),
    `<option value="${GRADUATE}"${chosen === GRADUATE ? " selected" : ""}>Graduated</option>`,
  ];
  return [
    `<label class="dest"><span class="dest-label">Moves to</span>`,
    `<select name="dest_${esc(row.class_group_id)}">${options.join("")}</select></label>`,
  ].join("");
}

const SUGGESTED = { promoted: "promote", repeated: "repeat" };

/** What the page offers a principal first for a child nobody has decided about. */
export function offered(child, graduate) {
  if (child.decision) return child.decision.status;
  if (child.suggested === "promoted") return graduate ? "graduated" : "promoted";
  return child.suggested === "repeated" ? "repeated" : "";
}

function childRow(child, { mayDecide, outcomes, graduate }) {
  const figures =
    child.average === null || child.average === undefined
      ? "No released results for the year, so nothing is suggested."
      : `Year's average ${esc(child.average)}%` +
        (SUGGESTED[child.suggested] ? `. Classnode suggests: ${SUGGESTED[child.suggested]}.` : ".");
  const decided = child.decision
    ? `<span class="decided">Decided: ${esc(child.decision.label)}</span>` +
      (child.decision.reason ? ` <small>${esc(child.decision.reason)}</small>` : "") +
      (child.decision.by ? ` <small>(${esc(child.decision.by)})</small>` : "")
    : '<span class="undecided">Not decided yet</span>';
  const first = offered(child, graduate);
  const choose = mayDecide
    ? [
        `<select name="decide_${esc(child.membership_id)}" aria-label="Decision for ${esc(child.name)}">`,
        `<option value=""${first ? "" : " selected"}>Decide…</option>`,
        ...outcomes.map(
          (o) => `<option value="${esc(o.value)}"${o.value === first ? " selected" : ""}>${esc(o.label)}</option>`,
        ),
        "</select>",
      ].join("")
    : "";
  return [
    `<li class="child${child.decision ? "" : " waiting"}">`,
    '<span class="who">',
    `${esc(child.name)}${child.reference ? ` <small>${esc(child.reference)}</small>` : ""}`,
    `<span class="figures">${figures}</span>`,
    `<span class="decision">${decided}</span>`,
    "</span>",
    choose,
    "</li>",
  ].join("");
}

/** One reason for the class, and the button that records its decisions. */
function decideRow(row) {
  return [
    '<div class="decide">',
    `<label><span class="dest-label">Reason, kept with each decision</span>`,
    `<input type="text" name="reason_${esc(row.class_group_id)}" maxlength="1000" autocomplete="off"></label>`,
    `<button type="button" class="btn" data-action="decide" data-class="${esc(row.class_group_id)}">Record decisions for ${esc(row.name)}</button>`,
    row.note ? `<p class="note" role="alert">${esc(row.note)}</p>` : "",
    "</div>",
  ].join("");
}

/**
 * How the year is averaged and the pass mark Classnode suggests against. For
 * the principal and the administrator; saved on its own, before anything else.
 */
export function yearSettings(settings) {
  if (!settings) return "";
  const weighted = settings.averaging === "weighted";
  const weight = (name, label) =>
    `<label><span class="dest-label">${label}</span>` +
    `<input type="number" name="${name}" min="0" max="100" step="0.01" inputmode="decimal" value="${esc(settings[name] === null || settings[name] === undefined ? "" : settings[name])}"></label>`;
  return [
    '<section class="card year-settings">',
    "<h2>How the year is reckoned</h2>",
    '<p class="hint">Classnode suggests promote or repeat from each child\'s released results for the year and this pass mark. ',
    "The decision is the principal's. A change here does not alter a report card that has gone home or a decision already recorded.</p>",
    '<form data-form="settings">',
    '<fieldset class="averaging"><legend>Average of the three terms</legend>',
    `<label><input type="radio" name="averaging" value="equal"${weighted ? "" : " checked"}> Each term counts equally</label>`,
    `<label><input type="radio" name="averaging" value="weighted"${weighted ? " checked" : ""}> Weight the terms (must add up to 100)</label>`,
    '<div class="weights">',
    weight("first_weight", "First term"),
    weight("second_weight", "Second term"),
    weight("third_weight", "Third term"),
    "</div>",
    "</fieldset>",
    '<label class="pass-mark"><span class="dest-label">Pass mark (%)</span>',
    `<input type="number" name="pass_mark" min="0" max="100" step="0.01" inputmode="decimal" value="${esc(settings.pass_mark)}" required></label>`,
    '<button type="submit" class="btn">Save</button>',
    settings.note ? `<p class="${settings.saved ? "saved" : "note"}" role="status">${esc(settings.note)}</p>` : "",
    "</form>",
    "</section>",
  ].join("");
}

export function review({
  term = "",
  to_term = "",
  classes = [],
  targets = [],
  problem = null,
  note = null,
  may_decide = false,
  undecided = 0,
  outcomes = [],
  settings = null,
} = {}) {
  if (problem) return unavailable({ problem, settings });
  const waiting = undecided
    ? `<p class="hint waiting-count">${esc(undecided)} ${undecided === 1 ? "child has" : "children have"} no decision yet. ` +
      (may_decide
        ? "Record a decision for each before the school can be promoted."
        : "The principal decides; nothing can be moved until every child has a decision.") +
      "</p>"
    : "";
  return [
    '<section class="state state-review" data-state="review">',
    `<div class="page-head"><div><h1>End-of-session promotion</h1><p>${esc(term)} &rarr; ${esc(to_term)}</p></div></div>`,
    yearSettings(settings),
    '<p class="hint">Whether each child is promoted, repeats, graduates or leaves is the principal\'s decision, recorded with a reason. ',
    "Choose where each class goes; the school is then moved as decided. Nothing moves until you confirm on the next step.</p>",
    waiting,
    `<form class="promotion${note ? " rejected" : ""}" data-form="review">`,
    classes
      .map((row) =>
        [
          `<section class="card class" data-class="${esc(row.class_group_id)}">`,
          `<div class="card-head"><h2>${esc(row.name)}</h2>${destinationSelect(row, targets)}</div>`,
          `<ul class="children">${row.children
            .map((child) => childRow(child, { mayDecide: may_decide, outcomes, graduate: row.graduate }))
            .join("")}</ul>`,
          may_decide ? decideRow(row) : "",
          "</section>",
        ].join(""),
      )
      .join(""),
    note ? `<p class="note" role="alert">${esc(note)}</p>` : "",
    classes.length
      ? '<button type="submit" class="btn primary">Review before confirming</button>'
      : "<p class=\"blank\">No class has any children placed this term.</p>",
    "</form>",
    "</section>",
  ].join("");
}

/** What confirming would do, in words, with the only button that writes. */
export function confirm({ summary = [], totals = {}, note = null } = {}) {
  return [
    '<section class="state state-confirm" data-state="confirm">',
    "<h1>Confirm promotion</h1>",
    `<p>${esc(totals.promoted)} promoted, ${esc(totals.repeated)} repeating, ${esc(totals.graduated)} graduating, ${esc(totals.left || 0)} leaving.`,
    " This moves every child at once, and the enrolment of a graduate or of a child who is leaving ends. It cannot be undone from here.</p>",
    '<ul class="summary">',
    summary
      .map(
        (row) =>
          `<li><strong>${esc(row.name)}</strong> &rarr; ${esc(row.to)}` +
          `${row.repeating ? ` <small>(${esc(row.repeating)} repeating)</small>` : ""}` +
          `${row.leaving ? ` <small>(${esc(row.leaving)} leaving)</small>` : ""}</li>`,
      )
      .join(""),
    "</ul>",
    `<form data-form="confirm"><input type="hidden" name="confirm" value="yes">`,
    '<button type="submit" class="btn primary">Confirm promotion</button> ',
    '<button type="button" class="btn" data-action="back">Go back</button>',
    note ? `<p class="note" role="alert">${esc(note)}</p>` : "",
    "</form>",
    "</section>",
  ].join("");
}

export function done({ promoted = 0, repeated = 0, graduated = 0, left = 0 } = {}) {
  return [
    '<section class="state state-done" data-state="done">',
    "<h1>Promotion done</h1>",
    `<p>${esc(promoted)} promoted, ${esc(repeated)} repeating, ${esc(graduated)} graduated, ${esc(left)} left. `,
    "Next session's first term now has its classes.</p>",
    "</section>",
  ].join("");
}

/** It is not the end of the session, or next session is not open yet. */
export function unavailable({ problem = "", settings = null } = {}) {
  return [
    '<section class="state state-unavailable" data-state="unavailable">',
    "<h1>Nothing to promote yet</h1>",
    `<p>${esc(problem)}</p>`,
    // The weighting is read when the third term is released, so it is set
    // before the end of the session and not only at it.
    yearSettings(settings),
    "</section>",
  ].join("");
}

export function notAllowed({ detail = "" } = {}) {
  return [
    '<section class="state state-not-allowed" data-state="not-allowed">',
    "<h1>You cannot promote children</h1>",
    `<p>${esc(detail) || "Promotion is done by a principal or an administrator of the school."}</p>`,
    "</section>",
  ].join("");
}

export function wrongHost() {
  return [
    '<section class="state state-wrong-host" data-state="wrong-host">',
    "<h1>Promotion lives on your school's own web address</h1>",
    "<p>This page is open on the sign-in site. Open it again from your ",
    "school's own address.</p>",
    "</section>",
  ].join("");
}

export function signedOut({ portal = "", expired = false } = {}) {
  return [
    '<section class="state state-signed-out" data-state="signed-out">',
    `<h1>${expired ? "Your session has ended" : "Please sign in"}</h1>`,
    expired
      ? "<p>You were signed out after a period of inactivity.</p>"
      : "<p>Sign in with your password to open promotion.</p>",
    portal
      ? `<p><a href="//${esc(portal)}/staff-sign-in/">Sign in again</a></p>`
      : "<p>Go back to the sign-in page you came from.</p>",
    "</section>",
  ].join("");
}

export function broken() {
  return [
    '<section class="state state-broken" data-state="broken">',
    "<h1>This page is not working</h1>",
    "<p>Something went wrong on our side. Please try again in a few minutes, ",
    "and tell whoever runs this system for your school.</p>",
    "</section>",
  ].join("");
}
