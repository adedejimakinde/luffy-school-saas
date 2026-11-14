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
 * **A figure over papers not all marked says so.** A subject with a paper
 * unmarked, and the average built on it, print as they are beside "incomplete",
 * and a child with any such subject has no position: "not ranked", which is not
 * last. The server decides which (`is_complete`); this page only says it.
 *
 * **Which figures these are is said on the page.** A released term is served
 * from the frozen cards and an unreleased one from live marks
 * (`from_snapshot`); a reader comparing two sheets needs to know which
 * question each answered.
 */

import { esc } from "../web/html.js";

const DASH = "-";

/** `value`, or a dash for null — and never a zero for nothing. */
export function figure(value) {
  return value === null || value === undefined || value === "" ? DASH : esc(value);
}

/** A score without a trailing ".00": "70.00" is "70", "72.50" is "72.5", "-" for none. */
export function score(value) {
  if (value === null || value === undefined || value === "") return DASH;
  const n = Number(value);
  return Number.isFinite(n) ? esc(String(Math.round(n * 100) / 100)) : esc(value);
}

/** 1 is "1st", 2 "2nd", 3 "3rd", 11 "11th"; a shared rank is "3=", as in the Pos. column. */
export function subjectPlace(rank, counts) {
  if (rank === null || rank === undefined) return "";
  if (counts.get(rank) > 1) return `${esc(rank)}=`;
  const n = Number(rank);
  const tail = n % 100 >= 11 && n % 100 <= 13 ? "th" : { 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th";
  return `${esc(rank)}${tail}`;
}

const SHORT = { mathematics: "Maths", "english language": "Eng.", english: "Eng." };

/** A header short enough for a 76px column; the full name rides in the title. */
export function shortSubject(name) {
  const full = String(name).trim();
  const known = SHORT[full.toLowerCase()];
  if (known) return known;
  const words = full.split(/\s+/);
  if (words.length === 1) return full.length <= 7 ? full : `${full.slice(0, 4)}.`;
  const [first, ...rest] = words;
  const head = first.length <= 6 ? first : `${first.slice(0, 4)}.`;
  const tail = rest.map((w) => (w.length <= 3 ? w : `${w.slice(0, 3)}.`)).join(" ");
  return `${head} ${tail}`;
}

/** First name on one line, the rest (surname) on the next, never cut off. */
export function nameCell(name) {
  const full = String(name).trim();
  const i = full.indexOf(" ");
  return i < 0 ? esc(full) : `${esc(full.slice(0, i))}<br>${esc(full.slice(i + 1))}`;
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

/**
 * Which figures these are. A neutral message carrying its label, the design's
 * one place for status colour (`docs/design.md`), rather than a tinted banner.
 */
export function banner(fromSnapshot) {
  return fromSnapshot
    ? '<div class="msg" data-figures="released"><span class="label label-ok">Released</span>' +
        "<p>These are the figures that went home, and they do not change.</p></div>"
    : '<div class="msg" data-figures="live"><span class="label label-warn">Not released</span>' +
        "<p>These are live marks, and they change as teachers mark.</p></div>";
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
          '<div class="scroll"><table class="overview stack">',
          "<thead><tr><th>Class</th><th>Class average (ranked students)</th>",
          "<th>Children ranked</th><th>Figures</th></tr></thead><tbody>",
          classes
            .map(
              (c) =>
                "<tr>" +
                `<td class="stack-head"><button type="button" data-action="open-class" data-class="${esc(c.class_group_id)}">` +
                `${esc(c.class_group)}</button></td>` +
                `<td class="num" data-label="Class average (ranked students)">${figure(c.class_average)}</td>` +
                `<td class="num" data-label="Children ranked">${esc(c.children_ranked)}</td>` +
                `<td data-label="Figures">${c.from_snapshot ? "Released" : "Live"}</td>` +
                "</tr>",
            )
            .join(""),
          "</tbody></table></div>",
        ].join("")
      : '<p class="blank">No class has anybody in it this term.</p>',
    "</section>",
  ].join("");
}

const INCOMPLETE = " <small>incomplete</small>";

/** A figure, with "incomplete" beside it when the server says it is over unmarked papers. */
function partial(value, isComplete) {
  const shown = figure(value);
  return value !== null && value !== undefined && value !== "" && isComplete === false
    ? shown + INCOMPLETE
    : shown;
}

/** The position cell: the rank, "not ranked" for a child with a subject unfinished, else a dash. */
function placing(row, counts) {
  if (row.is_complete === false) return '<span class="not-ranked" title="Not ranked" aria-label="Not ranked">-</span>';
  return rankLabel(row.current_rank, counts);
}

/** Rows in the server's rank order; the unranked (no marks, or not whole) last, by name. */
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
  const { class_group = "", term = "", class_average = null, from_snapshot = false, ranked = null, rows = [] } = body;
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
    rows.length && ranked !== null
      ? `<p class="ranked-count" data-ranked="${esc(ranked)}">${esc(ranked)} of ${esc(rows.length)} ranked.` +
        (rows.some((r) => r.is_complete === false)
          ? " A child with a paper not yet marked is not ranked."
          : "") +
        "</p>"
      : "",
    rows.length
      ? [
          // One of the three tables that scroll sideways on a phone: its
          // columns are the point. Position and name stay put.
          '<p class="swipe-cue">Swipe for more subjects</p>',
          '<div class="scroll wide"><table class="broadsheet">',
          '<thead><tr><th class="pos">Pos.</th><th class="name">Name</th>',
          subjects
            .map(([, name]) => `<th class="subj" tabindex="0" title="${esc(name)}" data-full="${esc(name)}">${esc(shortSubject(name))}</th>`)
            .join(""),
          '<th class="subj" tabindex="0" title="Average" data-full="Average">Avg.</th></tr></thead><tbody>',
          ordered(rows)
            .map((r) => {
              const cells = subjects.map(([id]) => {
                const s = r.subjects.find((x) => x.subject_id === id) || {};
                const second =
                  s.is_complete === false && s.percentage != null
                    ? "incomplete"
                    : subjectPlace(s.current_subject_rank, subjectCounts.get(id));
                return `<td class="num subj"><span class="sc">${score(s.percentage)}</span>${second ? `<small>${second}</small>` : ""}</td>`;
              });
              const avg = r.is_complete === false && r.average != null ? "incomplete" : "";
              return (
                "<tr>" +
                `<td class="rank pos">${placing(r, counts)}</td>` +
                `<td class="name">${nameCell(r.student)}</td>` +
                cells.join("") +
                `<td class="num subj"><span class="sc">${score(r.average)}</span>${avg ? `<small>${avg}</small>` : ""}</td>` +
                "</tr>"
              );
            })
            .join(""),
          "</tbody>",
          `<tfoot><tr><th class="name" colspan="2">Class average (ranked students)</th>` +
            `<td colspan="${subjects.length}"></td><td class="num subj"><span class="sc">${score(class_average)}</span></td></tr></tfoot>`,
          "</table></div>",
        ].join("")
      : '<p class="blank">Nobody in this class has a result this term.</p>',
    "</section>",
  ].join("");
}

export function noTerms() {
  return [
    '<section class="state state-no-terms" data-state="no-terms">',
    "<h1>No terms yet</h1>",
    "<p>Your school has not set up a term, so there is no broadsheet to read. ",
    "The school office sets terms up.</p>",
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
