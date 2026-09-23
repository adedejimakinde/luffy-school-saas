/**
 * Broadsheets: the school's classes for a term, and one class's sheet.
 *
 * The overview is also the way in: pick a term, see every class's average,
 * open a class. `?class=` (and `?term=`) open a class directly, which is how
 * the results chain's "Broadsheet" link lands a principal on the sheet she is
 * about to release.
 */

import { failureNote, sessionEnded, signOut } from "../web/signout.js";
import { REFUSAL, fetchBroadsheet, fetchOverview, fetchTerms } from "./api.js";
import * as states from "./states.js";

export function htmlFor(state, { portal = "", signOutFailed = false } = {}) {
  const after = signOutFailed ? failureNote() : "";
  switch (state.step) {
    case "overview":
      return states.overview(state) + after;
    case "sheet":
      return states.sheet(state) + after;
    case "no-terms":
      return states.noTerms() + after;
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

/** The term to open: the one asked for, else the current one, else the newest. */
export function chosenTerm(terms, asked) {
  if (asked && terms.some((t) => String(t.term_id) === String(asked))) return Number(asked);
  const current = terms.find((t) => t.is_current);
  return (current || terms[0]).term_id;
}

export async function mount(root, { fetchImpl = fetch, search = "" } = {}) {
  const portal = root.dataset.portal || "";
  const params = new URLSearchParams(search);
  let state = { step: "loading" };
  let signOutFailed = false;
  const draw = () => {
    root.innerHTML = htmlFor(state, { portal, signOutFailed });
  };
  const refused = (answer) => {
    state = { step: answer.refusal };
    draw();
  };

  if (root.dataset.onSchool !== "yes") {
    state = { step: REFUSAL.WRONG_HOST };
    draw();
    return state;
  }

  const terms = await fetchTerms({ fetchImpl });
  if (!terms.ok) return (refused(terms), state);
  if (!terms.body.terms.length) {
    state = { step: "no-terms" };
    draw();
    return state;
  }

  const showOverview = async (termId) => {
    const answer = await fetchOverview({ termId, fetchImpl });
    if (!answer.ok) return refused(answer);
    state = { step: "overview", terms: terms.body.terms, overview: answer.body };
    draw();
  };
  const showSheet = async (classId, termId) => {
    const answer = await fetchBroadsheet({ classId, termId, fetchImpl });
    if (!answer.ok) return refused(answer);
    state = { step: "sheet", terms: terms.body.terms, termId, broadsheet: answer.body };
    draw();
  };

  const termId = chosenTerm(terms.body.terms, params.get("term"));
  if (params.get("class")) await showSheet(Number(params.get("class")), termId);
  else await showOverview(termId);

  root.addEventListener("change", async (event) => {
    const field = event.target;
    if (!field || !field.dataset || field.dataset.term === undefined) return;
    await showOverview(Number(field.value));
  });

  root.addEventListener("click", async (event) => {
    const hit = event.target.closest("[data-action]");
    if (!hit) return;
    const action = hit.dataset.action;
    if (action === "open-class" && state.step === "overview") {
      await showSheet(Number(hit.dataset.class), state.overview.term_id);
      return;
    }
    if (action === "back" && state.step === "sheet") {
      await showOverview(state.termId);
      return;
    }
    if (action !== "sign-out") return;
    const ended = sessionEnded(await signOut({ fetchImpl }));
    if (ended) {
      root.innerHTML = states.signedOut({ portal });
      return;
    }
    signOutFailed = true;
    draw();
  });

  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("broadsheet");
  if (root) mount(root, { search: window.location.search });
}
