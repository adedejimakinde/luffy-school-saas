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
 *
 * ## A mark that did not land is kept, and shown, until the teacher says so
 *
 * `docs/offline.md` D5 and slice S2. Every answer that is not a save keeps the
 * value the teacher typed in `kept`, and it stays on screen until they save it
 * or dismiss it. Where it stays depends on what the teacher can do about it:
 *
 * - **in the box**, when typing again is the remedy: a number the server
 *   refused (422), a connection that failed, a session that ended. The last
 *   two also get **Try again**, which sends the kept value with the version
 *   the cell was drawn with. Replaying is safe; `test_session_expiry.py`
 *   pins that.
 * - **in the note**, when the box now belongs to somebody else's answer:
 *   a conflict (the box shows their mark, so overwriting is deliberate), a
 *   locked sheet (423) or a refusal of authority (403), where no box can be
 *   typed in at all.
 *
 * None of these replaces the sheet any more. It used to, for a failed
 * connection and for a lapsed session, and the typed mark went with it.
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
      return states.sheet({ ...state, portal }) + after;
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
  return { step: "sheet", ...answer.body, notes: {}, kept: {}, session: null };
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
 * - **invalid** — the number is the problem. What was typed is left in the
 *   box to be corrected, because clearing it would throw away the only copy.
 *
 * `typed` is what the teacher entered. Every branch that is not a save keeps
 * it — see the module docstring for where, and why there.
 */
export function applySave(state, id, result, typed = null) {
  const notes = { ...state.notes };
  const kept = { ...state.kept };
  if (result.ok) {
    delete notes[id];
    delete kept[id];
    return { ...state, notes, kept, session: null, rows: replace(state.rows, id, result.cell) };
  }
  if (result.outcome === SAVE.CONFLICT) {
    const current = result.body.current;
    notes[id] = {
      kind: "conflict",
      detail: current
        ? `Saved as ${current.value} by somebody else. You entered ${typed}. ` +
          "Type over it to change it."
        : `Somebody cleared this mark while you were typing it. You entered ${typed}.`,
    };
    kept[id] = { value: typed, inBox: false, retry: false };
    return {
      ...state,
      notes,
      kept,
      rows: replace(state.rows, id, current || { student_membership_id: id, value: null, version: null }),
    };
  }
  if (result.outcome === SAVE.LOCKED) {
    notes[id] = { kind: "unsaved", detail: `Not saved. You entered ${typed}.` };
    kept[id] = { value: typed, inBox: false, retry: false };
    return { ...state, notes, kept, locked: true, locked_reason: result.body.detail };
  }
  if (result.outcome === SAVE.INVALID) {
    notes[id] = { kind: "invalid", detail: result.body.detail };
    kept[id] = { value: typed, inBox: true, retry: false };
    return { ...state, notes, kept };
  }
  if (result.refusal === REFUSAL.NOT_A_MARKER) {
    // Authority changed under an open sheet. Nothing here can be typed any
    // more, so the value goes in the note and the sheet closes.
    notes[id] = { kind: "unsaved", detail: `Not saved. You entered ${typed}.` };
    kept[id] = { value: typed, inBox: false, retry: false };
    return {
      ...state,
      notes,
      kept,
      locked: true,
      locked_reason:
        (result.body && result.body.detail) ||
        "Your account can no longer enter marks on this sheet. The school office can say why.",
    };
  }
  if (
    result.refusal === REFUSAL.EXPIRED ||
    result.refusal === REFUSAL.SIGNED_OUT ||
    result.refusal === REFUSAL.BROKEN
  ) {
    const lapsed = result.refusal !== REFUSAL.BROKEN;
    notes[id] = {
      kind: "unsaved",
      detail: lapsed
        ? "Not saved: your session has ended. Sign in again, then press Try again."
        : "Not saved: the connection failed. Press Try again.",
    };
    kept[id] = { value: typed, inBox: true, retry: true };
    return {
      ...state,
      notes,
      kept,
      session: lapsed ? (result.refusal === REFUSAL.EXPIRED ? "expired" : "signed-out") : state.session,
    };
  }
  return { step: result.refusal, ...result.body };
}

/** The teacher is done with a kept value: forget it and the note about it. */
export function dismiss(state, id) {
  const notes = { ...state.notes };
  const kept = { ...state.kept };
  delete notes[id];
  delete kept[id];
  return { ...state, notes, kept };
}

function replace(rows, id, cell) {
  return (rows || []).map((row) =>
    row.student_membership_id === id ? { ...row, ...cell } : row,
  );
}

/** The version a cell's next save claims: what it was drawn with, or null. */
function versionOf(state, id) {
  const row = (state.rows || []).find((r) => r.student_membership_id === id);
  return row && row.version !== null && row.version !== undefined ? row.version : null;
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

  const save = async (id, value, expectedVersion) => {
    state = applySave(
      state,
      id,
      await saveScore({
        assessmentId: picked.assessmentId,
        studentMembershipId: id,
        value,
        expectedVersion,
        fetchImpl,
      }),
      value,
    );
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
      return;
    }
    if (action === "dismiss" && state.step === "sheet") {
      state = dismiss(state, Number(hit.dataset.child));
      draw();
      return;
    }
    if (action === "retry" && state.step === "sheet" && !state.locked) {
      const id = Number(hit.dataset.child);
      const held = (state.kept || {})[id];
      if (!held || !held.retry) return;
      await save(id, held.value, versionOf(state, id));
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
    await save(id, Number(raw), version === "" ? null : Number(version));
  }, true);

  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("marking");
  if (root) mount(root);
}
