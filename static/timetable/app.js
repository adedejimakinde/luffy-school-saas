/**
 * The timetable: one class's week, for one term.
 *
 * `?term=` and `?class=` open a week directly; otherwise the server picks the
 * current term and the page the first class. A teacher reads. An administrator
 * or the vice principal (academic) also sets lessons, clears them, copies last
 * term's timetable into an empty term, and adds or removes the day's periods.
 *
 * **After every write the week is fetched again**, rather than patched in
 * place: what the grid shows is then always what the database holds, which
 * matters most exactly when a write was refused.
 */

import { failureNote, sessionEnded, signOut } from "../web/signout.js";
import {
  REFUSAL,
  addPeriod,
  clearLesson,
  copyLastTerm,
  fetchIndex,
  fetchWeek,
  putLesson,
  removePeriod,
} from "./api.js";
import * as states from "./states.js";

export function htmlFor(state, { portal = "", signOutFailed = false } = {}) {
  const after = signOutFailed ? failureNote() : "";
  switch (state.step) {
    case "week":
      return states.week(state) + after;
    case "no-term":
      return states.noTerm(state) + after;
    case REFUSAL.NOT_YOURS:
      return states.notYours() + after;
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

export async function mount(root, { fetchImpl = fetch, search = "" } = {}) {
  const portal = root.dataset.portal || "";
  const params = new URLSearchParams(search);
  let state = { step: "loading" };
  let signOutFailed = false;
  const draw = () => {
    root.innerHTML = htmlFor(state, { portal, signOutFailed });
  };

  if (root.dataset.onSchool !== "yes") {
    state = { step: REFUSAL.WRONG_HOST };
    draw();
    return state;
  }

  /** Load the index for a term, then the chosen class's week in it. */
  const show = async ({ termId = null, classId = null, note = "" } = {}) => {
    const index = await fetchIndex({ termId, fetchImpl });
    if (!index.ok) {
      state = { step: index.refusal };
      draw();
      return;
    }
    if (index.body.term_id === null) {
      state = { step: "no-term", index: index.body };
      draw();
      return;
    }
    const classes = index.body.classes;
    const chosen =
      classes.find((c) => String(c.class_group_id) === String(classId)) || classes[0] || null;
    let week = null;
    if (chosen && index.body.periods.length) {
      const answer = await fetchWeek({
        classId: chosen.class_group_id,
        termId: index.body.term_id,
        fetchImpl,
      });
      if (!answer.ok) {
        state = { step: answer.refusal };
        draw();
        return;
      }
      week = answer.body;
    }
    state = {
      step: "week",
      index: index.body,
      week,
      classId: chosen ? chosen.class_group_id : null,
      note,
    };
    draw();
  };

  /** Redraw what is on screen, from the server, with a sentence on top. */
  const again = (note = "") =>
    show({ termId: state.index.term_id, classId: state.classId, note });

  /** A write's answer: a redraw, a sentence, or a state. */
  const after = async (answer, said) => {
    if (answer.ok) {
      await again(typeof said === "function" ? said(answer.body) : said);
      return;
    }
    if (answer.refusal) {
      state = { step: answer.refusal };
      draw();
      return;
    }
    state = { ...state, note: answer.body.detail };
    draw();
  };

  await show({
    termId: params.get("term") ? Number(params.get("term")) : null,
    classId: params.get("class"),
  });

  root.addEventListener("change", async (event) => {
    const field = event.target;
    if (!field || !field.dataset) return;
    if (field.dataset.term !== undefined) {
      await show({ termId: Number(field.value), classId: state.classId });
    } else if (field.dataset.class !== undefined && state.step === "week") {
      await show({ termId: state.index.term_id, classId: field.value });
    }
  });

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form) return;
    if (form.subject_id && state.step === "week") {
      if (event.preventDefault) event.preventDefault();
      const answer = await putLesson({
        classId: state.classId,
        lesson: {
          term_id: state.index.term_id,
          weekday: Number(form.weekday.value),
          period_id: Number(form.period_id.value),
          subject_id: Number(form.subject_id.value),
          teacher_membership_id: Number(form.teacher_membership_id.value),
        },
        fetchImpl,
      });
      await after(answer, "Saved.");
    } else if (form.starts_at && state.step === "week") {
      if (event.preventDefault) event.preventDefault();
      const answer = await addPeriod({
        startsAt: form.starts_at.value,
        endsAt: form.ends_at.value,
        label: form.label ? form.label.value : "",
        fetchImpl,
      });
      await after(answer, "Period added.");
    }
  });

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
    if (state.step !== "week") return;
    if (action === "clear") {
      const answer = await clearLesson({
        classId: state.classId,
        termId: state.index.term_id,
        weekday: Number(hit.dataset.weekday),
        periodId: Number(hit.dataset.period),
        fetchImpl,
      });
      await after(answer, "That period is free now.");
    } else if (action === "copy") {
      const answer = await copyLastTerm({ termId: state.index.term_id, fetchImpl });
      await after(answer, states.copiedSentence);
    } else if (action === "remove-period") {
      const answer = await removePeriod({ periodId: Number(hit.dataset.period), fetchImpl });
      await after(answer, "Period removed.");
    }
  });

  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("timetable");
  if (root) mount(root, { search: window.location.search });
}
