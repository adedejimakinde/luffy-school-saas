/** Day-first date fields: a one-line button and a calendar sheet. `docs/design.md`, "Dates". */
const MONTHS = "January February March April May June July August September October November December".split(" ");
const DAYS = "Sunday Monday Tuesday Wednesday Thursday Friday Saturday".split(" ");
const PHONE = "(max-width: 639.98px)";
const ZONE = "Africa/Lagos";
const pad = (n) => String(n).padStart(2, "0");
const short = (s) => s.slice(0, 3);

/** "2026-11-12" as {y, m, d}; anything else, or a day that is not on the calendar, as null. */
export function parse(text) {
  const found = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(text ?? ""));
  if (!found) return null;
  const [y, m, d] = [Number(found[1]), Number(found[2]), Number(found[3])];
  const real = new Date(Date.UTC(y, m - 1, d));
  return real.getUTCMonth() === m - 1 && real.getUTCDate() === d ? { y, m, d } : null;
}
export const iso = ({ y, m, d }) => `${y}-${pad(m)}-${pad(d)}`;
const utc = ({ y, m, d }) => Date.UTC(y, m - 1, d);
export const shift = (day, n) => {
  const t = new Date(utc(day) + n * 864e5);
  return { y: t.getUTCFullYear(), m: t.getUTCMonth() + 1, d: t.getUTCDate() };
};
const daysIn = (y, m) => new Date(Date.UTC(y, m, 0)).getUTCDate();
const weekday = (day) => new Date(utc(day)).getUTCDay();

/** Today in the school's zone, as `yyyy-mm-dd`: Lagos is an hour ahead of Greenwich, and a register is the school's day. */
export function todayIn(zone = ZONE, now = new Date()) {
  try {
    return new Intl.DateTimeFormat("en-CA", { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
  } catch {
    return iso({ y: now.getFullYear(), m: now.getMonth() + 1, d: now.getDate() });
  }
}

/** "Today, Thu 12 Nov" near today; else "Wed 4 Nov 2026" (no weekday for a birthday: "4 Nov 2012"). */
export function say(value, today, { weekdays = true } = {}) {
  const day = parse(value);
  if (!day) return "";
  const near = { 0: "Today", "-1": "Yesterday", 1: "Tomorrow" }[Math.round((utc(day) - utc(parse(today))) / 864e5)];
  const name = `${weekdays ? `${short(DAYS[weekday(day)])} ` : ""}${day.d} ${short(MONTHS[day.m - 1])}`;
  return near && weekdays ? `${near}, ${name}` : `${name} ${day.y}`;
}

/** A month as Monday-first weeks: a day, or null where the week spills into the next or last month. */
export function cells(y, m) {
  const lead = (weekday({ y, m, d: 1 }) + 6) % 7;
  const total = Math.ceil((lead + daysIn(y, m)) / 7) * 7;
  return Array.from({ length: total }, (_, i) => (i >= lead && i < lead + daysIn(y, m) ? { y, m, d: i - lead + 1 } : null));
}

/** Whether `day` is within [min, max] (either may be empty). */
export const within = (day, min, max) => (!min || iso(day) >= min) && (!max || iso(day) <= max);

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
const CALENDAR = "M5 6h14v13H5zM5 10h14M9 4v4M15 4v4";
const PREVIOUS = "M15 6l-6 6 6 6";
const NEXT = "M9 6l6 6-6 6";

let ui = null; // the one dialog
let open = null; // what is open: { field, step, view, at, phone }

function build() {
  const title = el("h2", { class: "date-title", id: "date-title" });
  const shut = el("button", { type: "button", class: "icon-button", "aria-label": "Close" }, icon("M6 6l12 12M18 6L6 18"));
  const head = el("div", { class: "date-head" }, el("div", { class: "date-handle" }), title, shut);
  const body = el("div", { class: "date-body" });
  const status = el("p", { class: "sr", "aria-live": "polite" });
  const dialog = el("dialog", { class: "date-sheet", "aria-labelledby": "date-title" }, head, body, status);
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    close();
  });
  dialog.addEventListener("close", () => dialog.open || close());
  dialog.addEventListener("click", (event) => event.target === dialog && close());
  shut.addEventListener("click", () => close());
  dialog.addEventListener("click", onClick);
  dialog.addEventListener("keydown", onKey);
  document.body.append(dialog);
  return { dialog, title, body, status };
}

/** The years a birthday may be in: newest first. */
function yearsOf(field) {
  const [hi, lo] = [field.max ? parse(field.max).y : parse(field.today).y, field.min ? parse(field.min).y : parse(field.today).y - 30];
  const own = (parse(field.native.value) || {}).y;
  const [top, bottom] = [Math.max(hi, own || hi), Math.min(lo, own || lo)];
  return Array.from({ length: top - bottom + 1 }, (_, i) => top - i);
}

const monthOpen = (field, y, m) => (!field.min || iso({ y, m, d: daysIn(y, m) }) >= field.min) && (!field.max || iso({ y, m, d: 1 }) <= field.max);

function draw(focus = true) {
  const { field, step, view } = open;
  const value = parse(field.native.value);
  const today = parse(field.today);
  const { body } = ui;
  const kids = [];
  const crumbs = () =>
    el("div", { class: "date-crumbs" },
      el("button", { type: "button", "data-step": "year", text: String(view.y) }),
      step === "day" ? el("button", { type: "button", "data-step": "month", text: MONTHS[view.m - 1] }) : "");
  let aim = null;
  if (step === "year") {
    const years = yearsOf(field);
    const grid = el("div", { class: "date-pick", "data-cols": "4", role: "group", "aria-label": "Year" });
    const at = years.includes((value || {}).y) ? value.y : years.includes(view.y) ? view.y : years[0];
    for (const y of years) {
      const b = el("button", { type: "button", "data-year": y, text: String(y), tabindex: y === at ? "0" : "-1", "aria-pressed": String(value ? value.y === y : false) });
      grid.append(b);
      if (y === at) aim = b;
    }
    kids.push(grid);
  } else if (step === "month") {
    kids.push(crumbs());
    const grid = el("div", { class: "date-pick", "data-cols": "3", role: "group", "aria-label": "Month" });
    const at = open.at && open.at.y === view.y ? open.at.m : view.m;
    MONTHS.forEach((name, i) => {
      const ok = monthOpen(field, view.y, i + 1);
      const b = el("button", { type: "button", "data-month": i + 1, text: short(name), tabindex: i + 1 === at ? "0" : "-1", "aria-pressed": String(Boolean(value) && value.y === view.y && value.m === i + 1) });
      if (!ok) b.setAttribute("aria-disabled", "true");
      grid.append(b);
      if (i + 1 === at) aim = b;
    });
    kids.push(grid);
  } else {
    const first = { y: view.y, m: view.m, d: 1 };
    const last = { ...first, d: daysIn(view.y, view.m) };
    const before = !field.birth && (!field.min || iso(first) > field.min);
    const after = !field.birth && (!field.max || iso(last) < field.max);
    kids.push(
      field.birth
        ? crumbs()
        : el("div", { class: "date-month" },
            el("button", { type: "button", class: "icon-button", "data-move": "-1", "aria-label": "Previous month", ...(before ? {} : { "aria-disabled": "true" }) }, icon(PREVIOUS)),
            el("h3", { class: "date-month-name", "aria-live": "polite", text: `${MONTHS[view.m - 1]} ${view.y}` }),
            el("button", { type: "button", class: "icon-button", "data-move": "1", "aria-label": "Next month", ...(after ? {} : { "aria-disabled": "true" }) }, icon(NEXT)),
          ),
    );
    const grid = el("div", { class: "date-grid", role: "grid", "aria-label": `${MONTHS[view.m - 1]} ${view.y}` });
    const heads = el("div", { class: "date-week date-heads", role: "row" });
    [1, 2, 3, 4, 5, 6, 0].forEach((n) => heads.append(el("span", { role: "columnheader", "aria-label": DAYS[n], text: DAYS[n].slice(0, 2) })));
    grid.append(heads);
    const all = cells(view.y, view.m);
    const want = open.at && open.at.y === view.y && open.at.m === view.m ? open.at.d : value && value.y === view.y && value.m === view.m ? value.d : within(today, field.min, field.max) && today.y === view.y && today.m === view.m ? today.d : 0;
    const enabled = all.filter((c) => c && within(c, field.min, field.max));
    const fallback = (enabled.find((c) => c.d >= want) || enabled[0] || { d: 1 }).d;
    for (let week = 0; week < all.length; week += 7) {
      const row = el("div", { class: "date-week", role: "row" });
      for (const day of all.slice(week, week + 7)) {
        if (!day) {
          row.append(el("span", { role: "gridcell", "aria-hidden": "true" }));
          continue;
        }
        const ok = within(day, field.min, field.max);
        const mine = value && iso(value) === iso(day);
        const b = el("button", {
          type: "button", role: "gridcell", class: "date-day", "data-day": iso(day), text: String(day.d),
          "aria-label": `${DAYS[weekday(day)]} ${day.d} ${MONTHS[day.m - 1]} ${day.y}`, "aria-selected": String(Boolean(mine)),
          tabindex: day.d === (want || fallback) ? "0" : "-1",
        });
        if (!ok) b.setAttribute("aria-disabled", "true");
        if (iso(day) === field.today) {
          b.classList.add("is-today");
          b.setAttribute("aria-current", "date");
        }
        if (day.d === (want || fallback)) aim = b;
        row.append(b);
      }
      grid.append(row);
    }
    kids.push(grid);
  }
  if (!field.native.required && !field.recent && field.native.value && step === "day") {
    kids.push(el("button", { type: "button", class: "date-clear", "data-clear": "1", text: "Clear the date" }));
  }
  body.replaceChildren(...kids);
  ui.status.textContent = step === "day" ? `${MONTHS[view.m - 1]} ${view.y}` : step === "month" ? `Choose a month in ${view.y}` : "Choose a year";
  if (focus && aim) aim.focus({ preventScroll: true });
  if (aim && step !== "day") aim.scrollIntoView({ block: "center" });
}

function show(field) {
  if (open) return;
  ui = ui || build();
  const value = parse(field.native.value);
  const today = parse(field.today);
  const base = value || (within(today, field.min, field.max) ? today : parse(field.min) || (parse(field.max) && { ...parse(field.max), d: 1 }) || today);
  open = { field, view: { y: base.y, m: base.m }, at: value, step: field.birth && !value ? "year" : "day", phone: matchMedia(PHONE).matches };
  ui.title.textContent = field.name;
  ui.dialog.className = `date-sheet ${open.phone ? "is-sheet" : "is-pop"}`;
  ui.dialog.showModal();
  place();
  addEventListener("resize", place);
  draw();
  place();
}

function close(day = null) {
  const was = open;
  if (!was) return;
  open = null;
  removeEventListener("resize", place);
  if (ui.dialog.open) ui.dialog.close();
  const { field } = was;
  if (field.button.isConnected) field.button.focus({ preventScroll: true });
  if (day !== null) field.set(day);
}

/** A phone's sheet rises from the bottom; a desk's opens under the field, or over it when there is no room below. */
function place() {
  if (!open) return;
  if (open.phone !== matchMedia(PHONE).matches || !open.field.button.isConnected) return close();
  if (open.phone) return;
  const { style } = ui.dialog;
  const box = open.field.button.getBoundingClientRect();
  const width = Math.min(Math.max(box.width, 320), innerWidth - 16);
  const below = innerHeight - box.bottom - 12;
  const up = ui.dialog.offsetHeight > below && box.top - 12 > below;
  style.setProperty("--left", `${Math.round(Math.min(Math.max(box.left, 8), innerWidth - width - 8))}px`);
  style.setProperty("--width", `${Math.round(width)}px`);
  style.setProperty("--room", `${Math.round(Math.max(Math.min(up ? box.top - 12 : below, 460), 200))}px`);
  style.top = up ? "auto" : `${Math.round(box.bottom + 4)}px`;
  style.bottom = up ? `${Math.round(innerHeight - box.top + 4)}px` : "auto";
}

function onClick(event) {
  if (!open) return;
  const hit = (sel) => event.target.closest && event.target.closest(sel);
  let node;
  if ((node = hit("[data-day]"))) {
    if (node.getAttribute("aria-disabled") === "true") return;
    close(node.dataset.day);
  } else if ((node = hit("[data-year]"))) {
    open.view = { y: Number(node.dataset.year), m: open.view.m };
    open.step = "month";
    draw();
  } else if ((node = hit("[data-month]"))) {
    if (node.getAttribute("aria-disabled") === "true") return;
    open.view = { y: open.view.y, m: Number(node.dataset.month) };
    open.step = "day";
    draw();
  } else if ((node = hit("[data-step]"))) {
    open.step = node.dataset.step;
    draw();
  } else if ((node = hit("[data-move]"))) {
    if (node.getAttribute("aria-disabled") !== "true") move(Number(node.dataset.move));
  } else if (hit("[data-clear]")) close("");
}

/** One month on; the day in view stays where it can. */
function move(by, day = null) {
  const to = new Date(Date.UTC(open.view.y, open.view.m - 1 + by, 1));
  open.view = { y: to.getUTCFullYear(), m: to.getUTCMonth() + 1 };
  open.at = day || (open.at && { ...open.at, y: open.view.y, m: open.view.m, d: Math.min(open.at.d, daysIn(open.view.y, open.view.m)) });
  draw();
}

function onKey(event) {
  if (!open) return;
  const { key } = event;
  if (key === "Escape") {
    event.preventDefault();
    return close();
  }
  const cell = event.target.closest && event.target.closest("[data-day], [data-year], [data-month]");
  if (!cell || event.ctrlKey || event.metaKey || event.altKey) return;
  if (key === "Enter" || key === " ") {
    event.preventDefault();
    return cell.click();
  }
  if (cell.dataset.day) {
    const here = parse(cell.dataset.day);
    const by = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[key];
    let to = by ? shift(here, by) : key === "Home" ? shift(here, -((weekday(here) + 6) % 7)) : key === "End" ? shift(here, 6 - ((weekday(here) + 6) % 7)) : null;
    if (key === "PageUp" || key === "PageDown") {
      const dir = key === "PageUp" ? -1 : 1;
      const months = event.shiftKey ? 12 * dir : dir;
      const y = new Date(Date.UTC(here.y, here.m - 1 + months, 1));
      to = { y: y.getUTCFullYear(), m: y.getUTCMonth() + 1, d: Math.min(here.d, daysIn(y.getUTCFullYear(), y.getUTCMonth() + 1)) };
    }
    if (!to) return;
    event.preventDefault();
    if (open.field.birth && (to.y !== open.view.y || to.m !== open.view.m)) return;
    if (open.field.min && iso(to) < open.field.min.slice(0, 10)) to = parse(open.field.min.slice(0, 10));
    if (open.field.max && iso(to) > open.field.max.slice(0, 10)) to = parse(open.field.max.slice(0, 10));
    if (!to) return;
    if (to.y === open.view.y && to.m === open.view.m) {
      open.at = to;
      ui.body.querySelectorAll("[data-day]").forEach((b) => b.setAttribute("tabindex", b.dataset.day === iso(to) ? "0" : "-1"));
      return ui.body.querySelector(`[data-day="${iso(to)}"]`).focus();
    }
    return move((to.y - open.view.y) * 12 + (to.m - open.view.m), to);
  }
  const grid = cell.parentElement;
  const all = [...grid.children];
  const cols = Number(grid.dataset.cols);
  const at = all.indexOf(cell);
  const to = { ArrowLeft: at - 1, ArrowRight: at + 1, ArrowUp: at - cols, ArrowDown: at + cols, Home: 0, End: all.length - 1 }[key];
  if (to === undefined) return;
  event.preventDefault();
  if (to < 0 || to >= all.length) return;
  all.forEach((b) => b.setAttribute("tabindex", b === all[to] ? "0" : "-1"));
  all[to].focus();
}

/** One date field: the native input stays the field, out of sight; a button says the day and opens the sheet. */
function upgrade(native, zone) {
  if (native.dataset.dated) return;
  native.dataset.dated = "1";
  const timed = native.type === "datetime-local";
  const mode = native.dataset.dates || "";
  const name = (native.labels && native.labels[0] ? native.labels[0].textContent : "Date").trim();
  const field = {
    native, name, birth: mode === "birth", recent: mode === "recent", today: todayIn(zone),
    get min() { return native.min.slice(0, 10); },
    get max() { return native.max.slice(0, 10); },
  };
  const text = el("span", { class: "date-text" });
  const button = el("button", { type: "button", class: "date-button", "aria-haspopup": "dialog" }, text, icon(CALENDAR));
  field.button = button;
  const time = timed ? Object.assign(document.createElement("input"), { type: "time", className: "date-time" }) : null;
  if (time) time.setAttribute("aria-label", `${name}: Time`);
  const chips = mode === "recent" ? el("div", { class: "date-chips", role: "group", "aria-label": `${name}: quick picks` }) : null;
  const quick = [];
  if (chips) {
    for (const [label, back] of [["Today", 0], ["Yesterday", 1]]) {
      const chip = el("button", { type: "button", class: "date-chip", text: label });
      chip.addEventListener("click", () => field.set(iso(shift(parse(field.today), -back))));
      chips.append(chip);
      quick.push([chip, back]);
    }
  }
  const paint = () => {
    const [date, clock = ""] = native.value.split("T");
    const said = say(date, field.today, { weekdays: !field.birth });
    text.textContent = said || (field.birth ? "Choose the date" : "Choose a date");
    text.classList.toggle("is-empty", !said);
    button.setAttribute("aria-label", `${name}: ${said || "not set"}`);
    if (time) time.value = clock.slice(0, 5);
    for (const [chip, back] of quick) {
      const day = shift(parse(field.today), -back);
      chip.setAttribute("aria-pressed", String(date === iso(day)));
      if (within(day, field.min, field.max)) chip.removeAttribute("aria-disabled");
      else chip.setAttribute("aria-disabled", "true");
    }
  };
  let own = false;
  field.set = (day) => {
    if (day && !within(parse(day), field.min, field.max)) return;
    const clock = time && (time.value || "08:00");
    native.value = day ? `${day}${timed ? `T${clock}` : ""}` : "";
    paint();
    own = true;
    ["input", "change"].forEach((type) => native.dispatchEvent(new Event(type, { bubbles: true })));
    own = false;
  };
  button.addEventListener("click", () => show(field));
  if (time) {
    time.addEventListener("change", () => {
      if (parse(native.value)) field.set(native.value.slice(0, 10));
    });
  }
  native.addEventListener("change", () => own || paint());
  native.addEventListener("focus", () => button.focus());
  native.classList.add("date-native");
  native.tabIndex = -1;
  native.setAttribute("aria-hidden", "true");
  const wrap = el("span", { class: "date-field" });
  native.before(wrap);
  wrap.append(button, ...(time ? [time] : []), ...(chips ? [chips] : []), native);
  paint();
}

/** Every date field under `root`, and any a redraw brings. */
export function enhanceDates(root) {
  if (!root || typeof HTMLDialogElement === "undefined" || !HTMLDialogElement.prototype.showModal) return;
  const zone = () => (root.closest("[data-time-zone]") || root).dataset.timeZone || ZONE;
  const all = () => root.querySelectorAll('input[type="date"], input[type="datetime-local"]').forEach((n) => upgrade(n, zone()));
  all();
  new MutationObserver(all).observe(root, { childList: true, subtree: true });
}
