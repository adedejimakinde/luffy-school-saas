/**
 * What this computer keeps of the attempt it holds, and the answers not yet sent.
 * `docs/cbt.md`, "Offline", and `docs/offline.md` S3 and S4.
 *
 * **Every choice is kept here first**, then sent. The outbox resends until the school
 * acknowledges each answer by its sequence number; `(session, seq)` is the server's
 * idempotency key, so a resend is harmless and nothing is sent twice in effect. The
 * attempt itself (the paper, the student, the deadline, the answers, the flags, the
 * question the student was on) is kept too, so a reload, or a power cut, reopens it
 * with or without a network.
 *
 * **Nothing is left behind**: `clear()` deletes every key once the school confirms the
 * submit, or on "This is not me". A copy that cannot be sent stays until it can; the
 * server refuses it if it is late.
 *
 * Storage is injected: `idbStorage()` in a browser (IndexedDB, one object store), and
 * `memoryStorage()` for the tests. Both answer `get`, `set` and `clear`.
 */

const DB = "classnode-sit";
const STORE = "kept";

export function memoryStorage(seed = {}) {
  const data = new Map(Object.entries(seed));
  return {
    data,
    async get(key) {
      return data.has(key) ? structuredClone(data.get(key)) : undefined;
    },
    async set(key, value) {
      data.set(key, structuredClone(value));
    },
    async clear() {
      data.clear();
    },
  };
}

/** IndexedDB, or memory where a browser refuses it (a private window). */
export function idbStorage(indexedDB = globalThis.indexedDB) {
  if (!indexedDB) return memoryStorage();
  let opened = null;
  const db = () => {
    if (!opened) {
      opened = new Promise((resolve, reject) => {
        const request = indexedDB.open(DB, 1);
        request.onupgradeneeded = () => request.result.createObjectStore(STORE);
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      });
    }
    return opened;
  };
  const run = async (mode, act) => {
    const handle = await db();
    return new Promise((resolve, reject) => {
      const tx = handle.transaction(STORE, mode);
      const request = act(tx.objectStore(STORE));
      tx.oncomplete = () => resolve(request ? request.result : undefined);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  };
  return {
    get: (key) => run("readonly", (s) => s.get(key)),
    set: (key, value) => run("readwrite", (s) => s.put(value, key)),
    clear: () => run("readwrite", (s) => s.clear()),
  };
}

/**
 * The kept attempt and its outbox, over `storage`.
 *
 * - `attempt` is `{ payload, answers, flags, current, offset, session }`;
 * - `pending` is the list of answers not yet acknowledged, in the order chosen;
 * - `events` is the list of device events (offline spans, leaving the page) not yet sent;
 * - `seq` is the next sequence number, per session, so a new session starts at 1.
 */
export function makeOutbox(storage) {
  // One write at a time: a choice and its acknowledgement must not race each other.
  let chain = Promise.resolve();
  const serial = (act) => {
    const next = chain.then(act, act);
    chain = next.catch(() => {});
    return next;
  };
  const read = async (key, fallback) => {
    const value = await storage.get(key);
    return value === undefined ? fallback : value;
  };

  return {
    attempt: () => read("attempt", null),
    pending: () => read("pending", []),
    events: () => read("events", []),

    /** Keep a freshly started (or reloaded) attempt. Unsent answers of the same session stay. */
    keep(attempt) {
      return serial(async () => {
        const before = await read("attempt", null);
        if (before && before.session !== attempt.session) {
          // Another session of this attempt (a reload elsewhere, a retake): the old
          // session's unsent answers still go, under the old session's cookie, which
          // this computer no longer holds; the server has them by time if they came.
          await storage.set("pending", []);
          await storage.set("events", []);
          await storage.set("seq", 1);
        }
        await storage.set("attempt", attempt);
      });
    },

    /** Change the kept attempt in place (the question the student is on, a flag). */
    update(change) {
      return serial(async () => {
        const kept = await read("attempt", null);
        if (!kept) return null;
        const next = { ...kept, ...change(kept) };
        await storage.set("attempt", next);
        return next;
      });
    },

    /** A choice: kept, then queued. Answers `{ seq, ... }`. */
    choose(itemId, chosen, chosenAt) {
      return serial(async () => {
        const seq = await read("seq", 1);
        const answer = { seq, item: Number(itemId), chosen: chosen === null ? null : Number(chosen), chosen_at: chosenAt };
        const pending = await read("pending", []);
        pending.push(answer);
        const kept = await read("attempt", null);
        if (kept) await storage.set("attempt", { ...kept, answers: { ...kept.answers, [String(itemId)]: answer.chosen } });
        await storage.set("pending", pending);
        await storage.set("seq", seq + 1);
        return answer;
      });
    },

    note(event) {
      return serial(async () => {
        const seq = await read("eventSeq", 1);
        const events = await read("events", []);
        events.push({ seq, ...event });
        await storage.set("events", events);
        await storage.set("eventSeq", seq + 1);
        return seq;
      });
    },

    /** The school has these answers and events: they leave the outbox. */
    acknowledge(seqs = [], eventSeqs = []) {
      return serial(async () => {
        const done = new Set(seqs);
        const pending = (await read("pending", [])).filter((a) => !done.has(a.seq));
        await storage.set("pending", pending);
        const doneEvents = new Set(eventSeqs);
        await storage.set("events", (await read("events", [])).filter((e) => !doneEvents.has(e.seq)));
        return pending;
      });
    },

    /** Nothing about this test is left on this computer. */
    clear() {
      return serial(() => storage.clear());
    },
  };
}
