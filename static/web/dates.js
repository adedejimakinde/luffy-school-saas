/** Day-first dates (`docs/design.md`, "Dates"): day, month, year, each a select of the shared picker. */
const MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(" ");
const pad = (n) => String(n).padStart(2, "0");

/** One date field: the native input stays the field, out of sight; the reader picks day, month, year (and a time). */
function upgrade(native) {
  if (native.dataset.dated) return;
  native.dataset.dated = "1";
  const timed = native.type === "datetime-local";
  const year = new Date().getFullYear();
  const [lo, hi] = [Number(native.min.slice(0, 4)) || year - 30, Number(native.max.slice(0, 4)) || year + 5];
  const name = (native.labels[0] ? native.labels[0].textContent : "Date").trim();
  const make = (what, items) => {
    const select = document.createElement("select");
    select.setAttribute("aria-label", `${name}: ${what}`);
    select.innerHTML = `<option value="">${what}</option>${items.map(([v, t]) => `<option value="${v}">${t}</option>`).join("")}`;
    return select;
  };
  const days = make("Day", Array.from({ length: 31 }, (_, i) => [i + 1, i + 1]));
  const months = make("Month", MONTHS.map((t, i) => [i + 1, t]));
  const [top, bottom] = [Math.max(hi, Number(native.value.slice(0, 4)) || hi), Math.min(lo, Number(native.value.slice(0, 4)) || lo)];
  const years = make("Year", Array.from({ length: top - bottom + 1 }, (_, i) => [top - i, top - i]));
  const time = timed ? Object.assign(document.createElement("input"), { type: "time" }) : null;
  if (time) time.setAttribute("aria-label", `${name}: Time`);
  const paint = () => {
    const [date, clock = ""] = native.value.split("T");
    const [y, m, d] = date ? date.split("-").map(Number) : ["", "", ""];
    [years.value, months.value, days.value] = [y, m, d];
    if (time) time.value = clock.slice(0, 5);
  };
  let own = false;
  const tell = () => {
    own = true;
    ["input", "change"].forEach((type) => native.dispatchEvent(new Event(type, { bubbles: true })));
    own = false;
  };
  const compose = () => {
    const [y, m] = [Number(years.value), Number(months.value)];
    let d = Number(days.value);
    if (y && m && d) {
      d = Math.min(d, new Date(Date.UTC(y, m, 0)).getUTCDate());
      days.value = d;
      native.value = `${y}-${pad(m)}-${pad(d)}${timed ? `T${time.value || "08:00"}` : ""}`;
    } else native.value = "";
    tell();
  };
  for (const part of [days, months, years, time]) if (part) part.addEventListener("change", compose);
  native.addEventListener("change", () => own || paint());
  native.addEventListener("focus", () => days.focus());
  native.classList.add("date-native");
  native.tabIndex = -1;
  native.setAttribute("aria-hidden", "true");
  const wrap = document.createElement("span");
  wrap.className = "date-field";
  native.before(wrap);
  wrap.append(days, months, years, ...(time ? [time] : []), native);
  paint();
}

/** Every date field under `root`, and any a redraw brings. */
export function enhanceDates(root) {
  if (!root) return;
  const all = () => root.querySelectorAll('input[type="date"], input[type="datetime-local"]').forEach(upgrade);
  all();
  new MutationObserver(all).observe(root, { childList: true, subtree: true });
}
