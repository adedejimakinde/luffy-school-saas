/**
 * The marks outbox: every mark the teacher entered that has not landed yet.
 *
 * `docs/offline.md` slice S3 — D1, D2, D6 and D7. The page no longer sends a
 * mark and forgets it: a blur **queues** the write here, the queue is kept in
 * the browser (`store.js`), and `drain()` sends it — at once when the
 * connection is there, and again when it comes back when it is not.
 *
 * ## What an entry is (D1)
 *
 * Exactly the request the online page would have sent: the cell, the value,
 * and the `expected_version` the teacher was shown. Nothing here judges a mark.
 * Whether 25 fits in 20, whether the sheet is open, whether this teacher may
 * write at all — the server decides all of it when the write arrives, with the
 * code that decides it online. A queue that evaluated a rule would be a second
 * gradebook on the phone, with none of the first one's rules.
 *
 * ## One entry per cell (D2)
 *
 * A teacher who types 15 and corrects it to 17 before anything was sent has
 * made one decision, and the server sees one write: 17, claiming the version
 * the teacher was shown. Two writes would be wrong rather than wasteful — the
 * second would claim a version the first had moved, and the teacher would be
 * shown a conflict with themselves.
 *
 * Once an attempt has **left** the device its body is fixed, because its
 * answer may be lost and it must be sent again exactly (D3). A value typed
 * after that waits in `next`, and becomes a write of its own once the first
 * one's answer says which version it produced.
 *
 * ## Every write carries a key (D3, slice S4)
 *
 * Minted when the entry's body is settled and sent with every attempt at it.
 * A write whose answer was lost is sent again with the same key, and the
 * server answers it from its receipt instead of judging it again
 * (`sync/receipts.py`). A changed body gets a new key, because a key names one
 * write: the server refuses a key reused for a different one.
 *
 * ## Some answers are final (D6)
 *
 * 423, 422 and 403 cannot be fixed by sending again, so the entry is **held**:
 * it is not sent again, and the teacher's value stays on the device and on
 * screen until they dismiss it (requirement 8). A 409 is held too, as D5's
 * conflict. A failed connection, a 5xx or a lapsed session is not an answer,
 * and the entry waits, key and all, to be sent again.
 *
 * ## Whose, and where (D7, D8)
 *
 * An outbox belongs to one person at one school host — `outboxName()` — and
 * `drain()` sends it only while that person is the one signed in. A teacher at
 * two schools has two outboxes, and a write queued at St Mary's is never sent
 * from Grace's page.
 */

/** Held entries, by the answer that stopped them. */
export const HELD = {
  /** 409: somebody else's mark is there now (D5). */
  CONFLICT: "conflict",
  /** 423: the sheet left draft. Sending again cannot reopen it. */
  LOCKED: "locked",
  /** 422: the number is the problem. The teacher can retype it. */
  INVALID: "invalid",
  /** 403: this account can no longer enter marks here. */
  FORBIDDEN: "forbidden",
  /**
   * Any other refusal from the server — a 404 for a pupil who left, say.
   * Not one D6 names, and final for D6's reason: it would say the same again.
   */
  REFUSED: "refused",
};

/** Why a `drain()` stopped. */
export const STOPPED = {
  /** Nothing left that may be sent. Held entries do not count. */
  EMPTY: "empty",
  /** The connection failed, or the server did not answer: send again later. */
  OFFLINE: "offline",
  /** The session lapsed. Sending waits until the teacher signs in again. */
  SESSION: "session",
  /** Somebody other than the outbox's owner is signed in here (D7). */
  NOT_THE_AUTHOR: "not-the-author",
  /**
   * Whoever is signed in here cannot enter marks at this school now. The
   * server does not say who they are, so the queue is left as it is: it may
   * be the owner with a changed role, or somebody else on a shared phone.
   */
  NOT_A_MARKER: "not-a-marker",
};

/**
 * How long a write may wait before it is flagged: OPEN-3, decided in review as
 * seven days, flagged and **not** deleted. Deleting a mark the teacher entered
 * is the silent loss offline mode exists to prevent.
 */
export const FLAG_AFTER_MS = 7 * 24 * 60 * 60 * 1000;

/**
 * Whose outbox, at which school. The host is in the name because the host is
 * what picks the school's schema: a user id alone is the same person at two
 * schools, and would send St Mary's marks to Grace.
 */
export function outboxName(host, userId) {
  return `${host} ${userId}`;
}

/** The one entry a cell can have (D2). */
export function cellOf(assessmentId, studentMembershipId) {
  return `${assessmentId}:${studentMembershipId}`;
}

/**
 * A fresh key for a write whose body is now settled: a version 4 UUID.
 *
 * `randomUUID()` exists only in a secure context — HTTPS, or localhost — and a
 * page served over plain HTTP would throw here, inside the blur, and the mark
 * would never be queued. `getRandomValues()` exists everywhere, so the same
 * UUID is built from it when it must be.
 */
export function newKey(source = globalThis.crypto) {
  if (typeof source.randomUUID === "function") return source.randomUUID();
  const bytes = source.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/**
 * Queue what the teacher typed into a cell. Returns the new entry list.
 *
 * - **Nothing queued for the cell:** a new entry, claiming the version the
 *   cell was drawn with.
 * - **Queued, not yet sent:** the value is replaced and the *original* version
 *   kept (D2). New key, because the body changed and the old key never left.
 * - **Sent, answer not yet known:** the attempt is left exactly as it went, and
 *   the value waits in `next`. Typing back the value already in flight is not
 *   a second decision, and clears `next`.
 * - **Held:** the teacher typing again *is* their answer to the hold — over a
 *   conflict, a deliberate overwrite of the mark now shown; over a refused
 *   number, the corrected one. A new write, with the version the cell now has.
 */
export function enqueue(
  entries,
  { assessmentId, studentMembershipId, value, expectedVersion },
  { now = Date.now(), mint = newKey } = {},
) {
  const cell = cellOf(assessmentId, studentMembershipId);
  const fresh = () => ({
    cell,
    assessmentId,
    studentMembershipId,
    value,
    expectedVersion,
    key: mint(),
    sent: false,
    next: null,
    queuedAt: now,
    held: null,
  });

  const at = entries.findIndex((entry) => entry.cell === cell);
  if (at === -1) return [...entries, fresh()];

  const entry = entries[at];
  if (entry.held) return [...without(entries, at), fresh()];
  if (!entry.sent) {
    if (entry.value === value) return entries;
    return replaceAt(entries, at, { ...entry, value, key: mint() });
  }
  return replaceAt(entries, at, { ...entry, next: value === entry.value ? null : value });
}

/**
 * The next entry to send, oldest first. Held entries are never sent again, and
 * one waiting for the sheet to say what version to claim is not sent yet.
 */
export function nextToSend(entries) {
  return entries.find((entry) => !entry.held && !entry.awaiting) || null;
}

/**
 * Settle every entry waiting on the sheet (`settle()`, #161) against the rows
 * the sheet has now. The cell still holds the write that landed: the waiting
 * value goes on the version it shows. It holds something else: somebody wrote
 * after the teacher, and the waiting value is held as a conflict with it, as
 * it would have been had it been sent.
 */
export function rebase(entries, assessmentId, rows) {
  let changed = false;
  const next = entries.map((entry) => {
    if (!entry.awaiting || entry.assessmentId !== assessmentId) return entry;
    const row = rows.find((r) => r.student_membership_id === entry.studentMembershipId);
    if (!row) return entry;
    changed = true;
    if (row.value === entry.awaiting.landed) {
      return { ...entry, expectedVersion: row.version, awaiting: null };
    }
    return {
      ...entry,
      awaiting: null,
      held: {
        kind: HELD.CONFLICT,
        detail: "",
        current: row.value === null || row.value === undefined
          ? null
          : { student_membership_id: row.student_membership_id, value: row.value, version: row.version },
      },
    };
  });
  return changed ? next : entries;
}

/** Mark an entry's attempt as having left the device: its body is now fixed. */
export function markSent(entries, cell) {
  const at = entries.findIndex((entry) => entry.cell === cell);
  if (at === -1 || entries[at].sent) return entries;
  return replaceAt(entries, at, { ...entries[at], sent: true });
}

/**
 * What one answer does to the entry it answers. Returns the new entry list.
 *
 * `answer` is `sendQueued()`'s: `{landed, cell}`, `{held, detail, current}`, or
 * `{stop}`.
 *
 * - **Landed:** the entry goes — unless the teacher typed again while it was
 *   in flight, in which case that value becomes a new write claiming the
 *   version this one produced.
 * - **Held:** kept, not sent again. The value kept is the teacher's latest:
 *   what they typed after the attempt left would meet the same conflict, lock
 *   or refusal of authority. A 422 is the exception — it judged only the number
 *   that was sent, so a later number is a new write and is sent.
 * - **Stop:** unchanged, key and all, to be sent again as it is — at the back
 *   of the queue when the answer was a server error, so that one write the
 *   server fails every time cannot keep every other write from going.
 */
export function settle(entries, cell, answer, { now = Date.now(), mint = newKey } = {}) {
  const at = entries.findIndex((entry) => entry.cell === cell);
  if (at === -1) return entries;
  const entry = entries[at];
  const typedSince = entry.next !== null && entry.next !== undefined;

  if (answer.landed) {
    if (!typedSince) return without(entries, at);
    if (!answer.cell) {
      // Landed, and answered "already saved" with no version (#161): the
      // write typed since cannot know what version to claim. It waits for the
      // sheet to be read again (`rebase()`), rather than claiming the version
      // before the landed write — a conflict with the teacher's own mark — or
      // a version read later, which could be somebody else's.
      return replaceAt(entries, at, {
        ...entry,
        value: entry.next,
        next: null,
        expectedVersion: null,
        key: mint(),
        sent: false,
        queuedAt: now,
        awaiting: { landed: entry.value },
      });
    }
    return replaceAt(entries, at, {
      ...entry,
      value: entry.next,
      next: null,
      expectedVersion: answer.cell.version,
      key: mint(),
      sent: false,
      queuedAt: now,
    });
  }
  if (answer.held) {
    if (answer.held === HELD.INVALID && typedSince) {
      return replaceAt(entries, at, {
        ...entry,
        value: entry.next,
        next: null,
        key: mint(),
        sent: false,
      });
    }
    return replaceAt(entries, at, {
      ...entry,
      value: typedSince ? entry.next : entry.value,
      next: null,
      held: {
        kind: answer.held,
        detail: answer.detail || "",
        current: answer.current === undefined ? null : answer.current,
      },
    });
  }
  if (answer.toTheBack) return [...without(entries, at), entry];
  return entries;
}

/**
 * The teacher sends a held value again, deliberately: after a send-back reopened
 * a locked sheet, say (D6). It goes as it was queued — the same value, and the
 * version the teacher was first shown — so a mark somebody changed meanwhile is
 * still a conflict rather than overwritten. New key: the last attempt had an
 * answer, so this one is a new write.
 */
export function release(entries, cell, { mint = newKey } = {}) {
  const at = entries.findIndex((entry) => entry.cell === cell && entry.held);
  if (at === -1) return entries;
  return replaceAt(entries, at, { ...entries[at], held: null, sent: false, key: mint() });
}

/** The teacher is done with a held value: forget it. Only they can decide that. */
export function dismiss(entries, cell) {
  const at = entries.findIndex((entry) => entry.cell === cell && entry.held);
  return at === -1 ? entries : without(entries, at);
}

/** Has this entry been on the device for longer than OPEN-3's seven days? */
export function isOverdue(entry, now = Date.now()) {
  return now - entry.queuedAt > FLAG_AFTER_MS;
}

/**
 * How long to wait before sending again after the connection failed: doubling
 * from two seconds, never more than a minute. A phone that retried at once
 * would spend its battery on a dead network; one that gave up would need the
 * teacher to remember.
 */
export function retryDelay(failures) {
  return Math.min(60_000, 2_000 * 2 ** Math.max(0, failures - 1));
}

/**
 * One queue, serialised: every change is a read, a pure function, and a write,
 * and no two overlap. The page queues a blur while a drain is waiting on the
 * network; without this, the drain's write of its answer could land on top of
 * the blur's, and the mark typed in between would be gone.
 */
export function openOutbox(store) {
  let last = Promise.resolve();
  const update = (change) => {
    const run = last.then(async () => {
      const before = await store.read();
      const after = change(before);
      if (after !== before) await store.write(after);
      return after;
    });
    last = run.catch(() => {});
    return run;
  };
  return { read: () => update((entries) => entries), update };
}

/**
 * Send what is queued, oldest first, until nothing is left or an answer says
 * stop. Resolves to one of `STOPPED`.
 *
 * **Who is signed in is asked first, every time** (D7, requirement 5). The
 * outbox is sent only under the session of the person who queued it. A shared
 * phone, or a second tab signed in as somebody else, sends nothing, and the
 * queue is left as it is for its owner.
 *
 * An entry is marked sent **before** it goes, and stored: if the page dies
 * with the request on the wire, the next drain knows the body is fixed and
 * sends it again with the same key.
 */
export async function drain({
  outbox,
  owner,
  whoIsSignedIn,
  send,
  onChange = () => {},
  now = Date.now,
  mint = newKey,
}) {
  // Nothing to send is nothing to ask: a page load with an empty outbox costs
  // no request.
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
    // Picked and marked in one update: a blur between the two could change the
    // body and the key, and the body sent would not be the body marked.
    let entry = null;
    await outbox.update((entries) => {
      entry = nextToSend(entries);
      return entry ? markSent(entries, entry.cell) : entries;
    });
    if (!entry) return STOPPED.EMPTY;

    const answer = await send(entry);
    const entries = await outbox.update((current) =>
      settle(current, entry.cell, answer, { now: now(), mint }),
    );
    onChange(entries, entry, answer);
    if (answer.stop) return answer.stop;
  }
}

function replaceAt(entries, at, entry) {
  return entries.map((existing, i) => (i === at ? entry : existing));
}

function without(entries, at) {
  return entries.filter((_, i) => i !== at);
}
