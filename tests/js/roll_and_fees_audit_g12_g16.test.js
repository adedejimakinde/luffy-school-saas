/**
 * The screens for audit part 2's G-12, G-14, G-15 and G-16: what the fees page
 * says is outstanding, the admission-number edit and "Has left" on a child's
 * details, and what the import preview says each row will do.
 *
 * The rules are the server's (`fees/outstanding.py`, `accounts/admission_numbers.py`,
 * `accounts/bulk.py`, `academics/leaving.py`) and are tested there; these hold
 * what the pages show of them.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import * as fees from "../../static/fees/states.js";
import * as importing from "../../static/roll-import/states.js";
import * as roll from "../../static/roll/states.js";

const ROLL = {
  term: "First term 2025/2026",
  children: [{ student_membership_id: 1, student: "Ada Obi", username: "STM/1", reference: "JSS/014", class_group_id: 3, class_group: "JSS 1A" }],
  classes: [{ class_group_id: 3, name: "JSS 1A", level: 1 }],
  details: { childId: 1, body: { student_membership_id: 1, student: "Ada Obi", may_edit: true }, note: null },
};

// -- G-12 ----------------------------------------------------------------------

test("the fees list says outstanding for all terms, with this term's part beneath", () => {
  const html = fees.books({
    books: {
      terms: [], term: "First term", classes: [], owing: 3,
      outstanding_kobo: 4_500_000, outstanding_this_term_kobo: 2_500_000,
    },
  });
  assert.match(html, /Outstanding \(all terms\)/);
  assert.match(html, /₦45,000\.00/);
  assert.match(html, /of which this term: ₦25,000\.00/);
});

test("nobody owing says nothing about outstanding", () => {
  assert.equal(fees.outstandingLine({ owing: 0, outstanding_kobo: 0 }), "");
});

test("a class row says what its children owe", () => {
  const html = fees.books({
    books: { terms: [], classes: [{ class_group_id: 3, class_group: "JSS 1A", children: 4, owing: 2, outstanding_kobo: 3_000_000 }] },
  });
  assert.match(html, /4 children · ₦30,000\.00 outstanding/);
});

// -- G-14 and G-16, on the roll ------------------------------------------------

test("the administrator sees the admission number to edit, and nobody else does", () => {
  const admin = roll.roll({ ...ROLL, may_admit: true });
  assert.match(admin, /data-form="admission-number"/);
  assert.match(admin, /value="JSS\/014"/);
  assert.doesNotMatch(roll.roll({ ...ROLL, may_place: true }), /data-form="admission-number"/);
});

test("a refused number keeps what was typed and says why", () => {
  const html = roll.roll({
    ...ROLL, may_admit: true,
    details: { ...ROLL.details, note: { kind: "rejected", form: "admission-number", detail: "Taken by Bisi Ade.", typed: { reference: "jss/015" } } },
  });
  assert.match(html, /value="jss\/015"/);
  assert.match(html, /Taken by Bisi Ade\./);
});

test("only the principal is offered Has left, with a reason and what it does", () => {
  const principal = roll.roll({ ...ROLL, may_place: true, may_take_off: true });
  assert.match(principal, /data-form="leave"/);
  assert.match(principal, /<textarea id="leave-reason" name="reason" required/);
  assert.match(principal, /family can still read the report cards/);
  assert.doesNotMatch(roll.roll({ ...ROLL, may_admit: true, may_place: true }), /data-form="leave"/);
});

test("the roll says who was taken off it", () => {
  const html = roll.roll({ ...ROLL, details: null, notes: { left: { detail: "Ada Obi was taken off the roll." } } });
  assert.match(html, /Ada Obi was taken off the roll\./);
});

// -- G-15, the import preview --------------------------------------------------

const row = (line, extra) => ({
  line, full_name: "Ada Obi", class_group: "JSS 1A", reference: "", username: "", guardian_name: "",
  guardian_contact: "", problems: [], ...extra,
});

test("a file already in says so and offers nothing to press", () => {
  const html = importing.preview({
    fileName: "jss1.xlsx",
    preview: { admissible: true, problem_rows: 0, rows: [row(2, { outcome: "skipped", matched: "Ada Obi", notes: ["Already on the roll as Ada Obi (matched by name)."] })] },
  });
  assert.match(html, /Already in/);
  assert.match(html, /already on the roll, and the file adds nothing/);
  assert.doesNotMatch(html, /data-action="admit"/);
  assert.match(html, /<span class="label">Already on the roll<\/span>/);
  assert.match(html, /matched by name/);
});

test("new, filled in and left alone are counted and each row says which", () => {
  const html = importing.preview({
    fileName: "jss1.xlsx",
    preview: {
      admissible: true, problem_rows: 0,
      rows: [
        row(2, { outcome: "new" }),
        row(3, { full_name: "Kola Ade", outcome: "updated", fills: ["admission number K1"] }),
        row(4, { full_name: "Bisi Ade", outcome: "skipped" }),
      ],
    },
  });
  assert.match(html, /1 new child, 1 child already on the roll to fill in, 1 child already on the roll, left as they are/);
  assert.match(html, /data-action="admit"[^>]*>Admit 1 child</);
  assert.match(html, /Fills in admission number K1\./);
});

test("the report after an import counts the children left as they were", () => {
  const html = importing.done({ report: { admitted: 0, updated: 1, skipped: 2 } });
  assert.match(html, /1 child already on the roll had details filled in/);
  assert.match(html, /2 children were already on the roll and left as they were/);
});
