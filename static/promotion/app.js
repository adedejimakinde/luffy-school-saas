/**
 * End-of-session promotion: review every class, then confirm once.
 *
 * **Nothing is written until the second button.** The first submit only reads
 * the form into a plan and shows what it would do; the confirm posts that plan
 * and the server moves every child or none. A refusal (the school changed since
 * the page was drawn, a child already placed) keeps the summary up with the
 * server's sentence, and nothing has moved.
 */

import { REFUSAL, confirmPlan, fetchReview } from "./api.js";
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
      children: Object.fromEntries(
        row.children.map((c) => {
          const field = form[`child_${c.membership_id}`];
          return [String(c.membership_id), field && field.value === "repeat" ? "repeat" : "promote"];
        }),
      ),
    });
  }
  return plan;
}

/** The words for a plan: where each class goes and how many stay behind. */
export function summarise(plan, classes, targets) {
  const named = new Map(targets.map((t) => [t.class_group_id, t.name]));
  const byId = new Map(classes.map((c) => [c.class_group_id, c]));
  const totals = { promoted: 0, repeated: 0, graduated: 0 };
  const summary = plan.map((entry) => {
    const repeating = Object.values(entry.children).filter((v) => v === "repeat").length;
    const total = Object.keys(entry.children).length;
    totals.repeated += repeating;
    totals[entry.graduate ? "graduated" : "promoted"] += total - repeating;
    return {
      name: byId.get(entry.class_group_id).name,
      to: entry.graduate ? "Graduated" : named.get(entry.destination_id) || "?",
      repeating,
    };
  });
  return { summary, totals };
}

export async function mount(root, { fetchImpl = fetch } = {}) {
  const portal = root.dataset.portal || "";
  const onSchool = root.dataset.onSchool === "yes";
  let state = { step: "loading" };
  let review = null;

  const draw = () => {
    root.innerHTML = htmlFor(state, { portal });
  };

  state = onSchool ? fromReview(await fetchReview({ fetchImpl })) : { step: REFUSAL.WRONG_HOST };
  if (state.step === "review") review = state;
  draw();

  root.addEventListener("click", (event) => {
    if (!event.target.closest || !event.target.closest('[data-action="back"]')) return;
    if (review) state = { ...review, note: null };
    draw();
  });

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form) return;
    if (event.preventDefault) event.preventDefault();

    if (form.confirm === undefined) {
      // Step one: read the form, write nothing.
      const plan = planFrom(form, review.classes);
      if (!plan) {
        state = { ...review, note: "Choose where every class goes before you continue." };
      } else {
        review = { ...review, classes: applyChoices(review.classes, plan), note: null };
        state = { step: "confirm", plan, note: null, ...summarise(plan, review.classes, review.targets) };
      }
      draw();
      return;
    }

    // Step two: the only write.
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
  if (root) mount(root);
}
