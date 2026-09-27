/**
 * Remarks: which class, then a list of who still needs what, then one child
 * at a time.
 *
 * ## Which class, and why it starts here now
 *
 * Issue #180: this page rendered no path at all to a `classGroupId` — the
 * frame set nothing, no query parameter existed, and nothing linked to one —
 * so every real caller silently asked for class 0 and read the wrong-host
 * refusal for it. `mount()` now starts at the chooser (`fetchClasses()`,
 * `states.choose()`) whenever it is not handed one directly, on the same
 * reasoning as `marking.choose()`: every class the school has, because
 * "who may sign" is the class list's question, asked once a class is picked,
 * not a scope this screen narrows in advance.
 *
 * ## Save on a button, not on blur
 *
 * The opposite of the marking sheet next door, and deliberately. A mark is two
 * keystrokes and thirty of them in twenty minutes, so losing the tab must not
 * lose the lot. A remark is a paragraph somebody composes, and a blur fires
 * every time they look away mid-sentence — saving half a thought thirty times
 * would fill the audit with drafts and, worse, `write_as()` is an upsert, so
 * each one overwrites the last complete version with a fragment.
 *
 * ## Ratings save on change, because they are not prose
 *
 * A score is one choice with no half-made state. There is nothing to lose by
 * committing it immediately and nothing to gain by making a teacher press a
 * second button for each of a dozen traits.
 */

import { failureNote, sessionEnded, signOut } from "../web/signout.js";
import { REFUSAL, SAVE, fetchChild, fetchClass, fetchClasses, saveRating, saveRemark } from "./api.js";
import * as states from "./states.js";

/** The markup for one state. Pure, so every branch is testable. */
export function htmlFor(state, { portal = "", signOutFailed = false } = {}) {
  const after = signOutFailed ? failureNote() : "";
  switch (state.step) {
    case "choose":
      return states.choose(state) + after;
    case "class":
      return states.classList(state) + after;
    case "child":
      return states.child(state) + after;
    case REFUSAL.NOT_A_SIGNATORY:
      return states.notASignatory(state) + after;
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

/** Issue #180: which class to open, drawn before anything else. */
export function fromClasses(answer) {
  if (!answer.ok) return { step: answer.refusal, ...answer.body };
  return { step: "choose", ...answer.body };
}

export function fromClass(answer) {
  if (!answer.ok) return { step: answer.refusal, ...answer.body };
  return { step: "class", ...answer.body };
}

export function fromChild(answer) {
  if (!answer.ok) return { step: answer.refusal, ...answer.body };
  return { step: "child", ...answer.body, notes: {} };
}

/**
 * What one save did to the screen.
 *
 * A **423** takes the whole screen read-only rather than retrying one box:
 * nothing the page can reload reopens a term that has left draft, and leaving
 * the other boxes live would invite a second paragraph into the same refusal.
 *
 * A **422** keeps what was typed. Clearing it would throw away the only copy
 * of the sentence the teacher just wrote, which is the failure the refusal
 * exists to prevent rather than cause.
 */
export function applySave(state, key, result) {
  const notes = { ...state.notes };
  if (result.ok) {
    delete notes[key];
    return { ...state, notes, saved: key };
  }
  if (result.refusal) return { step: result.refusal, ...result.body };
  if (result.outcome === SAVE.LOCKED) {
    return { ...state, notes, locked: true, locked_reason: result.body.detail };
  }
  notes[key] = {
    kind: result.outcome === SAVE.REJECTED ? "rejected" : "not-allowed",
    detail: result.body.detail,
  };
  return { ...state, notes };
}

export async function mount(root, { fetchImpl = fetch, classGroupId = null } = {}) {
  const portal = root.dataset.portal || "";
  // Issue #180: the frame never named a class. `classGroupId` is still here
  // for a page that one day does (a link from the results chain, say) and for
  // the tests that drive one class directly; a caller that gives neither
  // starts at the chooser rather than asking for class 0.
  let group = classGroupId !== null ? classGroupId : Number(root.dataset.class || 0) || null;
  let state = { step: "loading" };
  let signOutFailed = false;
  let openChild = null;
  // What is in each box right now, so a redraw after a save does not lose
  // typing the server has not been told about yet.
  let typed = {};

  const draw = () => {
    root.innerHTML = htmlFor(state, { portal, signOutFailed });
  };
  const loadClasses = async () => {
    group = null;
    openChild = null;
    typed = {};
    state = fromClasses(await fetchClasses({ fetchImpl }));
    draw();
  };
  const loadClass = async () => {
    openChild = null;
    typed = {};
    state = fromClass(await fetchClass({ classGroupId: group, fetchImpl }));
    draw();
  };
  const loadChild = async (id) => {
    openChild = id;
    typed = {};
    state = fromChild(await fetchChild({ studentMembershipId: id, fetchImpl }));
    draw();
  };

  if (group) await loadClass();
  else await loadClasses();

  root.addEventListener("click", async (event) => {
    const hit = event.target.closest("[data-action]");
    if (!hit) return;
    const action = hit.dataset.action;

    if (action === "sign-out") {
      const ended = sessionEnded(await signOut({ fetchImpl }));
      if (ended) {
        root.innerHTML = states.signedOut({ portal });
        return;
      }
      signOutFailed = true;
      draw();
      return;
    }
    if (action === "pick-class") {
      group = Number(hit.dataset.class);
      await loadClass();
      return;
    }
    if (action === "open") {
      await loadChild(Number(hit.dataset.child));
      return;
    }
    if (action === "back") {
      await loadClass();
      return;
    }
    if (action === "back-to-classes") {
      await loadClasses();
      return;
    }
    if (action === "phrase") {
      // Fills the box and leaves it editable — the bank is a starting point,
      // not a fixed set of answers.
      const author = hit.dataset.author;
      typed[author] = hit.dataset.text;
      state = {
        ...state,
        remarks: (state.remarks || []).map((r) =>
          r.author === author ? { ...r, body: hit.dataset.text } : r,
        ),
      };
      draw();
      return;
    }
    if (action === "save") {
      const author = hit.dataset.author;
      const box = root.querySelector
        ? root.querySelector(`[data-author="${author}"]`)
        : null;
      const body = box && box.value !== undefined ? box.value : typed[author] || "";
      state = applySave(
        state,
        author,
        await saveRemark({
          studentMembershipId: openChild,
          author,
          body,
          fetchImpl,
        }),
      );
      draw();
    }
  });

  root.addEventListener("change", async (event) => {
    const field = event.target;
    if (!field || !field.dataset || field.dataset.trait === undefined) return;
    if (state.step !== "child" || state.locked) return;
    const raw = String(field.value).trim();
    // An emptied select is "no score yet", and clearing a rating is a
    // different route. Sending 0 here would record a score nobody gave.
    if (raw === "") return;

    state = applySave(
      state,
      "rating",
      await saveRating({
        studentMembershipId: openChild,
        traitId: Number(field.dataset.trait),
        score: Number(raw),
        fetchImpl,
      }),
    );
    draw();
  });

  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("comments");
  if (root) mount(root);
}
