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
 * ## Absence is what is tapped
 *
 * `absent_ids` is the submission and everybody else the screen showed is
 * present. An empty list therefore means "every child was here", which is a
 * real register rather than an empty one.
 */

import { button as signOutButton, failureNote, sessionEnded, signOut } from "../web/signout.js";
import { REFUSAL, fetchRegister, fetchWhere, takeRegister } from "./api.js";
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
 *
 * `signOutFailed` renders **below** whatever is on screen rather than in place
 * of it: the register is still there and still submittable, and what changed is
 * only that the session is still open.
 */
export function htmlFor(state, { portal = "", signOutFailed = false } = {}) {
  const after = signOutFailed ? failureNote() : "";
  switch (state.step) {
    case "choose":
      return states.choose(state) + after;
    case "no-term":
      return states.noTerm() + after;
    case "marking":
      return states.marking(state) + after;
    case "done":
      return states.done(state) + after;
    case "refused":
      return states.refused(state) + after;
    case REFUSAL.NOT_A_MARKER:
      return states.notAMarker(state) + after;
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
  };
}

export async function mount(root, { fetchImpl = fetch, now = new Date() } = {}) {
  const portal = root.dataset.portal || "";
  let state = { step: "loading" };
  let signOutFailed = false;
  let where = null;
  let on = today(now, root.dataset.timeZone || SCHOOL_TIME_ZONE);

  const draw = () => {
    root.innerHTML = htmlFor(state, { portal, signOutFailed });
  };

  const load = async () => {
    const answer = await fetchWhere({ fetchImpl });
    if (answer.ok) where = answer.body;
    state = fromWhere(answer, { on });
    draw();
  };

  await load();

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

    if (action === "sign-out") {
      const ended = sessionEnded(await signOut({ fetchImpl }));
      if (ended) {
        // Not `expired: true`. Signing out on purpose deletes the cookie as
        // well as the session, so nothing lapsed and nothing is recoverable by
        // trying again.
        root.innerHTML = states.signedOut({ portal });
        return;
      }
      signOutFailed = true;
      draw();
      return;
    }

    if (action === "back") {
      state = fromWhere({ ok: true, body: where }, { on });
      draw();
      return;
    }

    if (action === "open") {
      state = fromRegister(
        await fetchRegister({
          classGroupId: Number(hit.dataset.class),
          termId: where.term_id,
          on,
          fetchImpl,
        }),
      );
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
      const shownIds = (state.rows || []).map((row) => row.student_membership_id);
      const answer = await takeRegister({
        classGroupId: state.class_group_id,
        termId: state.term_id,
        on: state.taken_on,
        absentIds: state.absent,
        shownIds,
        fetchImpl,
      });
      if (answer.ok) {
        // The names the screen drew, so the two warnings can say who rather
        // than print a membership id at a teacher.
        const names = {};
        for (const row of state.rows || []) names[row.student_membership_id] = row.student;
        state = { step: "done", ...answer.body, names };
      } else if (answer.refusal === null) {
        state = { step: "refused", ...answer.body };
      } else {
        state = { step: answer.refusal, ...answer.body };
      }
      draw();
    }
  });

  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("register");
  if (root) mount(root);
}
