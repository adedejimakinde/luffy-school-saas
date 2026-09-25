/**
 * Where the outbox is kept between page loads: IndexedDB, one record per
 * outbox (`outbox.js`, `outboxName()`).
 *
 * `docs/offline.md` D8. This is the first browser storage anything in
 * `static/` uses, and A6 is the risk it accepts: a lost phone holds the marks
 * its teacher had not yet sent, protected only by the phone's own lock. What is
 * kept is what the page would have sent — ids, numbers, versions — and nothing
 * it did not already show.
 *
 * One record per outbox rather than one per entry, so a change is one `put`
 * of the whole list and there is no moment at which half of it is written.
 * An outbox is a teacher's unsent marks for one school, tens of entries, not a
 * table.
 *
 * Both stores answer the same two calls, `read()` and `write(entries)`, and
 * nothing above them knows which it has. The memory one is what the tests
 * drive, and what the page falls back to when the browser will not open a
 * database — a private window, storage turned off — and says so.
 */

const DATABASE = "luffy-marks-outbox";
const OUTBOXES = "outboxes";

/**
 * The outbox named `name`, kept in IndexedDB. Resolves to null when the
 * browser has no IndexedDB, or refuses to open it.
 */
export async function indexedDbStore(name, { indexedDB = globalThis.indexedDB } = {}) {
  if (!indexedDB) return null;
  let db;
  try {
    db = await open(indexedDB);
  } catch {
    return null;
  }
  return {
    async read() {
      const record = await request(
        db.transaction(OUTBOXES, "readonly").objectStore(OUTBOXES).get(name),
      );
      return record ? record.entries : [];
    },
    async write(entries) {
      const tx = db.transaction(OUTBOXES, "readwrite");
      tx.objectStore(OUTBOXES).put({ name, entries });
      await done(tx);
    },
  };
}

/** The outbox named `name`, kept in `shelf` — a `Map` the caller owns. */
export function memoryStore(name, shelf = new Map()) {
  return {
    async read() {
      return structuredClone(shelf.get(name) || []);
    },
    async write(entries) {
      shelf.set(name, structuredClone(entries));
    },
  };
}

function open(indexedDB) {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DATABASE, 1);
    req.onupgradeneeded = () => {
      req.result.createObjectStore(OUTBOXES, { keyPath: "name" });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
    req.onblocked = () => reject(new Error("the outbox database is blocked"));
  });
}

function request(req) {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function done(tx) {
  return new Promise((resolve, reject) => {
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error || new Error("the outbox write was aborted"));
  });
}
