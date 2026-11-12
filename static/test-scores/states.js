/**
 * Every screen `/test-scores/` can show, as a pure function of what the school sent.
 *
 * Screens 09a (a student's own score and corrections) and 09b (a parent's children's
 * scores). Strings rather than DOM, so `node --test` can assert each one; every value goes
 * through `esc()`. A parent's screen has no question, no answer and no class average in
 * it because the school sends none.
 */

import { esc, waitInWords } from "../web/html.js";

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

/** "Fri 23 Oct" in the browser's time, or "". */
export function day(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}

function scoreRow(s) {
  return [
    '<li class="score-row">',
    `<span class="what"><strong>${esc(s.test_title)}</strong><span class="hint">${esc(s.subject)}, released ${esc(day(s.released_at))}</span></span>`,
    `<span class="figure"><strong>${esc(s.score)}/${esc(s.out_of)}</strong>${s.percent === null || s.percent === undefined ? "" : `<span class="hint">${esc(s.percent)}%</span>`}</span>`,
    "</li>",
  ].join("");
}

/** The student's door: the test code, their admission number, their exam PIN. */
export function door({ number = "", note = "", wait = 0 } = {}) {
  const said = wait
    ? `Too many wrong tries. Wait ${esc(waitInWords(wait))} and try again. Nothing has been locked.`
    : esc(note);
  return [
    '<section class="scores-card state state-door" data-state="door">',
    "<h1>Your test scores</h1>",
    "<p>Type the test code your teacher gives you, your admission number and the exam PIN from your slip.</p>",
    said ? `<p class="note" role="alert">${said}</p>` : "",
    '<form class="scores-form" data-form="door" autocomplete="off">',
    '<label for="code">Test code</label>',
    '<input id="code" name="code" autocapitalize="characters" spellcheck="false" maxlength="12" required>',
    '<label for="number">Admission number</label>',
    `<input id="number" name="number" autocapitalize="characters" spellcheck="false" value="${esc(number)}" required>`,
    '<label for="pin">Exam PIN</label>',
    '<input id="pin" name="pin" inputmode="numeric" spellcheck="false" required>',
    '<button type="submit" class="btn btn-primary">Show my score</button>',
    "</form>",
    '<p class="hint">Only your own scores, and only once your teacher releases them. Nothing is kept on this computer when you close the page.</p>',
    "</section>",
  ].join("");
}

function correction(c) {
  return [
    '<li class="correction">',
    `<p class="q"><strong>Your question ${esc(c.number)}</strong> <span class="label label-stop">Not right</span></p>`,
    `<p class="stem">${esc(c.stem)}</p>`,
    c.image_alt ? `<p class="hint">Picture: ${esc(c.image_alt)}</p>` : "",
    `<p class="answer"><span class="letter">${c.chosen ? esc(c.chosen) : "-"}</span> Your answer: ${c.chosen ? esc(c.chosen_text) : "none"}</p>`,
    `<p class="answer right"><span class="letter">${esc(c.right_letter)}</span> Right answer: ${esc(c.right_text)}</p>`,
    c.explanation ? `<p class="why"><strong>Why</strong> ${esc(c.explanation)}</p>` : "",
    "</li>",
  ].join("");
}

/** 09a: one student's released score, the ones they did not get right, earlier tests. */
export function student(s, { all = false } = {}) {
  const t = s.this;
  const wrong = t.corrections.filter((c) => !c.right);
  const shown = all ? t.corrections : wrong;
  return [
    '<section class="scores-card state state-student" data-state="student">',
    `<p class="who">${esc(s.name)}${s.class_name ? `, ${esc(s.class_name)}` : ""}</p>`,
    "<h1>Your test scores</h1>",
    `<h2>${esc(t.test_title)}</h2>`,
    `<p class="hint">${esc(t.subject)}. Released by ${esc(t.released_by)} on ${esc(day(t.released_at))}.</p>`,
    `<p class="big"><strong>${esc(t.score)}</strong> out of ${esc(t.out_of)}</p>`,
    `<p class="tally"><span>${plural(t.right, "right", "right")}</span> <span>${plural(t.questions - t.right, "not right", "not right")}</span></p>`,
    // Another class has still to sit this paper, so the server sent the score and
    // no answers. Said in its own words; never "you got every question right".
    t.answers_held
      ? `<p class="note held" role="status">${esc(t.answers_held_why || "Your answers will show here once every class has finished this test.")}</p>`
      : wrong.length || all
      ? `<h2>${all ? "Every question" : `The ${wrong.length === 1 ? "one" : wrong.length} you did not get right`}</h2>`
      : '<p class="done" role="status">You got every question right.</p>',
    shown.length ? `<ol class="corrections">${shown.map((c) => (c.right ? rightOne(c) : correction(c))).join("")}</ol>` : "",
    t.corrections.length > wrong.length
      ? `<p><button type="button" class="btn btn-quiet" data-action="${all ? "wrong-only" : "show-all"}">${all ? "Show only the ones not right" : `Show all ${t.questions}`}</button></p>`
      : "",
    s.earlier.length ? `<h2>Earlier tests</h2><ul class="scores">${s.earlier.map(scoreRow).join("")}</ul>` : "",
    '<p><button type="button" class="btn btn-quiet" data-action="done">Done</button></p>',
    "</section>",
  ].join("");
}

function rightOne(c) {
  return [
    '<li class="correction">',
    `<p class="q"><strong>Your question ${esc(c.number)}</strong> <span class="label label-ok">Right</span></p>`,
    `<p class="stem">${esc(c.stem)}</p>`,
    `<p class="answer right"><span class="letter">${esc(c.right_letter)}</span> Your answer: ${esc(c.right_text)}</p>`,
    "</li>",
  ].join("");
}

/** 09b: a parent's children, one at a time, each with their released scores. */
export function family(children, { current = 0 } = {}) {
  const child = children[current] || children[0];
  const switcher = children.length > 1
    ? `<nav class="child-switcher" aria-label="Your children">${children
        .map((c, i) => `<button type="button" class="btn btn-quiet${i === current ? " current" : ""}" data-action="child" data-index="${i}"${i === current ? ' aria-current="true"' : ""}>${esc(c.name)}</button>`)
        .join("")}</nav>`
    : "";
  return [
    '<section class="scores-card state state-family" data-state="family">',
    `<p class="who">${esc(child.name)}${child.class_name ? `, ${esc(child.class_name)}` : ""}</p>`,
    "<h1>Test scores</h1>",
    "<p>Tests on the computer at school, once the teacher releases them.</p>",
    switcher,
    child.scores.length
      ? `<ul class="scores">${child.scores.map(scoreRow).join("")}</ul>`
      : `<p class="blank">No test score for ${esc(child.name)} has been released yet.</p>`,
    '<p class="hint">A test score is not the report card. Teachers may count a test towards CA; the report card shows the term&#39;s results when the school releases them.</p>',
    child.waiting
      ? `<p class="hint">${esc(child.name.split(" ")[0])} has ${plural(child.waiting, "test", "tests")} waiting for release.</p>`
      : "",
    '<p><a href="/cards/">Report cards</a></p>',
    "</section>",
  ].join("");
}

/** A guardian with no child here: never the student's door. */
export function noChildren() {
  return '<section class="scores-card state state-blank" data-state="blank"><h1>Test scores</h1><p>There is no child of yours at this school to show scores for.</p></section>';
}

export function broken() {
  return '<section class="scores-card state state-refused" role="alert"><h1>Something went wrong</h1><p>The page could not load. Try again in a moment.</p></section>';
}
