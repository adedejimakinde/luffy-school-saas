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

/**
 * Whose work this phone holds that is not this person's, for the line a shared
 * handset shows (`docs/offline.md` D7): `[{id, name, count}]`. Only a count and
 * a name are read out; the entries are never shown to anybody but their owner.
 */
export async function heldElsewhere(openStore, host, userId) {
  try {
    const mine = await openStore(outboxesOf(host, userId)[0]);
    const people = new Map();
    for (const name of mine ? (await mine.names()).filter((n) => n.startsWith(`${host} `)) : []) {
      const [id, kind] = name.slice(host.length + 1).split(" ");
      if (id === String(userId)) continue;
      const who = people.get(id) || { id, name: "", count: 0 };
      people.set(id, who);
      const entries = await (await openStore(name)).read();
      if (kind === "who") who.name = entries[0] || "";
      else who.count += entries.length;
    }
    return [...people.values()].filter((who) => who.count);
  } catch {
    return []; // A phone that cannot say is no reason to stop the page.
  }
}

/** Remember this person's name beside their outboxes, for `heldElsewhere()`. */
export async function rememberWho(openStore, host, userId, name) {
  try {
    const store = await openStore(`${host} ${userId} who`);
    if (store && name) await store.write([name]);
  } catch {
    // Only a name for a sentence; the page does not depend on it.
  }
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
    async names() {
      return request(db.transaction(OUTBOXES, "readonly").objectStore(OUTBOXES).getAllKeys());
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
    async names() {
      return [...shelf.keys()];
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
