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
 *
 * ## A blur queues the mark; the outbox sends it
 *
 * `docs/offline.md` slice S3, and `outbox.js` has the rules. A blur no longer
 * sends: it puts the write in this teacher's outbox for this school, kept in
 * the browser, and the outbox is drained — at once when the connection is
 * there, again with backoff when it is not, and whenever the browser says it
 * is back online. An outbox left by an earlier page load is drained when the
 * page opens.
 *
 * What a teacher sees is still `applySave()`'s: every answer the outbox gets
 * is handed to it in the shape a direct save used to give it, so the sentences
 * and the in-the-box-or-in-the-note rules above stay in one place. What
 * changes is that a value not yet sent, and a value the server refused, are
 * now on the phone as well as on the screen, and are drawn back onto the sheet
 * when it is opened again (`withOutbox()`), until they land or the teacher
 * dismisses them.
 */

import { csrfToken } from "../web/http.js";
import { failureNote, sessionEnded, signOut } from "../web/signout.js";
import { REFUSAL, SAVE, fetchSheet, fetchWhere, sendQueued, whoIsSignedIn } from "./api.js";
import {
  HELD,
  STOPPED,
  cellOf,
  dismiss as dismissQueued,
  drain,
  enqueue,
  isOverdue,
  newKey,
  openOutbox,
  outboxName,
  release,
  retryDelay,
} from "./outbox.js";
import * as states from "./states.js";
import { indexedDbStore, memoryStore } from "./store.js";

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
        : "Not sent yet: the connection failed. It is kept on this phone and sent " +
          "when the connection is back, or press Try again.",
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

/** Is this outbox entry a cell of the sheet on screen? */
export function onThisSheet(state, entry) {
  return (
    state.step === "sheet" &&
    entry.assessmentId === state.assessment_id &&
    (state.rows || []).some((row) => row.student_membership_id === entry.studentMembershipId)
  );
}

/**
 * One outbox answer, drawn. `entries` is the outbox after the answer was
 * settled, which says what is now kept for the cell: the teacher's latest
 * value, which may be one typed while the attempt was out.
 */
export function afterSend(state, entries, entry, answer) {
  if (!onThisSheet(state, entry)) return state;
  const id = entry.studentMembershipId;
  const left = entries.find((e) => e.cell === entry.cell);
  const typed = left ? left.value : entry.value;

  if (answer.landed) {
    const landed = applySave(state, id, { ok: true, cell: answer.cell }, typed);
    // A value typed while this one was out is a write of its own, still queued.
    return left ? queued(landed, id, left.value) : landed;
  }
  if (answer.held) return held(state, id, answer, typed);
  if (answer.stop === STOPPED.SESSION) {
    return applySave(state, id, { ok: false, refusal: answer.refusal || REFUSAL.EXPIRED, body: {} }, typed);
  }
  return applySave(state, id, { ok: false, refusal: REFUSAL.BROKEN, body: {} }, typed);
}

/**
 * The sheet as the server drew it, with this teacher's outbox drawn over it:
 * every value not yet sent, and every value refused and not yet dismissed
 * (requirement 8). What a page load forgot, the phone kept.
 */
export function withOutbox(state, entries, { now = Date.now() } = {}) {
  let drawn = state;
  for (const entry of entries) {
    if (!onThisSheet(drawn, entry)) continue;
    const id = entry.studentMembershipId;
    const typed = entry.next === null || entry.next === undefined ? entry.value : entry.next;
    if (entry.held) {
      // The row is fresh from the server, so for a conflict it already shows
      // whatever is there now — which is what the teacher must see beside theirs.
      const row = drawn.rows.find((r) => r.student_membership_id === id);
      const current =
        row.value === null || row.value === undefined
          ? null
          : { student_membership_id: id, value: row.value, version: row.version };
      const closedTheSheet = [HELD.LOCKED, HELD.FORBIDDEN, HELD.REFUSED].includes(entry.held.kind);
      drawn = closedTheSheet
        ? heldBefore(drawn, id, entry.held, typed)
        : held(drawn, id, { ...entry.held, held: entry.held.kind, current }, typed);
    } else {
      drawn = queued(drawn, id, typed);
    }
    if (isOverdue(entry, now)) drawn = overdue(drawn, id);
  }
  return drawn;
}

/**
 * A value in the outbox and not yet answered. In the box, with Try again, and
 * with no Dismiss: it may already be on the wire, and a write that has left
 * cannot be called back.
 */
function queued(state, id, value) {
  return {
    ...state,
    notes: { ...state.notes, [id]: { kind: "queued", detail: "Not sent yet." } },
    kept: { ...state.kept, [id]: { value, inBox: true, retry: true, queued: true } },
  };
}

/** A final answer from the outbox, told to `applySave()` as a direct save's. */
function held(state, id, answer, typed) {
  switch (answer.held) {
    case HELD.CONFLICT:
      return applySave(state, id, { ok: false, outcome: SAVE.CONFLICT, body: { current: answer.current || null } }, typed);
    case HELD.LOCKED:
      return applySave(state, id, { ok: false, outcome: SAVE.LOCKED, body: { detail: answer.detail } }, typed);
    case HELD.INVALID:
      return applySave(state, id, { ok: false, outcome: SAVE.INVALID, body: { detail: answer.detail } }, typed);
    case HELD.FORBIDDEN:
      return applySave(state, id, { ok: false, refusal: REFUSAL.NOT_A_MARKER, body: { detail: answer.detail } }, typed);
    default:
      // Any other refusal: final, and nothing typed into the box would change it.
      return {
        ...state,
        notes: {
          ...state.notes,
          [id]: {
            kind: "unsaved",
            detail: `Not saved: ${answer.detail || "the school's server refused it."} You entered ${typed}.`,
          },
        },
        kept: { ...state.kept, [id]: { value: typed, inBox: false, retry: false } },
      };
  }
}

/**
 * A value a lock, or a refusal of authority, stopped on an earlier page load.
 *
 * Not drawn as the refusal was live, because it closed the sheet then and the
 * sheet as the server draws it now is what says whether it is closed. Still
 * locked: the note, and the boxes stay shut. Sent back since, or the teacher's
 * authority restored: the number is in the box with Try again, which sends it
 * as it was first queued (`release()`).
 */
function heldBefore(state, id, hold, typed) {
  const said = hold.detail ? ` ${hold.detail}` : "";
  if (state.locked) {
    return {
      ...state,
      notes: { ...state.notes, [id]: { kind: "unsaved", detail: `Not saved. You entered ${typed}.` } },
      kept: { ...state.kept, [id]: { value: typed, inBox: false, retry: false } },
    };
  }
  return {
    ...state,
    notes: {
      ...state.notes,
      [id]: { kind: "unsaved", detail: `Not saved when it was sent:${said} You entered ${typed}. Press Try again to send it now.` },
    },
    kept: { ...state.kept, [id]: { value: typed, inBox: true, retry: true } },
  };
}

/** OPEN-3: seven days, then flagged. Never deleted by the page. */
function overdue(state, id) {
  const note = state.notes[id];
  return {
    ...state,
    notes: { ...state.notes, [id]: { ...note, detail: `${note.detail} Entered more than seven days ago.` } },
  };
}

/**
 * Browsers that may delete what this page keeps. Safari, and every browser on
 * an iPhone or iPad, which all run Safari's engine, clear a site's stored data
 * after seven days of use without a visit to it (OPEN-6) — the same seven days
 * a queued mark is allowed to wait.
 */
export function storageMayBeCleared(userAgent = "") {
  if (/iPhone|iPad|iPod/.test(userAgent)) return true;
  return /Safari\//.test(userAgent) && !/(Chrome|Chromium|CriOS|Edg|OPR|Android)/.test(userAgent);
}

/** What a cell's box was drawn with: the kept number when it is in the box. */
function drawnValue(state, id) {
  const kept = (state.kept || {})[id];
  if (kept && kept.inBox) return kept.value;
  const row = (state.rows || []).find((r) => r.student_membership_id === id);
  return row ? row.value : null;
}

function replace(rows, id, cell) {
  return (rows || []).map((row) =>
    row.student_membership_id === id ? { ...row, ...cell } : row,
  );
}

/**
 * Draw the page into `root` and wire it.
 *
 * Everything the outbox needs from the browser is a parameter, so the tests
 * can hand it a store, a host and a clock: `openStore` is IndexedDB, `host` is
 * the school's (`outboxName()`), `schedule` is the backoff timer, `whenOnline`
 * is the browser's `online` event.
 */
export async function mount(
  root,
  {
    fetchImpl = fetch,
    host = root.dataset.host || (typeof location !== "undefined" ? location.host : ""),
    openStore = indexedDbStore,
    userAgent = typeof navigator !== "undefined" ? navigator.userAgent : "",
    schedule = (run, ms) => setTimeout(run, ms),
    whenOnline = (run) => {
      if (typeof window !== "undefined") window.addEventListener("online", run);
    },
    now = Date.now,
    mint = newKey,
  } = {},
) {
  const portal = root.dataset.portal || "";
  let state = { step: "loading" };
  let signOutFailed = false;
  let where = null;
  let picked = { assessmentId: null, classGroupId: null };
  let outbox = null;
  let owner = null;
  let warnings = [];
  let failures = 0;
  let draining = null;
  let again = false;
  let freshToken = false;
  let retrying = false;
  let stale = false;

  const draw = () => {
    root.innerHTML = htmlFor(state, { portal, signOutFailed });
  };

  const openSheet = async () => {
    if (!picked.assessmentId || !picked.classGroupId) return;
    state = fromSheet(await fetchSheet({ ...picked, fetchImpl }));
    if (state.step === "sheet") {
      state = { ...state, warnings };
      if (outbox) state = withOutbox(state, await outbox.read(), { now: now() });
    }
    draw();
  };

  /**
   * Drain the outbox, one drain at a time. A kick that arrives while a drain
   * runs is not dropped: that drain may already have found the queue empty, so
   * it goes round again.
   */
  const kick = () => {
    if (!outbox) return Promise.resolve(null);
    if (draining) {
      again = true;
      return draining;
    }
    draining = (async () => {
      let stopped;
      do {
        again = false;
        if (freshToken) {
          // D7: after an outage or a sign-in, the CSRF token is fetched afresh
          // before the first write rather than found stale by it.
          try {
            await csrfToken({ fetchImpl, refresh: true });
            freshToken = false;
          } catch {
            // No connection yet. The drain finds that out and says so.
          }
        }
        stopped = await drain({
          outbox,
          owner,
          whoIsSignedIn: () => whoIsSignedIn({ fetchImpl }),
          send: (entry) => sendQueued(entry, { fetchImpl }),
          onChange: (entries, entry, answer) => {
            state = afterSend(state, entries, entry, answer);
            // A resent write that landed may be answered from its receipt,
            // which says what the *first* arrival did (`sync/receipts.py`),
            // not what the cell holds now. The sheet is asked again once the
            // drain is done, rather than trusting that answer as current.
            if (answer.landed && entry.sent) stale = true;
            draw();
          },
          now,
          mint,
        });
      } while (again && stopped === STOPPED.EMPTY);
      return stopped;
    })().catch((error) => {
      // The browser refused to keep the outbox — a full disk, storage cleared
      // under the page. Said in the console and not swallowed; and the next
      // kick starts afresh rather than finding this one still running.
      console.error("The marks outbox could not be kept.", error);
      return null;
    });

    return draining.then(async (stopped) => {
      draining = null;
      if (stale) {
        stale = false;
        if (state.step === "sheet") await openSheet();
      }
      if (stopped === STOPPED.OFFLINE) {
        failures += 1;
        freshToken = true;
        // One retry waiting at a time. Every blur while offline ends in this
        // branch, and a timer each would be a polling loop per mark typed.
        if (!retrying) {
          retrying = true;
          schedule(() => {
            retrying = false;
            return kick();
          }, retryDelay(failures));
        }
      } else {
        failures = 0;
      }
      if (stopped === STOPPED.SESSION) freshToken = true;
      if (stopped === STOPPED.NOT_A_MARKER && state.step === "sheet" && !state.locked) {
        // As a 403 on a write closes the boxes (`applySave()`), and the marks
        // not yet sent stay queued: whoever this is, nothing is final for them.
        state = {
          ...state,
          locked: true,
          locked_reason:
            "The account signed in here cannot enter marks at this school now. The school " +
            "office can say why. Marks not yet sent are kept on this phone.",
        };
        draw();
      }
      if (state.step === "sheet") {
        const notTheAuthor = stopped === STOPPED.NOT_THE_AUTHOR;
        if (Boolean(state.notTheAuthor) !== notTheAuthor) {
          state = { ...state, notTheAuthor };
          draw();
        }
      }
      return stopped;
    });
  };

  const whereAnswer = await fetchWhere({ fetchImpl });
  if (whereAnswer.ok) {
    where = whereAnswer.body;
    owner = where.user_id;
    const name = outboxName(host, owner);
    const kept = await openStore(name);
    outbox = openOutbox(kept || memoryStore(name));
    if (!kept) {
      warnings = [
        "This browser is not keeping marks that have not been sent. " +
          "Keep this page open until every mark on it is saved.",
      ];
    } else if (storageMayBeCleared(userAgent)) {
      warnings = [
        "On this browser, marks that have not been sent can be deleted if this " +
          "site is not opened for seven days. Chrome on Android keeps them.",
      ];
    }
  }
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
      const id = Number(hit.dataset.child);
      const cell = cellOf(picked.assessmentId, id);
      const left = await outbox.update((entries) => dismissQueued(entries, cell));
      state = withOutbox(dismiss(state, id), left.filter((entry) => entry.cell === cell), { now: now() });
      draw();
      return;
    }
    if (action === "retry" && state.step === "sheet" && !state.locked) {
      const cell = cellOf(picked.assessmentId, Number(hit.dataset.child));
      await outbox.update((entries) => release(entries, cell, { mint }));
      await kick();
    }
  });

  // **The blur is the save.** `input` would fire per keystroke — thirty
  // requests for one two-digit mark. What it does now is queue the write and
  // kick the outbox, which sends it straight away when it can. A cell left as
  // it was drawn is not a write (below); sending a kept number again is what
  // Try again is for.
  root.addEventListener("blur", async (event) => {
    const field = event.target;
    if (!field || !field.dataset || field.dataset.child === undefined) return;
    if (state.step !== "sheet" || state.locked || !outbox) return;

    const id = Number(field.dataset.child);
    const raw = String(field.value).trim();
    // An emptied cell is not a mark of nought, and clearing one is a different
    // route. Leaving it alone here keeps `DELETE` the only way to unmark.
    if (raw === "") return;

    const version = field.dataset.version;
    const value = Number(raw);
    // Tabbing through a cell is not a decision about it. A box left as it was
    // drawn sends nothing: queued, an unchanged mark is a write that can come
    // back hours later as a conflict the teacher never made (D2's "cry
    // wolf"), and over a kept value it would replace that value with nobody
    // having chosen to (requirement 8).
    if (value === drawnValue(state, id)) return;
    await outbox.update((entries) =>
      enqueue(
        entries,
        {
          assessmentId: picked.assessmentId,
          studentMembershipId: id,
          value,
          expectedVersion: version === "" ? null : Number(version),
        },
        { now: now(), mint },
      ),
    );
    // Drawn as queued before it goes, so a redraw while it is on the wire —
    // the next cell's blur — shows the teacher's number and not the old one.
    state = queued(state, id, value);
    draw();
    await kick();
  }, true);

  // Whatever an earlier page load left queued goes now, if it can — after the
  // listeners, not before: a drain waits on the network, and a tap made while
  // it waited would land on a page with nothing listening for it.
  whenOnline(() => kick());
  await kick();

  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("marking");
  if (root) mount(root);
}
