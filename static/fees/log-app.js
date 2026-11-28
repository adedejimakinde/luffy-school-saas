/** The fee log page: a term's entries, or its reversals, a page at a time (docs/module-notes.md) */

import { esc } from "../web/html.js";
import { REFUSAL, read } from "./api.js";
import * as states from "./states.js";

export function logUrl({ termId = null, reversalsOnly = false, page = 1 } = {}) {
  const parts = [];
  if (termId != null) parts.push(`term_id=${encodeURIComponent(termId)}`);
  if (reversalsOnly) parts.push("reversals_only=true");
  if (page > 1) parts.push(`page=${encodeURIComponent(page)}`);
  return `/api/fees/log/${parts.length ? `?${parts.join("&")}` : ""}`;
}

export function feeLog({ log: body = {} } = {}) {
  const {
    terms = [], term_id: termId, term = "", reversals_only: only = false, reversals = 0,
    page = 1, has_more: more = false, entries = [],
  } = body;
  const toggle = (value, label, on) =>
    `<button type="button" data-action="log-view" data-only="${value}" aria-pressed="${on}">${label}</button>`;
  const pager = (to, label) => `<button type="button" data-action="log-page" data-page="${esc(to)}">${label}</button>`;
  return [
    '<section class="state state-log" data-state="log">',
    '<p class="back"><a class="btn" href="/fees/">Balances</a></p>',
    `<h1>${only ? "Reversals" : "Fee log"}</h1>`,
    '<form class="chooser"><label for="log-term">Term</label>',
    `<select id="log-term" data-log-term>${states.termOptions(terms, termId)}</select></form>`,
    `<h2>${esc(term)}</h2>`,
    '<p class="quiet">Nothing here can be changed or deleted. A mistake is reversed, and both entries stay.</p>',
    `<p class="log-views" role="group" aria-label="Show">${toggle("no", "Everything", !only)} ` +
      `${toggle("yes", `Reversals (${esc(reversals)})`, only)}</p>`,
    entries.length
      ? states.entryTable(entries, {})
      : `<p class="blank">${only ? "Nothing has been reversed this term." : "Nothing has been recorded this term."}</p>`,
    page > 1 || more
      ? `<p class="more">${page > 1 ? pager(page - 1, "Newer") : ""} ${more ? pager(page + 1, "Older") : ""}</p>`
      : "",
    "</section>",
  ].join("");
}

export function htmlFor(state, { portal = "" } = {}) {
  if (state.step === "log") return feeLog(state);
  if (state.step === "no-terms") return states.noTerms();
  if (state.step === REFUSAL.NOT_YOURS) return states.notYours();
  if (state.step === REFUSAL.WRONG_HOST) return states.wrongHost();
  if (state.step === REFUSAL.EXPIRED) return states.signedOut({ portal, expired: true });
  if (state.step === REFUSAL.SIGNED_OUT) return states.signedOut({ portal });
  return states.broken();
}

export async function mount(root, { fetchImpl = fetch, search = "" } = {}) {
  const portal = root.dataset.portal || "";
  const params = new URLSearchParams(search);
  let state = { step: REFUSAL.WRONG_HOST };
  const draw = () => {
    root.innerHTML = htmlFor(state, { portal });
  };
  const show = async ({ termId = null, reversalsOnly = false, page = 1 }) => {
    const answer = await read(logUrl({ termId, reversalsOnly, page }), fetchImpl);
    if (!answer.ok) state = { step: answer.refusal };
    else state = answer.body.term_id === null ? { step: "no-terms" } : { step: "log", log: answer.body };
    draw();
  };
  if (root.dataset.onSchool !== "yes") {
    draw();
    return state;
  }
  const term = params.get("term_id");
  await show({ termId: term ? Number(term) : null, reversalsOnly: params.get("reversals") === "1" });

  const now = () => state.log || {};
  root.addEventListener("change", async (event) => {
    if (event.target && event.target.dataset && event.target.dataset.logTerm !== undefined) {
      await show({ termId: Number(event.target.value), reversalsOnly: Boolean(now().reversals_only) });
    }
  });
  root.addEventListener("click", async (event) => {
    const hit = event.target.closest("[data-action]");
    if (!hit || state.step !== "log") return;
    if (hit.dataset.action === "log-view") {
      await show({ termId: now().term_id, reversalsOnly: hit.dataset.only === "yes" });
    } else if (hit.dataset.action === "log-page") {
      await show({ termId: now().term_id, reversalsOnly: Boolean(now().reversals_only), page: Number(hit.dataset.page) });
    }
  });
  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("fees");
  if (root) {
    import("../web/picker.js").then((picker) => picker.enhanceSelects(root), () => {});
    mount(root, { search: window.location.search });
  }
}
