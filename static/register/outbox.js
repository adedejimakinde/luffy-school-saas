/**
 * The registers outbox: every register the teacher took that has not landed.
 *
 * `docs/offline.md` slice S6, D2–D7. The marks outbox (`marking/outbox.js`)
 * has the long argument; this is the same queue for the other write, and only
 * what differs is said here.
 *
 * ## One entry per register per day, with its base (D2, D4)
 *
 * An entry is the request the page would send: the absent set, the roster the
 * screen drew, and the **base**, what the screen showed for each child when the
 * register was opened. Taking the same register again before it is sent
 * replaces the absent set and keeps the original base, so the server compares
 * with what the teacher was first shown. Once an attempt has left the device
 * its body is fixed (D3), and a retake waits in `next`.
 *
 * ## What comes back
 *
 * A register that lands may still need the teacher (D5): a child two people
 * answered differently (`conflicts`), a child who joined after the screen was
 * drawn (`appeared`), an absentee no longer in the class (`not_on_the_roster`).
 * The entry is then kept as a **report** until the teacher has answered each
 * conflict and dismissed the rest. A conflict is answered either way: keep the
 * school's, or send theirs again with the school's answer as the base, which is
 * a deliberate write over it.
 *
 * 422, 409 and 403 are final, as for marks; a failed connection, a 5xx and a
 * lapsed session are not answers.
 */

import { HELD, STOPPED, newKey } from "../marking/outbox.js";

export { HELD, STOPPED };

/** A held register that landed and still has something to say. */
export const REPORT = "report";

const ABSENT = "absent";
const PRESENT = "present";

/** One register: a class, a term, a day. */
export const registerId = (classGroupId, termId, on) => `${classGroupId}:${termId}:${on}`;

/**
 * The base as the API takes it, from the rows the screen drew: each child's
 * status then, or unmarked.
 */
export function baseOf(rows = []) {
  return {
    absent_ids: rows.filter((row) => row.status === ABSENT).map((row) => row.student_membership_id),
    present_ids: rows.filter((row) => row.status === PRESENT).map((row) => row.student_membership_id),
  };
}

/** Queue a register the teacher took. Returns the new entry list. */
export function enqueue(entries, write, { now = Date.now(), mint = newKey } = {}) {
  const id = registerId(write.classGroupId, write.termId, write.on);
  const absentIds = [...write.absentIds].sort((a, b) => a - b);
  const fresh = () => ({
    id,
    classGroupId: write.classGroupId,
    termId: write.termId,
    on: write.on,
    classGroup: write.classGroup || "",
    names: write.names || {},
    shownIds: write.shownIds,
    base: write.base,
    absentIds,
    key: mint(),
    sent: false,
    next: null,
    queuedAt: now,
    held: null,
  });
  const at = entries.findIndex((entry) => entry.id === id);
  if (at === -1) return [...entries, fresh()];
  const entry = entries[at];
  // Taking the register again is the teacher's answer to whatever was held.
  if (entry.held) return [...without(entries, at), fresh()];
  if (!entry.sent) {
    if (same(entry.absentIds, absentIds)) return entries;
    return replaceAt(entries, at, { ...entry, absentIds, key: mint() });
  }
  return replaceAt(entries, at, { ...entry, next: same(entry.absentIds, absentIds) ? null : absentIds });
}

export function nextToSend(entries) {
  return entries.find((entry) => !entry.held) || null;
}

export function markSent(entries, id) {
  const at = entries.findIndex((entry) => entry.id === id);
  if (at === -1 || entries[at].sent) return entries;
  return replaceAt(entries, at, { ...entries[at], sent: true });
}

/**
 * What one answer does to the entry it answers.
 *
 * Landed with a retake waiting: the retake becomes a write of its own, based on
 * what this one asked for, except that a child in conflict keeps the base the
 * teacher was first shown, so the conflict comes back rather than the retake
 * quietly writing over the school. Landed with something to say: kept as a
 * report. Landed with nothing to say: gone.
 */
export function settle(entries, id, answer, { now = Date.now(), mint = newKey } = {}) {
  const at = entries.findIndex((entry) => entry.id === id);
  if (at === -1) return entries;
  const entry = entries[at];
  const retake = entry.next !== null && entry.next !== undefined;

  if (answer.landed) {
    const taken = answer.taken || {};
    const conflicts = taken.conflicts || [];
    if (retake) {
      return replaceAt(entries, at, {
        ...entry,
        absentIds: entry.next,
        next: null,
        base: followingBase(entry, conflicts),
        key: mint(),
        sent: false,
        queuedAt: now,
      });
    }
    const report = {
      kind: REPORT,
      conflicts,
      appeared: entry.resolving ? [] : taken.appeared || [],
      notOnTheRoster: taken.not_on_the_roster || [],
    };
    if (!report.conflicts.length && !report.appeared.length && !report.notOnTheRoster.length) {
      return without(entries, at);
    }
    return replaceAt(entries, at, { ...entry, next: null, held: report });
  }
  if (answer.held) {
    if (answer.held === HELD.INVALID && retake) {
      return replaceAt(entries, at, { ...entry, absentIds: entry.next, next: null, key: mint(), sent: false });
    }
    return replaceAt(entries, at, {
      ...entry,
      absentIds: retake ? entry.next : entry.absentIds,
      next: null,
      held: { kind: answer.held, detail: answer.detail || "" },
    });
  }
  if (answer.toTheBack) return [...without(entries, at), entry];
  return entries;
}

/** The base a retake is sent with after its first attempt landed. */
function followingBase(entry, conflicts) {
  const absent = new Set(entry.absentIds);
  const was = Object.fromEntries(conflicts.map((c) => [c.student_membership_id, c.was]));
  const status = (sid) => (sid in was ? was[sid] : absent.has(sid) ? ABSENT : PRESENT);
  const shown = entry.shownIds || [];
  return {
    absent_ids: shown.filter((sid) => status(sid) === ABSENT),
    present_ids: shown.filter((sid) => status(sid) === PRESENT),
  };
}

/** Send a register held by a final answer again, deliberately. New key. */
export function release(entries, id, { mint = newKey } = {}) {
  const at = entries.findIndex((entry) => entry.id === id && entry.held && entry.held.kind !== REPORT);
  if (at === -1) return entries;
  return replaceAt(entries, at, { ...entries[at], held: null, sent: false, key: mint() });
}

/** The teacher is done with a held register. A report with conflicts left is not done. */
export function dismiss(entries, id) {
  const at = entries.findIndex((entry) => entry.id === id && entry.held);
  if (at === -1) return entries;
  const held = entries[at].held;
  if (held.kind === REPORT && held.conflicts.length) return entries;
  return without(entries, at);
}

/** The school's answer stands for this child. */
export function keepTheirs(entries, id, sid) {
  return answered(entries, id, sid);
}

/**
 * The teacher's answer goes over the school's, for this child alone: a new
 * write whose base is what the school has now, so it lands unless somebody
 * changes the child again first.
 */
export function useMine(entries, id, sid, { now = Date.now(), mint = newKey } = {}) {
  const entry = entries.find((e) => e.id === id);
  const conflict = entry && entry.held && (entry.held.conflicts || []).find((c) => c.student_membership_id === sid);
  if (!conflict) return entries;
  const write = {
    ...entry,
    id: `${id}#${sid}`,
    shownIds: [sid],
    absentIds: conflict.yours === ABSENT ? [sid] : [],
    base: {
      absent_ids: conflict.now === ABSENT ? [sid] : [],
      present_ids: conflict.now === PRESENT ? [sid] : [],
    },
    resolving: true,
    key: mint(),
    sent: false,
    next: null,
    queuedAt: now,
    held: null,
  };
  return [...answered(entries, id, sid).filter((e) => e.id !== write.id), write];
}

function answered(entries, id, sid) {
  const at = entries.findIndex((entry) => entry.id === id && entry.held && entry.held.kind === REPORT);
  if (at === -1) return entries;
  const held = entries[at].held;
  const conflicts = held.conflicts.filter((c) => c.student_membership_id !== sid);
  if (!conflicts.length && !held.appeared.length && !held.notOnTheRoster.length) return without(entries, at);
  return replaceAt(entries, at, { ...entries[at], held: { ...held, conflicts } });
}

/**
 * Send what is queued, oldest first, under the session of the person who
 * queued it and nobody else (D7). The same loop as `marking/outbox.js`'s.
 */
export async function drain({ outbox, owner, whoIsSignedIn, send, onChange = () => {}, now = Date.now, mint = newKey }) {
  if (!nextToSend(await outbox.read())) return STOPPED.EMPTY;
  let signedIn;
  try {
    signedIn = await whoIsSignedIn();
  } catch {
    return STOPPED.OFFLINE;
  }
  if (signedIn.stop) return signedIn.stop;
  if (signedIn.userId !== owner) return STOPPED.NOT_THE_AUTHOR;

  for (;;) {
    let entry = null;
    await outbox.update((entries) => {
      entry = nextToSend(entries);
      return entry ? markSent(entries, entry.id) : entries;
    });
    if (!entry) return STOPPED.EMPTY;
    const answer = await send(entry);
    const entries = await outbox.update((current) => settle(current, entry.id, answer, { now: now(), mint }));
    onChange(entries, entry, answer);
    if (answer.stop) return answer.stop;
  }
}

const same = (a, b) => a.length === b.length && a.every((value, i) => value === b[i]);

function replaceAt(entries, at, entry) {
  return entries.map((existing, i) => (i === at ? entry : existing));
}

function without(entries, at) {
  return entries.filter((_, i) => i !== at);
}
