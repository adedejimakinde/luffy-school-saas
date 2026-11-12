/** Date fields: a one-line button and a calendar sheet (docs/module-notes.md, `web/dates.js`). */
const MONTHS = "January February March April May June July August September October November December".split(" ");
const DAYS = "Sunday Monday Tuesday Wednesday Thursday Friday Saturday".split(" ");
const pad = (n) => String(n).padStart(2, "0");
const svg = (d) => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${d}"/></svg>`;

export function parse(text) {
  const f = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(text ?? ""));
  if (!f) return null;
  const [y, m, d] = [+f[1], +f[2], +f[3]];
  const t = new Date(Date.UTC(y, m - 1, d));
  return t.getUTCMonth() === m - 1 && t.getUTCDate() === d ? { y, m, d } : null;
}
export const iso = ({ y, m, d }) => `${y}-${pad(m)}-${pad(d)}`;
const utc = ({ y, m, d }) => Date.UTC(y, m - 1, d);
export const shift = (day, n) => {
  const t = new Date(utc(day) + n * 864e5);
  return { y: t.getUTCFullYear(), m: t.getUTCMonth() + 1, d: t.getUTCDate() };
};
const dim = (y, m) => new Date(Date.UTC(y, m, 0)).getUTCDate();
const wd = (day) => new Date(utc(day)).getUTCDay();
const months = (y, m, n) => {
  const t = new Date(Date.UTC(y, m - 1 + n, 1));
  return { y: t.getUTCFullYear(), m: t.getUTCMonth() + 1 };
};

/** Today in the school's zone as `yyyy-mm-dd`. */
export function todayIn(zone = "Africa/Lagos", now = new Date()) {
  try {
    return new Intl.DateTimeFormat("en-CA", { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
  } catch {
    return iso({ y: now.getFullYear(), m: now.getMonth() + 1, d: now.getDate() });
  }
}

/** "Today, Thu 12 Nov" near today, else "Wed 4 Nov 2026" ("4 Nov 2012" with no weekday). */
export function say(value, today, { weekdays = true } = {}) {
  const day = parse(value);
  if (!day) return "";
  const near = { 0: "Today", "-1": "Yesterday", 1: "Tomorrow" }[Math.round((utc(day) - utc(parse(today))) / 864e5)];
  const name = `${weekdays ? `${DAYS[wd(day)].slice(0, 3)} ` : ""}${day.d} ${MONTHS[day.m - 1].slice(0, 3)}`;
  return near && weekdays ? `${near}, ${name}` : `${name} ${day.y}`;
}

/** A month as Monday-first weeks: a day, or null where a week spills over. */
export function cells(y, m) {
  const lead = (wd({ y, m, d: 1 }) + 6) % 7;
  const n = dim(y, m);
  return Array.from({ length: Math.ceil((lead + n) / 7) * 7 }, (_, i) => (i >= lead && i < lead + n ? { y, m, d: i - lead + 1 } : null));
}

export const within = (day, min, max) => (!min || iso(day) >= min) && (!max || iso(day) <= max);

let ui = null;
let open = null; // { field, step, view, at, phone }
const PHONE = "(max-width: 639.98px)";
const hit = (e, sel) => e.target.closest && e.target.closest(sel);
const off = (ok) => (ok ? "" : ' aria-disabled="true"');

function build() {
  const d = document.createElement("dialog");
  d.className = "date-sheet";
  d.setAttribute("aria-labelledby", "date-title");
  d.innerHTML = `<div class="date-head"><h2 id="date-title"></h2><button type="button" class="icon-button" data-close aria-label="Close">${svg("M6 6l12 12M18 6L6 18")}</button></div><div class="date-body"></div><p class="sr" aria-live="polite"></p>`;
  d.addEventListener("cancel", (e) => (e.preventDefault(), close()));
  d.addEventListener("close", () => d.open || close());
  d.addEventListener("click", (e) => (e.target === d || hit(e, "[data-close]") ? close() : click(e)));
  d.addEventListener("keydown", key);
  document.body.append(d);
  return { d, title: d.querySelector("h2"), body: d.querySelector(".date-body"), say: d.querySelector(".sr") };
}

function draw() {
  const { field: f, step, view: v } = open;
  const val = parse(f.native.value);
  const t = parse(f.today);
  const lo = f.min;
  const hi = f.max;
  const crumbs = `<div class="date-crumbs"><button type="button" data-step="year">${v.y}</button>${step === "day" ? `<button type="button" data-step="month">${MONTHS[v.m - 1]}</button>` : ""}</div>`;
  let html;
  if (step === "year") {
    const top = Math.max(hi ? parse(hi).y : t.y, val ? val.y : 0);
    const bottom = Math.min(lo ? parse(lo).y : t.y - 30, val ? val.y : 9999);
    const at = val ? val.y : v.y;
    html = `<div class="date-pick" data-cols="4" role="group" aria-label="Year">${Array.from({ length: top - bottom + 1 }, (_, i) => top - i)
      .map((y) => `<button type="button" data-year="${y}" tabindex="${y === at || (y === top && at > top) ? 0 : -1}" aria-pressed="${!!val && val.y === y}">${y}</button>`).join("")}</div>`;
  } else if (step === "month") {
    html = `${crumbs}<div class="date-pick" data-cols="3" role="group" aria-label="Month">${MONTHS.map((n, i) => {
      const ok = (!lo || iso({ y: v.y, m: i + 1, d: dim(v.y, i + 1) }) >= lo) && (!hi || iso({ y: v.y, m: i + 1, d: 1 }) <= hi);
      return `<button type="button" data-month="${i + 1}" tabindex="${i + 1 === v.m ? 0 : -1}"${off(ok)} aria-pressed="${!!val && val.y === v.y && val.m === i + 1}">${n.slice(0, 3)}</button>`;
    }).join("")}</div>`;
  } else {
    const all = cells(v.y, v.m);
    const ok = (c) => c && within(c, lo, hi);
    const same = (c) => c && c.y === v.y && c.m === v.m;
    const want = same(open.at) ? open.at.d : same(val) ? val.d : same(t) ? t.d : 1;
    const aim = (all.filter(ok).find((c) => c.d >= want) || all.find(ok) || { d: 0 }).d;
    const first = { ...v, d: 1 };
    const nav = (by, can) => `<button type="button" class="icon-button" data-move="${by}" aria-label="${by < 0 ? "Previous" : "Next"} month"${off(can)}>${svg(by < 0 ? "M15 6l-6 6 6 6" : "M9 6l6 6-6 6")}</button>`;
    html = `${f.birth ? crumbs : `<div class="date-month">${nav(-1, !lo || iso(first) > lo)}<h3 aria-live="polite">${MONTHS[v.m - 1]} ${v.y}</h3>${nav(1, !hi || iso({ ...v, d: dim(v.y, v.m) }) < hi)}</div>`}`;
    html += `<div class="date-grid" role="grid" aria-label="${MONTHS[v.m - 1]} ${v.y}"><div class="date-week date-heads" role="row">${[1, 2, 3, 4, 5, 6, 0].map((n) => `<span role="columnheader" aria-label="${DAYS[n]}">${DAYS[n].slice(0, 2)}</span>`).join("")}</div>`;
    for (let i = 0; i < all.length; i += 7) {
      html += `<div class="date-week" role="row">${all.slice(i, i + 7).map((c) => !c ? '<span role="gridcell"></span>'
        : `<button type="button" role="gridcell" class="date-day${iso(c) === f.today ? " is-today" : ""}" data-day="${iso(c)}" tabindex="${c.d === aim ? 0 : -1}" aria-label="${DAYS[wd(c)]} ${c.d} ${MONTHS[c.m - 1]} ${c.y}" aria-selected="${!!val && iso(val) === iso(c)}"${iso(c) === f.today ? ' aria-current="date"' : ""}${off(ok(c))}>${c.d}</button>`).join("")}</div>`;
    }
    html += "</div>";
    if (!f.native.required && !f.recent && f.native.value) html += '<button type="button" class="date-clear" data-clear>Clear the date</button>';
  }
  ui.body.innerHTML = html;
  ui.say.textContent = step === "day" ? `${MONTHS[v.m - 1]} ${v.y}` : `Choose a ${step}`;
  const aimed = ui.body.querySelector('[tabindex="0"]');
  if (aimed) {
    aimed.focus({ preventScroll: true });
    if (step !== "day") aimed.scrollIntoView({ block: "center" });
  }
}

function show(field) {
  if (open) return;
  ui = ui || build();
  const val = parse(field.native.value);
  const t = parse(field.today);
  const base = val || (within(t, field.min, field.max) ? t : parse(field.min) || (field.max && { ...parse(field.max), d: 1 }) || t);
  open = { field, view: { y: base.y, m: base.m }, at: val, step: field.birth && !val ? "year" : "day", phone: matchMedia(PHONE).matches };
  ui.title.textContent = field.name;
  ui.d.className = `date-sheet ${open.phone ? "is-sheet" : "is-pop"}`;
  ui.d.showModal();
  addEventListener("resize", place);
  draw();
  place();
}

function close(day = null) {
  const was = open;
  if (!was) return;
  open = null;
  removeEventListener("resize", place);
  if (ui.d.open) ui.d.close();
  if (was.field.button.isConnected) was.field.button.focus({ preventScroll: true });
  if (day !== null) was.field.set(day);
}

/** A phone's sheet rises from the bottom; a desk's opens under the field, or over it with no room below. */
function place() {
  if (!open) return;
  if (open.phone !== matchMedia(PHONE).matches || !open.field.button.isConnected) return close();
  if (open.phone) return;
  const s = ui.d.style;
  const b = open.field.button.getBoundingClientRect();
  const w = Math.min(Math.max(b.width, 320), innerWidth - 16);
  const below = innerHeight - b.bottom - 12;
  const up = ui.d.offsetHeight > below && b.top - 12 > below;
  s.setProperty("--left", `${Math.round(Math.min(Math.max(b.left, 8), innerWidth - w - 8))}px`);
  s.setProperty("--width", `${Math.round(w)}px`);
  s.setProperty("--room", `${Math.round(Math.max(Math.min(up ? b.top - 12 : below, 460), 200))}px`);
  s.top = up ? "auto" : `${Math.round(b.bottom + 4)}px`;
  s.bottom = up ? `${Math.round(innerHeight - b.top + 4)}px` : "auto";
}

function click(e) {
  if (!open) return;
  const n = hit(e, "button");
  if (!n || n.getAttribute("aria-disabled") === "true") return;
  const { dataset: d } = n;
  if (d.day) return close(d.day);
  if (d.clear !== undefined) return close("");
  if (d.year) (open.view = { y: +d.year, m: open.view.m }), (open.step = "month");
  else if (d.month) (open.view = { y: open.view.y, m: +d.month }), (open.step = "day");
  else if (d.step) open.step = d.step;
  else if (d.move) return go(+d.move);
  else return;
  draw();
}

/** Months on; `to` is the day to land on. */
function go(by, to = null) {
  const v = months(open.view.y, open.view.m, by);
  open.view = v;
  open.at = to || (open.at && { ...v, d: Math.min(open.at.d, dim(v.y, v.m)) });
  draw();
}

function key(e) {
  if (!open || e.ctrlKey || e.metaKey || e.altKey) return;
  const n = hit(e, "[data-day], [data-year], [data-month]");
  if (!n) return;
  if (e.key === "Enter" || e.key === " ") return e.preventDefault(), n.click();
  const f = open.field;
  if (n.dataset.day) {
    const here = parse(n.dataset.day);
    const pg = e.key === "PageUp" ? -1 : e.key === "PageDown" ? 1 : 0;
    let to = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key];
    if (to) to = shift(here, to);
    else if (pg) to = { ...months(here.y, here.m, pg * (e.shiftKey ? 12 : 1)), d: here.d };
    else return;
    e.preventDefault();
    to.d = Math.min(to.d, dim(to.y, to.m));
    if (f.min && iso(to) < f.min) to = parse(f.min);
    if (f.max && iso(to) > f.max) to = parse(f.max);
    if (f.birth && (to.y !== open.view.y || to.m !== open.view.m)) return;
    if (to.y === open.view.y && to.m === open.view.m) {
      open.at = to;
      const all = [...ui.body.querySelectorAll("[data-day]")];
      all.forEach((b) => b.setAttribute("tabindex", b.dataset.day === iso(to) ? "0" : "-1"));
      return all.find((b) => b.dataset.day === iso(to)).focus();
    }
    return go((to.y - open.view.y) * 12 + to.m - open.view.m, to);
  }
  const all = [...n.parentElement.children];
  const cols = +n.parentElement.dataset.cols;
  const i = all.indexOf(n) + ({ ArrowLeft: -1, ArrowRight: 1, ArrowUp: -cols, ArrowDown: cols }[e.key] ?? NaN);
  if (!all[i]) return;
  e.preventDefault();
  all.forEach((b) => b.setAttribute("tabindex", b === all[i] ? "0" : "-1"));
  all[i].focus();
}

/** One date field: the native input stays the field, out of sight; a button says the day and opens the sheet. */
function upgrade(native, zone) {
  if (native.dataset.dated) return;
  native.dataset.dated = "1";
  const timed = native.type === "datetime-local";
  const mode = native.dataset.dates || "";
  const name = (native.labels && native.labels[0] ? native.labels[0].textContent : "Date").trim();
  const f = {
    native, name, birth: mode === "birth", recent: mode === "recent", today: todayIn(zone),
    get min() { return native.min.slice(0, 10); },
    get max() { return native.max.slice(0, 10); },
  };
  const wrap = document.createElement("span");
  wrap.className = "date-field";
  wrap.innerHTML = `<button type="button" class="date-button" aria-haspopup="dialog"><span class="date-text"></span>${svg("M5 6h14v13H5zM5 10h14M9 4v4M15 4v4")}</button>${timed ? '<input type="time" class="date-time">' : ""}${
    f.recent ? '<span class="date-chips" role="group"><button type="button" class="date-chip" data-back="0">Today</button><button type="button" class="date-chip" data-back="1">Yesterday</button></span>' : ""}`;
  const button = (f.button = wrap.querySelector(".date-button"));
  const text = wrap.querySelector(".date-text");
  const time = wrap.querySelector(".date-time");
  if (time) time.setAttribute("aria-label", `${name}: Time`);
  const chips = [...wrap.querySelectorAll(".date-chip")];
  const paint = () => {
    const [date, clock = ""] = native.value.split("T");
    const said = say(date, f.today, { weekdays: !f.birth });
    text.textContent = said || "Choose a date";
    text.classList.toggle("is-empty", !said);
    button.setAttribute("aria-label", `${name}: ${said || "not set"}`);
    if (time) time.value = clock.slice(0, 5);
    for (const c of chips) {
      const day = shift(parse(f.today), -c.dataset.back);
      c.setAttribute("aria-pressed", String(date === iso(day)));
      if (within(day, f.min, f.max)) c.removeAttribute("aria-disabled");
      else c.setAttribute("aria-disabled", "true");
    }
  };
  let own = false;
  f.set = (day) => {
    if (day && !within(parse(day), f.min, f.max)) return;
    native.value = day ? `${day}${timed ? `T${time.value || "08:00"}` : ""}` : "";
    paint();
    own = true;
    ["input", "change"].forEach((t) => native.dispatchEvent(new Event(t, { bubbles: true })));
    own = false;
  };
  wrap.addEventListener("click", (e) => {
    const c = hit(e, ".date-chip");
    if (c) f.set(iso(shift(parse(f.today), -c.dataset.back)));
    else if (hit(e, ".date-button")) show(f);
  });
  if (time) time.addEventListener("change", () => parse(native.value) && f.set(native.value.slice(0, 10)));
  native.addEventListener("change", () => own || paint());
  native.addEventListener("focus", () => button.focus());
  native.classList.add("date-native");
  native.tabIndex = -1;
  native.setAttribute("aria-hidden", "true");
  native.before(wrap);
  wrap.append(native);
  paint();
}

/** Every date field under `root`, and any a redraw brings. */
export function enhanceDates(root) {
  if (!root || typeof HTMLDialogElement === "undefined" || !HTMLDialogElement.prototype.showModal) return;
  const zone = () => (root.closest("[data-time-zone]") || root).dataset.timeZone || "Africa/Lagos";
  const all = () => root.querySelectorAll('input[type="date"], input[type="datetime-local"]').forEach((n) => upgrade(n, zone()));
  all();
  new MutationObserver(all).observe(root, { childList: true, subtree: true });
}
