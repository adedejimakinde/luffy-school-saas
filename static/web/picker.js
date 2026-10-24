/**
 * What every `<select>` opens: a sheet on a phone, a popover on a desk.
 * **The select stays the field** (label, submit, validation); only its
 * opening is taken over, and a choice is written back with `input` and
 * `change`. `docs/design.md` ("The picker") says the rest.
 */

/** More options than this gets a search box. */
export const SEARCH_ABOVE = 8;
const PHONE = "(max-width: 639.98px)";
const OPENERS = new Set([" ", "Enter", "ArrowDown", "ArrowUp", "F4", "Home", "End", "PageUp", "PageDown"]);

/** "  Ìfé (SS 2)" is "ife ss 2": no case, accents or punctuation. */
export function fold(text) {
  return String(text ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
}

export function rowsOf(select) {
  const rows = [];
  Array.from(select.options).forEach((option, index) => {
    if (option.hidden) return;
    const group = option.parentElement && option.parentElement.tagName === "OPTGROUP" ? option.parentElement : null;
    const label = String(option.label || option.textContent || "").replace(/\s+/g, " ").trim();
    const heading = group ? String(group.label || "") : "";
    const disabled = Boolean(option.disabled || (group && group.disabled));
    rows.push({ index, label, group: heading, disabled, hay: fold(`${label} ${heading}`) });
  });
  return rows;
}

/** Each typed word starts a word of the row or its group: "ss 2" is not JSS 2A. */
export function filterRows(rows, query) {
  const words = fold(query).split(" ").filter(Boolean);
  return rows.filter((row) => words.every((word) => row.hay.split(" ").some((part) => part.startsWith(word))));
}

/** Type to jump: the next enabled row after `from` starting with `typed`; a letter again moves on. */
export function nextMatch(rows, typed, from = -1) {
  const q = fold(typed);
  if (!q || !rows.length) return -1;
  const again = [...q].every((c) => c === q[0]);
  const start = again ? from + 1 : Math.max(from, 0);
  for (let k = 0; k < rows.length; k++) {
    const i = (start + k) % rows.length;
    if (!rows[i].disabled && fold(rows[i].label).startsWith(again ? q[0] : q)) return i;
  }
  return -1;
}

/** The field's label, less the select's own text; else its aria-label. */
export function labelOf(select) {
  const label = select.labels && select.labels[0];
  if (label) {
    const copy = label.cloneNode(true);
    copy.querySelectorAll("select, .hint").forEach((node) => node.remove());
    const text = copy.textContent.replace(/\s+/g, " ").trim();
    if (text) return text;
  }
  return (select.getAttribute("aria-label") || "").trim() || "Choose one";
}

function el(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (name === "text") node.textContent = value;
    else node.setAttribute(name, value);
  }
  node.append(...children);
  return node;
}

function icon(d) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  const path = document.createElementNS(ns, "path");
  svg.setAttribute("class", "icon");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  path.setAttribute("d", d);
  svg.append(path);
  return svg;
}

let ui = null; // the one dialog
let state = null; // what is open

function build() {
  const title = el("h2", { class: "picker-title", id: "picker-title" });
  const shut = el("button", { type: "button", class: "icon-button", "aria-label": "Close", tabindex: "-1" }, icon("M6 6l12 12M18 6L6 18"));
  const input = el("input", {
    type: "search", role: "combobox", "aria-controls": "picker-list", "aria-autocomplete": "list",
    "aria-expanded": "true", autocomplete: "off", spellcheck: "false", enterkeyhint: "done", placeholder: "Search",
  });
  const search = el("div", { class: "picker-search" }, icon("M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13zM15.5 15.5L20 20"), input);
  const list = el("div", { class: "picker-list", id: "picker-list", role: "listbox", tabindex: "0", "aria-labelledby": "picker-title" });
  const empty = el("p", { class: "picker-empty", hidden: "" });
  const status = el("p", { class: "sr", "aria-live": "polite" });
  const head = el("div", { class: "picker-head" }, el("div", { class: "picker-handle" }), title, shut);
  const dialog = el("dialog", { class: "picker", "aria-labelledby": "picker-title" }, head, search, list, empty, status);

  dialog.addEventListener("keydown", onKey);
  // A phone's back gesture.
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    close();
  });
  // Queued by `dialog.close()`: stale if the picker has opened again since.
  dialog.addEventListener("close", () => dialog.open || close());
  // The backdrop.
  dialog.addEventListener("click", (event) => event.target === dialog && close());
  shut.addEventListener("click", () => close());
  input.addEventListener("input", filter);
  list.addEventListener("click", (event) => {
    const row = rowAt(event.target);
    if (row && !row.disabled) close(row);
  });
  list.addEventListener("pointermove", (event) => {
    const row = rowAt(event.target);
    if (event.pointerType !== "mouse" || !row || row.disabled || row === state.active) return;
    state.keys = false;
    activate(row);
  });
  head.addEventListener("pointerdown", drag);
  document.body.append(dialog);
  return { dialog, title, input, search, list, empty, status };
}

function rowAt(target) {
  const node = target.closest && target.closest('[role="option"]');
  return node && state ? state.rows[node.dataset.row] : null;
}

function open(select, how, typed) {
  const rows = rowsOf(select);
  if (state || !rows.length) return;
  ui = ui || build();
  const phone = matchMedia(PHONE).matches;
  const searching = rows.length > SEARCH_ABOVE;
  state = { select, rows, shown: rows, active: null, keys: how === "keys", searching, phone, typed: "", typedAt: 0 };

  ui.title.textContent = labelOf(select);
  ui.input.value = "";
  ui.input.setAttribute("aria-label", `Search ${ui.title.textContent}`);
  ui.search.hidden = !searching;
  ui.empty.hidden = true;
  ui.status.textContent = "";
  ui.list.replaceChildren();
  let box = null;
  rows.forEach((row, n) => {
    if (!n || row.group !== rows[n - 1].group) {
      box = row.group
        ? el("div", { class: "picker-group", role: "group", "aria-labelledby": `picker-g${n}` },
            el("div", { class: "picker-group-label", id: `picker-g${n}`, role: "presentation", text: row.group }))
        : null;
      if (box) ui.list.append(box);
    }
    row.node = el("div", { class: "picker-option", role: "option", id: `picker-o${n}`, "aria-selected": String(row.index === select.selectedIndex), "data-row": n },
      el("span", { text: row.label }), icon("M5 12.5l4.5 4.5L19 7.5"));
    if (row.disabled) row.node.setAttribute("aria-disabled", "true");
    (box || ui.list).append(row.node);
  });

  ui.dialog.className = `picker ${phone ? "picker-sheet" : "picker-pop"}`;
  layout();
  ui.dialog.showModal();
  addEventListener("resize", layout);
  addEventListener("scroll", layout);
  if (window.visualViewport) visualViewport.addEventListener("resize", layout);
  // A phone's search waits for a tap, so its keyboard does not cover the list.
  const typing = searching && (how === "keys" || !matchMedia("(pointer: coarse)").matches);
  (typing ? ui.input : ui.list).focus({ preventScroll: true });
  activate(rows.find((row) => row.index === select.selectedIndex && !row.disabled) || rows.find((row) => !row.disabled) || null);
  if (state.active) state.active.node.scrollIntoView({ block: "center" });
  if (typed) typeKey(typed);
}

/** Back to the field, choosing `row` if given. */
function close(row = null) {
  const was = state;
  if (!was) return;
  state = null;
  removeEventListener("resize", layout);
  removeEventListener("scroll", layout);
  if (window.visualViewport) visualViewport.removeEventListener("resize", layout);
  if (ui.dialog.open) ui.dialog.close();
  const { select } = was;
  if (select.isConnected) select.focus({ preventScroll: true });
  if (row && !row.disabled && row.index !== select.selectedIndex) {
    select.selectedIndex = row.index;
    select.dispatchEvent(new Event("input", { bubbles: true }));
    select.dispatchEvent(new Event("change", { bubbles: true }));
  }
}

/** A sheet clear of the keyboard; a popover under the field, or over it near the foot. */
function layout() {
  if (!state) return;
  if (state.phone !== matchMedia(PHONE).matches || !state.select.isConnected) return close();
  const style = ui.dialog.style;
  const px = (n) => `${Math.round(n)}px`;
  if (state.phone) {
    const view = window.visualViewport;
    style.setProperty("--keyboard", px(view ? Math.max(0, innerHeight - view.height - view.offsetTop) : 0));
    return;
  }
  const field = state.select.getBoundingClientRect();
  const width = Math.min(Math.max(field.width, 240), innerWidth - 16);
  const below = innerHeight - field.bottom - 12;
  const above = field.top - 12;
  const up = below < 240 && above > below;
  style.setProperty("--left", px(Math.min(Math.max(field.left, 8), innerWidth - width - 8)));
  style.setProperty("--width", px(width));
  style.setProperty("--room", px(Math.max(Math.min(up ? above : below, 420), 120)));
  style.top = up ? "auto" : px(field.bottom + 4);
  style.bottom = up ? px(innerHeight - field.top + 4) : "auto";
}

function activate(row, scroll = false) {
  if (state.active) state.active.node.classList.remove("is-active");
  state.active = row;
  ui.dialog.classList.toggle("picker-keys", state.keys);
  for (const host of [ui.list, ui.input]) {
    if (row) host.setAttribute("aria-activedescendant", row.node.id);
    else host.removeAttribute("aria-activedescendant");
  }
  if (!row) return;
  row.node.classList.add("is-active");
  if (scroll) row.node.scrollIntoView({ block: "nearest" });
}

function filter() {
  const query = ui.input.value;
  const shown = new Set((state.shown = filterRows(state.rows, query)));
  for (const row of state.rows) row.node.hidden = !shown.has(row);
  for (const box of ui.list.querySelectorAll(".picker-group")) box.hidden = !box.querySelector('[role="option"]:not([hidden])');
  const n = shown.size;
  ui.empty.hidden = n > 0;
  ui.empty.textContent = `Nothing matches "${query.trim()}".`;
  ui.status.textContent = !fold(query) ? "" : n === 1 ? "1 match" : `${n || "No"} matches`;
  if (!shown.has(state.active)) activate(state.shown.find((row) => !row.disabled) || null, true);
}

function typeKey(key) {
  if (state.searching) {
    ui.input.value += key;
    ui.input.focus({ preventScroll: true });
    return filter();
  }
  const enabled = state.shown.filter((row) => !row.disabled);
  const now = Date.now();
  state.typed = now - state.typedAt > 600 ? key : state.typed + key;
  state.typedAt = now;
  const at = nextMatch(enabled, state.typed, enabled.indexOf(state.active));
  if (at < 0) return;
  state.keys = true;
  activate(enabled[at], true);
}

function onKey(event) {
  if (!state) return;
  const { key } = event;
  const inInput = event.target === ui.input;
  const enabled = state.shown.filter((row) => !row.disabled);
  const last = enabled.length - 1;
  const at = enabled.indexOf(state.active);
  const choose = () => state.active && close(state.active);
  let to;
  if (key === "ArrowDown") to = at < 0 ? 0 : Math.min(at + 1, last);
  else if (key === "ArrowUp" && event.altKey) to = choose();
  else if (key === "ArrowUp") to = at < 0 ? last : Math.max(at - 1, 0);
  else if (key === "PageDown") to = Math.min(Math.max(at, 0) + 10, last);
  else if (key === "PageUp") to = Math.max(at - 10, 0);
  else if ((key === "Home" || key === "End") && !inInput) to = key === "Home" ? 0 : last;
  else if (key === "Enter" || (key === " " && !inInput)) to = choose();
  else if (key === "Escape" || key === "Tab") to = close();
  else if (!inInput && key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) to = typeKey(key);
  else return;
  event.preventDefault();
  if (to == null || to < 0 || !state) return;
  state.keys = true;
  activate(enabled[to], true);
}

/** A swipe down on the sheet's head closes it. */
function drag(event) {
  if (!state || !state.phone || event.pointerType === "mouse" || event.target.closest("button")) return;
  const { dialog } = ui;
  const from = event.clientY;
  const began = event.timeStamp;
  let moved = 0;
  const move = (m) => {
    moved = Math.max(0, m.clientY - from);
    dialog.style.transform = `translateY(${moved}px)`;
  };
  const end = (e) => {
    dialog.removeEventListener("pointermove", move);
    dialog.removeEventListener("pointerup", end);
    dialog.removeEventListener("pointercancel", end);
    if (e.type === "pointerup" && (moved > 96 || (moved > 24 && moved / (e.timeStamp - began || 1) > 0.5))) close();
    dialog.classList.remove("is-dragging");
    dialog.style.transform = "";
  };
  dialog.classList.add("is-dragging");
  dialog.setPointerCapture(event.pointerId);
  dialog.addEventListener("pointermove", move);
  dialog.addEventListener("pointerup", end);
  dialog.addEventListener("pointercancel", end);
}

function selectAt(target) {
  const select = target && target.closest ? target.closest("select") : null;
  return select && !select.multiple && select.size < 2 && !select.disabled && !select.hasAttribute("data-native") ? select : null;
}

/** The picker, else the system menu. */
function start(select, how, typed = "") {
  try {
    open(select, how, typed);
  } catch {
    state = null;
    if (ui && ui.dialog.open) ui.dialog.close();
    try {
      select.showPicker();
    } catch {
      select.focus();
    }
  }
}

/** Every select under `root`, now and after any redraw, opens the picker. */
export function enhanceSelects(root) {
  if (!root || typeof HTMLDialogElement === "undefined" || !HTMLDialogElement.prototype.showModal) return;
  let touch = null;
  root.addEventListener("mousedown", (event) => {
    const select = selectAt(event.target);
    if (!select || event.button !== 0) return;
    event.preventDefault();
    start(select, "pointer");
  });
  // A tap, not a scroll; cancelled, it opens no system menu.
  root.addEventListener("touchstart", (event) => {
    const t = event.changedTouches[0];
    touch = selectAt(event.target) && t ? [t.clientX, t.clientY] : null;
  }, { passive: true });
  root.addEventListener("touchend", (event) => {
    const select = selectAt(event.target);
    const t = event.changedTouches[0];
    if (!select || !touch || !t || Math.hypot(t.clientX - touch[0], t.clientY - touch[1]) > 10) return;
    touch = null;
    event.preventDefault();
    start(select, "pointer");
  });
  root.addEventListener("keydown", (event) => {
    const select = selectAt(event.target);
    if (!select || event.ctrlKey || event.metaKey) return;
    const typed = event.key.length === 1 && event.key !== " " && !event.altKey ? event.key : "";
    if (!typed && !OPENERS.has(event.key)) return;
    event.preventDefault();
    start(select, "keys", typed);
  });
}
