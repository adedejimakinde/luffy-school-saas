/**
 * The website editor's pictures and albums (`docs/school-sites.md` PR 5), as pure functions of the
 * school's answer, like `states.js`: a list on the first screen, one picture's screen (its
 * description, caption, focal point, where it is used, delete and take down), the upload screen,
 * and an album's screen (its photos, in order, described and captioned, and publishing it).
 *
 * A picture is "Processing…" while the media worker draws its sizes; the editor asks again until
 * it is ready (`app.js`). Every upload asks the uploader to confirm parents have agreed.
 */

import { esc } from "../web/html.js";

function note(n) {
  if (!n) return "";
  const reload = n.stale ? ' <button type="button" class="again" data-action="reload">Reload</button>' : "";
  return `<p class="note" role="alert">${esc(n.detail)}${reload}</p>`;
}

const USE_LABELS = { hero: "Hero", portrait: "Portrait", gallery: "Gallery photo" };

/** The little square that stands for a picture: itself, "Processing…", or why it could not be used. */
export function thumb(p, { size = 96 } = {}) {
  if (!p) return "";
  if (p.state === "ready" && p.thumb) {
    return `<img class="thumb" src="${esc(p.thumb)}" alt="${esc(p.alt)}" width="${size}" height="${size}" loading="lazy">`;
  }
  if (p.state === "processing") {
    return `<span class="thumb thumb-busy" role="status">Processing&hellip;</span>`;
  }
  return `<span class="thumb thumb-failed">Could not be used</span>`;
}

function where(p) {
  const u = p.used || {};
  const lines = [];
  if (u.live) lines.push("On the live website");
  for (const title of u.albums_live || []) lines.push(`In the published album &ldquo;${esc(title)}&rdquo;`);
  for (const place of u.draft || []) lines.push(`In the draft: ${esc(place)}`);
  if (u.album && !(u.albums_live || []).includes(u.album)) lines.push(`In the album &ldquo;${esc(u.album)}&rdquo; (not published yet)`);
  return lines.length ? lines.join("<br>") : "Not used anywhere yet";
}

function size(bytes) {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  return `${Math.round(bytes / 1024 ** 2)} MB`;
}

/** On the first screen: the pictures sections can choose, the albums, and the storage used. */
export function picturesBlock(body, { notes = {} } = {}) {
  const pics = body.pictures || [];
  const albums = body.albums || [];
  const storage = body.storage;
  return [
    '<div class="pictures-block">',
    "<h2>Albums</h2>",
    '<p class="hint">Photo albums for the Gallery page and gallery sections. Each album is published on its own.</p>',
    albums.length
      ? `<ul class="classes albums-list">${albums.map((a) => [
          '<li class="group album-row">',
          a.cover ? `<img class="thumb" src="${esc(a.cover)}" alt="" width="64" height="64" loading="lazy">` : '<span class="thumb thumb-empty" aria-hidden="true"></span>',
          `<span class="name">${esc(a.title)}</span>`,
          `<span class="level">${a.count} ${a.count === 1 ? "photo" : "photos"} &middot; ${a.live ? (a.changes ? "Published, with changes not yet published" : "Published") : "Not published"}</span>`,
          `<span class="row-actions"><button type="button" data-action="open-album" data-id="${esc(a.id)}">Open<span class="visually-hidden"> ${esc(a.title)}</span></button></span>`,
          "</li>",
        ].join("")).join("")}</ul>`
      : '<p class="blank">No albums yet.</p>',
    '<form class="add-album" data-form="add-album" data-tracked>',
    "<h3>New album</h3>",
    '<label for="album-title">Title</label>',
    '<input id="album-title" name="title" maxlength="120" required placeholder="Inter-house sports, 2026">',
    '<button type="submit">Make the album</button>',
    note(notes["add-album"]),
    "</form>",
    "<h2>Pictures</h2>",
    '<p class="hint">Hero pictures and videos, and portraits. Choose them in their section in the editor.</p>',
    pics.length
      ? `<ul class="classes pictures-list">${pics.map((p) => [
          '<li class="group picture-row">',
          thumb(p, { size: 64 }),
          `<span class="name">${esc(p.alt || "No description yet")}</span>`,
          `<span class="level">${esc(USE_LABELS[p.use] || p.use)}${p.video ? " video" : ""} &middot; ${where(p)}</span>`,
          `<span class="row-actions"><button type="button" data-action="open-picture" data-id="${esc(p.id)}">Open<span class="visually-hidden"> ${esc(p.alt)}</span></button></span>`,
          "</li>",
        ].join("")).join("")}</ul>`
      : '<p class="blank">No pictures yet.</p>',
    storage ? `<p class="hint">Storage used: ${esc(size(storage.used))} of ${esc(size(storage.quota))}.</p>` : "",
    "</div>",
  ].join("");
}

/** The nine places a focal point can be set by keyboard, as well as by tapping the picture. */
const SPOTS = [
  ["Top left", 0.15, 0.15], ["Top", 0.5, 0.15], ["Top right", 0.85, 0.15],
  ["Left", 0.15, 0.5], ["Centre", 0.5, 0.5], ["Right", 0.85, 0.5],
  ["Bottom left", 0.15, 0.85], ["Bottom", 0.5, 0.85], ["Bottom right", 0.85, 0.85],
];

function focalPicker(p) {
  if (p.state !== "ready") return "";
  const x = Math.round((p.focal ? p.focal.x : 0.5) * 100);
  const y = Math.round((p.focal ? p.focal.y : 0.5) * 100);
  return [
    '<div class="focal">',
    "<h2>What to keep in view</h2>",
    '<p class="hint">Tap the part of the picture that must never be cut off, such as faces. Phones show less of a wide picture, and keep this part.</p>',
    `<button type="button" class="focal-pick" data-action="focal" data-id="${esc(p.id)}" aria-label="Tap the picture where it should stay in view">`,
    `<img src="${esc(p.preview || p.thumb)}" alt="" width="${esc(p.w || 480)}" height="${esc(p.h || 320)}">`,
    `<span class="focal-mark" style="left: ${x}%; top: ${y}%" aria-hidden="true"></span>`,
    "</button>",
    `<p class="hint">Now: ${x}% across, ${y}% down.</p>`,
    '<div class="focal-spots" role="group" aria-label="Or choose a part">',
    SPOTS.map(([label, sx, sy]) => `<button type="button" data-action="focal-spot" data-id="${esc(p.id)}" data-x="${sx}" data-y="${sy}">${esc(label)}</button>`).join(""),
    "</div>",
    "</div>",
  ].join("");
}

/** One picture: what it shows, its focal point, where it is used, and what may be done with it. */
export function pictureScreen(body, p, { confirming = null, notes = {}, back = "All photos" } = {}) {
  if (!p) return '<section class="state" data-state="picture"><p class="blank">That picture has gone.</p><button type="button" class="again" data-action="close-picture">Back</button></section>';
  const gallery = p.use === "gallery";
  const asked = confirming && confirming.what === "remove-picture";
  const live = p.on_public_site;
  return [
    '<section class="state state-picture" data-state="picture">',
    `<button type="button" class="again" data-action="close-picture">${esc(back)}</button>`,
    `<h1>${esc(USE_LABELS[p.use] || "Picture")}${p.video ? " video" : ""}</h1>`,
    `<p class="picture-big">${thumb(p, { size: 160 })}</p>`,
    p.problem ? `<p class="note" role="alert">${esc(p.problem)}</p>` : "",
    `<p class="level">${where(p)}</p>`,
    `<form class="picture-form" data-form="picture" data-id="${esc(p.id)}" data-tracked>`,
    `<label for="picture-alt">What the picture shows${gallery ? "" : ""}</label>`,
    '<span class="hint" id="picture-alt-hint">For people who cannot see it, and for search engines: for example &ldquo;Students in green uniforms at the school gate&rdquo;.</span>',
    `<input id="picture-alt" name="alt" maxlength="250" value="${esc(p.alt)}" aria-describedby="picture-alt-hint"${gallery ? "" : " required"}>`,
    gallery ? `<label for="picture-caption">Caption (optional)</label><input id="picture-caption" name="caption" maxlength="200" value="${esc(p.caption)}">` : "",
    '<button type="submit">Save</button>',
    note(notes.picture),
    "</form>",
    focalPicker(p),
    note(notes.focal),
    '<div class="remove-picture">',
    "<h2>Delete</h2>",
    live
      ? `<p class="hint">This picture is on the live website, so it cannot just be deleted.${body.can_publish ? " To remove it everywhere at once, use Take down now." : " Only the principal can take it down."}</p>`
      : asked
        ? '<p>Delete this picture? Its file is removed from the server.</p><button type="button" class="danger" data-action="remove-picture" data-sure="1">Delete it</button> <button type="button" data-action="keep">Keep it</button>'
        : '<button type="button" data-action="remove-picture">Delete this picture</button>',
    note(notes.remove),
    "</div>",
    body.can_publish
      ? [
          '<div class="take-down">',
          "<h2>Take down now</h2>",
          '<p class="hint">Removes it from the live website, every album and the draft straight away, and deletes it from the server. Use it when a parent withdraws consent.</p>',
          `<button type="button" class="danger" data-action="take-down" data-id="${esc(p.id)}">Take down now</button>`,
          "</div>",
        ].join("")
      : "",
    "</section>",
  ].join("");
}

/** Take down, asked once more, with the reason the history keeps. */
export function confirmTakeDown(body, p, { notes = {} } = {}) {
  return [
    '<section class="state state-confirm" data-state="confirm-take-down">',
    "<h1>Take this picture down now?</h1>",
    p ? `<p class="picture-big">${thumb(p, { size: 160 })}</p>` : "",
    "<p>It comes off the live website, every album and the draft straight away, and its file is deleted from the server. This cannot be undone.</p>",
    '<p class="hint">Copies stay in the encrypted backups until they are replaced, at most 12 months.</p>',
    `<form data-form="take-down" data-id="${esc(p ? p.id : "")}">`,
    '<label for="take-down-reason">Why, for the history</label>',
    '<input id="take-down-reason" name="reason" maxlength="200" required placeholder="Consent withdrawn">',
    '<button type="submit" class="btn-primary danger">Take it down now</button>',
    "</form>",
    '<button type="button" class="again" data-action="keep">Not now</button>',
    note(notes["take-down"]),
    "</section>",
  ].join("");
}

/** Uploading: the file or files, what it shows (where one picture is sent), and the consent box. */
export function uploadScreen(body, { use, album = null, video = false }, { notes = {} } = {}) {
  const gallery = use === "gallery";
  const most = body.uploads_at_once || 5;
  const accept = video ? "video/mp4,video/quicktime,video/webm" : "image/jpeg,image/png,image/webp,image/heic,image/heif";
  const what = gallery ? "Photos" : use === "portrait" ? "The principal's portrait" : video ? "The hero's video" : "The hero's picture";
  return [
    '<section class="state state-upload" data-state="upload">',
    '<button type="button" class="again" data-action="cancel-upload">Back</button>',
    `<h1>Upload: ${esc(what)}</h1>`,
    `<form class="upload-form" data-form="upload" data-use="${esc(use)}"${album ? ` data-album="${esc(album)}"` : ""}${video ? ' data-video="1"' : ""} data-tracked>`,
    `<label for="upload-file">${gallery ? `Up to ${most} photos at a time` : video ? "A short video" : "A photo"}</label>`,
    video
      ? '<span class="hint" id="upload-file-hint">MP4, MOV or WebM, at most 50 MB and about 10 seconds. It plays silently, on a loop. A longer video belongs on YouTube.</span>'
      : '<span class="hint" id="upload-file-hint">JPG, PNG, WebP or an iPhone photo, at most 15 MB each.</span>',
    `<input type="file" id="upload-file" name="photo" accept="${accept}"${gallery ? " multiple" : ""} required aria-describedby="upload-file-hint">`,
    gallery
      ? '<p class="hint">Describe each photo on the album screen once it is uploaded.</p>'
      : '<label for="upload-alt">What it shows</label><span class="hint" id="upload-alt-hint">For people who cannot see it: for example &ldquo;Students at the school gate&rdquo;.</span><input id="upload-alt" name="alt" maxlength="250" required aria-describedby="upload-alt-hint">',
    `<label class="check"><input type="checkbox" name="consent" required> ${esc(body.consent || "Parents have agreed to photos of their children being published.")}</label>`,
    '<button type="submit">Upload</button>',
    note(notes.upload),
    "</form>",
    "</section>",
  ].join("");
}

function photoRow(p, i, count, confirming, canPublish, leaving) {
  const asked = confirming && confirming.what === "remove-photo" && confirming.id === p.id;
  const live = (p.used && p.used.albums_live && p.used.albums_live.length) || false;
  const remove = live && !canPublish
    ? '<span class="hint">Published: only the principal can take it out.</span>'
    : asked
      ? `<button type="button" class="danger" data-action="remove-photo" data-id="${esc(p.id)}" data-sure="1">Remove it</button><button type="button" data-action="keep">Keep it</button>`
      : `<button type="button" data-action="remove-photo" data-id="${esc(p.id)}">Remove</button>`;
  return [
    `<li class="group photo-row${leaving ? " inactive" : ""}">`,
    thumb(p, { size: 72 }),
    `<form class="photo-form" data-form="photo" data-id="${esc(p.id)}" data-tracked>`,
    `<label for="photo-alt-${esc(p.id)}">What it shows</label>`,
    `<input id="photo-alt-${esc(p.id)}" name="alt" maxlength="250" value="${esc(p.alt)}">`,
    `<label for="photo-caption-${esc(p.id)}">Caption (optional)</label>`,
    `<input id="photo-caption-${esc(p.id)}" name="caption" maxlength="200" value="${esc(p.caption)}">`,
    '<button type="submit">Save</button>',
    "</form>",
    '<span class="row-actions">',
    `<button type="button" data-action="open-picture" data-id="${esc(p.id)}">Edit<span class="visually-hidden"> photo ${i + 1}</span></button>`,
    `<button type="button" class="icon-button" data-action="photo-up" data-id="${esc(p.id)}"${i === 0 ? " disabled" : ""} aria-label="Move photo ${i + 1} up">&uarr;</button>`,
    `<button type="button" class="icon-button" data-action="photo-down" data-id="${esc(p.id)}"${i === count - 1 ? " disabled" : ""} aria-label="Move photo ${i + 1} down">&darr;</button>`,
    remove,
    "</span></li>",
  ].join("");
}

/** One album: its title and words, its photos in order, uploading more, and publishing it. */
export function albumScreen(body, album, { confirming = null, notes = {} } = {}) {
  if (!album) return '<section class="state" data-state="album"><p class="blank">Loading the album&hellip;</p></section>';
  const photos = album.photos || [];
  const most = body.most_photos || 60;
  const canPublish = body.can_publish;
  const askedDelete = confirming && confirming.what === "remove-album";
  const status = album.live
    ? `<strong class="label label-ok">Published</strong> ${album.live_count} ${album.live_count === 1 ? "photo" : "photos"} on the website.${album.changes ? " <strong>Changes not yet published.</strong>" : ""}`
    : '<strong class="label label-warn">Not published</strong> The public cannot see this album.';
  return [
    '<section class="state state-album" data-state="album">',
    '<button type="button" class="again" data-action="close-album">All photos</button>',
    `<h1>${esc(album.title)}</h1>`,
    `<p class="site-status" role="status">${status}</p>`,
    `<p><a class="btn" href="${esc(album.preview)}" target="_blank" rel="noopener">Preview the album</a></p>`,
    canPublish
      ? [
          '<div class="site-actions">',
          (!album.live || album.changes) && photos.length ? `<button type="button" class="btn-primary" data-action="publish-album">${album.live ? "Publish the changes" : "Publish the album"}</button>` : "",
          album.live ? '<button type="button" data-action="unpublish-album">Take it off the website</button>' : "",
          "</div>",
        ].join("")
      : '<p class="hint">The principal publishes albums.</p>',
    note(notes.album),
    `<form class="album-form" data-form="album" data-tracked>`,
    '<label for="album-name">Title</label>',
    `<input id="album-name" name="title" maxlength="120" value="${esc(album.title)}" required>`,
    '<label for="album-words">A few words (optional)</label>',
    `<textarea id="album-words" name="description" maxlength="600" rows="3">${esc(album.description || "")}</textarea>`,
    album.address_fixed
      ? `<p class="level">${esc(album.path)}</p>`
      : `<label for="album-slug">Web address</label><span class="hint" id="album-slug-hint">/gallery/ and then this. It is fixed once the album is published.</span><input id="album-slug" name="slug" maxlength="40" value="${esc(album.slug)}" aria-describedby="album-slug-hint" autocapitalize="none">`,
    '<button type="submit">Save</button>',
    note(notes["album-form"]),
    "</form>",
    `<h2>Photos <span class="level">${photos.length} of at most ${most}</span></h2>`,
    photos.length < most ? '<p><button type="button" data-action="new-picture" data-use="gallery">Upload photos</button></p>' : "",
    photos.length
      ? `<ol class="sections-list photos-list">${photos.map((p, i) => photoRow(p, i, photos.length, confirming, canPublish, false)).join("")}</ol>`
      : '<p class="blank">No photos yet.</p>',
    (album.leaving || []).length ? `<p class="hint">${album.leaving.length} taken out: still on the website until the album is published again.</p>` : "",
    note(notes.photos),
    album.live
      ? ""
      : [
          '<div class="remove-page">',
          "<h2>Delete this album</h2>",
          askedDelete
            ? `<p>Delete ${esc(album.title)} and its photos?</p><button type="button" class="danger" data-action="remove-album" data-sure="1">Delete it</button> <button type="button" data-action="keep">Keep it</button>`
            : '<button type="button" data-action="remove-album">Delete this album</button>',
          note(notes["remove-album"]),
          "</div>",
        ].join(""),
    "</section>",
  ].join("");
}

/** Publishing an album, or taking it off, asked once more. */
export function confirmAlbum(body, album, what, { notes = {} } = {}) {
  const off = what === "unpublish-album";
  return [
    '<section class="state state-confirm" data-state="confirm-album">',
    `<h1>${off ? "Take the album off the website?" : "Publish the album?"}</h1>`,
    `<p>${off ? `Visitors will no longer see &ldquo;${esc(album.title)}&rdquo;. Its photos stay here, to publish again.` : `Everyone who visits the website will see &ldquo;${esc(album.title)}&rdquo; as it is now, straight away.`}</p>`,
    `<form data-form="${off ? "unpublish-album" : "publish-album"}">`,
    '<label for="album-note">A note for the history (optional)</label>',
    '<input id="album-note" name="note" maxlength="200">',
    `<button type="submit" class="btn-primary">${off ? "Take it off" : "Publish now"}</button>`,
    "</form>",
    '<button type="button" class="again" data-action="keep">Not now</button>',
    note(notes[what]),
    "</section>",
  ].join("");
}

/** Every picture visible on the screen now, to know whether to ask again while some are processing. */
export function visiblePictures(state) {
  const body = state.body || {};
  return [...(body.pictures || []), ...((state.album && state.album.photos) || [])];
}

export const processing = (state) => visiblePictures(state).some((p) => p.state === "processing");
