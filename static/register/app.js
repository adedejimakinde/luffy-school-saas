/**
 * The register screen: choose a class, mark who is absent, submit once.
 *
 * The first staff surface on a school's host. Everything before it was family.
 *
 * ## One submit, not one request per child
 *
 * `attendance/api.py` settled this and this page is the other half of it. A
 * marking sheet saves on blur because a teacher tabs through thirty cells over
 * twenty minutes and losing the tab must not lose the lot. A register is the
 * opposite interaction: one screen, a few taps, one submit, thirty seconds.
 * Forty-five conditional PUTs from a phone in a corridor is not a register.
 *
 * So the taps are held in the page's own memory until submit, and what goes
 * over the wire is the whole register — including `shown_ids`, the roster this
 * screen actually drew, which is what lets the answer name a child who joined
 * the group while it was open rather than silently marking them present.
 *
 * ## It opens with no connection, from a copy
 *
 * `docs/offline.md` S5. The page comes from the service worker (`/sw.js`); the
 * class list and rosters from a copy kept for this person at this school
 * (`web/snapshots.js`). A day nobody opened here shows the class's newest
 * roster, every child unmarked, as the server answers for a register not yet
 * taken.
 *
 * ## A submit queues the register; the outbox sends it
 *
 * Slice S6, and `outbox.js` has the rules. A submit puts the register in this
 * teacher's outbox for this school, with its **base**, what the screen showed
 * when it was opened (D4), and the outbox is drained at once when it can be and
 * again when the connection comes back. Online that is the same thirty seconds
 * as ever. With a base, the server writes only the children the teacher
 * changed, and a child somebody else changed meanwhile comes back as a conflict
 * the teacher answers on this page (D5).
 *
 * ## Absence is what is tapped
 *
 * `absent_ids` is the submission and everybody else the screen showed is
 * present. An empty list therefore means "every child was here", which is a
 * real register rather than an empty one.
 */

import { csrfToken } from "../web/http.js";
import { forgetPages, guardSignOut, registerWorker } from "../web/offline.js";
import { indexedDbSnapshots, liveOrCopy } from "../web/snapshots.js";
import { heldElsewhere, indexedDbStore, memoryStore, outboxesOf, othersOf, rememberWho } from "../web/store.js";
import { isOverdue, openOutbox, retryDelay } from "../marking/outbox.js";
import { REFUSAL, fetchRegister, fetchWhere, sendQueued, whoIsSignedIn } from "./api.js";
import {
  REPORT,
  STOPPED,
  baseOf,
  dismiss,
  drain,
  enqueue,
  keepTheirs,
  registerId,
  release,
  useMine,
} from "./outbox.js";
import * as states from "./states.js";

/**
 * The zone a school's day is counted in, when the page does not say.
 *
 * The page always says: `register_page()` renders `settings.TIME_ZONE` into
 * `data-time-zone`, the same setting `timezone.localdate()` reads on the
 * server, so the two cannot disagree about what "today" is.
 */
export const SCHOOL_TIME_ZONE = "Africa/Lagos";

/**
 * Today **in the school's time zone**, as the `YYYY-MM-DD` the API parses.
 *
 * It used to be `toISOString().slice(0, 10)`, which is the date in UTC. Lagos
 * is UTC+1, so from midnight to one in the morning that named yesterday. Nobody
 * takes a register at 00:30, which is why it went unnoticed. But a day is a
 * fact about the school, not about Greenwich, and a register queued offline
 * carries whatever day this computed (`docs/offline.md`, D9).
 *
 * `formatToParts` rather than a locale that happens to print ISO order, so the
 * answer does not depend on how some locale chooses to lay out a date.
 */
export function today(now = new Date(), timeZone = SCHOOL_TIME_ZONE) {
  const parts = {};
  for (const { type, value } of new Intl.DateTimeFormat("en-GB", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(now)) {
    parts[type] = value;
  }
  return `${parts.year}-${parts.month}-${parts.day}`;
}

/** What the date box may hold: a whole `YYYY-MM-DD`, and nothing else. */
const A_DAY = /^\d{4}-\d{2}-\d{2}$/;

/**
 * The markup for one state of the page. Pure, so every branch is testable.
 */
export function htmlFor(state, { portal = "", timeZone, now, entries = [], notTheAuthor = false, held = [] } = {}) {
  const queued = (list) =>
    states.waiting(list, { timeZone, now, notTheAuthor, overdue: (entry) => isOverdue(entry, now.getTime()) });
  switch (state.step) {
    case "choose":
      return queued(entries) + states.choose({ ...state, timeZone, now, held });
    case "kept":
      return states.kept(state);
    case "no-term":
      return states.noTerm();
    case "marking":
      return states.marking({ ...state, timeZone, now });
    case "done":
      return states.done(state) + queued(entries.filter((entry) => entry.id === state.entryId && entry.held));
    case "refused":
      return states.refused(state);
    case REFUSAL.NOT_A_MARKER:
      return states.notAMarker(state);
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
 * A 200 with no current term is **not** a refusal: the password was right, the
 * person may mark, and what is missing is a school setting. It gets its own
 * screen naming the thing the office can fix, for the same reason the staff
 * landing's `nowhere()` names the invitation.
 */
export function fromWhere(answer, { on = "" } = {}) {
  if (!answer.ok) return { step: answer.refusal, ...answer.body };
  if (!answer.body.term_id) return { step: "no-term" };
  return {
    step: "choose",
    term: answer.body.term,
    term_id: answer.body.term_id,
    classes: answer.body.classes || [],
    on,
    asOf: answer.asOf || null,
  };
}

/** Turn a `RegisterOut` into the marking screen, carrying nothing forward. */
export function fromRegister(answer) {
  if (!answer.ok) return { step: answer.refusal, ...answer.body };
  return {
    step: "marking",
    ...answer.body,
    // Pre-tapped from what is already recorded, so amending a register starts
    // from what it says rather than from blank — a teacher correcting one
    // child must not have to re-mark the other twenty-nine.
    absent: (answer.body.rows || [])
      .filter((row) => row.status === "absent")
      .map((row) => row.student_membership_id),
    // What the screen shows now, which the server compares with (D4).
    base: baseOf(answer.body.rows),
    asOf: answer.asOf || null,
  };
}

/** The name a register's copy is kept under: the class, the term and the day. */
export function registerName(classGroupId, termId, on) {
  return `register:${classGroupId}:${termId}:${on}`;
}

/**
 * The class's roster from the newest copy of any of its days, as the register
 * for `on` would read if nobody had taken it: every child unmarked. `null`
 * when the phone has no copy of this class at all.
 *
 * It is not a copy of `on`'s register and does not pretend to be: `asOf` is the
 * time the roster was seen, and `taken` is false.
 */
export function rosterFromEarlier(copies, on) {
  const newest = copies[0];
  if (!newest) return null;
  return {
    ok: true,
    asOf: newest.at,
    body: {
      ...newest.body,
      taken_on: on,
      taken: false,
      rows: (newest.body.rows || []).map((row) => ({ ...row, status: null })),
    },
  };
}

export async function mount(
  root,
  {
    fetchImpl = fetch,
    now = new Date(),
    host = root.dataset.host || (typeof location !== "undefined" ? location.host : ""),
    openSnapshots = indexedDbSnapshots,
    whenOnline = (run) => {
      if (typeof window !== "undefined") window.addEventListener("online", run);
    },
    signOutTarget = typeof document !== "undefined" ? document : null,
    confirmFn = (text) => (typeof window !== "undefined" ? window.confirm(text) : true),
    clearPages = forgetPages,
    openStore = indexedDbStore,
    schedule = (run, ms) => setTimeout(run, ms),
    mint,
  } = {},
) {
  const portal = root.dataset.portal || "";
  const timeZone = root.dataset.timeZone || undefined;
  let state = { step: "loading" };
  let where = null;
  let owner = null;
  let showingCopy = false;
  // Set at sign-out: nothing is kept after that, however late an answer comes.
  let leaving = false;
  let on = today(now, root.dataset.timeZone || SCHOOL_TIME_ZONE);
  const shelf = await openSnapshots();
  let outbox = null;
  let outboxName = null;
  let entries = [];
  let notTheAuthor = false;
  let held = [];
  let draining = null;
  let again = false;
  let failures = 0;
  let retrying = false;
  let freshToken = false;
  const answers = {};

  const draw = () => {
    root.innerHTML = htmlFor(state, { portal, timeZone, now, entries, notTheAuthor, held });
  };

  const change = async (update) => {
    entries = await outbox.update(update);
    return entries;
  };

  /**
   * Drain the outbox, one drain at a time; a kick that arrives during one is
   * not dropped. After a failed connection it tries again with backoff, and
   * fetches a fresh CSRF token first (D7).
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
          try {
            await csrfToken({ fetchImpl, refresh: true });
            freshToken = false;
          } catch {
            // Still no connection; the drain says so.
          }
        }
        stopped = await drain({
          outbox,
          owner,
          whoIsSignedIn: () => whoIsSignedIn({ fetchImpl }),
          send: (entry) => sendQueued(entry, { fetchImpl }),
          onChange: (list, entry, answer) => {
            entries = list;
            answers[entry.id] = answer;
          },
          now: () => now.getTime(),
          mint,
        });
      } while (again && stopped === STOPPED.EMPTY);
      return stopped;
    })().catch((error) => {
      console.error("The registers outbox could not be kept.", error);
      return null;
    });
    return draining.then(async (stopped) => {
      draining = null;
      entries = await outbox.read();
      notTheAuthor = stopped === STOPPED.NOT_THE_AUTHOR;
      if (stopped === STOPPED.OFFLINE || stopped === STOPPED.SESSION) freshToken = true;
      if (stopped === STOPPED.OFFLINE) {
        failures += 1;
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
      if (state.step === "choose") draw();
      return stopped;
    });
  };

  /** An answer from the server, or the phone's copy of the last one. */
  const seen = async (name, answer) => {
    const kept = await liveOrCopy({
      shelf,
      host,
      userId: name === "where" ? null : owner,
      name,
      answer,
      at: now.toISOString(),
      keeping: !leaving,
    });
    if (kept.asOf) showingCopy = true;
    return kept;
  };

  const load = async () => {
    showingCopy = false;
    const answer = await seen("where", await fetchWhere({ fetchImpl }));
    if (answer.ok) {
      where = answer.body;
      owner = answer.body.user_id;
    }
    if (owner !== null && owner !== undefined && !outbox) {
      outboxName = outboxesOf(host, owner)[1];
      outbox = openOutbox((await openStore(outboxName)) || memoryStore(outboxName));
      entries = await outbox.read();
      // Another person's unsent work on this phone: said, never shown (D7).
      await rememberWho(openStore, host, owner, where.full_name);
      held = await heldElsewhere(openStore, host, owner);
    }
    state = fromWhere(answer, { on });
    draw();
  };

  await load();

  // The connection is back while a copy is on screen: ask the server again.
  // Only from the class list — a register being looked at is left where it is,
  // and the next "Another class" is live.
  whenOnline(async () => {
    await kick();
    if (showingCopy && state.step === "choose") await load();
  });

  // Signing out deletes what is waiting on the phone, registers and marks
  // alike, so it asks first (D8).
  guardSignOut(signOutTarget, {
    waiting: async () => {
      let count = outbox ? (await outbox.read()).length : 0;
      for (const other of await othersOf(openStore, host, owner, outboxName)) count += (await other.read()).length;
      return count;
    },
    clear: async () => {
      leaving = true;
      if (shelf) await shelf.clearAll();
      if (outbox) await change(() => []);
      for (const other of await othersOf(openStore, host, owner, outboxName)) await other.write([]);
      await clearPages();
    },
    confirmFn,
  });

  // The day box. `states.choose()` has always drawn it, and until now nothing
  // listened, so a register for Wednesday entered on Friday was filed against
  // Friday. `change` rather than `input`: it fires once the date is committed,
  // not on every keystroke of a half-typed one. A box emptied or holding
  // something that is not a whole date keeps the day it had, because a register
  // filed against no day is worse than one filed against the last day chosen.
  root.addEventListener("change", (event) => {
    const field = event.target.closest('[data-field="on"]');
    if (!field) return;
    const picked = String(field.value || "");
    if (!A_DAY.test(picked)) return;
    on = picked;
    if (state.step === "choose") state = { ...state, on };
  });

  // Delegated from the root, because every state is redrawn wholesale and a
  // listener bound to a button would be bound to a node about to be replaced.
  root.addEventListener("click", async (event) => {
    const hit = event.target.closest("[data-action]");
    if (!hit) return;
    const action = hit.dataset.action;

    if (action === "back") {
      state = fromWhere({ ok: true, body: where }, { on });
      draw();
      return;
    }

    // What the list of waiting registers offers (`states.waiting()`).
    const id = hit.dataset.entry;
    if (outbox && id) {
      const sid = Number(hit.dataset.child);
      if (action === "retry") await change((list) => release(list, id, { mint }));
      if (action === "dismiss") await change((list) => dismiss(list, id));
      if (action === "keep-theirs") await change((list) => keepTheirs(list, id, sid));
      if (action === "use-mine") await change((list) => useMine(list, id, sid, { now: now.getTime(), mint }));
      draw();
      if (action === "retry" || action === "use-mine") await kick();
      draw();
      return;
    }

    if (action === "open") {
      const classGroupId = Number(hit.dataset.class);
      const live = await fetchRegister({ classGroupId, termId: where.term_id, on, fetchImpl });
      let answer = await seen(registerName(classGroupId, where.term_id, on), live);
      if (!answer.ok && live.offline && owner !== null && shelf) {
        const earlier = rosterFromEarlier(
          await shelf.copiesBeginning(host, owner, `register:${classGroupId}:${where.term_id}:`),
          on,
        );
        if (earlier) {
          answer = earlier;
          showingCopy = true;
        }
      }
      state = fromRegister(answer);
      draw();
      return;
    }

    if (action === "toggle" && state.step === "marking") {
      const id = Number(hit.dataset.child);
      const absent = new Set(state.absent);
      if (absent.has(id)) absent.delete(id);
      else absent.add(id);
      state = { ...state, absent: [...absent] };
      draw();
      return;
    }

    if (action === "submit" && state.step === "marking") {
      const rows = state.rows || [];
      // The names the screen drew, so every later sentence can say who.
      const names = {};
      for (const row of rows) names[row.student_membership_id] = row.student;
      const write = {
        classGroupId: state.class_group_id,
        termId: state.term_id,
        on: state.taken_on,
        absentIds: state.absent,
        shownIds: rows.map((row) => row.student_membership_id),
        base: state.base,
        classGroup: state.class_group,
        names,
      };
      if (!outbox) {
        state = { step: REFUSAL.BROKEN };
        draw();
        return;
      }
      const entryId = registerId(write.classGroupId, write.termId, write.on);
      await change((list) => enqueue(list, write, { now: now.getTime(), mint }));
      delete answers[entryId];
      const stopped = await kick();
      const left = entries.find((entry) => entry.id === entryId);
      const answer = answers[entryId];
      if (answer && answer.landed && (!left || (left.held && left.held.kind === REPORT))) {
        state = { step: "done", ...answer.taken, names, entryId };
      } else if (left && left.held) {
        state = { step: "refused", detail: left.held.detail };
      } else if (stopped === STOPPED.SESSION) {
        state = { step: REFUSAL.EXPIRED };
      } else {
        state = { step: "kept", class_group: write.classGroup, taken_on: write.on };
      }
      draw();
    }
  });

  // Whatever an earlier page load left queued goes now, if it can.
  await kick();
  draw();

  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("register");
  if (root) {
    registerWorker();
    mount(root);
  }
}
