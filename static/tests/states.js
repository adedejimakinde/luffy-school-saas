/** Every screen the Tests page can show, as a pure function of what the school sent. (docs/module-notes.md) */

import { esc } from "../web/html.js";

export const LETTERS = "ABCDE";

const note = (n) => (n ? `<p class="note" role="alert">${esc(n)}</p>` : "");
const done = (text) => (text ? `<p class="done" role="status">${esc(text)}</p>` : "");
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const lines = (text) => esc(text).replace(/\n/g, "<br>");

/** The two halves of the page, for a login that reads banks. */
function tabs(view, summariesOnly) {
  if (summariesOnly) return "";
  const tab = (key, label, href) =>
    `<a class="tab${view === key ? " current" : ""}" href="${href}"${view === key ? ' aria-current="page"' : ""}>${label}</a>`;
  return `<nav class="tests-tabs" aria-label="Tests">${tab("tests", "Tests", "#")}${tab("banks", "Question bank", "#banks")}</nav>`;
}

// -- tests --

function classNames(classes) {
  return classes && classes.length ? classes.map((c) => esc(c.name)).join(", ") : "No class yet";
}

function testRow(t, { summariesOnly }) {
  const what = `${esc(t.subject)}${t.level_name ? `, ${esc(t.level_name)}` : ""}. ${classNames(t.classes)}.`;
  const when = `Opens ${esc(t.opens)}, closes ${esc(t.closes)}. ${plural(t.duration, "minute", "minutes")} each.`;
  const size = `${plural(t.size, "question", "questions")}. ${t.code_set ? "Test code set." : "No test code yet."}`;
  const open = summariesOnly ? "" : `<a class="btn btn-quiet" href="#test/${esc(t.id)}">Open</a>`;
  const sitting = t.state === "published" ? `<a class="btn btn-quiet" href="#sitting/${esc(t.id)}" aria-label="The sitting of ${esc(t.title)}">Sitting</a>` : "";
  const results = t.state === "published" || t.state === "closed" ? `<a class="btn btn-quiet" href="results/#${esc(t.id)}">Results</a>` : "";
  return [
    `<li class="test-row" data-test="${esc(t.id)}">`,
    `<span class="name">${esc(t.title)}</span> <span class="badge state-${esc(t.state)}">${esc(t.state_label)}</span>`,
    `<span class="level">${what} ${when} ${size} Set by ${esc(t.set_by)}.</span>`,
    `<span class="row-actions">${open}${sitting}${results}</span>`,
    "</li>",
  ].join("");
}

export function testsView({ term = null, summaries_only = false, may_set = false, approves = false, tests = [], choices = [] } = {}, { done: said = "" } = {}) {
  const waiting = tests.filter((t) => t.state === "submitted");
  return [
    '<section class="state state-tests" data-state="tests">',
    tabs("tests", summaries_only),
    "<h1>Tests</h1>",
    term ? `<p class="hint">This term: ${esc(term)}.</p>` : '<p class="note" role="alert">No term is open. The current term is set on the Setup page.</p>',
    done(said),
    summaries_only
      ? '<p class="hint">You see each test&#39;s classes, window and size. Its questions are its teachers&#39; and the principal&#39;s.</p>'
      : "",
    may_set
      ? choices.length
        ? '<p><a class="btn btn-primary" href="#new-test">Set a test</a></p>'
        : '<p class="hint">To set a test, first write questions into one of your banks.</p>'
      : "",
    approves && waiting.length
      ? `<p class="msg"><span class="label label-brand">Waiting for you</span> ${plural(waiting.length, "test is", "tests are")} waiting for your approval.</p>`
      : "",
    tests.length
      ? `<ul class="classes tests-list">${tests.map((t) => testRow(t, { summariesOnly: summaries_only })).join("")}</ul>`
      : '<p class="blank">No test yet this term.</p>',
    "</section>",
  ].join("");
}

// -- banks --

export function banksView({ term = null, banks = [], empty_because = "" } = {}) {
  return [
    '<section class="state state-banks" data-state="banks">',
    tabs("banks", false),
    "<h1>Question bank</h1>",
    '<p class="hint">Questions you and your colleagues write, by subject and class level.',
    term ? ` For ${esc(term)}.` : "",
    "</p>",
    banks.length
      ? `<ul class="classes banks-list">${banks
          .map(
            (b) =>
              `<li class="group" data-bank="${esc(b.subject_id)}-${esc(b.level)}"><span class="name">${esc(b.subject)}, ${esc(b.level_name)}</span>` +
              `<span class="level">${plural(b.in_use, "question", "questions")} in use${b.retired ? `, ${b.retired} retired` : ""}.${b.may_write ? "" : " You read this bank."}</span>` +
              `<a class="btn btn-quiet" href="#bank/${esc(b.subject_id)}/${esc(b.level)}">Open</a></li>`,
          )
          .join("")}</ul>`
      : `<p class="blank">${esc(empty_because)}</p>`,
    "</section>",
  ].join("");
}

function questionRow(q, n, bank) {
  const picture = q.picture ? (q.picture.url ? " With a picture." : " Picture being processed.") : "";
  return [
    `<li class="question${q.retired ? " retired" : ""}" data-question="${esc(q.id)}">`,
    `<span class="number">${n}</span>`,
    `<span class="what"><span class="stem">${lines(q.stem)}</span>`,
    `<span class="who">${q.topic ? `${esc(q.topic)}. ` : ""}${q.options.length === 5 ? "A to E" : "A to D"}. Answer ${LETTERS[q.correct_index]}. ${plural(q.marks, "mark", "marks")}.${picture} `,
    `${q.used_in ? `In ${plural(q.used_in, "test", "tests")}.` : "Not used yet."} ${q.retired ? "Retired." : `Edited ${esc(q.updated_at)} by ${esc(q.updated_by)}.`}</span></span>`,
    bank.may_write && !q.retired ? `<a class="btn btn-quiet" href="#question/${esc(bank.subject_id)}/${esc(bank.level)}/${esc(q.id)}" aria-label="Edit question ${n}">Edit</a>` : "",
    "</li>",
  ].join("");
}

export function bankView(bank, { done: said = "" } = {}) {
  const live = bank.questions.filter((q) => !q.retired);
  const retired = bank.questions.filter((q) => q.retired);
  return [
    '<section class="state state-bank" data-state="bank">',
    tabs("banks", false),
    `<p><a href="#banks">All banks</a></p>`,
    `<h1>${esc(bank.subject)}, ${esc(bank.level_name)}</h1>`,
    `<p class="hint">${esc(bank.readers)}</p>`,
    done(said),
    bank.may_write ? `<p><a class="btn btn-primary" href="#question/${esc(bank.subject_id)}/${esc(bank.level)}/new">Add question</a></p>` : "",
    live.length ? `<ol class="questions">${live.map((q, i) => questionRow(q, i + 1, bank)).join("")}</ol>` : '<p class="blank">No question in this bank yet.</p>',
    retired.length ? `<h2>Retired</h2><ol class="questions">${retired.map((q, i) => questionRow(q, i + 1, bank)).join("")}</ol>` : "",
    '<div class="msg"><span class="label label-brand">Good to know</span><p>A test sent for approval carries its own copy of each question. Editing here never changes a test already set. A used question is retired, not deleted, so old tests keep their questions.</p></div>',
    "</section>",
  ].join("");
}

/** The question form. (docs/module-notes.md) */
export function questionForm(bank, q, { detail = "", values = null, confirming = null } = {}) {
  const v = values || (q ? { ...q, image_key: q.picture ? q.picture.key : "" } : null) || {};
  const options = v.options || ["", "", "", ""];
  const n = options.length === 5 ? 5 : 4;
  const shown = v.picture || null;
  const field = (i) =>
    `<div class="option"><label for="option-${i}">Option ${LETTERS[i]}</label>` +
    `<input id="option-${i}" name="option${i}" maxlength="300" value="${esc(options[i] || "")}" required>` +
    `<label class="choice correct"><input type="radio" name="correct" value="${i}"${v.correct_index === i ? " checked" : ""} required> Correct answer</label></div>`;
  return [
    '<section class="state state-question" data-state="question">',
    tabs("banks", false),
    `<p><a href="#bank/${esc(bank.subject_id)}/${esc(bank.level)}">${esc(bank.subject)}, ${esc(bank.level_name)}</a></p>`,
    `<h1>${q ? "Edit question" : "Add question"}</h1>`,
    q && q.used_in ? `<p class="hint">Used in ${plural(q.used_in, "test", "tests")}. They keep the version they were set with.</p>` : "",
    `<form data-form="question" class="${detail ? "rejected" : ""}" novalidate>`,
    q ? `<input type="hidden" name="version" value="${esc(q.version)}">` : "",
    '<label for="stem">Question</label>',
    `<textarea id="stem" name="stem" rows="4" maxlength="1000" required>${esc(v.stem || "")}</textarea>`,
    '<p class="hint">Plain text, as the student will read it. Type powers as characters: x², 10³.</p>',
    '<label for="picture">Picture, optional</label>',
    shown && shown.url ? `<img class="picture" src="${esc(shown.url)}" alt="${esc(v.image_alt || "")}">` : "",
    shown && !shown.url ? `<p class="hint">${shown.error ? esc(shown.error) : "The picture is being processed."}</p>` : "",
    `<input type="hidden" name="image_key" value="${esc(shown ? shown.key : "")}">`,
    '<input id="picture" name="picture" type="file" accept="image/png,image/jpeg,image/webp" data-action="picture">',
    '<p class="hint">PNG, JPG or WebP. It downloads with the test, so keep it small.</p>',
    '<label for="image_alt">Describe the picture for a student who cannot see it</label>',
    `<input id="image_alt" name="image_alt" maxlength="200" value="${esc(v.image_alt || "")}">`,
    shown ? '<button type="button" class="again" data-action="no-picture">Remove the picture</button>' : "",
    '<fieldset><legend>Number of options</legend>',
    `<label class="choice"><input type="radio" name="count" value="4" data-action="count"${n === 4 ? " checked" : ""}> A to D</label>`,
    `<label class="choice"><input type="radio" name="count" value="5" data-action="count"${n === 5 ? " checked" : ""}> A to E</label>`,
    "</fieldset>",
    '<fieldset class="options"><legend>Options and the correct answer</legend>',
    Array.from({ length: n }, (_, i) => field(i)).join(""),
    '<p class="hint">One correct answer. The order is shuffled for each student; the letters here are only yours.</p>',
    "</fieldset>",
    '<label for="marks">Marks</label>',
    `<input id="marks" name="marks" type="number" min="1" max="10" value="${esc(v.marks || 1)}" inputmode="numeric">`,
    '<label for="topic">Topic, optional</label>',
    `<input id="topic" name="topic" maxlength="60" value="${esc(v.topic || "")}">`,
    '<label for="explanation">Explanation, optional</label>',
    `<textarea id="explanation" name="explanation" rows="3" maxlength="1000">${esc(v.explanation || "")}</textarea>`,
    '<p class="hint">Students see this with their corrections, after scores are released.</p>',
    note(detail),
    '<div class="actions"><button type="submit" class="submit">Save question</button>',
    `<a class="btn btn-quiet" href="#bank/${esc(bank.subject_id)}/${esc(bank.level)}">Cancel</a></div>`,
    "</form>",
    q ? retireOrDelete(q, confirming) : "",
    "</section>",
  ].join("");
}

function retireOrDelete(q, confirming) {
  if (confirming === "retire") {
    return '<div class="confirm"><p>Retire this question? It stays for the tests that used it, and no new test draws it.</p><button type="button" class="submit" data-action="retire">Retire it</button><button type="button" class="again" data-action="keep">Not now</button></div>';
  }
  if (confirming === "delete") {
    return '<div class="confirm"><p>Delete this question? No test has used it, and it cannot be brought back.</p><button type="button" class="submit" data-action="delete-question">Delete it</button><button type="button" class="again" data-action="keep">Not now</button></div>';
  }
  return `<div class="actions"><button type="button" class="again" data-action="ask-retire">Retire question</button>${q.used_in ? "" : '<button type="button" class="again" data-action="ask-delete">Delete question</button>'}</div>`;
}

// -- setting a test --

/** "2026-11-09T09:00" in the browser's own time, for a datetime-local field. */
export function localInput(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const box = (name, label, on, hint = "") =>
  `<label class="choice"><input type="checkbox" name="${name}"${on ? " checked" : ""}> <span>${label}${hint ? `<span class="hint">${hint}</span>` : ""}</span></label>`;

export function testForm(choices, test = null, { detail = "", choice = null } = {}) {
  const key = choice || (test ? `${test.subject_id}-${test.level}` : choices.length ? `${choices[0].subject_id}-${choices[0].level}` : "");
  const picked = choices.find((c) => `${c.subject_id}-${c.level}` === key) || null;
  const chosen = new Set(test ? test.class_group_ids : []);
  return [
    '<section class="state state-test-form" data-state="test-form">',
    tabs("tests", false),
    `<p><a href="${test ? `#test/${esc(test.id)}` : "#"}">${test ? esc(test.title) : "Tests"}</a></p>`,
    `<h1>${test ? "Change the test" : "Set a test"}</h1>`,
    '<p class="hint">Questions come from your bank. They are drawn and copied into the test when you send it for approval, and nothing is shown to students until it opens.</p>',
    `<form data-form="test" class="${detail ? "rejected" : ""}" novalidate>`,
    '<label for="title">Title</label>',
    `<input id="title" name="title" maxlength="120" value="${esc(test ? test.title : "")}" required>`,
    '<label for="bank">Questions from</label>',
    `<select id="bank" name="bank" data-action="bank">${choices
      .map((c) => `<option value="${esc(c.subject_id)}-${esc(c.level)}"${`${c.subject_id}-${c.level}` === key ? " selected" : ""}>${esc(c.subject)}, ${esc(c.level_name)} (${plural(c.in_use, "question", "questions")})</option>`)
      .join("")}</select>`,
    '<fieldset><legend>Classes</legend>',
    picked
      ? picked.classes.map((c) => `<label class="choice"><input type="checkbox" name="class" value="${esc(c.id)}"${chosen.has(c.id) || (!test && picked.classes.length === 1) ? " checked" : ""}> ${esc(c.name)}</label>`).join("")
      : '<p class="hint">Choose where the questions come from first.</p>',
    '<p class="hint">Only classes you teach this subject to.</p></fieldset>',
    '<label for="question_count">Number of questions</label>',
    `<input id="question_count" name="question_count" type="number" min="1" max="${esc(picked ? picked.in_use : 200)}" value="${esc(test ? test.question_count : Math.min(20, picked ? picked.in_use : 20))}" inputmode="numeric">`,
    '<label for="opens_at">Opens</label>',
    `<input id="opens_at" name="opens_at" type="datetime-local" value="${esc(test ? localInput(test.opens_at) : "")}" required>`,
    '<label for="closes_at">Closes</label>',
    `<input id="closes_at" name="closes_at" type="datetime-local" value="${esc(test ? localInput(test.closes_at) : "")}" required>`,
    '<label for="duration">Time for each student, in minutes</label>',
    `<input id="duration" name="duration" type="number" min="1" max="300" value="${esc(test ? test.duration : 30)}" inputmode="numeric">`,
    '<p class="hint">The school&#39;s clock decides, not the device&#39;s. A student who starts late still gets this long, up to when it closes.</p>',
    '<label for="late_window">If the network drops near the end</label>',
    `<select id="late_window" name="late_window">${[
      [2, "Accept answers saved before time, if they arrive within 2 minutes"],
      [5, "Accept answers saved before time, if they arrive within 5 minutes"],
      [0, "Refuse anything that arrives after time"],
    ]
      .map(([v, l]) => `<option value="${v}"${(test ? test.late_window : 2) === v ? " selected" : ""}>${l}</option>`)
      .join("")}</select>`,
    '<fieldset><legend>Fair for every student</legend>',
    box("shuffle_questions", "Shuffle question order", test ? test.shuffle_questions : true, "Each student gets the questions in their own order."),
    box("shuffle_options", "Shuffle option order", test ? test.shuffle_options : true, "Marking follows the option, not the letter."),
    box("can_go_back", "Students can go back to a question", test ? test.can_go_back : true),
    box("grid", "Question number grid", test ? test.grid : true),
    box("calculator", "Calculator on screen", test ? test.calculator : false),
    "</fieldset>",
    '<fieldset><legend>Signing in to sit it</legend>',
    box("require_pin", "Exam PIN from the student&#39;s slip", test ? test.require_pin : true, "Without it, this is a practice test: anybody with the class list can sit as anybody, so its scores are never sent to a CA column or released to students or parents. The server refuses both."),
    "</fieldset>",
    '<p class="hint">This does not lock the browser. Supervise the room.</p>',
    note(detail),
    `<div class="actions"><button type="submit" class="submit">${test ? "Save changes" : "Save draft"}</button></div>`,
    "</form>",
    "</section>",
  ].join("");
}

// -- one test --

function itemRow(i) {
  return [
    `<li class="item" data-item="${esc(i.number)}">`,
    `<p class="stem"><strong>${esc(i.number)}.</strong> ${lines(i.stem)} <span class="who">${plural(i.marks, "mark", "marks")}</span></p>`,
    i.picture_url ? `<img class="picture" src="${esc(i.picture_url)}" alt="${esc(i.image_alt)}">` : "",
    `<ol class="options" type="A">${i.options
      .map((o, n) => `<li${n === i.correct_index ? ' class="correct"' : ""}>${esc(o)}${n === i.correct_index ? ' <span class="badge">Correct</span>' : ""}</li>`)
      .join("")}</ol>`,
    i.explanation ? `<p class="hint">${lines(i.explanation)}</p>` : "",
    "</li>",
  ].join("");
}

function actions(t, confirming) {
  if (confirming === "send-back") {
    return [
      '<form data-form="send-back" class="confirm">',
      '<label for="note">Why it goes back, for its teacher</label>',
      '<input id="note" name="note" maxlength="200" required>',
      '<button type="submit" class="submit">Send it back</button>',
      '<button type="button" class="again" data-action="keep">Not now</button>',
      "</form>",
    ].join("");
  }
  if (confirming === "approve") {
    return `<div class="confirm"><p>Approve ${esc(t.title)}? It opens to ${classNames(t.classes)} at ${esc(t.opens)}, with these ${plural(t.size, "question", "questions")}.</p><button type="button" class="submit" data-action="approve">Approve</button><button type="button" class="again" data-action="keep">Not now</button></div>`;
  }
  if (confirming === "delete") {
    return '<div class="confirm"><p>Delete this draft?</p><button type="button" class="submit" data-action="delete-test">Delete it</button><button type="button" class="again" data-action="keep">Not now</button></div>';
  }
  const out = [];
  if (t.may_edit) out.push(`<a class="btn btn-quiet" href="#edit-test/${esc(t.id)}">Change</a>`);
  if (t.may_submit) out.push('<button type="button" class="submit" data-action="submit">Send for approval</button>');
  if (t.may_withdraw) out.push('<button type="button" class="again" data-action="withdraw">Withdraw from approval</button>');
  if (t.may_approve) {
    out.push('<button type="button" class="submit" data-action="ask-approve">Approve</button>');
    out.push('<button type="button" class="again" data-action="ask-send-back">Send back</button>');
  }
  if (t.items.length) out.push(`<a class="btn btn-quiet" href="#preview/${esc(t.id)}">Try it as a student</a>`);
  if (t.state === "published") out.push(`<a class="btn btn-quiet" href="#sitting/${esc(t.id)}">The sitting</a>`);
  if (t.state === "published" || t.state === "closed") out.push(`<a class="btn btn-quiet" href="results/#${esc(t.id)}">Results</a>`);
  if (t.may_delete) out.push('<button type="button" class="again" data-action="ask-delete">Delete draft</button>');
  return out.length ? `<div class="actions">${out.join("")}</div>` : "";
}

function classesForm(t, confirming) {
  if (!t.may_change_classes) return "";
  if (confirming !== "classes") return '<p><button type="button" class="again" data-action="ask-classes">Change classes</button></p>';
  const chosen = new Set(t.class_group_ids);
  return [
    '<form data-form="classes" class="confirm">',
    '<fieldset><legend>Who sits it</legend>',
    t.class_choices.map((c) => `<label class="choice"><input type="checkbox" name="class" value="${esc(c.id)}"${chosen.has(c.id) ? " checked" : ""}> ${esc(c.name)}</label>`).join(""),
    "</fieldset>",
    '<p class="hint">The change is logged with your name.</p>',
    '<button type="submit" class="submit">Save classes</button>',
    '<button type="button" class="again" data-action="keep">Not now</button>',
    "</form>",
  ].join("");
}

export function testView(t, { detail = "", confirming = null, done: said = "" } = {}) {
  const settings = [
    t.shuffle_questions ? "questions shuffled" : "questions in order",
    t.shuffle_options ? "options shuffled" : "options in order",
    t.can_go_back ? "can go back" : "no going back",
    t.grid ? "number grid" : "no grid",
    t.calculator ? "calculator" : "no calculator",
    t.require_pin ? "exam PIN" : "practice: no exam PIN, so never to CA and never released",
    t.late_window ? `answers accepted up to ${t.late_window} minutes late if saved in time` : "nothing accepted late",
  ];
  return [
    '<section class="state state-test" data-state="test">',
    tabs("tests", false),
    '<p><a href="#">Tests</a></p>',
    `<h1>${esc(t.title)}</h1>`,
    `<p><span class="badge state-${esc(t.state)}">${esc(t.state_label)}</span> ${esc(t.subject)}, ${esc(t.level_name)}. ${classNames(t.classes)}.</p>`,
    `<p class="hint">Opens ${esc(t.opens)}, closes ${esc(t.closes)}. ${plural(t.duration, "minute", "minutes")} each. ${plural(t.question_count, "question", "questions")}${t.total_marks ? `, ${plural(t.total_marks, "mark", "marks")}` : ""}. Set by ${esc(t.set_by)}.</p>`,
    `<p class="hint">${esc(settings.join("; "))}.</p>`,
    done(said),
    note(detail),
    actions(t, confirming),
    classesForm(t, confirming),
    t.items.length
      ? `<h2>The paper</h2><p class="hint">As it was copied from the bank. Editing the bank does not change it.</p><ol class="items">${t.items.map(itemRow).join("")}</ol>`
      : '<p class="hint">Its questions are drawn from the bank and copied in when it is sent for approval.</p>',
    t.history.length
      ? `<h2>What happened</h2><ul class="history">${t.history.map((h) => `<li>${esc(h.what)}, by ${esc(h.by)}, ${esc(h.at)}${h.note ? `: ${esc(h.note)}` : ""}</li>`).join("")}</ul>`
      : "",
    "</section>",
  ].join("");
}

export function previewView(testId, p) {
  return [
    '<section class="state state-preview" data-state="preview">',
    `<p><a href="#test/${esc(testId)}">Back to the test</a></p>`,
    `<h1>${esc(p.title)}</h1>`,
    `<p class="hint">As one student might see it: shuffled for them, and with no answer in it. ${plural(p.duration, "minute", "minutes")}.</p>`,
    `<ol class="items paper">${p.items
      .map(
        (i) =>
          `<li class="item"><p class="stem"><strong>${esc(i.number)}.</strong> ${lines(i.stem)}</p>` +
          (i.image ? `<img class="picture" src="${esc(i.image)}" alt="${esc(i.image_alt)}">` : "") +
          `<ol class="options" type="A">${i.options.map((o) => `<li>${esc(o.text)}</li>`).join("")}</ol></li>`,
      )
      .join("")}</ol>`,
    "</section>",
  ].join("");
}

// -- the sitting (CBT step 4) --

/** "Fri 13 Nov, 09:05" in the browser's time, or "". */
export function shortTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function sittingClass(log, c, confirming) {
  const state = c.open ? '<span class="label label-ok">Open</span>' : '<span class="label">Closed</span>';
  const head = `<li class="group sit-class" data-class="${esc(c.id)}"><span class="name">${esc(c.name)} ${state}</span><span class="level">${esc(c.said)}</span>`;
  if (!log.may_run) return `${head}</li>`;
  const kind = c.open ? "close" : "open";
  if (confirming !== `${kind}-${c.id}`) {
    return `${head}<button type="button" class="again" data-action="ask-${kind}-${esc(c.id)}">${c.open ? "Close it now" : "Open it now"}</button></li>`;
  }
  return [
    head,
    `<form data-form="control" data-kind="${kind}" data-class="${esc(c.id)}" class="confirm">`,
    `<label for="reason-${esc(c.id)}">Why, for the record</label>`,
    `<input id="reason-${esc(c.id)}" name="reason" maxlength="200" required>`,
    c.open ? '<label class="choice"><input type="checkbox" name="end_attempts"> <span>Also end every attempt in progress now<span class="hint">Without this, students already sitting carry on to their own time. Nothing they chose is lost either way.</span></span></label>' : "",
    `<button type="submit" class="submit">${c.open ? "Close the sitting" : "Open the sitting"}</button>`,
    '<button type="button" class="again" data-action="keep">Not now</button>',
    "</form></li>",
  ].join("");
}

function codePart(log, { confirming, code }) {
  if (code) {
    return `<div class="msg sit-code" role="status"><span class="label label-brand">Test code</span><p><strong class="code">${esc(code)}</strong> Write it on the board. It is shown this once; if it is lost, set a new one.</p></div>`;
  }
  const said = log.code_set ? "A test code is set. Students type it with their admission number and exam PIN." : "No test code yet. Students cannot sign in until one is set.";
  if (!log.may_run) return `<p class="hint">${said}</p>`;
  if (log.code_set && confirming === "code") {
    return `<div class="confirm"><p>Set a new code? The old one stops working. Students already sitting carry on; one who signs in again needs the new code.</p><button type="button" class="submit" data-action="set-code">Set a new code</button><button type="button" class="again" data-action="keep">Not now</button></div>`;
  }
  return `<p class="hint">${said}</p><p><button type="button" class="${log.code_set ? "again" : "submit"}" data-action="${log.code_set ? "ask-code" : "set-code"}">${log.code_set ? "Change the code" : "Set the test code"}</button></p>`;
}

function studentRow(log, r, confirming) {
  const when = [
    r.started_at ? `Started ${shortTime(r.started_at)}` : "",
    r.deadline ? `time ends ${shortTime(r.deadline)}` : "",
    r.extra_minutes ? `${r.extra_minutes} extra minutes` : "",
    r.submitted_at ? `closed ${shortTime(r.submitted_at)}` : "",
  ].filter(Boolean);
  const counts = r.number
    ? [
        ["Computers", r.computers],
        ["Dropped off", r.disconnects],
        ["Left the page", r.left_page],
        ["Late, refused", r.late_refused],
        ["Answers received", r.answers_received],
      ]
    : [];
  const sitting = r.state === "Sitting" || r.state === "Not started";
  const acts = [];
  if (log.may_extend && sitting) acts.push(`<button type="button" class="again" data-action="ask-extra-${esc(r.student_id)}">Extra time</button>`);
  if (r.may_retake) acts.push(`<button type="button" class="again" data-action="ask-retake-${esc(r.student_id)}">Allow a retake</button>`);
  let form = "";
  if (confirming === `extra-${r.student_id}`) {
    form = [
      `<form data-form="extra" data-student="${esc(r.student_id)}" class="confirm">`,
      `<label for="minutes-${esc(r.student_id)}">Extra minutes for ${esc(r.name)}</label>`,
      `<input id="minutes-${esc(r.student_id)}" name="minutes" type="number" min="1" max="120" value="10" inputmode="numeric">`,
      `<label for="why-${esc(r.student_id)}">Why, for the record</label>`,
      `<input id="why-${esc(r.student_id)}" name="reason" maxlength="200" required>`,
      '<button type="submit" class="submit">Give the time</button><button type="button" class="again" data-action="keep">Not now</button>',
      "</form>",
    ].join("");
  } else if (confirming === `retake-${r.student_id}`) {
    form = [
      `<form data-form="retake" data-student="${esc(r.student_id)}" class="confirm">`,
      `<label for="retake-${esc(r.student_id)}">Why ${esc(r.name)} sits it again, for the record</label>`,
      `<input id="retake-${esc(r.student_id)}" name="reason" maxlength="200" required>`,
      '<button type="submit" class="submit">Allow a retake</button><button type="button" class="again" data-action="keep">Not now</button>',
      "</form>",
    ].join("");
  }
  const events = r.events.length
    ? `<details><summary>What happened (${r.events.length})</summary><ul class="history">${r.events
        .map((e) => `<li>${esc(shortTime(e.at))}: ${esc(e.what)}${e.seat ? `, ${esc(e.seat)}` : ""}${e.detail.minutes ? `, ${esc(e.detail.minutes)} min` : ""}${e.detail.seconds && e.kind === "left_page" ? `, ${esc(e.detail.seconds)} s` : ""}${e.detail.reason ? `: ${esc(e.detail.reason)}` : ""}${e.detail.by ? ` (${esc(e.detail.by)})` : ""}${e.said_by === "device" ? " (said by the student&#39;s computer)" : ""}</li>`)
        .join("")}</ul></details>`
    : "";
  const tone = r.state === "Sitting" ? " label-brand" : r.state === "Not started" ? "" : " label-ok";
  return [
    `<li class="sit-student-row" data-student="${esc(r.student_id)}">`,
    `<p class="name"><strong>${esc(r.name)}</strong> <span class="label${tone}">${esc(r.number > 1 ? `${r.state}, attempt ${r.number}` : r.state)}</span></p>`,
    `<p class="level">${esc(r.class_name)}${r.admission_number ? `, ${esc(r.admission_number)}` : ""}.${when.length ? ` ${esc(when.join(", "))}.` : ""}</p>`,
    counts.length ? `<dl class="sit-counts">${counts.map(([k, v]) => `<div data-count="${esc(k)}"><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>` : "",
    acts.length ? `<div class="row-actions">${acts.join("")}</div>` : "",
    form,
    events,
    "</li>",
  ].join("");
}

export function sittingView(log, { detail = "", confirming = null, done: said = "", code = null } = {}) {
  return [
    '<section class="state state-sitting" data-state="sitting">',
    `<p><a href="#">Tests</a></p>`,
    `<h1>${esc(log.title)}: the sitting</h1>`,
    `<p class="hint">Opens ${esc(shortTime(log.opens_at))}, closes ${esc(shortTime(log.closes_at))}. ${plural(log.duration, "minute", "minutes")} each, the school&#39;s clock. Students sign in at this school&#39;s address, /sit/.</p>`,
    done(said),
    note(detail),
    "<h2>Test code</h2>",
    codePart(log, { confirming, code }),
    "<h2>Classes</h2>",
    `<ul class="classes">${log.classes.map((c) => sittingClass(log, c, confirming)).join("")}</ul>`,
    "<h2>Students</h2>",
    '<p class="hint">Who started, dropped off and submitted, and when. No answer or score is shown here.</p>',
    log.rows.length
      ? `<ul class="sitting-log">${log.rows.map((r) => studentRow(log, r, confirming)).join("")}</ul>`
      : '<p class="blank">Nobody is placed in its classes this term.</p>',
    "</section>",
  ].join("");
}

// -- refusals --

export function notYours({ detail = "" } = {}) {
  return [
    '<section class="state state-refused" role="alert">',
    "<h1>This page is not yours</h1>",
    `<p>${esc(detail) || "Tests are set by teachers and approved by the principal or the vice principal."}</p>`,
    "</section>",
  ].join("");
}

export function wrongHost() {
  return '<section class="state state-refused" role="alert"><h1>This is not a school&#39;s address</h1><p>Open this page from your school&#39;s own address.</p></section>';
}

export function signedOut({ portal = "", expired = false } = {}) {
  const link = portal ? `<a href="//${esc(portal)}/staff-sign-in/">Sign in</a>` : "Sign in";
  return `<section class="state state-refused" role="alert"><h1>${expired ? "Your session has ended" : "You are signed out"}</h1><p>${link} again to carry on.</p></section>`;
}

export function broken() {
  return '<section class="state state-refused" role="alert"><h1>Something went wrong</h1><p>The page could not load. Try again in a moment.</p></section>';
}
