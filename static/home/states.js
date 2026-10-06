/**
 * Every screen the principal's home can show, as a pure function of an API body.
 *
 * Strings rather than DOM, for `card/states.js`' reason: every branch can be
 * asserted in `node --test` with no browser.
 *
 * **Nothing here acts.** Each "Waiting for you" row is a link to the screen
 * that does the work: a release is taken on the results page, behind the
 * question it asks there, and never with one tap from here.
 */

import { naira } from "../fees/money.js";
import { esc } from "../web/html.js";

/** Nothing to show: data, not a sentence (`docs/design.md`). */
const DASH = "—";

const UNITS = [
  [100_000_000_000n, "bn"],
  [100_000_000n, "m"],
  [100_000n, "k"],
];

/**
 * "₦18.4m" for 1,840,000,000 kobo: a stat card's figure, short enough never to
 * wrap. Rounded on purpose and in whole integers, never a float; the exact
 * figure is `naira()`'s, and rides along in the card's `title`.
 */
export function shortNaira(kobo) {
  const k = BigInt(kobo < 0 ? -kobo : kobo);
  for (let i = 0; i < UNITS.length; i++) {
    const [unit, suffix] = UNITS[i];
    if (k < unit) continue;
    // Tenths of the unit, rounded half up; one decimal below 100 of it.
    const tenths = (k * 10n + unit / 2n) / unit;
    const whole = tenths / 10n;
    const tenth = tenths % 10n;
    // 999.96k rounds to a thousand of them, which is the next unit up.
    if (whole >= 1000n && i > 0) return `₦1${UNITS[i - 1][1]}`;
    return `₦${whole}${tenth && whole < 100n ? `.${tenth}` : ""}${suffix}`;
  }
  const whole = (k + 50n) / 100n;
  return whole >= 1000n ? "₦1k" : `₦${whole}`;
}

function percent(part, whole) {
  if (!whole) return 0;
  return Math.round((part * 100) / whole);
}

export function home(body) {
  const { school = "", term = null } = body;
  return [
    '<section class="state state-home" data-state="home">',
    contactEmailBanner(body),
    '<div class="page-head"><div>',
    "<h1>Home</h1>",
    `<p>${esc(school)}${term ? ` &middot; ${esc(term)}` : ""}</p>`,
    "</div></div>",
    '<section class="stats" aria-label="This term">',
    releasedCard(body.released),
    presentCard(body.present),
    feesCard(body.fees),
    absentCard(body.absent),
    "</section>",
    '<div class="split">',
    waiting(body.waiting || []),
    today(body.happened, body.today),
    "</div>",
    "</section>",
  ].join("");
}

/**
 * Until the school sets a contact email, every email sent for it goes out with
 * no `Reply-To` (`docs/messaging.md` D17). The server decides whether this
 * login should be asked (`needs_contact_email`); the page only draws it.
 */
function contactEmailBanner({ needs_contact_email: needed = false }) {
  if (!needed) return "";
  return [
    '<p class="banner" role="note" data-banner="contact-email">',
    "Add your school's contact email so parents' replies reach you. ",
    '<a href="/setup/#contact-email">Add it now</a>',
    "</p>",
  ].join("");
}

function stat(name, value, middle, foot, extra = "") {
  return [
    `<div class="card stat"${extra}>`,
    `<span class="stat-name">${name}</span>`,
    `<span class="stat-value">${value}</span>`,
    middle,
    `<span class="stat-foot">${foot}</span>`,
    "</div>",
  ].join("");
}

function bar(pct) {
  return `<div class="progress"><span style="width: ${pct}%"></span></div>`;
}

const NO_TERM = "No term is open";

function releasedCard(released) {
  if (!released) return stat("Results released", DASH, "", NO_TERM);
  const { released: n, classes } = released;
  const left = classes - n;
  return stat(
    "Results released",
    `${n} <small>of ${classes}</small>`,
    bar(percent(n, classes)),
    left ? `${left} ${left === 1 ? "class" : "classes"} still to go` : "Every class released",
  );
}

function presentCard(present) {
  const { today: day, week = [] } = present;
  const bars = week.length
    ? `<div class="minibars" aria-label="This week">${week
        .map(
          (d) =>
            `<span${d.on === day.on ? ' class="today"' : ""} style="height: ${percent(d.present, d.marked)}%"></span>`,
        )
        .join("")}</div>`
    : "";
  if (!day.marked) return stat("Present today", DASH, bars, "No register taken yet today");
  return stat(
    "Present today",
    `${percent(day.present, day.marked)}%`,
    bars,
    `${day.present} of ${day.marked} marked present`,
  );
}

function feesCard(fees) {
  if (!fees) return stat("Fees collected", DASH, "", NO_TERM);
  const { collected_kobo: collected, billed_kobo: billed } = fees;
  const exact = ` title="${esc(naira(collected))} of ${esc(naira(billed))}"`;
  return stat(
    "Fees collected",
    shortNaira(collected),
    bar(Math.min(100, percent(collected, billed))),
    billed ? `of ${shortNaira(billed)} billed` : "Nothing billed this term yet",
    exact,
  );
}

function absentCard(absent) {
  if (!absent) return stat("Absent too often", DASH, "", NO_TERM);
  const { children: n, threshold_percent: threshold } = absent;
  return stat(
    "Absent too often",
    `${n} <small>${n === 1 ? "pupil" : "pupils"}</small>`,
    n
      ? '<span><span class="label label-stop">Needs a look</span></span>'
      : '<span><span class="label label-ok">None</span></span>',
    `Absent on ${threshold}% or more of marked days`,
  );
}

/**
 * What each kind of row says, what its button reads, and whether the button is
 * the primary one. The link itself is the server's (`WaitingOut.href`).
 */
const KINDS = {
  release: { what: "Approved", label: ["label-ok", "Ready"], button: "Release", primary: true },
  approve: { what: "Checked, needs your approval", button: "Open" },
  check: { what: "Submitted, needs checking", button: "Open" },
  remarks: { what: "Remarks missing", button: "Open" },
  sent_back: { what: "Sent back by you", button: "Open" },
};

function whatFor(row) {
  const kind = KINDS[row.kind] || { what: "", button: "Open" };
  let label = "";
  if (row.kind === "remarks" && row.missing) {
    label = ` <span class="label label-warn">${row.missing} ${row.missing === 1 ? "pupil" : "pupils"}</span>`;
  } else if (kind.label) {
    label = ` <span class="label ${kind.label[0]}">${kind.label[1]}</span>`;
  }
  return { ...kind, html: `${esc(kind.what)}${label}` };
}

/** "2 days", with its unit, in the table and in the phone's stacked rows alike. */
function days(n) {
  if (n === null || n === undefined) return DASH;
  return `${n} ${n === 1 ? "day" : "days"}`;
}

export function waiting(rows) {
  const head = `<div class="card-head"><h2>Waiting for you</h2><span class="label">${rows.length}</span></div>`;
  if (!rows.length) {
    return [
      '<section class="card waiting-card">',
      head,
      '<div class="empty">',
      '<svg class="icon"><use href="#i-inbox"/></svg>',
      "<h2>Nothing waiting</h2>",
      "<p>When a class is ready for you, it appears here.</p>",
      '<a class="btn" href="/results/">Open results</a>',
      "</div>",
      "</section>",
    ].join("");
  }
  return [
    '<section class="card waiting-card">',
    head,
    '<div class="waiting-wrap">',
    '<table class="waiting">',
    '<thead><tr><th>Class</th><th>What</th><th class="num">Waiting</th><th><span class="sr">Action</span></th></tr></thead>',
    "<tbody>",
    rows
      .map((row) => {
        const what = whatFor(row);
        return [
          `<tr data-kind="${esc(row.kind)}">`,
          `<td class="class">${esc(row.class_group)}</td>`,
          `<td class="what">${what.html}</td>`,
          `<td class="num days">${days(row.days)}</td>`,
          `<td class="act"><a class="btn row-btn${what.primary ? " primary" : ""}" href="${esc(row.href)}">`,
          `<span>${what.button}</span><span class="sr"> ${esc(row.class_group)}</span></a></td>`,
          "</tr>",
        ].join("");
      })
      .join(""),
    "</tbody></table></div>",
    "</section>",
  ].join("");
}

const WEEKDAYS = new Set([1, 2, 3, 4, 5]);

function isWeekday(iso) {
  // A date with no time, read as that calendar day wherever the browser is.
  return WEEKDAYS.has(new Date(`${iso}T12:00:00Z`).getUTCDay());
}

export function today(happened, on) {
  const { registers = 0, classes = 0, payments = 0, steps = [] } = happened || {};
  const items = [];
  if (registers || (on && isWeekday(on))) {
    const left = Math.max(0, classes - registers);
    items.push([
      "",
      `Registers: ${registers} of ${classes} ${classes === 1 ? "class" : "classes"} taken` +
        (left ? ` <span class="label label-warn">${left} left</span>` : ""),
    ]);
  }
  items.push([
    "",
    payments
      ? `${payments} ${payments === 1 ? "payment" : "payments"} recorded`
      : "No payments recorded yet",
  ]);
  for (const step of steps) items.push([esc(step.at), esc(step.text)]);
  return [
    '<section class="card today-card">',
    "<h2>Today</h2>",
    '<ul class="today-list">',
    // No time, no <time>: an empty one still holds its column and indents the row.
    items.map(([at, text]) => `<li>${at ? `<time>${at}</time>` : ""}<span>${text}</span></li>`).join(""),
    "</ul>",
    "</section>",
  ].join("");
}

/** Signed in, and not the principal or the vice principal. */
export function notYours({ detail = "" } = {}) {
  return [
    '<section class="state state-not-yours" data-state="not-yours">',
    "<h1>This page is not yours</h1>",
    `<p>${esc(detail) || "This page is the principal's and the vice principal's."}</p>`,
    "</section>",
  ].join("");
}

/** This host is not a school's, so there are no figures behind this URL. */
export function wrongHost() {
  return [
    '<section class="state state-wrong-host" data-state="wrong-host">',
    "<h1>Your home page lives on your school's own web address</h1>",
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
      ? "<p>You were signed out after a period of inactivity.</p>"
      : "<p>Sign in with your password to see your school's home page.</p>",
    portal
      ? `<p><a href="//${esc(portal)}/staff-sign-in/">Sign in again</a></p>`
      : "<p>Go back to the sign-in page you came from.</p>",
    "</section>",
  ].join("");
}

/** Anything the page cannot explain: a 500, a dead transport, an unreadable body. */
export function broken() {
  return [
    '<section class="state state-broken" data-state="broken">',
    "<h1>This page is not working</h1>",
    "<p>Something went wrong on our side. Please try again in a few minutes, ",
    "and tell your school if it keeps happening.</p>",
    "</section>",
  ].join("");
}
