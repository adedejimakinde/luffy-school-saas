/**
 * The OGSERA filler: choose, map (the first time), check, download.
 *
 * The chosen file is held in memory and sent again with each step; nothing of
 * it is stored on the server. A heading with no mapping sends the office to
 * the mapping step first, because a check against a half-mapped file would
 * report a fill that leaves columns empty for no reason it can say.
 */

import { REFUSAL, checkFile, fetchDoor, fillFile, readHeadings, saveMapping } from "./api.js";
import * as states from "./states.js";

export function htmlFor(state, { portal = "" } = {}) {
  switch (state.step) {
    case "choose":
      return states.choose(state);
    case "mapping":
      return states.mapping(state);
    case "checked":
      return states.checked(state);
    case REFUSAL.NOT_THE_OFFICE:
      return states.notTheOffice(state);
    case REFUSAL.NOT_OGUN:
      return states.notOgun(state);
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

/** Nothing mapped yet, or no column holds the learner's ID: map first. */
export function needsMapping(headings) {
  return !headings.some((h) => h.field === "learner_id");
}

export async function mount(root, { fetchImpl = fetch, makeUrl = (blob) => URL.createObjectURL(blob) } = {}) {
  const portal = root.dataset.portal || "";
  let state = { step: "loading" };
  let door = {};
  let file = null;
  let picked = {};

  const draw = () => {
    root.innerHTML = htmlFor(state, { portal });
  };
  const refused = (answer) => ({ step: answer.refusal, ...answer.body });

  const start = (note = null) => {
    state = { step: "choose", ...door, picked, note };
    draw();
  };

  const runCheck = async (replace = false) => {
    const answer = await checkFile({ file, ...picked, replace, fetchImpl });
    if (answer.refusal) state = refused(answer);
    else if (!answer.ok) return start(answer.body.detail);
    else state = { step: "checked", check: answer.body, replace };
    draw();
  };

  const first = await fetchDoor({ fetchImpl });
  if (!first.ok) {
    state = refused(first);
    draw();
    return state;
  }
  door = first.body;
  start();

  root.addEventListener("click", async (event) => {
    const hit = event.target.closest("[data-action]");
    if (!hit) return;
    if (hit.dataset.action === "again") {
      file = null;
      start();
    }
    if (hit.dataset.action === "remap" && file) {
      const answer = await readHeadings({ file, fetchImpl });
      if (answer.refusal) state = refused(answer);
      else state = { step: "mapping", headings: answer.body.headings || [], fields: door.fields };
      draw();
    }
  });

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    const which = form && form.dataset ? form.dataset.form : undefined;
    if (!which) return;
    if (event.preventDefault) event.preventDefault();

    if (which === "choose") {
      file = form.file && form.file.files ? form.file.files[0] : null;
      if (!file) return;
      picked = { classGroupId: form.class_group_id.value, subjectId: form.subject_id.value };
      const answer = await readHeadings({ file, fetchImpl });
      if (answer.refusal) {
        state = refused(answer);
        draw();
        return;
      }
      if (!answer.ok) return start(answer.body.detail);
      const headings = answer.body.headings || [];
      if (needsMapping(headings)) {
        state = { step: "mapping", headings, fields: door.fields };
        draw();
        return;
      }
      await runCheck();
      return;
    }

    if (which === "mapping") {
      const columns = {};
      for (const [i, h] of (state.headings || []).entries()) {
        const box = form[`map_${i}`];
        columns[h.heading] = box ? box.value : "";
      }
      const answer = await saveMapping({ columns, fetchImpl });
      if (answer.refusal) {
        state = refused(answer);
        draw();
        return;
      }
      if (!answer.ok) {
        state = {
          ...state,
          headings: state.headings.map((h) => ({ ...h, field: columns[h.heading] })),
          note: answer.body.detail,
        };
        draw();
        return;
      }
      door = { ...door, ...answer.body };
      await runCheck();
      return;
    }

    if (which === "fill") {
      const replace = Boolean(form.replace && form.replace.checked);
      if (replace !== state.replace) {
        // What "replace" changes is what the check counts; say it before the file.
        await runCheck(replace);
      }
      const answer = await fillFile({ file, ...picked, replace, fetchImpl });
      if (answer.refusal) {
        state = refused(answer);
      } else if (!answer.ok) {
        state = { ...state, note: answer.body.detail };
      } else {
        const name = `${String(file.name || "ogsera").replace(/\.xlsx$/i, "")}-filled.xlsx`;
        state = { ...state, download: { url: makeUrl(answer.blob), name } };
      }
      draw();
    }
  });

  return state;
}

if (typeof document !== "undefined") {
  const root = document.getElementById("ogsera");
  if (root) mount(root);
}
