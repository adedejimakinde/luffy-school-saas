/**
 * A test's sitting: its code, classes opened or closed by hand, extra time and retakes, the
 * log, and exam slips for staff who may print them. `/tests/sitting/#<test id>`, beside the
 * Tests page, which links here (an old `/tests/#sitting/<id>` link is sent on).
 *
 * Every write redraws from what the write answered. The slips are the routes the exam slips
 * page uses; the PDF goes to the browser and is dropped, and nothing here holds a PIN.
 */

import { saveFile } from "../exam-slips/print.js";
import * as api from "./api.js";
import * as states from "./states.js";

const { REFUSAL } = api;

export function htmlFor(state, { portal = "" } = {}) {
  switch (state.step) {
    case "sitting":
      return states.sittingView(state.log, state);
    case REFUSAL.NOT_YOURS:
      return states.notYours(state);
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

/** `#9` → `["9"]`. */
export function routeOf(hash) {
  return String(hash || "").replace(/^#\/?/, "").split("/").filter(Boolean);
}

const refusal = (answer) => ({ step: answer.refusal, ...answer.body });

/** The sitting of the test the hash names, read from the school. */
export async function load(route, { fetchImpl = fetch } = {}) {
  const answer = await api.fetchSitting({ testId: route[0] || "", fetchImpl });
  if (!answer.ok) return answer.rejected ? { step: REFUSAL.NOT_YOURS, detail: answer.detail } : refusal(answer);
  return { step: "sitting", log: answer.body };
}

export async function mount(root, { fetchImpl = fetch, location = window.location, save = saveFile } = {}) {
  const portal = root.dataset.portal || "";
  let state = await load(routeOf(location.hash), { fetchImpl });
  const draw = () => {
    root.innerHTML = htmlFor(state, { portal });
    // A confirmation that cancels something opens on Cancel.
    const safe = root.querySelector && root.querySelector("[data-default]");
    if (safe && safe.focus) safe.focus();
  };
  draw();
  const route = async () => {
    state = await load(routeOf(location.hash), { fetchImpl });
    draw();
    if (root.scrollIntoView) root.scrollIntoView({ block: "start" });
  };
  if (typeof window !== "undefined" && window.addEventListener) window.addEventListener("hashchange", route);

  /** A refusal for the page, or a sentence on this view. */
  const answered = (result, next) => {
    if (result.ok) return next(result.body);
    if (result.refusal) state = refusal(result);
    else state = { ...state, detail: result.detail, confirming: null };
    return draw();
  };

  root.addEventListener("click", async (event) => {
    const hit = event.target.closest("[data-action]");
    if (!hit || hit.tagName === "INPUT" || hit.tagName === "SELECT") return;
    const { action } = hit.dataset;
    if (action.startsWith("ask-")) {
      state = { ...state, confirming: action.slice(4), detail: "", done: "" };
      return draw();
    }
    if (action === "keep") {
      state = { ...state, confirming: null };
      return draw();
    }
    if (state.step !== "sitting") return null;
    if (action === "print-class" || action === "print-student") {
      const one = action === "print-student";
      const result = await api.printSlips({
        classGroupId: Number(hit.dataset.class),
        studentId: one ? Number(hit.dataset.student) : null,
        replace: !one,
        fetchImpl,
      });
      if (!result.ok) return answered(result, () => null);
      save(result.blob, result.filename);
      const again = await api.fetchSitting({ testId: state.log.test_id, fetchImpl });
      const said = one
        ? `Printed. Saved as ${result.filename}. Their earlier slip no longer works.`
        : `Printed. Saved as ${result.filename}. Hand the slips out; any earlier slips for these students no longer work.`;
      state = again.ok ? { step: "sitting", log: again.body, code: state.code, done: said } : { ...state, confirming: null, detail: "", done: said };
      return draw();
    }
    if (action === "set-code") {
      const result = await api.setCode({ testId: state.log.test_id, fetchImpl });
      return answered(result, (log) => {
        state = { step: "sitting", log, code: log.code, done: "" };
        draw();
      });
    }
    return null;
  });

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form || !form.dataset || state.step !== "sitting") return;
    if (event.preventDefault) event.preventDefault();
    const kind = form.dataset.form;
    const testId = state.log.test_id;
    let result;
    let said;
    if (kind === "control") {
      const opening = form.dataset.kind === "open";
      result = await api.controlSitting({
        testId, classId: form.dataset.class, kind: form.dataset.kind, reason: form.reason.value,
        endAttempts: Boolean(form.end_attempts && form.end_attempts.checked), fetchImpl,
      });
      said = opening ? "Opened. Its students can start now. This is logged." : "Closed. Nobody new can start. This is logged.";
    } else if (kind === "extra") {
      result = await api.giveExtraTime({ testId, studentId: form.dataset.student, minutes: Number(form.minutes.value || 0), reason: form.reason.value, fetchImpl });
      said = "Extra time given. Their timer grows when their computer next hears from the school.";
    } else if (kind === "retake") {
      result = await api.allowRetake({ testId, studentId: form.dataset.student, reason: form.reason.value, fetchImpl });
      said = "Retake allowed. They sign in again with the code and their slip.";
    } else return;
    answered(result, (log) => {
      state = { step: "sitting", log, done: said };
      draw();
    });
  });

  return { state: () => state, route };
}

if (typeof document !== "undefined") {
  const root = document.getElementById("test-sitting");
  if (root) mount(root);
}
