/**
 * The copy a page keeps of what it last showed, so it can open with no
 * connection (`docs/offline.md` S5, D8, D10). It is the server's last answer as
 * it came, drawn with the time it was taken; it decides nothing.
 *
 * Each copy belongs to one person at one school host. Offline nobody can say who
 * is signed in, so the page reads the copy of whoever last opened this host
 * online (`last()`); on a phone two people share, that can be the wrong one
 * (slice S7). Own database, apart from the outbox: a copy can be fetched again.
 * Where there is no IndexedDB there are no copies: one in memory would not
 * survive the reload that needs it.
 */

import { esc } from "./html.js";

const DATABASE = "luffy-snapshots";
const SNAPSHOTS = "snapshots";

/** A record's key: host, person and name, joined by a character none contains. */
export const snapshotId = (host, userId, name) => `${host}\u0000${userId}\u0000${name}`;

/** The record that says whose copy this host last showed. */
export const lastId = (host) => `${host}\u0000last`;

/** The snapshots in IndexedDB; null when the browser has none or will not open it. */
export async function indexedDbSnapshots({ indexedDB = globalThis.indexedDB } = {}) {
  if (!indexedDB) return null;
  let db;
  try {
    db = await open(indexedDB);
  } catch {
    return null;
  }
  const store = (mode) => db.transaction(SNAPSHOTS, mode).objectStore(SNAPSHOTS);
  return snapshotsOver({
    async get(id) {
      return (await request(store("readonly").get(id))) || null;
    },
    async put(record) {
      const tx = db.transaction(SNAPSHOTS, "readwrite");
      tx.objectStore(SNAPSHOTS).put(record);
      await done(tx);
    },
    async list(predicate) {
      return (await request(store("readonly").getAll())).filter(predicate);
    },
    async remove(predicate) {
      const tx = db.transaction(SNAPSHOTS, "readwrite");
      const objects = tx.objectStore(SNAPSHOTS);
      await new Promise((resolve, reject) => {
        const cursor = objects.openCursor();
        cursor.onsuccess = () => {
          const at = cursor.result;
          if (!at) return resolve();
          if (predicate(at.value)) at.delete();
          at.continue();
        };
        cursor.onerror = () => reject(cursor.error);
      });
      await done(tx);
    },
  });
}

/**
 * The calls every store answers, over four primitives (`get`, `put`, `list`,
 * `remove`). Exported so a test can drive the same calls over a `Map`.
 */
export function snapshotsOver({ get, put, list, remove }) {
  return {
    async keep(host, userId, name, body, at) {
      await put({ id: snapshotId(host, userId, name), host, userId, name, at, body });
      await put({ id: lastId(host), host, userId, name: null, at, body: null });
    },
    async copy(host, userId, name) {
      const record = await get(snapshotId(host, userId, name));
      return record ? { at: record.at, body: record.body } : null;
    },
    async last(host) {
      const record = await get(lastId(host));
      return record ? record.userId : null;
    },
    async copiesBeginning(host, userId, prefix) {
      const found = await list(
        (record) =>
          record.host === host &&
          record.userId === userId &&
          typeof record.name === "string" &&
          record.name.startsWith(prefix),
      );
      return found
        .map((record) => ({ name: record.name, at: record.at, body: record.body }))
        .sort((a, b) => (a.at < b.at ? 1 : -1));
    },
    async clearHost(host) {
      await remove((record) => record.host === host);
    },
    async clearAll() {
      await remove(() => true);
    },
  };
}

/**
 * What a page does with an answer, given the copy it may need.
 *
 * - A live 200 is kept as the new copy and handed back.
 * - No answer at all (`answer.offline`: the connection failed, or a 5xx): the
 *   copy comes back as a 200 carrying `asOf`; with none, the failure as it was.
 * - Any other answer (401, 403, 404) is the server's and is handed back: a copy
 *   is never put over a refusal. A 401 with nobody signed in
 *   (`answer.signedOut`) also drops this host's copies.
 *
 * `userId` null means the page's first fetch: live, the id is in the body;
 * offline, it is `shelf.last()`. `keeping: false` serves and keeps nothing: an
 * answer still on its way when the copies were cleared must not write one again.
 * A store that fails never fails the page; with no store (`shelf` null) a page
 * has no copies and nothing changes.
 */
export async function liveOrCopy({ shelf, host, userId = null, name, answer, at = new Date().toISOString(), keeping = true }) {
  const quietly = async (work) => {
    try {
      await work();
    } catch (error) {
      console.error("The copies of this page could not be kept.", error);
    }
  };
  if (!shelf) return answer;
  if (answer.ok) {
    const owner = userId === null ? answer.body.user_id : userId;
    if (keeping && owner !== undefined && owner !== null) {
      await quietly(() => shelf.keep(host, owner, name, answer.body, at));
    }
    return answer;
  }
  if (answer.signedOut) {
    await quietly(() => shelf.clearHost(host));
    return answer;
  }
  if (!answer.offline) return answer;
  try {
    const owner = userId === null ? await shelf.last(host) : userId;
    if (owner === null) return answer;
    const copy = await shelf.copy(host, owner, name);
    if (!copy) return answer;
    return { ok: true, body: copy.body, asOf: copy.at, copyOf: owner };
  } catch {
    return answer;
  }
}

/**
 * When a copy was taken, in a teacher's words: "today 16:40", "yesterday
 * 16:40", or the date. In the school's zone: "today" is the school's, not the
 * phone's (A7).
 */
export function asOfText(at, { now = new Date(), timeZone = "Africa/Lagos" } = {}) {
  const taken = new Date(at);
  if (Number.isNaN(taken.getTime())) return "an earlier time";
  const show = (date, options) => new Intl.DateTimeFormat("en-GB", { timeZone, ...options }).format(date);
  // dd/mm/yyyy in the school's zone, as a whole day.
  const day = (date) =>
    Date.parse(show(date, { year: "numeric", month: "2-digit", day: "2-digit" }).split("/").reverse().join("-"));
  const clock = show(taken, { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
  const apart = Math.round((day(now) - day(taken)) / 86_400_000);
  if (apart === 0) return `today ${clock}`;
  if (apart === 1) return `yesterday ${clock}`;
  return `${show(taken, { weekday: "short", day: "numeric", month: "short" })} ${clock}`;
}

/** The line shown when a page draws a copy and not the server's answer. */
export function copyNote(asOf, { timeZone, now, saying = "" } = {}) {
  if (!asOf) return "";
  const when = asOfText(asOf, { now: now || new Date(), timeZone: timeZone || "Africa/Lagos" });
  return (
    `<p class="copy" role="status">This is a copy from ${esc(when)}. ` +
    `You are not connected.${saying ? ` ${esc(saying)}` : ""}</p>`
  );
}

function open(indexedDB) {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DATABASE, 1);
    req.onupgradeneeded = () => {
      req.result.createObjectStore(SNAPSHOTS, { keyPath: "id" });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
    req.onblocked = () => reject(new Error("the snapshot database is blocked"));
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
    tx.onabort = () => reject(tx.error);
  });
}
