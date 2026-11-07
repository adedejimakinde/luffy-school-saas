/**
 * A simple on-screen calculator: + − × ÷ and decimals, one operation at a time, as a
 * pocket calculator works. Only for a test its teacher set "Calculator on screen".
 *
 * Pure: `press(state, key)` answers the next state, so every sequence is testable.
 * Keys: `0`-`9`, `.`, `+`, `-`, `*`, `/`, `=`, `C` (clear), `back`.
 */

export const START = Object.freeze({ shown: "0", held: null, op: null, fresh: true, error: false });

const LIMIT = 12;

function apply(a, op, b) {
  switch (op) {
    case "+":
      return a + b;
    case "-":
      return a - b;
    case "*":
      return a * b;
    case "/":
      return b === 0 ? NaN : a / b;
    default:
      return b;
  }
}

/** A number as the screen shows it: at most 12 significant figures, no float noise. */
export function show(n) {
  if (!Number.isFinite(n)) return "Error";
  const rounded = Number.parseFloat(n.toPrecision(LIMIT));
  const text = String(rounded);
  if (text.length <= LIMIT + 2) return text;
  return rounded.toExponential(6);
}

export function press(state, key) {
  const s = state.error && key !== "C" ? START : state;
  if (key === "C") return START;
  if (/^[0-9]$/.test(key)) {
    if (s.fresh) return { ...s, shown: key, fresh: false };
    if (s.shown.replace(/[-.]/g, "").length >= LIMIT) return s;
    return { ...s, shown: s.shown === "0" ? key : s.shown + key };
  }
  if (key === ".") {
    if (s.fresh) return { ...s, shown: "0.", fresh: false };
    return s.shown.includes(".") ? s : { ...s, shown: `${s.shown}.` };
  }
  if (key === "back") {
    if (s.fresh) return s;
    const shorter = s.shown.length > 1 ? s.shown.slice(0, -1) : "0";
    return { ...s, shown: shorter === "-" ? "0" : shorter };
  }
  if (["+", "-", "*", "/"].includes(key)) {
    if (s.op && !s.fresh) {
      const result = apply(s.held, s.op, Number(s.shown));
      if (!Number.isFinite(result)) return { ...START, shown: "Error", error: true };
      return { shown: show(result), held: result, op: key, fresh: true, error: false };
    }
    return { ...s, held: Number(s.shown), op: key, fresh: true };
  }
  if (key === "=") {
    if (!s.op) return { ...s, fresh: true };
    const result = apply(s.held, s.op, Number(s.shown));
    if (!Number.isFinite(result)) return { ...START, shown: "Error", error: true };
    return { shown: show(result), held: null, op: null, fresh: true, error: false };
  }
  return s;
}

/** The keys as drawn, in rows: label, key, what a screen reader says. */
export const KEYS = [
  [["C", "C", "Clear"], ["Del", "back", "Delete last digit"], ["÷", "/", "Divide"], ["×", "*", "Times"]],
  [["7", "7"], ["8", "8"], ["9", "9"], ["−", "-", "Minus"]],
  [["4", "4"], ["5", "5"], ["6", "6"], ["+", "+", "Plus"]],
  [["1", "1"], ["2", "2"], ["3", "3"], ["=", "=", "Equals"]],
  [["0", "0"], [".", ".", "Point"]],
];

/** A typed key, as the calculator's key, or null. */
export function keyFor(typed) {
  if (/^[0-9]$/.test(typed)) return typed;
  return { ".": ".", ",": ".", "+": "+", "-": "-", "*": "*", x: "*", "/": "/", "=": "=", Enter: "=", Backspace: "back", Escape: "C", Delete: "C" }[typed] || null;
}
