/**
 * The snapshots over a `Map`, for the tests: the same calls the page's
 * IndexedDB store answers, over the same logic (`snapshotsOver`). Not served;
 * a page with no IndexedDB has no copies.
 */

import { snapshotsOver } from "../../static/web/snapshots.js";

export function memorySnapshots(shelf = new Map()) {
  return snapshotsOver({
    async get(id) {
      return shelf.has(id) ? structuredClone(shelf.get(id)) : null;
    },
    async put(record) {
      shelf.set(record.id, structuredClone(record));
    },
    async list(predicate) {
      return [...shelf.values()].filter(predicate).map((record) => structuredClone(record));
    },
    async remove(predicate) {
      for (const [id, record] of [...shelf]) if (predicate(record)) shelf.delete(id);
    },
  });
}
