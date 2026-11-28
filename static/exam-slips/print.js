/** What the exam slips page and the sitting page share: the two questions asked before a print, and saving the PDF. */

import { esc, keepTogether } from "../web/html.js";

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

/**
 * The question before a whole class is printed, shared with the sitting page. A class that
 * already holds live PINs asks, with Cancel first and the default; one that holds none says
 * what it will print. Neither prints until the second tap.
 */
export function classConfirm(c, key = `class${c.id}`) {
  const count = c.printable ?? c.students;
  if (c.with_a_pin) {
    return (
      `<div class="confirm warn" data-confirm="${esc(key)}" role="alertdialog" aria-label="Give ${esc(keepTogether(c.name))} new PINs"><p><strong>This gives all ${count} students new PINs. Slips already handed out will stop working.</strong></p>` +
      // Cancel first, and the one the page focuses: Enter or a stray tap changes nothing.
      '<button type="button" class="submit" data-action="keep" data-default>Cancel</button>' +
      `<button type="button" data-action="print-class" data-class="${esc(c.id)}">Give ${esc(keepTogether(c.name))} new PINs and print</button></div>`
    );
  }
  return (
    `<div class="confirm" data-confirm="${esc(key)}"><p>${esc(keepTogether(c.name))} gets ${plural(count, "slip", "slips")}.</p>` +
    `<button type="button" class="submit" data-action="print-class" data-class="${esc(c.id)}">Print ${esc(keepTogether(c.name))}</button>` +
    '<button type="button" class="again" data-action="keep">Not now</button></div>'
  );
}

/** The question before one student gets a new PIN. Cancel first and the default. */
export function studentConfirm(c, s, key = `student${s.id}`) {
  return (
    `<div class="confirm warn" data-confirm="${esc(key)}" role="alertdialog" aria-label="Give ${esc(s.name)} a new exam PIN"><p><strong>This gives ${esc(s.name)} a new exam PIN. Their old slip will stop working.</strong></p>` +
    '<button type="button" class="submit" data-action="keep" data-default>Cancel</button>' +
    `<button type="button" data-action="print-student" data-class="${esc(c.id)}" data-student="${esc(s.id)}">Give ${esc(s.name)} a new PIN and print</button></div>`
  );
}

/** Saves the PDF, then lets go of it: the page keeps no copy of a PIN. */
export function saveFile(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}
