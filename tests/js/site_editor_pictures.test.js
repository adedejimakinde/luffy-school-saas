/**
 * Photos and albums at `/website/photos/` (`static/site-editor/photos-app.js`, `pictures.js`), and the
 * editor's picture and album fields (`forms.js`). `docs/school-sites.md` PR 5.
 *
 * What it promises a person: a section chooses one of the school's pictures or albums, with a way to
 * upload one; every upload asks the uploader to confirm parents agreed; a
 * picture still processing says "Processing…" and the page asks again until it is ready; an album
 * has its own screen, and only the principal publishes it; only the principal takes a picture down,
 * from its own confirm screen, saying why.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { fromOverview as editorOverview, htmlFor as editorHtml } from "../../static/site-editor/app.js";
import { collect, fields, pictureValue } from "../../static/site-editor/forms.js";
import { findPicture, focalFrom, fromHash, fromOverview, htmlFor, mount } from "../../static/site-editor/photos-app.js";
import * as pics from "../../static/site-editor/pictures.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const picture = (id, over = {}) => ({
  id, use: "hero", video: false, album: null, removed: false, alt: `Picture ${id}`, caption: "", focal: { x: 0.5, y: 0.5 },
  version: 1, state: "ready", problem: "", thumb: `/website/pictures/k${id}/480.webp`, preview: `/website/pictures/k${id}/828.webp`,
  w: 1920, h: 1280, uploaded_by: "Rev. Sr. Okafor", uploaded_at: "2026-11-01T09:00:00Z",
  used: { draft: [], live: false, albums_live: [], album: "" }, on_public_site: false, ...over,
});

const ALBUM = {
  id: 4, title: "Sports day", slug: "sports-day", path: "/gallery/sports-day/", preview: "/website/preview/gallery/sports-day/",
  version: 3, count: 2, live: true, live_count: 2, changes: false, address_fixed: true, cover: "/website/pictures/k21/480.webp",
  description: "", published_at: "2026-11-01T10:00:00Z", published_by: "Rev. Sr. Okafor", leaving: [],
  photos: [picture(21, { use: "gallery", album: 4, used: { draft: [], live: false, albums_live: ["Sports day"], album: "Sports day" }, on_public_site: true }),
    picture(22, { use: "gallery", album: 4, alt: "", state: "processing", thumb: "" })],
};

const OVERVIEW = {
  role: "principal", can_edit: true, can_publish: true, delegated: false, school: "St Mary's",
  state: { published: true, revision: 2, published_at: "2026-10-30T10:00:00Z", published_by: "Rev. Sr. Okafor",
    changes: false, ready: false, ready_by: "", ready_at: null, draft_version: 7 },
  version: 3, colour: "", card_colour: "#143D8C", footer: { address_line: "", social: [] }, networks: [], preview: "/website/preview/",
  consent: "Parents have agreed to photos of their children being published.", uploads_at_once: 5, most_photos: 60,
  storage: { used: 50 * 1024 * 1024, quota: 1024 ** 3 },
  pages: [{
    key: "home", kind: "fixed", slug: "", ref: "home", label: "Home", title: "", description: "", path: "/", preview: "/website/preview/",
    enabled: true, version: 4, menu_position: 0, address_fixed: true,
    kinds: [{ kind: "hero", label: "Hero", available: true, hint: "" }, { kind: "gallery", label: "Gallery", available: true, hint: "" }],
    sections: [{ id: 11, kind: "hero", variant: "image", version: 2, data: { heading: "Welcome", buttons: [], image: 5, video: null } },
      { id: 12, kind: "gallery", variant: "grid", version: 1, data: { album: 4, count: 6 } }],
  }],
  pictures: [picture(5, { used: { draft: ["Hero on Home"], live: true, albums_live: [], album: "" }, on_public_site: true }),
    picture(6, { video: true, alt: "Arriving", state: "processing", thumb: "" }),
    picture(7, { use: "portrait", alt: "The principal" })],
  albums: [{ ...ALBUM, photos: undefined }],
  log: [{ kind: "taken_down", revision: 3, subject: "A child", note: "Consent withdrawn", by: "Rev. Sr. Okafor", at: "2026-11-01T11:00:00Z" },
    { kind: "album_published", revision: null, subject: "Sports day", note: "", by: "Rev. Sr. Okafor", at: "2026-11-01T10:00:00Z" }],
};

const ADMIN = { ...OVERVIEW, role: "admin", can_publish: false, delegated: true };

function serve(routes, calls = []) {
  return async (url, options = {}) => {
    calls.push({ url, method: options.method || "GET", body: options.body });
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    for (const [match, answer] of routes) {
      if (url.includes(match) && (!answer.method || answer.method === (options.method || "GET"))) {
        const value = typeof answer.reply === "function" ? answer.reply(options, url) : answer;
        return { status: value.status, json: async () => value.body };
      }
    }
    throw new Error(`no stub for ${options.method || "GET"} ${url}`);
  };
}

const opened = async (routes = [], body = OVERVIEW, extra = {}) => {
  forgetToken();
  const calls = [];
  const root = fakeRoot({ portal: "app.example.test" });
  const app = await mount(root, {
    fetchImpl: serve([...routes, ["/api/website/", { status: 200, body, method: "GET" }]], calls),
    ask: () => true, win: { addEventListener() {} }, pollMs: 0, ...extra,
  });
  return { root, app, calls };
};

test("photos and albums lists the albums and the pictures, says which are processing, and the storage used", () => {
  const html = htmlFor(fromOverview({ ok: true, body: OVERVIEW }));
  assert.match(html, /<a class="btn" href="\/website\/">Back to the website editor<\/a>/);
  assert.match(html, /data-action="new-picture" data-use="hero" data-video="1"/);
  assert.match(html, /<h2>Albums<\/h2>/);
  assert.match(html, /Sports day<\/span><span class="level">2 photos &middot; Published/);
  assert.match(html, /data-action="open-album" data-id="4"/);
  assert.match(html, /<span class="thumb thumb-busy" role="status">Processing&hellip;<\/span>/);
  assert.match(html, /On the live website<br>In the draft: Hero on Home/);
  assert.match(html, /Storage used: 50 MB of 1.0 GB/);
});

test("the editor links to photos and albums, and its log says what happened to albums and pictures", () => {
  const html = editorHtml(editorOverview({ ok: true, body: OVERVIEW }));
  assert.match(html, /<a class="btn" href="\/website\/photos\/">Photos and albums<\/a>/);
  assert.match(html, /Took down a picture \(&ldquo;A child&rdquo;\), as version 3 by Rev. Sr. Okafor: &ldquo;Consent withdrawn&rdquo;/);
  assert.match(html, /Published the album &ldquo;Sports day&rdquo;/);
  assert.doesNotMatch(html, /Go back to version 3/);
});

test("a hero chooses among the school's hero pictures and videos, and reads back as image or video", () => {
  const html = fields("hero", { heading: "Hi", image: 5 }, { pictures: OVERVIEW.pictures });
  assert.match(html, /<option value="image:5" selected>Picture 5<\/option>/);
  assert.match(html, /<option value="video:6">Arriving \(video\) – Processing…<\/option>/);
  assert.doesNotMatch(html, /The principal/, "a portrait is not offered for a hero");
  assert.match(html, /<img class="thumb" src="\/website\/pictures\/k5\/480.webp" alt="Picture 5"/);
  assert.match(html, /href="\/website\/photos\/#upload-hero-video">Upload a video<\/a>/);
  assert.match(html, /href="\/website\/photos\/#picture-5">Edit this picture<\/a>/);
  assert.match(fields("hero", { heading: "Hi", image: 99 }, { pictures: OVERVIEW.pictures }),
    /<option value="image:99" selected>The current picture<\/option>/, "a picture not in the list stays chosen");
  assert.deepEqual(collect("hero", { heading: "Hi", media: "video:6" }), { heading: "Hi", subheading: "", buttons: [], image: null, video: 6 });
  assert.deepEqual(collect("hero", { heading: "Hi", media: "" }).image, null);
  assert.equal(collect("principal_message", { message: "Hello", portrait: "7" }).portrait, 7);
  assert.equal(pictureValue("hero", { id: 9, video: true }), "video:9");
});

test("a gallery section chooses an album and says so in the list", () => {
  const html = fields("gallery", { album: 4, count: 6 }, { albums: OVERVIEW.albums });
  assert.match(html, /<option value="4" selected>Sports day<\/option>/);
  assert.deepEqual(collect("gallery", { album: "4", count: "3" }), { album: 4, count: 3 });
  const page = editorHtml({ ...editorOverview({ ok: true, body: OVERVIEW }), open: "home" });
  assert.match(page, /<span class="name">Gallery<\/span><span class="level">Sports day<\/span>/);
  assert.match(page, /data-action="edit-section" data-id="12"/, "a gallery section can be edited now");
});

test("uploading asks for consent, sends the files, and opens the new picture with a way back to the editor", async () => {
  let sent = null;
  const answer = { ...OVERVIEW, pictures: [...OVERVIEW.pictures, picture(9, { state: "processing", thumb: "" })], made: [9] };
  const { root, app, calls } = await opened([["/api/website/pictures/", {
    method: "POST", reply: (options) => { sent = options.body; return { status: 200, body: answer }; },
  }]], OVERVIEW, { hash: "#upload-hero" });
  assert.match(root.innerHTML, /<h1>Upload: The hero&#39;s picture<\/h1>/);
  assert.match(root.innerHTML, /<input type="checkbox" name="consent" required> Parents have agreed to photos of their children being published./);
  assert.match(root.innerHTML, /<input id="upload-alt" name="alt" maxlength="250" required/);
  const file = new Blob(["x"], { type: "image/jpeg" });
  await root.submit({ alt: "The gate", consent: { type: "checkbox", checked: true }, photo: { files: [file] } },
    { form: "upload" });
  assert.equal(sent.get("use"), "hero");
  assert.equal(sent.get("consent"), "1");
  assert.equal(sent.get("alt"), "The gate");
  assert.equal(sent.getAll("photo").length, 1);
  assert.ok(calls.some((c) => c.method === "POST" && c.url === "/api/website/pictures/"));
  assert.equal(app.current().uploading, null);
  assert.equal(app.current().picture, 9);
  assert.match(root.innerHTML, /Uploaded. Choose it in its section in the editor, then Save. <a href="\/website\/">Back to the website editor<\/a>/);
  assert.match(root.innerHTML, /Processing&hellip;/);
});

test("a link opens a screen directly", () => {
  assert.deepEqual(fromHash("#album-4"), { albumId: 4 });
  assert.deepEqual(fromHash("#picture-12"), { picture: 12 });
  assert.deepEqual(fromHash("#upload-hero-video"), { uploading: { use: "hero", album: null, video: true } });
  assert.deepEqual(fromHash("#upload-portrait"), { uploading: { use: "portrait", album: null, video: false } });
  assert.deepEqual(fromHash("#upload-portrait-video").uploading.video, false, "only a hero is a video");
  assert.deepEqual(fromHash("#nothing"), {});
});

test("a refused upload keeps the upload screen with the school's sentence", async () => {
  const { root, app } = await opened([["/api/website/pictures/", {
    method: "POST", status: 422, body: { detail: "A photo can be at most 15 MB. Save it smaller and try again." },
  }]]);
  await root.click({ "data-action": "new-picture", "data-use": "portrait" });
  assert.match(root.innerHTML, /<h1>Upload: The principal&#39;s portrait<\/h1>/);
  await root.submit({ alt: "Me", consent: { type: "checkbox", checked: true }, photo: { files: [new Blob(["x"])] } }, { form: "upload" });
  assert.equal(app.current().notes.upload.detail, "A photo can be at most 15 MB. Save it smaller and try again.");
  assert.ok(app.current().uploading);
});

test("an album has its own screen: photos in order, publishing for the principal only", async () => {
  const { root } = await opened([["/api/website/albums/4/", { method: "GET", status: 200, body: { album: ALBUM } }]]);
  await root.click({ "data-action": "open-album", "data-id": "4" });
  assert.match(root.innerHTML, /<h1>Sports day<\/h1>/);
  assert.match(root.innerHTML, /<strong class="label label-ok">Published<\/strong> 2 photos on the website./);
  assert.match(root.innerHTML, /data-action="unpublish-album"/);
  assert.match(root.innerHTML, /<h2>Photos <span class="level">2 of at most 60<\/span><\/h2>/);
  assert.match(root.innerHTML, /data-action="new-picture" data-use="gallery"/);
  assert.doesNotMatch(root.innerHTML, /Delete this album/, "a published album is taken off before it is deleted");
  const admin = pics.albumScreen(ADMIN, ALBUM);
  assert.match(admin, /The principal publishes albums/);
  assert.doesNotMatch(admin, /data-action="publish-album"|data-action="unpublish-album"/);
  assert.match(admin, /Published: only the principal can take it out/);
});

test("photos move up and down by sending the whole order with the album's version", async () => {
  let order = null;
  const { root } = await opened([
    ["/api/website/albums/4/photos/", { method: "PUT", reply: (o) => { order = JSON.parse(o.body); return { status: 200, body: { ...OVERVIEW, album: ALBUM } }; } }],
    ["/api/website/albums/4/", { method: "GET", status: 200, body: { album: ALBUM } }],
  ]);
  await root.click({ "data-action": "open-album", "data-id": "4" });
  await root.click({ "data-action": "photo-down", "data-id": "21" });
  assert.deepEqual(order, { version: 3, order: [22, 21] });
});

test("only the principal takes a picture down, from its own screen, saying why", async () => {
  let sent = null;
  const { root, app } = await opened([["/api/website/pictures/5/take-down/", {
    method: "POST", reply: (o) => { sent = JSON.parse(o.body); return { status: 200, body: OVERVIEW }; },
  }]]);
  await root.click({ "data-action": "open-picture", "data-id": "5" });
  assert.match(root.innerHTML, /This picture is on the live website, so it cannot just be deleted. To remove it everywhere at once, use Take down now./);
  await root.click({ "data-action": "take-down", "data-id": "5" });
  assert.match(root.innerHTML, /<h1>Take this picture down now\?<\/h1>/);
  assert.match(root.innerHTML, /Copies stay in the encrypted backups until they are replaced, at most 12 months./);
  assert.match(root.innerHTML, /<input id="take-down-reason" name="reason" maxlength="200" required/);
  await root.submit({ reason: "Consent withdrawn" }, { form: "take-down", id: "5" });
  assert.deepEqual(sent, { reason: "Consent withdrawn" });
  assert.equal(app.current().picture, null);
  const admin = pics.pictureScreen(ADMIN, OVERVIEW.pictures[0]);
  assert.doesNotMatch(admin, /Take down now<\/button>/);
  assert.match(admin, /Only the principal can take it down/);
});

test("the focal point is set by a tap on the picture, or by one of nine places", async () => {
  assert.deepEqual(focalFrom({ clientX: 150, clientY: 75 }, { left: 50, top: 25, width: 400, height: 200 }), { x: 0.25, y: 0.25 });
  assert.deepEqual(focalFrom({ clientX: 999, clientY: -5 }, { left: 0, top: 0, width: 100, height: 100 }), { x: 1, y: 0 });
  let sent = null;
  const { root } = await opened([["/api/website/pictures/7/", {
    method: "PUT", reply: (o) => { sent = JSON.parse(o.body); return { status: 200, body: OVERVIEW }; },
  }]]);
  await root.click({ "data-action": "open-picture", "data-id": "7" });
  assert.match(root.innerHTML, /<span class="focal-mark" style="left: 50%; top: 50%"/);
  await root.click({ "data-action": "focal-spot", "data-id": "7", "data-x": "0.5", "data-y": "0.15" });
  assert.deepEqual(sent, { version: 1, focal: { x: 0.5, y: 0.15 } });
});

test("while a picture is processing the page asks again, and redraws when it is ready", async () => {
  const pending = [];
  const timers = { setTimeout: (fn) => { pending.push(fn); return pending.length; } };
  const ready = { ...OVERVIEW, pictures: OVERVIEW.pictures.map((p) => ({ ...p, state: "ready", thumb: `/t/${p.id}.webp` })) };
  let reads = 0;
  forgetToken();
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([["/api/website/", { method: "GET", reply: () => ({ status: 200, body: reads++ ? ready : OVERVIEW }) }]]),
    ask: () => true, win: { addEventListener() {} }, pollMs: 10, timers,
  });
  assert.match(root.innerHTML, /Processing&hellip;/);
  assert.equal(pending.length, 1);
  await pending.shift()();
  assert.doesNotMatch(root.innerHTML, /Processing&hellip;/);
  assert.equal(pending.length, 0, "nothing processing: no more asking");
});

test("a picture is found on the screen it was opened from", () => {
  const state = { body: OVERVIEW, album: ALBUM };
  assert.equal(findPicture(state, 22).state, "processing");
  assert.equal(findPicture(state, 7).use, "portrait");
  assert.equal(findPicture(state, 99), null);
});
