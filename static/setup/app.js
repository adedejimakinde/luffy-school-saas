/**
 * School setup: the calendar, and the groups children sit in.
 *
 * The office's own screen. Two forms and one button, and everything it writes
 * is a thing every other tenant table hangs off — a placement, a register, a
 * result sheet, a card.
 *
 * **Every write reloads the shape rather than patching one row.** The other
 * screens redraw a row from the answer, and this one deliberately does not:
 * making a term current *changes another row* — the one that stops being
 * current — and a page that patched only the row it POSTed would show two
 * terms as current until somebody refreshed. Reloading is one extra request on
 * a screen used a handful of times a year.
 */

import {
  REFUSAL,
  SAVE,
  addTrait,
  changeTrait,
  createClass,
  createTerm,
  fetchSetup,
  makeCurrent,
  removeCrest,
  saveOrder,
  saveScaleLabel,
  saveSection,
  saveColour,
  saveContactEmail,
  saveDepartment,
  saveLga,
  saveShowMinistry,
  saveShowPosition,
  saveTemplate,
  savePublicPage,
  uploadCrest,
} from "./api.js";
import * as states from "./states.js";

/** The markup for one state. Pure, so every branch is testable. */
export function htmlFor(state, { portal = "" } = {}) {
  switch (state.step) {
    case "setup":
      return states.shape(state);
    case REFUSAL.NOT_THE_OFFICE:
      return states.notTheOffice(state);
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

export function fromSetup(answer) {
  if (!answer.ok) return { step: answer.refusal, ...answer.body };
  return { step: "setup", ...answer.body, notes: {} };
}

/**
 * What one write did to the screen.
 *
 * A rejection keeps the form open with the server's sentence under it — the
 * calendar disagreeing with itself is something the person retypes, and
 * clearing the form would make them type all of it again to fix one date.
 */
export function applyWrite(state, key, result) {
  const notes = { ...state.notes };
  if (result.ok) {
    delete notes[key];
    return { state: { ...state, notes }, reload: true };
  }
  if (result.refusal) return { state: { step: result.refusal, ...result.body }, reload: false };
  notes[key] = {
    kind: result.outcome === SAVE.REJECTED ? "rejected" : "not-allowed",
    detail: result.body.detail,
  };
  return { state: { ...state, notes }, reload: false };
}

/** The trait with this id, with the section it is in, from the last answer. */
function findTrait(state, traitId) {
  for (const section of (state.conduct && state.conduct.sections) || []) {
    const trait = section.traits.find((t) => t.trait_id === traitId);
    if (trait) return { ...trait, group: section.group };
  }
  return null;
}

/**
 * A section's trait ids with one moved a place, or `null` at the end of the list.
 * The whole list is sent, hidden traits included: the server renumbers the
 * group, and a list that left some out would put them after the others.
 */
export function movedOrder(state, group, traitId, by) {
  const section = ((state.conduct && state.conduct.sections) || []).find((s) => s.group === group);
  if (!section) return null;
  const ids = section.traits.map((t) => t.trait_id);
  const at = ids.indexOf(traitId);
  const to = at + by;
  if (at < 0 || to < 0 || to >= ids.length) return null;
  [ids[at], ids[to]] = [ids[to], ids[at]];
  return ids;
}

const POLLS = 30;
const POLL_MS = 2000;

/** Is a crest uploaded a moment ago still with the media worker? */
export function stillPreparing(state) {
  return Boolean(state && state.card && state.card.crest_processing);
}

export async function mount(root, { fetchImpl = fetch } = {}) {
  const portal = root.dataset.portal || "";
  let state = { step: "loading" };

  const draw = () => {
    root.innerHTML = htmlFor(state, { portal });
  };
  // A new crest is drawn by the media worker after the upload answers, so
  // while the look says it is still being prepared, ask again every couple of
  // seconds, for at most a minute (`files.service`).
  let polls = 0;
  const load = async (notes = {}) => {
    state = fromSetup(await fetchSetup({ fetchImpl }));
    if (state.step === "setup") state = { ...state, notes };
    draw();
    if (state.step === "setup" && stillPreparing(state) && polls < POLLS && typeof setTimeout === "function") {
      polls += 1;
      setTimeout(() => load(state.notes), POLL_MS);
    } else if (!stillPreparing(state)) {
      polls = 0;
    }
  };

  await load();

  const after = async (key, result) => {
    const applied = applyWrite(state, key, result);
    state = applied.state;
    if (applied.reload) await load(state.notes);
    else draw();
  };

  root.addEventListener("click", async (event) => {
    const hit = event.target.closest("[data-action]");
    if (!hit) return;
    if (hit.dataset.action === "remove-crest") {
      await after("crest", await removeCrest({ fetchImpl }));
      return;
    }
    if (hit.dataset.action === "hide-trait" || hit.dataset.action === "show-trait") {
      const trait = findTrait(state, Number(hit.dataset.trait));
      await after(
        trait ? `conduct_${trait.group}` : "conduct_scale",
        await changeTrait({ traitId: Number(hit.dataset.trait), hidden: hit.dataset.action === "hide-trait", fetchImpl }),
      );
      return;
    }
    if (hit.dataset.action === "move-up" || hit.dataset.action === "move-down") {
      const group = hit.dataset.group;
      const ids = movedOrder(state, group, Number(hit.dataset.trait), hit.dataset.action === "move-up" ? -1 : 1);
      if (ids) await after(`conduct_${group}`, await saveOrder({ group, traitIds: ids, fetchImpl }));
      return;
    }
    if (hit.dataset.action === "make-current") {
      await after(
        "term",
        await makeCurrent({ termId: Number(hit.dataset.term), fetchImpl }),
      );
    }
  });

  // A department is saved as it is chosen: one select per subject, no button.
  root.addEventListener("change", async (event) => {
    const field = event.target;
    if (field && field.dataset && field.dataset.switch !== undefined) {
      const group = field.dataset.switch;
      await after(`conduct_${group}`, await saveSection({ group, enabled: Boolean(field.checked), fetchImpl }));
      return;
    }
    if (field && field.dataset && field.dataset.traitName !== undefined) {
      const trait = findTrait(state, Number(field.dataset.traitName));
      const name = String(field.value || "").trim();
      if (trait && name === trait.name) return;
      await after(
        trait ? `conduct_${trait.group}` : "conduct_scale",
        await changeTrait({ traitId: Number(field.dataset.traitName), name: field.value, fetchImpl }),
      );
      return;
    }
    if (field && field.dataset && field.dataset.scale !== undefined) {
      await after("conduct_scale", await saveScaleLabel({ value: Number(field.dataset.scale), label: field.value, fetchImpl }));
      return;
    }
    if (!field || !field.dataset || field.dataset.subject === undefined) return;
    await after(
      "department",
      await saveDepartment({ subjectId: Number(field.dataset.subject), department: field.value, fetchImpl }),
    );
  });

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (!form) return;
    if (event.preventDefault) event.preventDefault();

    const which = form.dataset ? form.dataset.form : undefined;
    if (which === "add-trait") {
      const group = form.dataset.group;
      await after(`conduct_${group}`, await addTrait({ group, name: form.name.value, fetchImpl }));
      return;
    }
    if (which === "ministry") {
      const box = form.show_ministry;
      await after("ministry", await saveShowMinistry({ show_ministry: Boolean(box && box.checked), fetchImpl }));
      return;
    }
    if (which === "position") {
      const box = form.show_position;
      await after("position", await saveShowPosition({ show_position: Boolean(box && box.checked), fetchImpl }));
      return;
    }
    if (which === "template") {
      const result = await saveTemplate({ template: form.template.value, fetchImpl });
      if (result.ok) {
        // Kept across the reload: what choosing Ogun set up is said once,
        // under the choice, until the page is next opened.
        await load({ template: { kind: "applied", applied: result.row.applied || null } });
        return;
      }
      await after("template", result);
      return;
    }
    if (which === "colour") {
      await after("colour", await saveColour({ colour: form.colour.value, fetchImpl }));
      return;
    }
    if (which === "crest") {
      const file = form.crest && form.crest.files ? form.crest.files[0] : null;
      if (!file) return;
      await after("crest", await uploadCrest({ file, fetchImpl }));
      return;
    }
    if (which === "public-page") {
      await after(
        "public_page",
        await savePublicPage({
          about: form.about.value,
          address: form.address.value,
          phone: form.phone.value,
          fetchImpl,
        }),
      );
      return;
    }
    if (which === "lga") {
      await after(
        "lga",
        await saveLga({ lga: form.lga.value, school_code: form.school_code ? form.school_code.value : "", fetchImpl }),
      );
      return;
    }
    if (which === "contact-email") {
      await after(
        "contact_email",
        await saveContactEmail({ contact_email: form.contact_email.value, fetchImpl }),
      );
      return;
    }
    if (form.session) {
      // Sent as typed. The server's `full_clean()` is what turns the model's
      // constraints into sentences, and a page that validated dates first
      // would be a second rule to keep in step with them.
      await after("term", await createTerm({
        term: {
          session: form.session.value,
          name: form.name.value,
          starts_on: form.starts_on.value,
          ends_on: form.ends_on.value,
        },
        fetchImpl,
      }));
      return;
    }
    if (form.name) {
      await after("class", await createClass({
        group: { name: form.name.value, level: Number(form.level.value || 0) },
        fetchImpl,
      }));
    }
  });

  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("setup");
  if (root) {
    // An enhancement: if it cannot load, each select opens the system menu.
    import("../web/picker.js").then((picker) => picker.enhanceSelects(root), () => {});
    mount(root);
  }
}
