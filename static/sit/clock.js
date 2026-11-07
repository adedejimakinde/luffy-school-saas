/**
 * The exam's clock: the **server's** time, carried forward on this device's monotonic
 * clock, never its wall clock. `docs/cbt.md`, "Offline".
 *
 * The server sends its `now` and the attempt's `deadline` with every answer it takes.
 * `sync()` pins the server's time to `performance.now()` at the moment the answer arrived,
 * less half the round trip, so a device whose own clock is wrong by an hour still counts
 * down the right minutes. Between answers it counts on its own.
 *
 * After a reload with no network there is no monotonic clock to carry over, so the clock
 * starts from the wall clock plus the offset it last measured (`fromKept()`): the one place
 * the wall clock is read, and the server enforces the deadline whatever this says.
 */

export const WARN_MS = 5 * 60 * 1000;

const monotonic = () => (typeof performance !== "undefined" && performance.now ? performance.now() : Date.now());

export function makeClock({ now = monotonic, wall = () => Date.now() } = {}) {
  let base = null; // { server: ms, at: monotonic ms }
  let offset = 0; // server ms - wall ms, at the last sync
  return {
    /** The server said `serverNow` (ISO or ms); the request left at `sentAt` (monotonic). */
    sync(serverNow, sentAt = null) {
      const server = typeof serverNow === "number" ? serverNow : Date.parse(serverNow);
      if (Number.isNaN(server)) return;
      const at = now();
      const half = sentAt === null ? 0 : Math.max(0, (at - sentAt) / 2);
      base = { server: server + half, at };
      offset = base.server - wall();
    },
    /** Start from a kept offset, for a reload with no network. */
    fromKept(keptOffset) {
      offset = Number(keptOffset) || 0;
      base = { server: wall() + offset, at: now() };
    },
    serverNow() {
      if (!base) return wall() + offset;
      return base.server + (now() - base.at);
    },
    offset() {
      return Math.round(offset);
    },
  };
}

/** `24:37`, or `1:12:40` past an hour. Never negative. */
export function formatLeft(ms) {
  const total = Math.max(0, Math.ceil(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const two = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${two(m)}:${two(s)}` : `${two(m)}:${two(s)}`;
}

/** The words a screen reader is given, once a minute: "24 minutes left". */
export function spokenLeft(ms) {
  const minutes = Math.max(0, Math.ceil(ms / 60000));
  if (minutes >= 60) {
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    return `${h} hour${h === 1 ? "" : "s"}${m ? ` ${m} minute${m === 1 ? "" : "s"}` : ""} left`;
  }
  return `${minutes} minute${minutes === 1 ? "" : "s"} left`;
}
