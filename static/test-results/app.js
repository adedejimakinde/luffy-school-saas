/**
 * A test's results: screen 7 and its item analysis, release and restore, key corrections,
 * closing the test, and Send to CA (screens 8a, 8b). `/tests/results/`, beside the Tests
 * page, which links here.
 *
 * Routed by its hash: `#<test id>` the results, `#ca/<test id>` Send to CA. Each view asks
 * the school afresh, and every write redraws from what the write answered.
 */

import * as api from "./api.js";
import * as states from "./states.js";

const { REFUSAL } = api;

export function htmlFor(state, { portal = "" } = {}) {
  switch (state.step) {
    case "results":
      return states.resultsView(state.results, state);
    case "ca":
      return states.caView(state.preview, state);
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

/** `#ca/9` → `["ca", "9"]`; `#9` → `["results", "9"]`. */
export function routeOf(hash) {
  const parts = String(hash || "").replace(/^#\/?/, "").split("/").filter(Boolean);
  if (parts[0] === "ca") return ["ca", parts[1] || ""];
  return ["results", parts[0] || ""];
}

const refusal = (answer) => ({ step: answer.refusal, ...answer.body });

export async function load(route, { fetchImpl = fetch } = {}) {
  const [view, testId] = route;
  if (!/^\d+$/.test(testId)) return { step: REFUSAL.WRONG_HOST };
  if (view === "ca") {
    const answer = await api.previewCa({ testId, fetchImpl });
    if (!answer.ok) return answer.rejected ? { step: REFUSAL.NOT_YOURS, detail: answer.detail } : refusal(answer);
    const results = await api.fetchResults({ testId, fetchImpl });
    return { step: "ca", preview: { ...answer.body, title: results.ok ? results.body.title : "" } };
  }
  const answer = await api.fetchResults({ testId, fetchImpl });
  if (!answer.ok) return answer.rejected ? { step: REFUSAL.NOT_YOURS, detail: answer.detail } : refusal(answer);
  return { step: "results", results: answer.body };
}

/** The chosen radio's value, or null. A form without `querySelectorAll` (a test's) gives `.value`. */
function radio(form, name) {
  if (!form.querySelectorAll) return form[name] ? form[name].value : null;
  const hit = Array.from(form.querySelectorAll(`input[name="${name}"]`)).find((i) => i.checked);
  return hit ? hit.value : null;
}

export async function mount(root, { fetchImpl = fetch, location = window.location } = {}) {
  const portal = root.dataset.portal || "";
  let state = await load(routeOf(location.hash), { fetchImpl });
  const draw = () => {
    root.innerHTML = htmlFor(state, { portal });
  };
  draw();
  const route = async () => {
    state = await load(routeOf(location.hash), { fetchImpl });
    draw();
    if (root.scrollIntoView) root.scrollIntoView({ block: "start" });
  };
  if (typeof window !== "undefined" && window.addEventListener) window.addEventListener("hashchange", route);

  const answered = (result, next) => {
    if (result.ok) return next(result.body);
    if (result.refusal) state = refusal(result);
    else state = { ...state, detail: result.detail, confirming: null };
    draw();
    return null;
  };
  const results = (said, extra = {}) => (body) => {
    state = { step: "results", results: body, done: said, ...extra };
    draw();
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
    if (state.step !== "results") return null;
    const testId = state.results.test_id;
    if (action === "close-test") {
      return answered(await api.closeTest({ testId, fetchImpl }), results("Closed. Nobody can start it again; its scores and answers are kept."));
    }
    if (action === "release") {
      return answered(
        await api.releaseClass({ testId, classId: hit.dataset.class, fetchImpl }),
        results("Released. Each student sees their own score, and each parent their own child's."),
      );
    }
    return null;
  });

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form || !form.dataset) return;
    if (event.preventDefault) event.preventDefault();
    const kind = form.dataset.form;
    if (state.step === "results" && kind === "key") {
      const result = await api.correctKey({
        testId: state.results.test_id, itemId: form.dataset.item, newIndex: Number(radio(form, "new_index")), reason: form.reason.value, fetchImpl,
      });
      answered(result, (body) => {
        const moved = body.corrected.changes.length;
        results(`Key corrected and every attempt marked again. ${moved === 1 ? "1 score changed" : `${moved} scores changed`}; they are listed under Keys corrected.`, { corrected: body.corrected })(body);
      });
    } else if (state.step === "results" && kind === "restore") {
      const result = await api.restoreRelease({ releaseId: form.dataset.release, reason: form.reason.value, fetchImpl });
      answered(result, results("Restored. Students and parents no longer see these scores. The release and your reason are kept."));
    } else if (state.step === "ca" && kind === "ca-preview") {
      const existing = radio(form, "existing") || "keep";
      const result = await api.previewCa({ testId: state.preview.test_id, assessment: form.assessment.value, existing, fetchImpl });
      answered(result, (preview) => {
        state = { step: "ca", preview: { ...preview, title: state.preview.title } };
        draw();
      });
    } else if (state.step === "ca" && kind === "ca-send") {
      const p = state.preview;
      const result = await api.sendCa({
        testId: p.test_id, assessmentId: p.assessment.id, existing: p.existing, shown: api.shownOf(p),
        confirmReplace: Boolean(form.confirm_replace && form.confirm_replace.checked), fetchImpl,
      });
      answered(result, (sent) => {
        state = { step: "ca", preview: p, sent };
        draw();
      });
    }
  });

  return { state: () => state, route };
}

if (typeof document !== "undefined") {
  const root = document.getElementById("test-results");
  if (root) {
    import("../web/picker.js").then((picker) => picker.enhanceSelects(root), () => {});
    mount(root);
  }
}
