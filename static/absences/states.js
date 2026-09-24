/**
 * Every screen the absence page can show, as a pure function of API bodies.
 *
 * **Every number is the server's**, and so is the order. The route sends the
 * children worst first and this module draws them in the order they came; it
 * works out no rate of its own, because a rate rounded twice is a rate that can
 * disagree with the one the list was drawn by.
 *
 * **"Nobody is on the list" is two sentences.** A term in which registers were
 * taken and nobody crossed the line is a finding. A term in which no register
 * was taken is the absence of one, and saying "nobody is absent too often"
 * then would be telling a principal something nobody has looked at.
 */

import { esc } from "../web/html.js";
import { button as signOutButton } from "../web/signout.js";

function termChooser(terms, termId) {
  return [
    '<label for="term">Term</label>',
    '<select id="term" data-term>',
    terms
      .map(
        (t) =>
          `<option value="${esc(t.term_id)}"${String(t.term_id) === String(termId) ? " selected" : ""}>` +
          `${esc(t.term)}${t.is_current ? " (current)" : ""}</option>`,
      )
      .join(""),
    "</select>",
  ].join("");
}

/** What the list was drawn by, in the words the school chose it in. */
export function rule({ threshold_percent: percent, min_marked_days: days }) {
  return (
    `Absent on at least ${esc(percent)}% of the days marked, ` +
    `once ${esc(days)} ${days === 1 ? "day has" : "days have"} been marked.`
  );
}

function thresholdForm(body, note) {
  if (!body.may_change_threshold) return "";
  return [
    '<form class="threshold" data-threshold>',
    "<fieldset><legend>Change what counts as too often</legend>",
    '<label>Absent on at least <input type="number" name="threshold_percent" min="1" max="100" ',
    `value="${esc(body.threshold_percent)}" required>% of the days marked</label>`,
    '<label>once <input type="number" name="min_marked_days" min="1" max="365" ',
    `value="${esc(body.min_marked_days)}" required> days have been marked</label>`,
    '<button type="submit">Save</button>',
    "</fieldset>",
    note ? `<p class="note" role="status">${esc(note)}</p>` : "",
    "</form>",
  ].join("");
}

function table(children) {
  return [
    '<div class="scroll"><table class="absences">',
    "<thead><tr><th>Name</th><th>Class</th>",
    '<th class="num">Days absent</th><th class="num">Days marked</th>',
    '<th class="num">Absent</th></tr></thead><tbody>',
    children
      .map(
        (c) =>
          "<tr>" +
          `<td>${esc(c.student)}</td>` +
          `<td>${esc(c.class_group)}</td>` +
          `<td class="num">${esc(c.absent)}</td>` +
          `<td class="num">${esc(c.marked)}</td>` +
          `<td class="num">${esc(c.rate)}%</td>` +
          "</tr>",
      )
      .join(""),
    "</tbody></table></div>",
  ].join("");
}

/** Why the list is empty — which is never "because nobody looked". */
export function emptyReason(body) {
  if (!body.registers_taken) {
    return (
      '<p class="blank" data-empty="no-registers">No register has been taken this term, ' +
      "so nobody can be on this list yet.</p>"
    );
  }
  return (
    '<p class="blank" data-empty="nobody">Nobody is absent that often this term.</p>'
  );
}

export function list({ absences: body = {}, note = "" } = {}) {
  const { terms = [], term_id: termId = null, term = "", children = [] } = body;
  return [
    '<section class="state state-list" data-state="list">',
    "<h1>Absent too often</h1>",
    `<form class="chooser">${termChooser(terms, termId)}</form>`,
    `<h2>${esc(term)}</h2>`,
    `<p class="rule">${rule(body)} A day with no register counts for nothing.</p>`,
    children.length ? table(children) : emptyReason(body),
    thresholdForm(body, note),
    signOutButton(),
    "</section>",
  ].join("");
}

/** No term to show: none set up, or none marked current and none chosen. */
export function noTerm({ absences: body = {} } = {}) {
  const { terms = [] } = body;
  return [
    '<section class="state state-no-term" data-state="no-term">',
    "<h1>Absent too often</h1>",
    terms.length
      ? `<p>No term is marked current. Choose one:</p><form class="chooser">${termChooser(terms, null)}</form>`
      : "<p>Your school has not set up a term, so there is nothing to count yet. " +
        "The school office sets terms up.</p>",
    signOutButton(),
    "</section>",
  ].join("");
}

/**
 * Refused, or no such term. **One state for both**, because the server gives
 * one answer for both — see `api.js`.
 */
export function notYours() {
  return [
    '<section class="state state-not-yours" data-state="not-yours">',
    "<h1>This is not a list you can open</h1>",
    "<p>This list is read by the principal, the vice principal (academic) and ",
    "the school's administrators. If that should include you, whoever runs ",
    "this system for your school can arrange it.</p>",
    signOutButton(),
    "</section>",
  ].join("");
}

export function wrongHost() {
  return [
    '<section class="state state-wrong-host" data-state="wrong-host">',
    "<h1>This list lives on your school's own web address</h1>",
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
      : "<p>Sign in with your password to read this list.</p>",
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
