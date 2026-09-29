/**
 * Every screen the promotion page can show, as a pure function of an API body.
 *
 * Three steps and one rule. The review lists every class with every child, each
 * defaulting to "promote". "Review" moves nothing; it shows what confirming
 * would do, and only the second button, on the summary, writes, moving every
 * child or none.
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

function childRow(child) {
  const promote = child.action !== "repeat" && child.action !== "leave";
  return [
    '<li class="child">',
    `<span class="who">${esc(child.name)}${child.reference ? ` <small>${esc(child.reference)}</small>` : ""}</span>`,
    `<select name="child_${esc(child.membership_id)}" aria-label="${esc(child.name)}">`,
    `<option value="promote"${promote ? " selected" : ""}>Promote</option>`,
    `<option value="repeat"${child.action === "repeat" ? " selected" : ""}>Repeat</option>`,
    `<option value="leave"${child.action === "leave" ? " selected" : ""}>Leaving</option>`,
    "</select>",
    "</li>",
  ].join("");
}

export function review({ term = "", to_term = "", classes = [], targets = [], problem = null, note = null } = {}) {
  if (problem) return unavailable({ problem });
  return [
    '<section class="state state-review" data-state="review">',
    `<div class="page-head"><div><h1>End-of-session promotion</h1><p>${esc(term)} &rarr; ${esc(to_term)}</p></div></div>`,
    "<p class=\"hint\">Choose where each class goes and, for each child, whether they are promoted, repeat or are leaving the school. ",
    "Nothing moves until you confirm on the next step.</p>",
    `<form class="promotion${note ? " rejected" : ""}" data-form="review">`,
    classes
      .map((row) =>
        [
          `<section class="card class" data-class="${esc(row.class_group_id)}">`,
          `<div class="card-head"><h2>${esc(row.name)}</h2>${destinationSelect(row, targets)}</div>`,
          `<ul class="children">${row.children.map(childRow).join("")}</ul>`,
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
export function unavailable({ problem = "" } = {}) {
  return [
    '<section class="state state-unavailable" data-state="unavailable">',
    "<h1>Nothing to promote yet</h1>",
    `<p>${esc(problem)}</p>`,
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
