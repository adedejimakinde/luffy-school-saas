/**
 * Every screen the broadsheet page can show, as a pure function of API bodies.
 *
 * **Every number is the server's.** The ranks are `current_rank` and
 * `current_subject_rank` as sent; this module sorts rows by them and marks a
 * shared rank with "=", and never counts rows to make a rank of its own — a
 * page that numbered rows 1, 2, 3 would print a tie as two different places.
 *
 * **No marks is "—", never 0.** A null average means the child has no marks,
 * and a zero would claim they sat every exam and scored nothing.
 *
 * **Which figures these are is said on the page.** A released term is served
 * from the frozen cards and an unreleased one from live marks
 * (`from_snapshot`); a reader comparing two sheets needs to know which
 * question each answered.
 */

import { esc } from "../web/html.js";
import { button as signOutButton } from "../web/signout.js";

const DASH = "—";

/** `value`, or a dash for null — and never a zero for nothing. */
export function figure(value) {
  return value === null || value === undefined || value === "" ? DASH : esc(value);
}

/** "1", or "1=" when another row on the page holds the same rank. */
export function rankLabel(rank, counts) {
  if (rank === null || rank === undefined) return DASH;
  return `${esc(rank)}${counts.get(rank) > 1 ? "=" : ""}`;
}

function countsOf(ranks) {
  const counts = new Map();
  for (const rank of ranks) {
    if (rank !== null && rank !== undefined) counts.set(rank, (counts.get(rank) || 0) + 1);
  }
  return counts;
}

export function banner(fromSnapshot) {
  return fromSnapshot
    ? '<p class="banner released" data-figures="released">Released: these are the ' +
        "figures that went home, and they do not change.</p>"
    : '<p class="banner live" data-figures="live">Not released: these are live ' +
        "marks, and they change as teachers mark.</p>";
}

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

/**
 * The school's classes for one term: the principal's view.
 *
 * **No names and no ranks.** It compares classes; whoever wants children
 * opens the class. Each row says whether its figures are released or live,
 * because a term part-way through release has both on one page.
 */
export function overview({ terms = [], overview: body = {} } = {}) {
  const { term_id: termId, term = "", classes = [] } = body;
  return [
    '<section class="state state-overview" data-state="overview">',
    "<h1>Broadsheets</h1>",
    `<form class="chooser">${termChooser(terms, termId)}</form>`,
    `<h2>${esc(term)}</h2>`,
    classes.length
      ? [
          '<div class="scroll"><table class="overview">',
          "<thead><tr><th>Class</th><th>Class average</th>",
          "<th>Children with an average</th><th>Figures</th></tr></thead><tbody>",
          classes
            .map(
              (c) =>
                "<tr>" +
                `<td><button type="button" data-action="open-class" data-class="${esc(c.class_group_id)}">` +
                `${esc(c.class_group)}</button></td>` +
                `<td class="num">${figure(c.class_average)}</td>` +
                `<td class="num">${esc(c.children_with_an_average)}</td>` +
                `<td>${c.from_snapshot ? "Released" : "Live"}</td>` +
                "</tr>",
            )
            .join(""),
          "</tbody></table></div>",
        ].join("")
      : '<p class="blank">No class has anybody in it this term.</p>',
    signOutButton(),
    "</section>",
  ].join("");
}

/** Rows in the server's rank order; the unranked (no marks) last, by name. */
export function ordered(rows) {
  return [...rows].sort((a, b) => {
    const ra = a.current_rank ?? Infinity;
    const rb = b.current_rank ?? Infinity;
    if (ra !== rb) return ra - rb;
    return String(a.student).localeCompare(String(b.student));
  });
}

/** One class's broadsheet. */
export function sheet({ broadsheet: body = {} } = {}) {
  const { class_group = "", term = "", class_average = null, from_snapshot = false, rows = [] } = body;
  const subjects = rows.length ? rows[0].subjects.map((s) => [s.subject_id, s.subject]) : [];
  const counts = countsOf(rows.map((r) => r.current_rank));
  const subjectCounts = new Map(
    subjects.map(([id]) => [
      id,
      countsOf(rows.map((r) => (r.subjects.find((s) => s.subject_id === id) || {}).current_subject_rank)),
    ]),
  );
  return [
    '<section class="state state-sheet" data-state="sheet">',
    '<p class="back"><button type="button" data-action="back">All classes</button></p>',
    `<h1>${esc(class_group)}</h1>`,
    `<p class="term">${esc(term)}</p>`,
    banner(from_snapshot),
    rows.length
      ? [
          '<div class="scroll"><table class="broadsheet">',
          "<thead><tr><th>Pos.</th><th>Name</th>",
          subjects.map(([, name]) => `<th>${esc(name)}</th>`).join(""),
          "<th>Average</th></tr></thead><tbody>",
          ordered(rows)
            .map((r) => {
              const cells = subjects.map(([id]) => {
                const s = r.subjects.find((x) => x.subject_id === id) || {};
                return (
                  `<td class="num">${figure(s.percentage)}` +
                  (s.current_subject_rank == null
                    ? ""
                    : ` <small>(${rankLabel(s.current_subject_rank, subjectCounts.get(id))})</small>`) +
                  "</td>"
                );
              });
              return (
                "<tr>" +
                `<td class="num rank">${rankLabel(r.current_rank, counts)}</td>` +
                `<td>${esc(r.student)}</td>` +
                cells.join("") +
                `<td class="num">${figure(r.average)}</td>` +
                "</tr>"
              );
            })
            .join(""),
          "</tbody>",
          `<tfoot><tr><th colspan="${subjects.length + 2}">Class average</th>` +
            `<td class="num">${figure(class_average)}</td></tr></tfoot>`,
          "</table></div>",
        ].join("")
      : '<p class="blank">Nobody in this class has a result this term.</p>',
    signOutButton(),
    "</section>",
  ].join("");
}

export function noTerms() {
  return [
    '<section class="state state-no-terms" data-state="no-terms">',
    "<h1>No terms yet</h1>",
    "<p>Your school has not set up a term, so there is no broadsheet to read. ",
    "The school office sets terms up.</p>",
    signOutButton(),
    "</section>",
  ].join("");
}

/**
 * Refused, or no such class or term. **One state for both**, because the
 * server gives one answer for both — see `api.js`.
 */
export function notYours() {
  return [
    '<section class="state state-not-yours" data-state="not-yours">',
    "<h1>This is not a broadsheet you can open</h1>",
    "<p>Broadsheets are read by teachers, the vice principal (academic), the ",
    "principal and the school's administrators. If that should include you, ",
    "whoever runs this system for your school can arrange it.</p>",
    signOutButton(),
    "</section>",
  ].join("");
}

export function wrongHost() {
  return [
    '<section class="state state-wrong-host" data-state="wrong-host">',
    "<h1>Broadsheets live on your school's own web address</h1>",
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
      : "<p>Sign in with your password to read broadsheets.</p>",
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
