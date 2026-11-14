/**
 * End-of-session promotion: review every class, then confirm once.
 *
 * **Nothing moves until the second button.** The first submit only reads the
 * form into a plan and shows what it would do; the confirm posts that plan and
 * the server moves every child or none. A refusal (the school changed since
 * the page was drawn, a child already placed, a child not decided) keeps the
 * summary up with the server's sentence, and nothing has moved.
 *
 * **Each child's choice is the principal's decision, not a field on this page**
 * (audit finding G-04). The plan sends what the review said was decided, and
 * the server refuses anything else. The principal records decisions a class at
 * a time, with a reason, which is a write of its own; the page is then drawn
 * again from the school.
 */

import {
  REFUSAL,
  confirmPlan,
  fetchReview,
  fetchYearSettings,
  recordDecisions,
  saveYearSettings,
} from "./api.js";
import * as states from "./states.js";

export function htmlFor(state, { portal = "" } = {}) {
  switch (state.step) {
    case "review":
      return states.review(state);
    case "confirm":
      return states.confirm(state);
    case "done":
      return states.done(state.outcome);
    case REFUSAL.NOT_ALLOWED:
      return states.notAllowed(state);
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

export function fromReview(answer) {
  if (!answer.ok) return { step: answer.refusal, ...answer.body };
  return { step: "review", ...answer.body, note: null };
}

/**
 * What the form's fields say, as the plan the server takes: every class with
 * its destination and every child's choice. `null` when a class has no
 * destination chosen, which the page says instead of posting.
 */
export function planFrom(form, classes = []) {
  const plan = [];
  for (const row of classes) {
    const dest = form[`dest_${row.class_group_id}`];
    const value = dest ? dest.value : "";
    if (!value) return null;
    const graduate = value === "graduate";
    plan.push({
      class_group_id: row.class_group_id,
      graduate,
      destination_id: graduate ? null : Number(value),
      // What the principal decided, as the review gave it. Never a default.
      children: Object.fromEntries(row.children.map((c) => [String(c.membership_id), c.action])),
    });
  }
  return plan;
}

/** How many children nobody has decided about. The plan waits for nought. */
export function undecidedIn(classes = []) {
  return classes.reduce((n, row) => n + row.children.filter((c) => !c.action).length, 0);
}

/**
 * The decisions one class's controls ask to record: every child whose select
 * says something other than what is already decided. `{}` when nothing would
 * change.
 */
export function decisionsFrom(form, row) {
  const wanted = {};
  for (const child of row.children) {
    const field = form[`decide_${child.membership_id}`];
    const value = field ? field.value : "";
    if (value && (!child.decision || child.decision.status !== value)) {
      wanted[String(child.membership_id)] = value;
    }
  }
  return wanted;
}

/** The settings form's fields, as the route takes them. */
export function settingsFrom(form) {
  const weighted = form.averaging && form.averaging.value === "weighted";
  const text = (name) => (form[name] && form[name].value !== "" ? String(form[name].value) : null);
  return {
    averaging: weighted ? "weighted" : "equal",
    first_weight: weighted ? text("first_weight") : null,
    second_weight: weighted ? text("second_weight") : null,
    third_weight: weighted ? text("third_weight") : null,
    pass_mark: text("pass_mark"),
  };
}

/** Where each class was pointed, so drawing the page again keeps it. */
function destinationsOf(form, classes) {
  const kept = {};
  for (const row of classes) {
    const field = form[`dest_${row.class_group_id}`];
    if (field && field.value) kept[row.class_group_id] = field.value;
  }
  return kept;
}

function withDestinations(classes, kept) {
  return classes.map((row) => {
    const value = kept[row.class_group_id];
    if (!value) return row;
    return value === "graduate"
      ? { ...row, graduate: true, destination_id: null }
      : { ...row, graduate: false, destination_id: Number(value) };
  });
}

/** The words for a plan: where each class goes and how many stay behind. */
export function summarise(plan, classes, targets) {
  const named = new Map(targets.map((t) => [t.class_group_id, t.name]));
  const byId = new Map(classes.map((c) => [c.class_group_id, c]));
  const totals = { promoted: 0, repeated: 0, graduated: 0, left: 0 };
  const summary = plan.map((entry) => {
    const repeating = Object.values(entry.children).filter((v) => v === "repeat").length;
    const leaving = Object.values(entry.children).filter((v) => v === "leave").length;
    const total = Object.keys(entry.children).length;
    totals.repeated += repeating;
    totals.left += leaving;
    totals[entry.graduate ? "graduated" : "promoted"] += total - repeating - leaving;
    return {
      name: byId.get(entry.class_group_id).name,
      to: entry.graduate ? "Graduated" : named.get(entry.destination_id) || "?",
      repeating,
      leaving,
    };
  });
  return { summary, totals };
}

export async function mount(root, { fetchImpl = fetch } = {}) {
  const portal = root.dataset.portal || "";
  const onSchool = root.dataset.onSchool === "yes";
  let state = { step: "loading" };
  let review = null;
  let settings = null;

  const draw = () => {
    root.innerHTML = htmlFor(state, { portal });
  };

  /** The review as the school has it now, keeping where the classes were pointed. */
  const load = async (kept = {}, notes = {}) => {
    const fresh = fromReview(await fetchReview({ fetchImpl }));
    if (fresh.step === "review") {
      fresh.settings = settings;
      if (fresh.classes) {
        fresh.classes = withDestinations(fresh.classes, kept).map((row) =>
          notes[row.class_group_id] ? { ...row, note: notes[row.class_group_id] } : row,
        );
      }
      review = fresh;
    }
    state = fresh;
  };

  if (onSchool) {
    settings = await fetchYearSettings({ fetchImpl });
    await load();
  } else {
    state = { step: REFUSAL.WRONG_HOST };
  }
  draw();

  root.addEventListener("click", async (event) => {
    const hit = event.target.closest ? event.target.closest("[data-action]") : null;
    if (!hit) return;
    if (hit.dataset.action === "back") {
      if (review) state = { ...review, note: null };
      draw();
      return;
    }
    if (hit.dataset.action === "decide" && review) {
      // The principal records one class's decisions, with one reason.
      const form = hit.form;
      const classId = Number(hit.dataset.class);
      const row = review.classes.find((c) => c.class_group_id === classId);
      if (!form || !row) return;
      const kept = destinationsOf(form, review.classes);
      const children = decisionsFrom(form, row);
      const reasonField = form[`reason_${classId}`];
      const reason = reasonField ? reasonField.value.trim() : "";
      let note = "";
      if (!Object.keys(children).length) note = "Nothing to record: every child here already has that decision.";
      else if (!reason) note = "Say why. The reason is kept with each decision.";
      if (!note) {
        const result = await recordDecisions({ children, reason }, { fetchImpl });
        if (result.refusal) {
          state = { step: result.refusal, ...result.body };
          draw();
          return;
        }
        if (!result.ok) note = result.note;
      }
      await load(kept, note ? { [classId]: note } : {});
      draw();
    }
  });

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form) return;
    if (event.preventDefault) event.preventDefault();

    if (form.dataset && form.dataset.form === "settings") {
      const result = await saveYearSettings(settingsFrom(form), { fetchImpl });
      settings = result.ok
        ? { ...result.body, note: "Saved.", saved: true }
        : { ...(settings || {}), ...settingsFrom(form), note: result.note, saved: false };
      // A new pass mark changes what is suggested: read the school again.
      await load();
      if (state.step !== "review") state = { ...state, settings };
      draw();
      return;
    }

    if (form.confirm === undefined) {
      // Step one: read the form, write nothing.
      const plan = planFrom(form, review.classes);
      const waiting = undecidedIn(review.classes);
      if (!plan) {
        state = { ...review, note: "Choose where every class goes before you continue." };
      } else if (waiting) {
        review = { ...review, classes: withDestinations(review.classes, destinationsOf(form, review.classes)) };
        state = {
          ...review,
          note: `${waiting} ${waiting === 1 ? "child has" : "children have"} no decision from the principal yet. Nothing can be moved until every child has one.`,
        };
      } else {
        review = { ...review, classes: applyChoices(review.classes, plan), note: null };
        state = { step: "confirm", plan, note: null, ...summarise(plan, review.classes, review.targets) };
      }
      draw();
      return;
    }

    // Step two: the only write that moves anybody.
    const result = await confirmPlan(state.plan, { fetchImpl });
    if (result.ok) {
      state = { step: "done", outcome: result.body };
    } else if (result.refusal) {
      state = { step: result.refusal, ...result.body };
    } else {
      state = { ...state, note: result.note };
    }
    draw();
  });

  return state;
}

/** The choices just made, so "Go back" shows them rather than the defaults. */
function applyChoices(classes, plan) {
  const byId = new Map(plan.map((p) => [p.class_group_id, p]));
  return classes.map((row) => {
    const entry = byId.get(row.class_group_id);
    return {
      ...row,
      graduate: entry.graduate,
      destination_id: entry.destination_id,
      children: row.children.map((c) => ({ ...c, action: entry.children[String(c.membership_id)] })),
    };
  });
}

if (typeof document !== "undefined") {
  const root = document.getElementById("promotion");
  if (root) {
    // An enhancement: if it cannot load, each select opens the system menu.
    import("../web/picker.js").then((picker) => picker.enhanceSelects(root), () => {});
    mount(root);
  }
}
