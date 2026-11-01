/**
 * The website's look at `/website/look/`: its colours and its animated backgrounds
 * (`docs/school-sites-theme-modern.md`). The principal's, like the theme itself.
 *
 * A frame of its own beside the editor at `/website/`, so each stays within the 150 KB a page may
 * cost before it draws (`tests/test_budget.py`). Four colours: the main one (from the crest), the
 * accent of the main buttons, the gold detail of the line art, and the dark band. The pale panels
 * are worked out from them by the server. Each colour can go back to the theme's own (the main one
 * to the report card's). The five animated backgrounds are each switched on or off.
 *
 * The page says at once, as a colour is picked, whether writing will read on it, by the same
 * rules the server holds every save to (`schoolsite/themes.py`); the server is the judge, and a
 * refusal comes back as the school's own sentence under the form. Nothing is kept in the browser.
 */

import { esc } from "../web/html.js";
import { putJson } from "../web/http.js";
import { REFUSAL, classify, fetchOverview } from "./api.js";

const ROLES = [
  ["primary", "Main colour", "From the crest. The header, the admissions band and links. White writing goes on it."],
  ["accent", "Accent", "The main buttons, like Apply now. Dark writing goes on it."],
  ["detail", "Detail", "The gold of the line art. Decoration only."],
  ["dark", "Dark band", "The one dark band. White writing goes on it."],
];
const WHITE = "#FFFFFF";
const UNSAVED = "You have unsaved changes. Leave anyway?";

function luminance(hex) {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const [r, g, b] = c.map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** WCAG contrast between two `#RRGGBB` colours. */
export function contrast(a, b) {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
}

/** What will not read with these colours: one sentence per role, the server's rules. */
export function problems(c) {
  const out = {};
  if (contrast(WHITE, c.primary) < 4.5) out.primary = "Too light: white writing on it would be hard to read.";
  if (contrast(c.dark, c.accent) < 4.5) out.accent = "The dark writing on these buttons would be hard to read.";
  if (contrast(WHITE, c.dark) < 4.5) out.dark = "Too light: white writing on the band would be hard to read.";
  if (contrast(c.detail, c.dark) < 3) out.detail = "It would not show on the dark band.";
  return out;
}

const HEX = /^#[0-9A-F]{6}$/;

/** The colours the form shows: what is typed, else what the site draws now. */
export function coloursOf(values, look) {
  const out = {};
  for (const [role] of ROLES) {
    const typed = String(values[role] || "").toUpperCase();
    out[role] = HEX.test(typed) ? typed : look.palette[role];
  }
  return out;
}

/** What a save sends: each colour changed from what is chosen, and every switch. */
export function changeFrom(values, look) {
  const colours = {};
  for (const [role] of ROLES) {
    const typed = String(values[role] || "").toUpperCase();
    if (values[`${role}_reset`]) colours[role] = "";
    else if (HEX.test(typed) && typed !== String(look.chosen[role] || "").toUpperCase() && typed !== look.palette[role]) colours[role] = typed;
  }
  const animations = {};
  for (const name of Object.keys(look.animation_names)) animations[name] = Boolean(values[`anim_${name}`]);
  return { colours, animations };
}

function swatches(c) {
  return [
    '<div class="look-sample" aria-hidden="true">',
    `<span class="chip" data-chip="primary">Main</span>`,
    `<span class="chip" data-chip="accent">Apply now</span>`,
    `<span class="chip" data-chip="dark">Band <i data-chip="detail"></i></span>`,
    "</div>",
    `<p class="hint">Now: main ${esc(c.primary)}, accent ${esc(c.accent)}, detail ${esc(c.detail)}, dark band ${esc(c.dark)}.</p>`,
  ].join("");
}

export function htmlFor(state) {
  const back = '<p><a class="btn" href="/website/">Back to the website editor</a></p>';
  if (state.step !== "look") {
    const words = {
      [REFUSAL.NOT_YOURS]: "The school&#39;s website is looked after by its principal.",
      [REFUSAL.WRONG_HOST]: "Open the website editor on your school&#39;s own address.",
      [REFUSAL.SIGNED_OUT]: 'Please <a href="/staff-sign-in/?next=/website/look/">sign in</a> to change the website&#39;s look.',
      [REFUSAL.EXPIRED]: 'You were signed out after a while away. <a href="/staff-sign-in/?next=/website/look/">Sign in</a>.',
    }[state.step] || 'Something went wrong. <button type="button" data-action="reload">Try again</button>';
    return `<section class="state state-refused" data-state="${esc(state.step)}"><h1>Colours and animations</h1><p>${words}</p></section>`;
  }
  const body = state.body;
  if (!body.can_publish) {
    return `<section class="state" data-state="look"><h1>Colours and animations</h1>${back}<p class="hint">Only the principal changes the website&#39;s colours and animations.</p></section>`;
  }
  const look = body.look;
  const shown = coloursOf(state.values || {}, look);
  const issues = problems(shown);
  const note = state.note ? `<p class="refused" role="alert">${esc(state.note)}${state.stale ? ' <button type="button" data-action="reload">Reload</button>' : ""}</p>` : "";
  const done = state.done ? `<p class="done" role="status">${esc(state.done)} Publish the website for families to see it.</p>` : "";
  const roles = ROLES.map(([role, label, hint]) => {
    const own = look.chosen[role];
    const reset = own ? `<label class="check"><input type="checkbox" name="${role}_reset"> Go back to ${role === "primary" ? "the report card&#39;s colour" : "the theme&#39;s own"}</label>` : "";
    // Always there, empty while the colour is fine, so a pick can say at once what will not read.
    const issue = `<span class="refused" id="look-${role}-issue" aria-live="polite">${esc(issues[role] || "")}</span>`;
    return [
      `<div class="row-group"><label for="look-${role}">${esc(label)}</label><span class="hint">${esc(hint)}</span>`,
      `<input type="color" id="look-${role}" name="${role}" value="${esc(shown[role].toLowerCase())}" aria-describedby="look-${role}-issue">`,
      `${issue}${reset}</div>`,
    ].join("");
  }).join("");
  const switches = Object.entries(look.animation_names).map(([name, label]) => {
    const on = state.values && `anim_${name}` in state.values ? state.values[`anim_${name}`] : look.animations[name];
    return `<label class="check"><input type="checkbox" name="anim_${name}"${on ? " checked" : ""}> ${esc(label)}</label>`;
  }).join("");
  return [
    '<section class="state state-look" data-state="look">',
    `<h1>Colours and animations</h1>${back}${done}`,
    `<p class="hint">The ${esc(look.theme)} theme. Changes go live when you publish the website.</p>`,
    '<form data-form="look">',
    `<h2>Colours</h2>${swatches(shown)}${roles}`,
    `<h2>Animated backgrounds</h2><p class="hint">Slow, faint line art behind the words. They never move for visitors who ask their phone for less motion.</p>${switches}`,
    note,
    `<button type="submit"${Object.keys(issues).length ? " disabled" : ""}>Save</button>`,
    "</form></section>",
  ].join("");
}

/** A form's fields as name to value; a checkbox's value is whether it is ticked. */
export function valuesOf(form) {
  const values = {};
  for (const el of Array.from(form.elements || [])) {
    if (el.name) values[el.name] = el.type === "checkbox" ? Boolean(el.checked) : el.value;
  }
  return values;
}

function fromAnswer(answer, kept = {}) {
  if (!answer.ok) return { step: answer.refusal || REFUSAL.BROKEN, body: answer.body || {} };
  return { step: "look", body: answer.body, values: null, note: "", stale: false, ...kept };
}

export async function mount(root, { fetchImpl = fetch, win = null } = {}) {
  let state = fromAnswer(await fetchOverview({ fetchImpl }));
  let dirty = false;
  // The chips, the sentences and Save follow the form as it is picked, without drawing it again
  // (which would close a phone's colour picker). Colours are set as properties, never as markup.
  const follow = (values) => {
    if (state.step !== "look" || !state.body.can_publish) return;
    const shown = coloursOf(values, state.body.look);
    const issues = problems(shown);
    root.querySelectorAll("[data-chip]").forEach((chip) => chip.style.setProperty("--chip", shown[chip.dataset.chip]));
    for (const [role] of ROLES) {
      const line = root.querySelector(`#look-${role}-issue`);
      if (line) line.textContent = issues[role] || "";
    }
    const save = root.querySelector("form [type=submit]");
    if (save) save.disabled = Object.keys(issues).length > 0;
  };
  const draw = () => {
    root.innerHTML = htmlFor(state);
    follow(state.values || {});
  };
  draw();
  root.addEventListener("input", (event) => {
    const form = event.target.closest("form");
    if (!form) return;
    dirty = true;
    state = { ...state, values: valuesOf(form), done: "" };
    follow(state.values);
  });
  root.addEventListener("click", async (event) => {
    if (event.target.closest("[data-action=reload]")) {
      state = fromAnswer(await fetchOverview({ fetchImpl }));
      dirty = false;
      draw();
    }
  });
  root.addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = valuesOf(event.target);
    const change = changeFrom(values, state.body.look);
    const answer = classify(await putJson("/api/website/look/", { version: state.body.version, ...change }, { fetchImpl }).catch(
      (error) => ({ status: 0, body: { detail: String(error) } }),
    ));
    if (answer.ok) {
      dirty = false;
      state = fromAnswer(answer, { done: "Saved." });
    } else if (answer.rejected) {
      state = { ...state, values, note: answer.body.detail || "That could not be saved.", stale: answer.stale };
    } else {
      state = fromAnswer(answer);
    }
    draw();
  });
  if (win) {
    win.addEventListener("beforeunload", (event) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = UNSAVED;
      }
    });
  }
  return { get state() { return state; } };
}

if (typeof document !== "undefined" && document.getElementById("website-look")) {
  mount(document.getElementById("website-look"), { win: window });
}
