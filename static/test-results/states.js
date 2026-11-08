/**
 * Every screen of a test's results page, as a pure function of what the school sent.
 *
 * `docs/cbt.md`, step 5: screen 7 (each student's score, the questions hardest first,
 * the classes and their releases, the keys corrected, the sends to CA) and screens 8a
 * and 8b (Send to CA, its preview and its confirm). Strings rather than DOM, so
 * `node --test` can assert each one; every value goes through `esc()`.
 *
 * No authority question is asked here: a button is drawn only where the school's
 * answer says this login may press it, and every route refuses anybody else. The
 * office's results have no question, option or key in them because the school sends
 * none.
 */

import { esc } from "../web/html.js";

export const LETTERS = "ABCDE";

const note = (n) => (n ? `<p class="note" role="alert">${esc(n)}</p>` : "");
const done = (text) => (text ? `<p class="done" role="status">${esc(text)}</p>` : "");
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const lines = (text) => esc(text).replace(/\n/g, "<br>");

/** "Fri 13 Nov, 09:05" in the browser's time, or "". */
export function shortTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("en-GB", { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

const pct = (n) => (n === null || n === undefined ? "" : `${n}%`);

function statsPart(r) {
  const s = r.stats;
  if (!s.sat) return `<p class="blank">${r.released_only ? "No class&#39;s scores have been released yet." : "Nobody has finished it yet."}</p>`;
  const tiles = [
    ["Sat", `${s.sat}${r.released_only ? "" : ` of ${s.placed}`}`, r.released_only ? "released" : "students"],
    ["Average", `${s.average} out of ${r.out_of}`, pct(s.percent)],
    ["Highest", String(s.highest), plural(s.highest_count, "student", "students")],
    ["Lowest", String(s.lowest), plural(s.lowest_count, "student", "students")],
  ];
  return `<dl class="results-stats">${tiles.map(([k, v, h]) => `<div><dt>${k}</dt><dd>${esc(v)}</dd><dd class="hint">${esc(h)}</dd></div>`).join("")}</dl>`;
}

/** "Most students scored 12 to 17": the narrowest run of scores holding half of them. */
export function mostScored(distribution) {
  const total = distribution.reduce((n, d) => n + d.count, 0);
  if (total < 2) return "";
  let best = null;
  for (let a = 0; a < distribution.length; a++) {
    let held = 0;
    for (let b = a; b < distribution.length; b++) {
      held += distribution[b].count;
      if (held * 2 >= total) {
        if (!best || b - a < best[1] - best[0]) best = [a, b];
        break;
      }
    }
  }
  if (!best) return "";
  const [lo, hi] = [distribution[best[0]].score, distribution[best[1]].score];
  return lo === hi ? `Half of them scored ${lo}.` : `Half of them scored ${lo} to ${hi}.`;
}

function classPart(r, c, { confirming }) {
  const head = `<li class="group result-class" data-class="${esc(c.id)}"><span class="name">${esc(c.name)} ${
    c.released ? '<span class="label label-ok">Released</span>' : '<span class="label">Not released</span>'
  }</span>`;
  const lines = [];
  if (c.released) lines.push(`<span class="level">Released by ${esc(c.released_by)}, ${esc(shortTime(c.released_at))}. Each student sees their own score and corrections, each parent their own child&#39;s score.</span>`);
  else if (c.why_not) lines.push(`<span class="level">${esc(c.why_not)}</span>`);
  for (const h of c.history || []) {
    if (h.restored) lines.push(`<span class="level hint">Released ${esc(shortTime(h.at))} by ${esc(h.by)}; restored ${esc(shortTime(h.restored_at))} by ${esc(h.restored_by)}: ${esc(h.reason)}</span>`);
  }
  let act = "";
  if (c.may_release) {
    act = confirming === `release-${c.id}`
      ? `<div class="confirm"><p>Release ${esc(c.name)}&#39;s scores? Each student then sees their own score and corrections, and each parent their own child&#39;s score. A release is final; only the principal can restore it, with a reason.</p><button type="button" class="submit" data-action="release" data-class="${esc(c.id)}">Release scores</button><button type="button" class="again" data-action="keep">Not now</button></div>`
      : `<button type="button" class="submit" data-action="ask-release-${esc(c.id)}">Release scores</button>`;
  } else if (c.released && r.may_restore) {
    act = confirming === `restore-${c.id}`
      ? [
          `<form data-form="restore" data-release="${esc(c.release_id)}" class="confirm">`,
          `<label for="restore-${esc(c.id)}">Why the scores are hidden again, for the record and the teacher</label>`,
          `<input id="restore-${esc(c.id)}" name="reason" maxlength="200" required>`,
          '<button type="submit" class="submit">Restore the release</button><button type="button" class="again" data-action="keep">Not now</button>',
          "</form>",
        ].join("")
      : `<button type="button" class="again" data-action="ask-restore-${esc(c.id)}">Restore</button>`;
  }
  return `${head}${lines.join("")}${act}</li>`;
}

function optionBars(i) {
  return `<ol class="option-bars" type="A">${i.options
    .map((text, n) => {
      const tone = n === i.key ? " is-key" : n === i.most_wrong ? " is-wrong" : "";
      const said = n === i.key ? "the right answer" : n === i.most_wrong ? "the wrong answer chosen most" : "";
      return `<li class="opt${tone}"><span class="letter">${LETTERS[n]}</span><span class="text">${esc(text)}${said ? ` <span class="hint">(${said})</span>` : ""}</span><span class="n">${esc(i.chose[n])}, ${esc(i.percent[n])}%</span></li>`;
    })
    .join("")}</ol>`;
}

function itemPart(r, i, { confirming }) {
  const flags = [];
  if (i.check_key) flags.push('<span class="label label-warn">Check the key</span>');
  if (i.key_corrected) flags.push(`<span class="label label-brand">Key corrected from ${LETTERS[i.original_key]}</span>`);
  let act = "";
  if (r.may_correct) {
    act = confirming === `key-${i.item_id}`
      ? [
          `<form data-form="key" data-item="${esc(i.item_id)}" class="confirm">`,
          `<fieldset><legend>The right answer to question ${esc(i.number)}</legend>${i.options
            .map((text, n) => `<label class="choice"><input type="radio" name="new_index" value="${n}"${n === i.key ? " checked" : ""}> <span>${LETTERS[n]}. ${esc(text)}</span></label>`)
            .join("")}</fieldset>`,
          `<label for="key-why-${esc(i.item_id)}">Why, for the record</label>`,
          `<input id="key-why-${esc(i.item_id)}" name="reason" maxlength="200" required>`,
          '<p class="hint">Every attempt is marked again, and you are shown whose scores changed. The change is logged.</p>',
          '<button type="submit" class="submit">Correct the key</button><button type="button" class="again" data-action="keep">Not now</button>',
          "</form>",
        ].join("")
      : `<button type="button" class="again" data-action="ask-key-${esc(i.item_id)}">Correct the key</button>`;
  }
  return [
    `<li class="item-row" data-item="${esc(i.item_id)}">`,
    `<p class="item-head"><strong>Question ${esc(i.number)}</strong> <span class="facility">${i.facility === null ? "-" : `${esc(i.facility)}% right`}</span> ${flags.join(" ")}</p>`,
    `<p class="stem">${lines(i.stem)}</p>`,
    optionBars(i),
    i.blank ? `<p class="hint">${plural(i.blank, "student", "students")} left it blank.</p>` : "",
    act,
    "</li>",
  ].join("");
}

function studentsTable(r) {
  if (!r.rows.length) return '<p class="blank">Nobody is placed in these classes this term.</p>';
  const head = r.released_only
    ? "<tr><th>Student</th><th>Class</th><th>Score</th></tr>"
    : "<tr><th>Student</th><th>Class</th><th>Score</th><th>Started</th><th>Submitted</th><th>Dropped off</th></tr>";
  const body = r.rows
    .map((row) => {
      const score = row.score === null || row.score === undefined ? "-" : `${row.score}/${row.out_of}`;
      const state = row.state === "Submitted" || row.state === "The student submitted" || row.state === "Released" ? "" : ` <span class="label">${esc(row.state)}</span>`;
      const late = row.late_refused ? ` <span class="label label-warn">${plural(row.late_refused, "answer", "answers")} refused</span>` : "";
      const name = `<td class="stack-head" data-label="Student"><strong>${esc(row.name)}</strong>${row.number > 1 ? ` <span class="label">attempt ${esc(row.number)}</span>` : ""}${state}${late}</td>`;
      if (r.released_only) return `<tr>${name}<td data-label="Class">${esc(row.class_name)}</td><td data-label="Score">${esc(score)}</td></tr>`;
      return `<tr>${name}<td data-label="Class">${esc(row.class_name)}</td><td data-label="Score">${esc(score)}</td><td data-label="Started">${esc(clock(row.started_at))}</td><td data-label="Submitted">${esc(clock(row.submitted_at))}</td><td data-label="Dropped off">${esc(row.number ? row.disconnects : "")}</td></tr>`;
    })
    .join("");
  return `<table class="stack results-students"><thead>${head}</thead><tbody>${body}</tbody></table>`;
}

/** "08:02" in the browser's time, or "". */
export function clock(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

function correctionsPart(r, justDone) {
  if (!r.corrections.length) return "";
  return `<h2>Keys corrected</h2><ul class="history corrections-made">${r.corrections
    .map((c) => {
      const moved = c.changes.length
        ? `${plural(c.changes.length, "score", "scores")} changed: ${c.changes.map((x) => `${esc(x.name)} ${esc(x.before)} to ${esc(x.after)}`).join("; ")}`
        : "No score changed.";
      return `<li${justDone && justDone.item_id === c.item_id && justDone.at === c.at ? ' class="just"' : ""}>Question ${esc(c.number)}: ${esc(c.old)} to ${esc(c.new)}, by ${esc(c.by)}, ${esc(shortTime(c.at))}: ${esc(c.reason)}. ${moved}</li>`;
    })
    .join("")}</ul>`;
}

function transfersPart(r) {
  if (!r.transfers.length) return "";
  return `<h2>Sent to CA</h2><ul class="history">${r.transfers
    .map((t) => `<li>${esc(t.assessment)} (out of ${esc(t.max_score)}), by ${esc(t.by)}, ${esc(shortTime(t.at))}: ${esc(t.counts.written)} written, ${esc(t.counts.kept)} kept, ${esc(t.counts.not_sat)} did not sit, ${esc(t.counts.locked)} locked, ${esc(t.counts.changed_meanwhile)} changed meanwhile.</li>`)
    .join("")}</ul>`;
}

export function resultsView(r, { detail = "", confirming = null, done: said = "", corrected = null } = {}) {
  const released = r.classes.filter((c) => c.released).length;
  const status = r.state === "closed" ? "Closed." : "Open.";
  const acts = [];
  if (r.may_send) acts.push(`<a class="btn btn-primary" href="#ca/${esc(r.test_id)}">Send to CA</a>`);
  if (!r.sends_to_ca && !r.released_only) acts.push('<span class="hint">Sat without the exam PIN, so its scores never go to CA.</span>');
  if (r.may_close) {
    acts.push(
      confirming === "close"
        ? '<span class="confirm"><span>Close this test? Nobody can start it again, by its window or by hand. Its scores and answers are kept.</span><button type="button" class="submit" data-action="close-test">Close the test</button><button type="button" class="again" data-action="keep">Not now</button></span>'
        : '<button type="button" class="again" data-action="ask-close">Close the test</button>',
    );
  }
  if (r.state === "published") acts.push(`<a class="btn btn-quiet" href="../#sitting/${esc(r.test_id)}">The sitting</a>`);
  const hardest = [...r.items].sort((a, b) => (a.facility ?? 101) - (b.facility ?? 101) || a.number - b.number);
  const often = mostScored(r.distribution);
  return [
    '<section class="state state-results" data-state="results">',
    '<p><a href="../">Tests</a></p>',
    `<h1>${esc(r.title)}</h1>`,
    `<p><span class="badge state-${esc(r.state)}">${esc(r.state_label)}</span> ${esc(r.subject)}. ${status} Marked by the computer. ${released ? `${plural(released, "class", "classes")} released.` : "Not released."}</p>`,
    r.released_only ? '<p class="hint">You see each student&#39;s score once its class is released. No question or answer is shown here.</p>' : "",
    r.open_attempts ? `<p class="msg">${plural(r.open_attempts, "student is", "students are")} still sitting it; their scores come when they finish.</p>` : "",
    done(said),
    note(detail),
    acts.length ? `<div class="actions">${acts.join("")}</div>` : "",
    statsPart(r),
    often ? `<p class="hint">${esc(often)} Scores out of ${esc(r.out_of)}.</p>` : "",
    "<h2>Classes</h2>",
    `<ul class="classes">${r.classes.map((c) => classPart(r, c, { confirming })).join("")}</ul>`,
    r.items.length && !r.released_only
      ? `<h2>Questions, hardest first</h2><p class="hint">How many got each one right, and who chose what. The right answer is shown to staff only.</p><ol class="item-analysis">${hardest.map((i) => itemPart(r, i, { confirming })).join("")}</ol>`
      : "",
    correctionsPart(r, corrected),
    "<h2>Students</h2>",
    studentsTable(r),
    transfersPart(r),
    "</section>",
  ].join("");
}

// -- send to CA (screens 8a, 8b) ----------------------------------------------------------------

const WILL = {
  new: ["New", "label-ok"],
  replace: ["Replaces", "label-warn"],
  kept: ["Kept", ""],
  same: ["Already this mark", ""],
  not_sat: ["No mark", ""],
  locked: ["Locked", "label-stop"],
};

function caLine(line) {
  const [word, tone] = WILL[line.will] || [line.will, ""];
  const now = line.current === null || line.current === undefined ? "-" : String(line.current);
  const test = line.test_score === null || line.test_score === undefined ? (line.sitting_now ? "Still sitting" : "Did not sit") : String(line.test_score);
  const said = line.will === "replace" ? `${word} ${now}` : line.will === "kept" ? `Kept at ${now}` : word;
  return [
    "<tr>",
    `<td class="stack-head" data-label="Student"><strong>${esc(line.name)}</strong> <span class="label ${tone}">${esc(said)}</span>${line.will === "replace" && line.by_hand ? ' <span class="label label-warn">Typed by hand</span>' : ""}</td>`,
    `<td data-label="Class">${esc(line.class_name)}</td>`,
    `<td data-label="Test">${esc(test)}</td>`,
    `<td data-label="CA mark">${esc(line.mark === null || line.mark === undefined ? "-" : line.mark)}</td>`,
    `<td data-label="In the column now">${esc(now)}</td>`,
    "</tr>",
  ].join("");
}

/** How many marks a send of this preview would write. */
export const toWrite = (p) => (p.counts.new || 0) + (p.counts.replace || 0);

export function caView(p, { detail = "", confirming = null, sent = null } = {}) {
  const columns = p.columns || [];
  const chosen = p.assessment;
  const parts = [
    '<section class="state state-ca" data-state="ca">',
    `<p><a href="#${esc(p.test_id)}">Back to the results</a></p>`,
    "<h1>Send to CA</h1>",
    p.title ? `<p class="hint">${esc(p.title)}</p>` : "",
    "<p>Turn the test scores into marks in one CA column, for the classes you teach.</p>",
    note(detail),
  ];
  if (!columns.length) {
    parts.push('<p class="blank">This subject has no CA column this term. Columns are set on Teaching.</p></section>');
    return parts.join("");
  }
  parts.push(
    '<form data-form="ca-preview" class="ca-form">',
    '<label for="assessment">CA column</label>',
    `<select id="assessment" name="assessment">${columns.map((c) => `<option value="${esc(c.id)}"${chosen && chosen.id === c.id ? " selected" : ""}>${esc(c.name)}, out of ${esc(c.max_score)}</option>`).join("")}</select>`,
    "<fieldset><legend>Students who already have a mark in the column</legend>",
    `<label class="choice"><input type="radio" name="existing" value="keep"${!p.existing || p.existing === "keep" ? " checked" : ""}> <span>Keep their mark<span class="hint">Nothing they have is changed.</span></span></label>`,
    `<label class="choice"><input type="radio" name="existing" value="replace"${p.existing === "replace" ? " checked" : ""}> <span>Replace it with the test mark<span class="hint">Each change shows on the marking sheet with your name.</span></span></label>`,
    "</fieldset>",
    '<p class="hint">Scaled to the column, to the nearest whole mark, halves up. A student who did not sit gets no mark, not a zero.</p>',
    '<button type="submit" class="submit">Preview</button>',
    "</form>",
  );
  if (sent) {
    parts.push(
      `<p class="done" role="status">Sent to ${esc(sent.assessment)}: ${plural(sent.counts.written, "mark", "marks")} written, ${esc(sent.counts.kept)} kept, ${esc(sent.counts.not_sat)} did not sit, ${esc(sent.counts.locked)} locked, ${esc(sent.counts.changed_meanwhile)} changed meanwhile and not sent.</p>`,
      sent.lines.some((l) => l.outcome === "changed_meanwhile" || l.outcome === "locked")
        ? `<ul class="history">${sent.lines.filter((l) => l.outcome === "changed_meanwhile" || l.outcome === "locked").map((l) => `<li>${esc(l.name)}: ${esc(l.outcome_label)}. ${esc(l.detail)}</li>`).join("")}</ul>`
        : "",
      `<p><a class="btn btn-quiet" href="#${esc(p.test_id)}">Back to the results</a></p>`,
      "</section>",
    );
    return parts.join("");
  }
  if (!chosen) return [...parts, "</section>"].join("");
  const n = toWrite(p);
  const c = p.counts;
  parts.push(
    "<h2>What will happen</h2>",
    `<p class="hint">Nothing is written until you send. ${esc(chosen.name)} is out of ${esc(chosen.max_score)}; the test is out of ${esc(p.out_of)}.</p>`,
    ...p.locked_classes.map((l) => `<p class="msg"><span class="label label-stop">${esc(l.class_name)} cannot take marks now</span> Its results are ${esc(l.state === "released" ? "released" : l.state)}. Ask for them to be sent back, then send again.</p>`),
    p.lines.length ? `<table class="stack ca-lines"><thead><tr><th>Student</th><th>Class</th><th>Test</th><th>CA mark</th><th>In the column now</th></tr></thead><tbody>${p.lines.map(caLine).join("")}</tbody></table>` : '<p class="blank">Nobody in your classes sits this test.</p>',
    `<dl class="ca-counts"><div><dt>New marks</dt><dd>${esc(c.new || 0)}</dd></div><div><dt>Replaced</dt><dd>${esc(c.replace || 0)}</dd></div><div><dt>Kept as they are</dt><dd>${esc((c.kept || 0) + (c.same || 0))}</dd></div><div><dt>Did not sit, no mark</dt><dd>${esc(c.not_sat || 0)}</dd></div><div><dt>Locked, not sent</dt><dd>${esc(c.locked || 0)}</dd></div></dl>`,
  );
  if (!n) parts.push('<p class="hint">There is nothing to write.</p>');
  else if (confirming === "send") {
    parts.push(
      '<form data-form="ca-send" class="confirm">',
      `<p>Send ${plural(n, "mark", "marks")} to ${esc(chosen.name)}? They go onto the marking sheet like any mark you type, and reach report cards only through the class&#39;s results.</p>`,
      p.replaces_by_hand && p.existing === "replace"
        ? `<label class="choice"><input type="checkbox" name="confirm_replace" required> <span>Replace the ${plural(p.replaces_by_hand, "mark", "marks")} typed on the marking sheet, shown above</span></label>`
        : "",
      `<button type="submit" class="submit">Send ${plural(n, "mark", "marks")}</button><button type="button" class="again" data-action="keep">Go back</button>`,
      "</form>",
    );
  } else {
    parts.push(`<p><button type="button" class="submit" data-action="ask-send">Send ${plural(n, "mark", "marks")}</button></p>`);
  }
  parts.push("</section>");
  return parts.join("");
}

// -- refusals ----------------------------------------------------------------------------------

export function notYours({ detail = "" } = {}) {
  return `<section class="state state-refused" role="alert"><h1>This page is not yours</h1><p>${esc(detail) || "A test&#39;s results are read by its teachers, the principal and the vice principal."}</p><p><a href="../">Tests</a></p></section>`;
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
