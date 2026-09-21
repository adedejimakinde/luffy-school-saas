/**
 * The marking screen: pick a paper and a class, then type marks.
 *
 * ## Save on blur, one mark per request
 *
 * `gradebook/api.py` settled the shape and this is the other half of it. A
 * teacher marking thirty children does not fill in a form and press Save at
 * the bottom: they tab through thirty cells, and each has to save as it loses
 * focus — because the alternative is twenty minutes of marking lost with the
 * tab. So the unit of a write is one cell, and there is no bulk submit.
 *
 * The opposite of the register next door, deliberately: a register is a few
 * taps and one submit, and `attendance/api.py` says why. Thirty conditional
 * PUTs would be wrong there; one bulk PUT would be wrong here.
 *
 * ## The version travels with the cell
 *
 * Each input carries the version it was drawn with, and sends it back as
 * `expected_version`. Empty means "I was shown no mark", which the server
 * reads as an insert — so a cell that has never been marked cannot silently
 * overwrite one that has been marked since the sheet loaded.
 *
 * **Every answer carries the new version and total**, so the cell is redrawn
 * from the response rather than from a local guess. A page that recomputed the
 * total itself would be a second implementation of a sum the server already
 * did, free to disagree.
 */

import { failureNote, sessionEnded, signOut } from "../web/signout.js";
import { REFUSAL, SAVE, fetchSheet, fetchWhere, saveScore } from "./api.js";
import * as states from "./states.js";

/** The markup for one state. Pure, so every branch is testable. */
export function htmlFor(state, { portal = "", signOutFailed = false } = {}) {
  const after = signOutFailed ? failureNote() : "";
  switch (state.step) {
    case "choose":
      return states.choose(state) + after;
    case "no-term":
      return states.noTerm() + after;
    case "sheet":
      return states.sheet(state) + after;
    case REFUSAL.NOT_A_MARKER:
      return states.notAMarker(state) + after;
    case REFUSAL.WRONG_HOST:
      return states.wrongHost();
    case REFUSAL.EXPIRED:
      return states.signedOut({ portal, expired: true });
    case REFUSAL.SIGNED_OUT:
      return states.signedOut({ portal });
    default:
      return states.broken();
  }
}

/**
 * Turn the `/where/` answer into a state.
 *
 * A 200 with no current term is **not** a refusal: the password was right and
 * this person may mark. What is missing is a school setting, so it gets its
 * own screen naming who can fix it.
 */
export function fromWhere(answer) {
  if (!answer.ok) return { step: answer.refusal, ...answer.body };
  if (!answer.body.term_id) return { step: "no-term" };
  return { step: "choose", ...answer.body };
}

/** Turn a `SheetOut` into the marking screen. */
export function fromSheet(answer) {
  if (!answer.ok) return { step: answer.refusal, ...answer.body };
  return { step: "sheet", ...answer.body, notes: {} };
}

/**
 * What one save did to one cell, as the next render of the sheet.
 *
 * The three refusals are kept apart because their remedies are:
 *
 * - **conflict** — somebody else moved it. The cell is redrawn to *their*
 *   value and *their* version, because "somebody changed this" is not useful
 *   and "Kemi entered 17 while you were typing" is. Redrawing to their version
 *   is also what makes the teacher's next save a deliberate overwrite rather
 *   than a second conflict. A null `current` means it was **cleared**, which
 *   is a different sentence from a new number.
 * - **locked** — the term left draft. Nothing the page can reload reopens it,
 *   so the whole sheet is marked locked rather than the one cell retried.
 * - **invalid** — the number is the problem. What was typed is left in place
 *   to be corrected, because clearing it would throw away the only copy.
 */
export function applySave(state, id, result) {
  const notes = { ...state.notes };
  if (result.ok) {
    delete notes[id];
    return { ...state, notes, rows: replace(state.rows, id, result.cell) };
  }
  if (result.outcome === SAVE.CONFLICT) {
    const current = result.body.current;
    notes[id] = {
      kind: "conflict",
      detail: current
        ? `Saved as ${current.value} by somebody else. Type over it to change it.`
        : "Somebody cleared this mark while you were typing it.",
    };
    return {
      ...state,
      notes,
      rows: replace(state.rows, id, current || { student_membership_id: id, value: null, version: null }),
    };
  }
  if (result.outcome === SAVE.LOCKED) {
    return { ...state, notes, locked: true, locked_reason: result.body.detail };
  }
  if (result.outcome === SAVE.INVALID) {
    notes[id] = { kind: "invalid", detail: result.body.detail };
    return { ...state, notes };
  }
  return { step: result.refusal, ...result.body };
}

function replace(rows, id, cell) {
  return (rows || []).map((row) =>
    row.student_membership_id === id ? { ...row, ...cell } : row,
  );
}

export async function mount(root, { fetchImpl = fetch } = {}) {
  const portal = root.dataset.portal || "";
  let state = { step: "loading" };
  let signOutFailed = false;
  let where = null;
  let picked = { assessmentId: null, classGroupId: null };

  const draw = () => {
    root.innerHTML = htmlFor(state, { portal, signOutFailed });
  };

  const openSheet = async () => {
    if (!picked.assessmentId || !picked.classGroupId) return;
    state = fromSheet(await fetchSheet({ ...picked, fetchImpl }));
    draw();
  };

  const whereAnswer = await fetchWhere({ fetchImpl });
  if (whereAnswer.ok) where = whereAnswer.body;
  state = fromWhere(whereAnswer);
  draw();

  // Delegated from the root: every state is redrawn wholesale, so a listener
  // bound to an input would be bound to a node about to be replaced.
  root.addEventListener("click", async (event) => {
    const hit = event.target.closest("[data-action]");
    if (!hit) return;
    const action = hit.dataset.action;

    if (action === "sign-out") {
      const ended = sessionEnded(await signOut({ fetchImpl }));
      if (ended) {
        // Not `expired: true`. Signing out on purpose deletes the cookie as
        // well as the session, so nothing lapsed.
        root.innerHTML = states.signedOut({ portal });
        return;
      }
      signOutFailed = true;
      draw();
      return;
    }
    if (action === "back") {
      picked = { assessmentId: null, classGroupId: null };
      state = fromWhere({ ok: true, body: where });
      draw();
      return;
    }
    if (action === "pick-assessment") {
      picked = { ...picked, assessmentId: Number(hit.dataset.assessment) };
      await openSheet();
      return;
    }
    if (action === "pick-class") {
      picked = { ...picked, classGroupId: Number(hit.dataset.class) };
      await openSheet();
    }
  });

  // **The blur is the save.** `change` would not fire for a cell retyped to
  // the same value, and `input` would fire per keystroke — thirty requests for
  // one two-digit mark.
  root.addEventListener("blur", async (event) => {
    const field = event.target;
    if (!field || !field.dataset || field.dataset.child === undefined) return;
    if (state.step !== "sheet" || state.locked) return;

    const id = Number(field.dataset.child);
    const raw = String(field.value).trim();
    // An emptied cell is not a mark of nought, and clearing one is a different
    // route. Leaving it alone here keeps `DELETE` the only way to unmark.
    if (raw === "") return;

    const version = field.dataset.version;
    state = applySave(
      state,
      id,
      await saveScore({
        assessmentId: picked.assessmentId,
        studentMembershipId: id,
        value: Number(raw),
        expectedVersion: version === "" ? null : Number(version),
        fetchImpl,
      }),
    );
    draw();
  }, true);

  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("marking");
  if (root) mount(root);
}
