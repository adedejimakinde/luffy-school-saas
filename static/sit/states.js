/**
 * Every screen of `/sit/`, as a pure function of what the school sent and what the
 * student has done. `docs/cbt.md`, step 4, and the approved design of the exam screen.
 *
 * Strings rather than DOM, for `checker/states.js`' reason: `node --test` asserts each
 * one with no browser. Every value a teacher or a student typed goes through `esc()`: a
 * question is plain text, drawn as text, never as markup.
 *
 * **There is no answer key to draw.** The paper the school sends carries none
 * (`cbt.paper.for_device()`), and nothing here says which option is right.
 *
 * One exam screen for every width: two columns on a computer or a tablet (the question
 * card on the left; the number grid, the summary and the keyboard hints on the right), and
 * on a phone a compact top bar, a strip of question numbers, the question, and a bar
 * fixed at the foot with Previous, Calculator and Next. `sit.css` makes the change.
 */

import { esc } from "../web/html.js";
import { KEYS } from "./calculator.js";
import { formatLeft, WARN_MS } from "./clock.js";

export const LETTERS = "ABCDE";

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const lines = (text) => esc(text).replace(/\n/g, "<br>");
const icon = (name) => `<svg class="icon" aria-hidden="true"><use href="#${name}"/></svg>`;

/** The school's crest, or its initials in a tile of its colour. */
function crest(school) {
  if (!school || !school.name) return "";
  return `<span class="crest" aria-hidden="true">${
    school.crest ? `<img src="${esc(school.crest)}" alt="" width="40" height="40">` : esc(school.initials || "")
  }</span>`;
}

function noteOf(detail, kind = "stop") {
  return detail ? `<p class="sit-note sit-note-${kind}" role="alert">${esc(detail)}</p>` : "";
}

// -- the door -------------------------------------------------------------------------

/**
 * The door: the code on the board, the admission number and the PIN on the slip.
 *
 * The PIN box is always drawn empty and the other two are kept, as the checker does:
 * a PIN left in a box on a lab computer is a PIN the next student can read.
 */
export function door({ school = {}, code = "", number = "", detail = "", fragile = false } = {}) {
  return [
    '<section class="sit-door state" data-state="door">',
    `<div class="sit-door-head">${crest(school)}<p class="sit-school">${esc(school.name || "")}</p></div>`,
    "<h1>Sit a test</h1>",
    "<p>Type the test code your teacher gives you, and your admission number and exam PIN from your exam slip.</p>",
    noteOf(detail),
    fragile
      ? '<p class="sit-note sit-note-warn" role="note">This browser may not keep your answers if the power goes off. Use Chrome if this computer has it.</p>'
      : "",
    '<form class="sit-form" data-form="door" novalidate>',
    '<label for="code">Test code</label>',
    `<input id="code" name="code" autocomplete="off" autocapitalize="characters" spellcheck="false" maxlength="12" value="${esc(code)}" required>`,
    '<label for="number">Admission number</label>',
    `<input id="number" name="number" autocomplete="off" autocapitalize="characters" spellcheck="false" value="${esc(number)}" required>`,
    '<label for="pin">Exam PIN</label>',
    '<input id="pin" name="pin" inputmode="numeric" autocomplete="off" spellcheck="false" placeholder="1234 5678" required>',
    '<button type="submit" class="submit">Continue</button>',
    "</form>",
    '<p class="sit-small">Your teacher is watching the room. This page does not lock your computer.</p>',
    "</section>",
  ].join("");
}

/** "Is this you?", before the clock starts. */
export function confirm({ school = {}, who, test, resuming = false, minutesLeft = null, busy = false, detail = "" }) {
  const facts = [
    ["Name", who.name],
    ["Class", who.class_name],
    ["Admission number", who.admission_number],
  ];
  const about = resuming
    ? `You have started this test already. Your answers are kept and about ${plural(minutesLeft || 0, "minute is", "minutes are")} left.`
    : `${plural(test.questions, "question", "questions")}, ${plural(test.duration, "minute", "minutes")}. The clock starts when you press Start.`;
  return [
    '<section class="sit-door state" data-state="confirm">',
    `<div class="sit-door-head">${crest(school)}<p class="sit-school">${esc(school.name || "")}</p></div>`,
    "<h1>Is this you?</h1>",
    `<dl class="sit-who">${facts.map(([k, v]) => `<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>`,
    `<p><strong>${esc(test.title)}</strong></p>`,
    `<p>${esc(about)}</p>`,
    noteOf(detail),
    '<div class="sit-actions">',
    `<button type="button" class="submit" data-action="start"${busy ? " disabled" : ""}>${resuming ? "Carry on" : "Start the test"}</button>`,
    '<button type="button" class="btn" data-action="not-me">This is not me</button>',
    "</div>",
    "</section>",
  ].join("");
}

// -- the exam screen ----------------------------------------------------------------

/** One numbered tile: answered, not answered, flagged, current. */
function tile(n, { answered, flagged, current, disabled }) {
  const said = [`Question ${n}`, answered ? "answered" : "not answered", flagged ? "flagged for review" : "", current ? "the one shown" : ""]
    .filter(Boolean)
    .join(", ");
  const cls = ["tile", answered ? "answered" : "", flagged ? "flagged" : "", current ? "current" : ""].filter(Boolean).join(" ");
  return `<button type="button" class="${cls}" data-action="go" data-index="${n - 1}" aria-label="${esc(said)}"${current ? ' aria-current="true"' : ""}${disabled ? " disabled" : ""}>${n}</button>`;
}

function tiles(view) {
  return view.items
    .map((item, i) =>
      tile(i + 1, {
        answered: view.answers[String(item.id)] !== undefined && view.answers[String(item.id)] !== null,
        flagged: view.flags.includes(item.id),
        current: i === view.current,
        disabled: !view.canGoBack && i < view.current,
      }),
    )
    .join("");
}

export function legend() {
  return [
    '<p class="sit-legend">',
    '<span><i class="key answered" aria-hidden="true"></i>Answered</span>',
    '<span><i class="key" aria-hidden="true"></i>Not answered</span>',
    '<span><i class="key flagged" aria-hidden="true"></i>Flagged</span>',
    '<span><i class="key current" aria-hidden="true"></i>This question</span>',
    "</p>",
  ].join("");
}

/** The countdown: navy, tabular, amber under five minutes. */
export function timer(leftMs, { compact = false } = {}) {
  const warn = leftMs <= WARN_MS;
  return `<p class="sit-timer${warn ? " warn" : ""}${compact ? " compact" : ""}" data-timer><span class="sit-timer-label">Time left</span> <span class="sit-timer-value" data-timer-value>${formatLeft(leftMs)}</span></p>`;
}

function topBar(view) {
  const { student, title, school } = view;
  return [
    '<header class="sit-top">',
    '<div class="sit-top-in">',
    `<div class="sit-brand">${crest(school)}<div class="sit-brand-words"><p class="sit-test">${esc(title)}</p><p class="sit-school">${esc(school.name || "")}</p></div></div>`,
    timer(view.leftMs),
    `<div class="sit-student"><p class="sit-student-name">${esc(student.name)}</p><p class="sit-student-meta"><span>${esc(student.admission_number)}</span><span class="sit-class">${esc(student.class_name)}</span></p></div>`,
    "</div>",
    "</header>",
  ].join("");
}

function banners(view) {
  const out = [];
  if (!view.online) {
    out.push(
      `<p class="sit-banner sit-banner-offline" role="status">${icon("i-sit-offline")}<span>You're offline. Your answers are saved on this device and will send when you reconnect.</span></p>`,
    );
  }
  if (view.leftMs <= WARN_MS && view.leftMs > 0) {
    out.push('<p class="sit-banner sit-banner-warn" role="status">Less than 5 minutes left. Your answers submit by themselves at 00:00.</p>');
  }
  if (view.leftWarning) {
    out.push(
      '<p class="sit-banner sit-banner-left" role="alert"><span>You left the test&#39;s page. This has been recorded.</span><button type="button" class="btn" data-action="dismiss-left">OK</button></p>',
    );
  }
  return out.join("");
}

function question(view) {
  const item = view.items[view.current];
  const chosen = view.answers[String(item.id)];
  const flagged = view.flags.includes(item.id);
  const n = view.current + 1;
  const total = view.items.length;
  const saved = chosen === undefined || chosen === null
    ? '<p class="sit-saved sit-saved-none" data-saved>Not answered yet</p>'
    : `<p class="sit-saved" data-saved role="status">${icon("i-sit-check")}Answer saved</p>`;
  return [
    `<section class="card sit-question" aria-labelledby="stem-${esc(item.id)}">`,
    '<div class="sit-question-head">',
    `<p class="sit-count">Question ${n} of ${total}</p>`,
    `<button type="button" class="sit-flag${flagged ? " on" : ""}" data-action="flag" aria-pressed="${flagged ? "true" : "false"}">${flagged ? "Flagged for review" : "Flag for review"}</button>`,
    "</div>",
    `<p class="sit-stem" id="stem-${esc(item.id)}">${lines(item.stem)}</p>`,
    item.image ? `<img class="sit-picture" src="${esc(item.image)}" alt="${esc(item.image_alt || "")}">` : "",
    `<div class="sit-options" role="radiogroup" aria-labelledby="stem-${esc(item.id)}">`,
    item.options
      .map((o, i) => {
        const on = chosen === o.index;
        return `<button type="button" class="sit-option${on ? " chosen" : ""}" role="radio" aria-checked="${on ? "true" : "false"}" data-action="choose" data-option="${esc(o.index)}" data-key="${LETTERS[i]}"${view.closed ? " disabled" : ""}><span class="sit-letter" aria-hidden="true">${LETTERS[i]}</span><span class="sit-option-text"><span class="sr">Option ${LETTERS[i]}: </span>${esc(o.text)}</span></button>`;
      })
      .join(""),
    "</div>",
    '<div class="sit-question-foot">',
    `<button type="button" class="btn sit-prev" data-action="prev"${view.current === 0 || !view.canGoBack ? " disabled" : ""}>${icon("i-sit-prev")}Previous</button>`,
    saved,
    `<button type="button" class="btn btn-primary sit-next" data-action="next"${view.current === total - 1 ? " disabled" : ""}>Next${icon("i-sit-next")}</button>`,
    "</div>",
    "</section>",
  ].join("");
}

function summary(view) {
  const answered = view.items.filter((i) => view.answers[String(i.id)] !== undefined && view.answers[String(i.id)] !== null).length;
  return [
    '<section class="card sit-summary" aria-label="Your progress">',
    `<p class="sit-progress"><span>Answered <strong>${answered}</strong> of ${view.items.length}</span><span>Flagged <strong>${view.flags.length}</strong></span></p>`,
    view.calculator ? `<button type="button" class="btn sit-calc-open" data-action="calculator" aria-expanded="${view.calcOpen ? "true" : "false"}">${icon("i-sit-calc")}Calculator</button>` : "",
    '<button type="button" class="btn btn-primary sit-submit" data-action="ask-submit">Submit test</button>',
    "</section>",
  ].join("");
}

function keyHints() {
  return [
    '<section class="sit-keys" aria-label="Keyboard shortcuts">',
    '<p><span class="kbd">A</span><span class="kbd">B</span><span class="kbd">C</span><span class="kbd">D</span> choose</p>',
    '<p><span class="kbd">N</span> next</p>',
    '<p><span class="kbd">P</span> previous</p>',
    '<p><span class="kbd">F</span> flag</p>',
    "</section>",
  ].join("");
}

export function calculator(calc) {
  return [
    '<section class="card sit-calc" role="dialog" aria-label="Calculator" data-calculator>',
    '<div class="sit-calc-head"><p class="sit-calc-title">Calculator</p><button type="button" class="btn btn-quiet" data-action="calculator">Close</button></div>',
    `<output class="sit-calc-shown" aria-live="polite">${esc(calc.shown)}</output>`,
    '<div class="sit-calc-keys">',
    KEYS.flat()
      .map(([label, key, said]) => `<button type="button" class="sit-calc-key${key === "=" ? " eq" : ""}${key === "0" ? " zero" : ""}" data-action="calc" data-calc="${esc(key)}"${said ? ` aria-label="${esc(said)}"` : ""}>${esc(label)}</button>`)
      .join(""),
    "</div>",
    "</section>",
  ].join("");
}

/** "You have 3 unanswered and 2 flagged questions. Submit anyway?" */
export function submitQuestion(view) {
  const unanswered = view.items.filter((i) => view.answers[String(i.id)] === undefined || view.answers[String(i.id)] === null).length;
  const flagged = view.flags.length;
  let ask = "Submit your test? You cannot change your answers after.";
  if (unanswered || flagged) {
    const parts = [];
    if (unanswered) parts.push(`${unanswered} unanswered`);
    if (flagged) parts.push(`${flagged} flagged`);
    ask = `You have ${parts.join(" and ")} question${unanswered + flagged === 1 && parts.length === 1 ? "" : "s"}. Submit anyway?`;
  }
  return [
    '<div class="sit-dialog-back">',
    '<section class="card sit-dialog" role="alertdialog" aria-modal="true" aria-labelledby="submit-ask">',
    `<p id="submit-ask" class="sit-dialog-ask">${esc(ask)}</p>`,
    '<div class="sit-actions">',
    '<button type="button" class="btn btn-primary" data-action="submit">Submit</button>',
    '<button type="button" class="btn" data-action="keep">Go back to the test</button>',
    "</div>",
    "</section>",
    "</div>",
  ].join("");
}

/**
 * The exam screen. `view` is:
 * `{ school, title, student, items, answers, flags, current, leftMs, online, calculator,
 *    calcOpen, calc, canGoBack, grid, asking, leftWarning, closed, timeUp }`.
 */
export function exam(view) {
  const grid = view.grid
    ? `<section class="card sit-grid-card" aria-label="Questions"><p class="sit-grid-title">Questions</p><div class="sit-grid">${tiles(view)}</div>${legend()}</section>`
    : "";
  return [
    `<div class="sit-exam" data-state="exam">`,
    topBar(view),
    `<div class="sit-banners">${banners(view)}</div>`,
    view.timeUp
      ? '<p class="sit-banner sit-banner-warn" role="alert">Time is up. Your answers are being sent to the school.</p>'
      : "",
    view.grid ? `<nav class="sit-strip" aria-label="Questions">${tiles(view)}</nav>` : "",
    '<div class="sit-body">',
    `<main class="sit-main">${question(view)}</main>`,
    `<aside class="sit-side">${grid}${summary(view)}${view.calcOpen ? calculator(view.calc) : ""}${keyHints()}</aside>`,
    "</div>",
    '<nav class="sit-bar" aria-label="Move between questions">',
    `<button type="button" class="btn" data-action="prev"${view.current === 0 || !view.canGoBack ? " disabled" : ""}>${icon("i-sit-prev")}Prev</button>`,
    view.calculator ? `<button type="button" class="btn" data-action="calculator" aria-expanded="${view.calcOpen ? "true" : "false"}">${icon("i-sit-calc")}Calculator</button>` : "",
    `<button type="button" class="btn btn-primary" data-action="next"${view.current === view.items.length - 1 ? " disabled" : ""}>Next${icon("i-sit-next")}</button>`,
    "</nav>",
    view.asking ? submitQuestion(view) : "",
    "</div>",
  ].join("");
}

// -- after ---------------------------------------------------------------------------

function when(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

/**
 * Submitted. **No score**: `docs/cbt.md` keeps scores until the teacher releases them
 * (step 5), so the screen says when the student will see it.
 */
export function finished({ school = {}, name = "", title = "", submittedAt = null, answered = 0, questions = 0, received = null, byClock = false, minutes = null }) {
  const first = String(name || "").split(" ")[0];
  const facts = [
    ["Submitted", when(submittedAt)],
    ["Answered", `${answered} of ${questions}`],
    ["Received by the school", received === null ? "Waiting to send" : received === answered ? `All ${received}` : `${received} of ${answered}`],
  ];
  if (minutes !== null) facts.push(["Time used", plural(minutes, "minute", "minutes")]);
  return [
    '<section class="sit-door sit-done state" data-state="finished">',
    `<div class="sit-door-head">${crest(school)}<p class="sit-school">${esc(school.name || "")}</p></div>`,
    `<span class="sit-done-mark">${icon("i-sit-check")}</span>`,
    `<h1>${byClock ? "Time is up. Your test is in." : "Submitted."} Well done${first ? `, ${esc(first)}` : ""}.</h1>`,
    `<p class="sit-small">${esc(title)}</p>`,
    `<dl class="sit-who">${facts.map(([k, v]) => `<div><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>`,
    "<p>Your score will show when your teacher releases it. Your parents see it then too.</p>",
    '<p class="sit-small">Nothing about this test is left on this computer.</p>',
    '<button type="button" class="submit" data-action="done">Done</button>',
    "</section>",
  ].join("");
}

/** The time ran out while the device could not reach the school. */
export function waitingToSend({ school = {} } = {}) {
  return [
    '<section class="sit-door state" data-state="waiting">',
    `<div class="sit-door-head">${crest(school)}<p class="sit-school">${esc(school.name || "")}</p></div>`,
    "<h1>Time is up</h1>",
    "<p>Your answers are saved on this computer and will send when it reconnects. Do not close this page, and tell your teacher.</p>",
    "</section>",
  ].join("");
}

export function replaced({ school = {} } = {}) {
  return [
    '<section class="sit-door state" data-state="replaced">',
    `<div class="sit-door-head">${crest(school)}<p class="sit-school">${esc(school.name || "")}</p></div>`,
    "<h1>This test is open on another computer</h1>",
    "<p>Somebody signed in to this test with your slip on another computer, so it has stopped here. If that was you, carry on there: nothing you chose here is lost.</p>",
    "<p>If it was not you, tell your teacher now.</p>",
    "</section>",
  ].join("");
}

export function notMe({ school = {} } = {}) {
  return [
    '<section class="sit-door state" data-state="not-me">',
    `<div class="sit-door-head">${crest(school)}<p class="sit-school">${esc(school.name || "")}</p></div>`,
    "<h1>Nothing has started</h1>",
    "<p>Tell your teacher that the slip you used is not yours. This has been recorded.</p>",
    '<button type="button" class="submit" data-action="done">Back to the start</button>',
    "</section>",
  ].join("");
}

export function guardian() {
  return [
    '<section class="sit-door state" data-state="guardian" role="alert">',
    "<h1>Tests are sat with the student&#39;s exam slip</h1>",
    "<p>This device is signed in to a parent&#39;s account. Sign out of it first, then open this page again.</p>",
    "</section>",
  ].join("");
}

export function broken(detail = "") {
  return [
    '<section class="sit-door state" data-state="broken" role="alert">',
    "<h1>Something went wrong</h1>",
    `<p>${esc(detail) || "The test could not load. Check the connection and try again."}</p>`,
    '<button type="button" class="submit" data-action="done">Try again</button>',
    "</section>",
  ].join("");
}

export const TEXT = {
  OFFLINE: "You're offline. Your answers are saved on this device and will send when you reconnect.",
  WARN: "Less than 5 minutes left. Your answers submit by themselves at 00:00.",
  LEFT: "You left the test's page. This has been recorded.",
};
