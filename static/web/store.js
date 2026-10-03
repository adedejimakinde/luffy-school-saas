/**
 * Where the outboxes are kept between page loads: IndexedDB, one record per
 * outbox, a person's marks or registers at one host (`outboxesOf()`), so a
 * change is one `put` of the whole list. `docs/offline.md` D8: the first browser
 * storage in `static/`, and A6 is the risk it accepts; only what the page would
 * have sent is kept. The memory store is what the tests drive and what a page
 * falls back to when the browser will not open a database, and says so.
 */

// The name predates the registers' outbox and stays: renaming it would strand
// whatever a phone already holds.
const DATABASE = "luffy-marks-outbox";

/** The outboxes one person keeps at one host: marks first, then registers. */
export const outboxesOf = (host, userId) => [`${host} ${userId}`, `${host} ${userId} register`];

/** This person's other outboxes here, for sign-out to count and clear (D8). */
export async function othersOf(openStore, host, userId, mine) {
  const names = outboxesOf(host, userId).filter((name) => name !== mine);
  return (await Promise.all(names.map((name) => openStore(name)))).filter(Boolean);
}
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
