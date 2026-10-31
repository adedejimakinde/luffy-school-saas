/**
 * The website editor at `/website/`: pages, their sections, and publishing. `docs/school-sites.md` PR 4.
 *
 * Every write answers with the whole overview and the page redraws from it. Each form has its
 * own Save; switching a page on or off, moving and removing save at once. A refusal keeps the
 * form it came from open with the school's sentence under it; a 409 says somebody else changed
 * it since, with a Reload. **Nothing is kept in the browser**: leaving a form with edits not
 * saved asks first ("You have unsaved changes. Leave anyway?"), in the editor and on leaving
 * the page, and the edits are gone if you say yes. Removing asks twice; publishing and going
 * back to an earlier version each have their own confirm screen.
 */

import { esc } from "../web/html.js";
import * as api from "./api.js";
import { collect } from "./forms.js";
import * as states from "./states.js";

const { REFUSAL } = api;

/** The markup for one state. Pure, so every branch is testable. */
export function htmlFor(state, { portal = "" } = {}) {
  switch (state.step) {
    case "editor": {
      const body = state.body;
      if (state.confirming && state.confirming.what === "publish") return states.confirmPublish(body, state);
      if (state.confirming && state.confirming.what === "rollback") {
        return states.confirmRollback(body, state.confirming.number, state);
      }
      if (state.open && state.editing) {
        return states.section(body, state.open, { ...state.editing, notes: state.notes });
      }
      if (state.open && body.can_edit) return states.page(body, state.open, state);
      return states.site(body, state);
    }
    case REFUSAL.NOT_YOURS:
      return states.notYours();
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

/** The overview the school sent, with what this page had open kept. */
export function fromOverview(answer, kept = {}) {
  if (!answer.ok) return { step: answer.refusal || REFUSAL.BROKEN, body: answer.body || {} };
  return { open: null, editing: null, confirming: null, told: null, ...kept, body: answer.body, step: "editor", notes: {} };
}

/** A form's fields as name to value; a checkbox's value is whether it is ticked. */
export function valuesOf(form) {
  const values = {};
  for (const el of Array.from(form.elements || [])) {
    if (!el.name) continue;
    values[el.name] = el.type === "checkbox" ? Boolean(el.checked) : el.value;
  }
  return values;
}

const pageOf = (body, ref) => (body.pages || []).find((p) => p.ref === ref);

/** `items` with the one at `index` moved by `step`, or null if it would leave the list. */
export function moved(items, index, step) {
  const to = index + step;
  if (index < 0 || to < 0 || to >= items.length) return null;
  const out = items.slice();
  [out[index], out[to]] = [out[to], out[index]];
  return out;
}

/** The footer as the server checks it, from the footer form's values. */
export function footerFrom(values, networks) {
  return {
    address_line: String(values.address_line || ""),
    social: networks
      .map((network) => ({ network, url: String(values[`social_${network}`] || "").trim() }))
      .filter((s) => s.url),
  };
}

export async function mount(root, { fetchImpl = fetch, ask = (q) => window.confirm(q), win = null } = {}) {
  const portal = root.dataset.portal || "";
  let state = fromOverview(await api.fetchOverview({ fetchImpl }));
  let dirty = false;
  const draw = () => {
    root.innerHTML = htmlFor(state, { portal });
    dirty = false;
  };
  draw();

  /** Leaving where we are: fine unless a form holds edits not saved and the person says stay. */
  const mayLeave = () => !dirty || ask(states.UNSAVED);

  /** A write's answer: the new overview, or the sentence under the form `key`, or a refusal. */
  const after = (key, result, kept = {}) => {
    if (result.ok) {
      state = fromOverview(result, { open: state.open, ...kept });
    } else if (result.rejected) {
      state = { ...state, notes: { [key]: { detail: result.body.detail || "That was not saved.", stale: result.stale } } };
      // Keep the edits on screen: put the sentence under the form, and leave the form as typed.
      const form = root.querySelector ? root.querySelector(`[data-form="${key}"]`) : null;
      if (form) {
        const old = form.querySelector(".note");
        if (old) old.remove();
        form.insertAdjacentHTML("beforeend", noteHtml(state.notes[key]));
        return;
      }
    } else {
      state = fromOverview(result);
    }
    draw();
  };

  const noteHtml = (n) =>
    `<p class="note" role="alert">${esc(n.detail)}${n.stale ? ' <button type="button" class="again" data-action="reload">Reload</button>' : ""}</p>`;

  const go = (change) => {
    if (!mayLeave()) return;
    state = { ...state, notes: {}, told: null, ...change };
    draw();
    if (root.scrollIntoView) root.scrollIntoView({ block: "start" });
  };

  root.addEventListener("input", (event) => {
    if (event.target.closest && event.target.closest("[data-tracked]")) dirty = true;
  });

  root.addEventListener("change", async (event) => {
    const el = event.target;
    const body = state.body || {};
    if (el.dataset && el.dataset.action === "switch-page") {
      const p = pageOf(body, el.dataset.ref);
      after("top", await api.changePage({ ref: p.ref, version: p.version, change: { enabled: el.checked }, fetchImpl }));
    } else if (el.dataset && el.dataset.action === "delegation") {
      after("delegation", await api.changeDelegation({ on: el.checked, fetchImpl }));
    }
  });

  root.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    const values = valuesOf(form);
    const body = state.body || {};
    const which = form.dataset.form;
    const p = state.open ? pageOf(body, state.open) : null;
    if (which === "add-page") {
      after("add-page", await api.addPage({ version: body.version, title: values.title, slug: values.slug, fetchImpl }));
    } else if (which === "page") {
      const change = { title: values.title, description: values.description };
      if (values.slug !== undefined && values.slug !== p.slug) {
        after("page", await api.changePage({ ref: p.ref, version: p.version, change: { slug: values.slug, title: values.title }, fetchImpl }), {
          open: values.slug,
        });
        return;
      }
      after("page", await api.changePage({ ref: p.ref, version: p.version, change, fetchImpl }));
    } else if (which === "add-section") {
      if (!values.kind) return;
      go({ editing: { id: null, kind: values.kind } });
    } else if (which === "section") {
      const kind = form.dataset.kind;
      const id = state.editing && state.editing.id;
      const existing = id ? (p.sections || []).find((s) => s.id === id) : null;
      const data = collect(kind, values, existing ? existing.data : {});
      const result = existing
        ? await api.changeSection({ id, version: existing.version, data, fetchImpl })
        : await api.addSection({ ref: p.ref, version: p.version, kind, data, fetchImpl });
      after("section", result, result.ok ? { editing: null } : {});
    } else if (which === "footer") {
      after("footer", await api.changeFooter({ version: body.version, footer: footerFrom(values, body.networks || []), fetchImpl }));
    } else if (which === "colour") {
      after("colour", await api.changeColour({ version: body.version, colour: values.colour, fetchImpl }));
    } else if (which === "ready") {
      const result = await api.markReady({ note: values.note, fetchImpl });
      after("ready", result, result.ok ? { told: result.body.told } : {});
    } else if (which === "publish") {
      const result = await api.publish({ draftVersion: body.state.draft_version, note: values.note, fetchImpl });
      after("publish", result, result.ok ? { confirming: null, open: null } : {});
    } else if (which === "rollback") {
      const result = await api.rollback({ number: Number(form.dataset.number), note: values.note, fetchImpl });
      after("rollback", result, result.ok ? { confirming: null, open: null } : {});
    }
  });

  root.addEventListener("click", async (event) => {
    const button = event.target.closest && event.target.closest("[data-action]");
    if (!button || button.tagName === "INPUT") return;
    const body = state.body || {};
    const action = button.dataset.action;
    const p = state.open ? pageOf(body, state.open) : null;
    if (action === "reload") {
      if (!mayLeave()) return;
      state = fromOverview(await api.fetchOverview({ fetchImpl }), { open: state.open });
      draw();
    } else if (action === "open-page") {
      go({ open: button.dataset.ref, editing: null, confirming: null });
    } else if (action === "back") {
      go({ open: state.confirming ? state.open : null, editing: null, confirming: null });
    } else if (action === "cancel") {
      go({ editing: null });
    } else if (action === "edit-section") {
      go({ editing: { id: Number(button.dataset.id), kind: null } });
    } else if (action === "keep") {
      state = { ...state, confirming: null };
      draw();
    } else if (action === "publish") {
      go({ confirming: { what: "publish" } });
    } else if (action === "rollback") {
      go({ confirming: { what: "rollback", number: Number(button.dataset.number) } });
    } else if (action === "colour-reset") {
      after("colour", await api.changeColour({ version: body.version, colour: "", fetchImpl }));
    } else if (action === "page-up" || action === "page-down") {
      const order = (body.pages || []).map((x) => x.ref);
      const next = moved(order, order.indexOf(button.dataset.ref), action === "page-up" ? -1 : 1);
      if (next && next[0] === order[0]) after("top", await api.orderMenu({ version: body.version, order: next, fetchImpl }));
    } else if (action === "section-up" || action === "section-down") {
      const order = (p.sections || []).map((s) => s.id);
      const next = moved(order, order.indexOf(Number(button.dataset.id)), action === "section-up" ? -1 : 1);
      if (next) after("sections", await api.orderSections({ ref: p.ref, version: p.version, order: next, fetchImpl }));
    } else if (action === "remove-section") {
      const id = Number(button.dataset.id);
      if (!button.dataset.sure) {
        state = { ...state, confirming: { what: "remove-section", id } };
        draw();
        return;
      }
      const s = (p.sections || []).find((x) => x.id === id);
      after("sections", await api.removeSection({ id, version: s.version, fetchImpl }), { confirming: null });
    } else if (action === "remove-page") {
      if (!button.dataset.sure) {
        state = { ...state, confirming: { what: "remove-page" } };
        draw();
        return;
      }
      const result = await api.removePage({ ref: p.ref, version: p.version, fetchImpl });
      after("remove", result, result.ok ? { open: null, confirming: null } : {});
    }
  });

  const host = win || (typeof window !== "undefined" ? window : null);
  if (host && host.addEventListener) {
    host.addEventListener("beforeunload", (event) => {
      if (dirty) event.preventDefault();
    });
  }
  return { current: () => state, isDirty: () => dirty };
}

if (typeof document !== "undefined") {
  const root = document.getElementById("website-editor");
  if (root) mount(root);
}
