/**
 * Photos and albums at `/website/photos/`: the website editor's pictures (`docs/school-sites.md` PR 5).
 *
 * A frame of its own beside the editor at `/website/`, so each stays within the 150 KB a page may
 * cost before it draws (`tests/test_budget.py`). The editor's section forms choose a picture or an
 * album; this is where they are uploaded, described, cropped, arranged, published and taken down.
 *
 * Every write answers with the school's overview (and the album, where one is open) and the page
 * redraws from it, as the editor does: each form has its own Save, a refusal keeps the form as typed
 * with the school's sentence under it, removing asks twice, and publishing an album and taking a
 * picture down each have their own confirm screen. While a picture is "Processing…" the page asks
 * again every few seconds, and redraws only when no form holds unsaved edits. A link can open a
 * screen directly: `#album-4`, `#picture-12`, `#upload-hero`, `#upload-hero-video`, `#upload-portrait`.
 */

import { esc } from "../web/html.js";
import { REFUSAL } from "./api.js";
import * as api from "./photos-api.js";
import * as pics from "./pictures.js";

const UNSAVED = "You have unsaved changes. Leave anyway?";

/** A picture on the screen now, from the school's pictures or the open album's photos. */
export function findPicture(state, id) {
  return pics.visiblePictures(state).find((p) => p.id === Number(id)) || null;
}

/** Where a focal point is, from a tap on the picture: 0 to 1 across and down, to three places. */
export function focalFrom(event, rect) {
  const clamp = (v) => Math.min(1, Math.max(0, Math.round(v * 1000) / 1000));
  return { x: clamp((event.clientX - rect.left) / rect.width), y: clamp((event.clientY - rect.top) / rect.height) };
}

/** What a link's `#…` opens: an album, a picture, or an upload. */
export function fromHash(hash = "") {
  const album = /^#album-(\d+)$/.exec(hash);
  if (album) return { albumId: Number(album[1]) };
  const picture = /^#picture-(\d+)$/.exec(hash);
  if (picture) return { picture: Number(picture[1]) };
  const upload = /^#upload-(hero|portrait)(-video)?$/.exec(hash);
  if (upload) return { uploading: { use: upload[1], album: null, video: Boolean(upload[2]) && upload[1] === "hero" } };
  return {};
}

/** The overview the school sent, with what this page had open kept. */
export function fromOverview(answer, kept = {}) {
  if (!answer.ok) return { step: answer.refusal || REFUSAL.BROKEN, body: answer.body || {} };
  const fresh = { confirming: null, picture: null, albumId: null, album: null, uploading: null, done: null, ...kept,
    body: answer.body, step: "photos", notes: {} };
  // An answer about an album carries it: the album screen redraws from it, or closes if it has gone.
  if (answer.body && answer.body.album !== undefined) {
    fresh.album = answer.body.album;
    if (answer.body.album === null) fresh.albumId = null;
  }
  return fresh;
}

function home(body, state) {
  const back = '<p><a class="btn" href="/website/">Back to the website editor</a></p>';
  if (!body.can_edit) {
    return `<section class="state" data-state="photos"><h1>Photos and albums</h1>${back}<p class="hint">The principal has not let you edit the website.</p></section>`;
  }
  return [
    '<section class="state state-photos" data-state="photos">',
    "<h1>Photos and albums</h1>",
    back,
    '<div class="site-actions">',
    '<button type="button" data-action="new-picture" data-use="hero">Upload a hero photo</button>',
    '<button type="button" data-action="new-picture" data-use="hero" data-video="1">Upload a hero video</button>',
    '<button type="button" data-action="new-picture" data-use="portrait">Upload a portrait</button>',
    "</div>",
    pics.picturesBlock(body, state),
    "</section>",
  ].join("");
}

/** The markup for one state. Pure, so every branch is testable. */
export function htmlFor(state) {
  if (state.step !== "photos") {
    const words = {
      [REFUSAL.NOT_YOURS]: "The school&#39;s website is looked after by its principal, and by the administrator when the principal allows it.",
      [REFUSAL.WRONG_HOST]: "Open the website editor on your school&#39;s own address.",
      [REFUSAL.SIGNED_OUT]: 'Please <a href="/staff-sign-in/?next=/website/photos/">sign in</a> to edit the school&#39;s website.',
      [REFUSAL.EXPIRED]: 'You were signed out after a while away. <a href="/staff-sign-in/?next=/website/photos/">Sign in</a>.',
    }[state.step] || 'Something went wrong loading the photos. <button type="button" data-action="reload">Try again</button>';
    return `<section class="state state-refused" data-state="${esc(state.step)}"><h1>Photos and albums</h1><p>${words}</p></section>`;
  }
  const body = state.body;
  const confirming = state.confirming || {};
  if (state.uploading) return pics.uploadScreen(body, state.uploading, state);
  if (confirming.what === "take-down") return pics.confirmTakeDown(body, findPicture(state, confirming.id), state);
  if (confirming.what === "publish-album" || confirming.what === "unpublish-album") {
    return pics.confirmAlbum(body, state.album || {}, confirming.what, state);
  }
  if (state.picture) {
    const done = state.done ? `<p class="done" role="status">${esc(state.done)} <a href="/website/">Back to the website editor</a></p>` : "";
    return done + pics.pictureScreen(body, findPicture(state, state.picture), { ...state, back: state.albumId ? "Back to the album" : "All photos" });
  }
  if (state.albumId) return pics.albumScreen(body, state.album, state);
  return home(body, state);
}

/** A form's fields as name to value; a checkbox's value is whether it is ticked. */
export function valuesOf(form) {
  const values = {};
  const els = form.elements
    ? Array.from(form.elements)
    : Object.entries(form).filter(([name]) => name !== "dataset").map(([name, field]) => ({ name, ...field }));
  for (const el of els) {
    if (!el.name) continue;
    values[el.name] = el.type === "checkbox" ? Boolean(el.checked) : el.value;
  }
  return values;
}

function moved(items, index, step) {
  const to = index + step;
  if (index < 0 || to < 0 || to >= items.length) return null;
  const out = items.slice();
  [out[index], out[to]] = [out[to], out[index]];
  return out;
}

export async function mount(
  root,
  { fetchImpl = fetch, ask = (q) => window.confirm(q), win = null, pollMs = 3000, timers = globalThis, hash = "" } = {},
) {
  let state = fromOverview(await api.fetchOverview({ fetchImpl }));
  let dirty = false;
  let timer = null;
  let polls = 0;

  const draw = () => {
    root.innerHTML = htmlFor(state);
    dirty = false;
    schedule();
  };

  /** While a picture on screen is processing, ask again in a moment; give up after a while. */
  function schedule() {
    if (timer || !pollMs || polls > 200 || state.step !== "photos" || !pics.processing(state)) return;
    timer = timers.setTimeout(poll, pollMs);
  }
  async function poll() {
    timer = null;
    polls += 1;
    if (dirty || state.uploading) return schedule();
    const answer = await api.fetchOverview({ fetchImpl });
    let album = state.album;
    if (answer.ok && state.albumId) {
      const fetched = await api.fetchAlbum({ id: state.albumId, fetchImpl });
      if (fetched.ok) album = fetched.body.album;
    }
    if (!answer.ok || dirty) return schedule();
    const { confirming, picture, albumId, done } = state;
    state = { ...fromOverview(answer, { confirming, picture, albumId, done }), album };
    draw();
  }

  const openAlbum = async (id) => {
    const result = await api.fetchAlbum({ id, fetchImpl });
    state = result.ok
      ? { ...state, notes: {}, confirming: null, picture: null, albumId: result.body.album.id, album: result.body.album }
      : { ...state, notes: { top: { detail: "That album is not on this site." } }, albumId: null, album: null };
  };

  if (state.step === "photos") {
    const asked = fromHash(hash || (typeof location !== "undefined" ? location.hash : ""));
    if (asked.albumId) await openAlbum(asked.albumId);
    else state = { ...state, ...asked };
  }
  draw();

  const mayLeave = () => !dirty || ask(UNSAVED);

  const noteHtml = (n) =>
    `<p class="note" role="alert">${esc(n.detail)}${n.stale ? ' <button type="button" class="again" data-action="reload">Reload</button>' : ""}</p>`;

  /** A write's answer: the new overview, or the sentence under the form `key`, or a refusal. */
  const after = (key, result, kept = {}) => {
    if (result.ok) {
      state = fromOverview(result, { picture: state.picture, albumId: state.albumId, album: state.album, ...kept });
    } else if (result.rejected) {
      state = { ...state, notes: { [key]: { detail: result.body.detail || "That was not saved.", stale: result.stale } } };
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

  const go = (change) => {
    if (!mayLeave()) return;
    state = { ...state, notes: {}, done: null, ...change };
    draw();
    if (root.scrollIntoView) root.scrollIntoView({ block: "start" });
  };

  root.addEventListener("input", (event) => {
    if (event.target.closest && event.target.closest("[data-tracked]")) dirty = true;
  });

  root.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    const values = valuesOf(form);
    const which = form.dataset.form;
    if (which === "add-album") {
      const result = await api.addAlbum({ title: values.title, fetchImpl });
      after("add-album", result, result.ok && result.body.album ? { albumId: result.body.album.id } : {});
    } else if (which === "album") {
      const change = { title: values.title, description: values.description };
      if (values.slug !== undefined && values.slug !== state.album.slug) change.slug = values.slug;
      after("album-form", await api.changeAlbum({ id: state.albumId, version: state.album.version, change, fetchImpl }));
    } else if (which === "photo" || which === "picture") {
      const p = findPicture(state, form.dataset.id);
      if (!p) return;
      const change = { alt: values.alt };
      if (values.caption !== undefined) change.caption = values.caption;
      after(which, await api.changePicture({ id: p.id, version: p.version, change, fetchImpl }));
    } else if (which === "upload") {
      const input = form.querySelector ? form.querySelector('input[type="file"]') : form.photo;
      const chosen = input && input.files ? Array.from(input.files) : [];
      const up = state.uploading;
      const fields = { use: up.use, alt: values.alt || "", consent: values.consent ? "1" : "", album: up.album || "", video: up.video ? "1" : "" };
      // The button says it is working, without redrawing the form and losing the files chosen.
      const submit = form.querySelector ? form.querySelector('button[type="submit"]') : null;
      if (submit) {
        submit.disabled = true;
        submit.textContent = "Uploading…";
      }
      const result = await api.uploadPictures({ fields, files: chosen, fetchImpl });
      if (submit) {
        submit.disabled = false;
        submit.textContent = "Upload";
      }
      if (!result.ok) return after("upload", result);
      const made = (result.body.made || [])[0];
      if (up.use === "gallery" || !made) {
        after("upload", result, { uploading: null });
      } else {
        after("upload", result, { uploading: null, picture: made, done: "Uploaded. Choose it in its section in the editor, then Save." });
      }
    } else if (which === "take-down") {
      const result = await api.takeDown({ id: Number(form.dataset.id), reason: values.reason, fetchImpl });
      after("take-down", result, result.ok ? { confirming: null, picture: null } : {});
    } else if (which === "publish-album" || which === "unpublish-album") {
      const call = which === "publish-album" ? api.publishAlbum : api.unpublishAlbum;
      const result = await call({ id: state.albumId, version: state.album.version, note: values.note, fetchImpl });
      after(which, result, result.ok ? { confirming: null } : {});
    }
  });

  root.addEventListener("click", async (event) => {
    const button = event.target.closest && event.target.closest("[data-action]");
    if (!button || button.tagName === "INPUT") return;
    const action = button.dataset.action;
    const ask2 = (what, extra = {}) => {
      state = { ...state, confirming: { what, ...extra } };
      draw();
    };
    if (action === "reload") {
      if (!mayLeave()) return;
      const answer = await api.fetchOverview({ fetchImpl });
      state = fromOverview(answer, { picture: state.picture, albumId: state.albumId });
      if (state.albumId) await openAlbum(state.albumId);
      draw();
    } else if (action === "keep") {
      state = { ...state, confirming: null };
      draw();
    } else if (action === "open-album") {
      if (!mayLeave()) return;
      await openAlbum(Number(button.dataset.id));
      draw();
    } else if (action === "close-album") {
      go({ albumId: null, album: null, picture: null, confirming: null });
    } else if (action === "open-picture") {
      go({ picture: Number(button.dataset.id), confirming: null });
    } else if (action === "close-picture") {
      go({ picture: null, confirming: null });
    } else if (action === "new-picture") {
      go({ uploading: { use: button.dataset.use, album: state.albumId, video: button.dataset.video === "1" } });
    } else if (action === "cancel-upload") {
      go({ uploading: null });
    } else if (action === "focal" || action === "focal-spot") {
      const pic = findPicture(state, button.dataset.id);
      if (!pic) return;
      let focal;
      if (action === "focal-spot") {
        focal = { x: Number(button.dataset.x), y: Number(button.dataset.y) };
      } else {
        const img = button.querySelector("img");
        focal = focalFrom(event, (img || button).getBoundingClientRect());
      }
      after("focal", await api.changePicture({ id: pic.id, version: pic.version, change: { focal }, fetchImpl }));
    } else if (action === "remove-picture") {
      if (!button.dataset.sure) return ask2("remove-picture");
      const pic = findPicture(state, state.picture);
      const result = await api.removePicture({ id: pic.id, version: pic.version, fetchImpl });
      after("remove", result, result.ok ? { picture: null, confirming: null } : {});
    } else if (action === "take-down") {
      go({ confirming: { what: "take-down", id: Number(button.dataset.id) } });
    } else if (action === "photo-up" || action === "photo-down") {
      const order = (state.album.photos || []).map((x) => x.id);
      const next = moved(order, order.indexOf(Number(button.dataset.id)), action === "photo-up" ? -1 : 1);
      if (next) after("photos", await api.orderPhotos({ id: state.albumId, version: state.album.version, order: next, fetchImpl }));
    } else if (action === "remove-photo") {
      const id = Number(button.dataset.id);
      if (!button.dataset.sure) return ask2("remove-photo", { id });
      after("photos", await api.removePhoto({ id: state.albumId, photo: id, version: state.album.version, fetchImpl }), { confirming: null });
    } else if (action === "remove-album") {
      if (!button.dataset.sure) return ask2("remove-album");
      const result = await api.removeAlbum({ id: state.albumId, version: state.album.version, fetchImpl });
      after("remove-album", result, result.ok ? { albumId: null, album: null, confirming: null } : {});
    } else if (action === "publish-album" || action === "unpublish-album") {
      go({ confirming: { what: action } });
    }
    return undefined;
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
  const root = document.getElementById("website-photos");
  if (root) mount(root);
}
