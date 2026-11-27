/**
 * A test's sitting, as a pure function of what the school sent: its code, each class opened
 * or closed by hand, the log of who started and submitted, and exam slips for staff who may
 * print them. `/tests/sitting/`, beside the Tests page (`docs/cbt.md`, step 4). No answer,
 * item or score is in anything drawn here.
 */

import { classConfirm, studentConfirm } from "../exam-slips/print.js";
import { esc } from "../web/html.js";

const note = (n) => (n ? `<p class="note" role="alert">${esc(n)}</p>` : "");
const done = (text) => (text ? `<p class="done" role="status">${esc(text)}</p>` : "");
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

/** "Fri 13 Nov, 09:05" in the browser's time, or "". */
export function shortTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

/** "14:05" in the browser's time, or "". */
export function clockTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

/** Sign-ins at the exam door that did not get through, with the real reason. Staff only:
 * the student is told one sentence whatever was wrong, and this is never sent to them. */
function signIns(r) {
  const tries = r.sign_ins || [];
  if (!tries.length) return "";
  const lines = tries
    .map((s) => {
      const until = s.until ? `, until ${esc(clockTime(s.until))}` : "";
      const computer = s.device ? ` <span class="hint">(computer ${esc(s.device)})</span>` : "";
      return `<li data-reason="${esc(s.reason)}">${esc(shortTime(s.at))}: ${esc(s.what)}${until}${computer}</li>`;
    })
    .join("");
  return `<details class="sign-ins"><summary>Failed sign-ins (${tries.length})</summary><p class="hint">Only staff see this. The student is told the same sentence whatever was wrong.</p><ul class="history">${lines}</ul></details>`;
}

function sittingClass(log, c, confirming) {
  const state = c.open ? '<span class="label label-ok">Open</span>' : '<span class="label">Closed</span>';
  const head = `<li class="group sit-class" data-class="${esc(c.id)}"><span class="name">${esc(c.name)} ${state}</span><span class="level">${esc(c.said)}</span><span class="level pins-issued">${
    c.pins_issued ? `PINs last issued: ${esc(c.pins_issued.at)} by ${esc(c.pins_issued.by)}` : "PINs not issued yet this term"
  }</span>`;
  const acts = [];
  const asking = confirming === `print-class-${c.id}`;
  if (log.may_run) {
    const kind = c.open ? "close" : "open";
    if (confirming !== `${kind}-${c.id}`) acts.push(`<button type="button" data-action="ask-${kind}-${esc(c.id)}">${c.open ? "Close it now" : "Open it now"}</button>`);
  }
  // Exam slips: only for a login that may already print them (the server asks again).
  if (log.may_print && c.printable && !asking) acts.push(`<button type="button" data-action="ask-print-class-${esc(c.id)}">Print exam PIN slips</button>`);
  const print = log.may_print && c.printable && asking ? classConfirm(c, `print-class-${c.id}`) : "";
  const bar = acts.length ? `<div class="actions">${acts.join("")}</div>` : "";
  if (!log.may_run || confirming !== `${c.open ? "close" : "open"}-${c.id}`) return `${head}${bar}${print}</li>`;
  const kind = c.open ? "close" : "open";
  return [
    head,
    `<form data-form="control" data-kind="${kind}" data-class="${esc(c.id)}" class="confirm">`,
    `<label for="reason-${esc(c.id)}">Why, for the record</label>`,
    `<input id="reason-${esc(c.id)}" name="reason" maxlength="200" required>`,
    c.open ? '<label class="choice"><input type="checkbox" name="end_attempts"> <span>Also end every attempt in progress now<span class="hint">Without this, students already sitting carry on to their own time. Nothing they chose is lost either way.</span></span></label>' : "",
    `<button type="submit" class="submit">${c.open ? "Close the sitting" : "Open the sitting"}</button>`,
    '<button type="button" class="again" data-action="keep">Not now</button>',
    "</form>",
    bar,
    "</li>",
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
  return `<p class="hint">${said}</p><p><button type="button"${log.code_set ? "" : ' class="submit"'} data-action="${log.code_set ? "ask-code" : "set-code"}">${log.code_set ? "Change the code" : "Set the test code"}</button></p>`;
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
  if (log.may_extend && sitting) acts.push(`<button type="button" data-action="ask-extra-${esc(r.student_id)}">Extra time</button>`);
  if (r.may_retake) acts.push(`<button type="button" data-action="ask-retake-${esc(r.student_id)}">Allow a retake</button>`);
  if (log.may_print && r.class_id && r.admission_number && confirming !== `print-student-${r.student_id}`) {
    acts.push(`<button type="button" data-action="ask-print-student-${esc(r.student_id)}" aria-label="Reissue slip for ${esc(r.name)}">Reissue slip</button>`);
  }
  let form = "";
  if (confirming === `print-student-${r.student_id}` && log.may_print && r.class_id) {
    form = studentConfirm({ id: r.class_id }, { id: r.student_id, name: r.name }, `print-student-${r.student_id}`);
  } else if (confirming === `extra-${r.student_id}`) {
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
  const failed = (r.sign_ins || []).length;
  return [
    `<li class="sit-student-row" data-student="${esc(r.student_id)}">`,
    `<p class="name"><strong>${esc(r.name)}</strong> <span class="label${tone}">${esc(r.number > 1 ? `${r.state}, attempt ${r.number}` : r.state)}</span>${failed ? ` <span class="label label-warn" data-failed-sign-ins>${esc(failed)} failed sign-in${failed === 1 ? "" : "s"}</span>` : ""}</p>`,
    `<p class="level">${esc(r.class_name)}${r.admission_number ? `, ${esc(r.admission_number)}` : ""}.${when.length ? ` ${esc(when.join(", "))}.` : ""}</p>`,
    counts.length ? `<dl class="sit-counts">${counts.map(([k, v]) => `<div data-count="${esc(k)}"><dt>${k}</dt><dd>${esc(v)}</dd></div>`).join("")}</dl>` : "",
    acts.length ? `<div class="row-actions">${acts.join("")}</div>` : "",
    form,
    signIns(r),
    events,
    "</li>",
  ].join("");
}

export function sittingView(log, { detail = "", confirming = null, done: said = "", code = null } = {}) {
  return [
    '<section class="state state-sitting" data-state="sitting">',
    `<p><a href="../">Tests</a></p>`,
    `<h1>${esc(log.title)}: the sitting</h1>`,
    `<p class="hint">Opens ${esc(shortTime(log.opens_at))}, closes ${esc(shortTime(log.closes_at))}. ${plural(log.duration, "minute", "minutes")} each, the school&#39;s clock. Students sign in at this school&#39;s address, /sit/.</p>`,
    done(said),
    note(detail),
    "<h2>Test code</h2>",
    codePart(log, { confirming, code }),
    "<h2>Classes</h2>",
    `<ul class="classes">${log.classes.map((c) => sittingClass(log, c, confirming)).join("")}</ul>`,
    "<h2>Students</h2>",
    '<p class="hint">Who started, dropped off and submitted, and when, and each sign-in that did not get through, with the real reason. No answer or score is shown here.</p>',
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
    `<p>${esc(detail) || "Sittings are run by teachers and approved by the principal or the vice principal."}</p>`,
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
