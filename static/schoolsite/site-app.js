/**
 * A school's public website: the only script it runs, and nothing needs it to work.
 * `docs/school-sites.md` §4.3, §9.2, PR 5. Loaded as a module only on a page with a
 * gallery or a hero video; the page's policy allows this file and no other script.
 *
 * - **Tap to enlarge.** Each gallery photo is a link to its large JPEG, which opens
 *   with no script at all. Here a tap opens it over the page instead, in a <dialog>,
 *   in AVIF or WebP where the browser takes them, with its caption, the next and the
 *   previous photo (buttons, arrow keys, a swipe), and Escape or Close to leave.
 * - **The hero video** gets its source only after the page has loaded, and only when
 *   the screen is at least 768px wide (or the theme lets phones have it), data saver
 *   is off and reduced motion is not asked for. Otherwise the poster stays. Once it
 *   plays, a visible button pauses it.
 */

const WIDE = "(min-width: 48em)";
const STILL = "(prefers-reduced-motion: reduce)";

function el(tag, attrs = {}, text = "") {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text) node.textContent = text;
  return node;
}

/** The photos a link belongs with: its own list, in order. */
function setOf(link) {
  const list = link.closest("[data-lightbox]");
  return list ? Array.from(list.querySelectorAll("a.photo")) : [link];
}

export function lightbox(doc = document) {
  if (typeof HTMLDialogElement === "undefined") return;
  let dialog = null;
  let links = [];
  let at = 0;
  let opener = null;

  const build = () => {
    dialog = el("dialog", { class: "lightbox", "aria-label": "Photo" });
    const picture = el("picture");
    picture.append(el("source", { type: "image/avif" }), el("source", { type: "image/webp" }), el("img", { alt: "" }));
    const caption = el("p", { class: "lightbox-caption" });
    const bar = el("div", { class: "lightbox-bar" });
    const prev = el("button", { type: "button", class: "lightbox-prev" }, "Previous");
    const next = el("button", { type: "button", class: "lightbox-next" }, "Next");
    const close = el("button", { type: "button", class: "lightbox-close" }, "Close");
    bar.append(prev, next, close);
    dialog.append(picture, caption, bar);
    prev.addEventListener("click", () => show(at - 1));
    next.addEventListener("click", () => show(at + 1));
    close.addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", (e) => {
      if (e.target === dialog) dialog.close();
    });
    dialog.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft") show(at - 1);
      else if (e.key === "ArrowRight") show(at + 1);
    });
    let startX = null;
    dialog.addEventListener("touchstart", (e) => { startX = e.touches[0].clientX; }, { passive: true });
    dialog.addEventListener("touchend", (e) => {
      if (startX === null) return;
      const moved = e.changedTouches[0].clientX - startX;
      if (Math.abs(moved) > 50) show(at + (moved < 0 ? 1 : -1));
      startX = null;
    });
    dialog.addEventListener("close", () => {
      if (opener) opener.focus();
    });
    doc.body.append(dialog);
  };

  const show = (i) => {
    if (!links.length) return;
    at = (i + links.length) % links.length;
    const link = links[at];
    const [avif, webp, img] = dialog.querySelectorAll("picture > *");
    const thumb = link.querySelector("img");
    avif.srcset = link.dataset.avif || "";
    webp.srcset = link.dataset.webp || "";
    img.src = link.href;
    img.alt = thumb ? thumb.alt : "";
    if (link.dataset.w) img.width = Number(link.dataset.w);
    if (link.dataset.h) img.height = Number(link.dataset.h);
    const figure = link.closest("figure");
    const caption = figure ? figure.querySelector("figcaption") : null;
    dialog.querySelector(".lightbox-caption").textContent = caption ? caption.textContent : "";
    const many = links.length > 1;
    dialog.querySelector(".lightbox-prev").hidden = !many;
    dialog.querySelector(".lightbox-next").hidden = !many;
  };

  doc.addEventListener("click", (event) => {
    const link = event.target.closest && event.target.closest("a.photo");
    if (!link || event.metaKey || event.ctrlKey || event.shiftKey || event.button > 0) return;
    event.preventDefault();
    if (!dialog) build();
    opener = link;
    links = setOf(link);
    show(links.indexOf(link));
    dialog.showModal();
    dialog.querySelector(".lightbox-close").focus();
  });
}

/** Whether this visit may play the hero video (§9.2). */
export function mayPlay(video, win = window) {
  const phones = video.dataset.phones === "1";
  const wide = win.matchMedia ? win.matchMedia(WIDE).matches : false;
  const still = win.matchMedia ? win.matchMedia(STILL).matches : true;
  const saving = Boolean(win.navigator && win.navigator.connection && win.navigator.connection.saveData);
  return (wide || phones) && !saving && !still;
}

export function heroVideo(doc = document, win = window) {
  const video = doc.querySelector("video.hero-video[data-src]");
  if (!video) return;
  const start = () => {
    if (!mayPlay(video, win)) return;
    const pause = video.parentElement.querySelector("button.pause");
    video.src = video.dataset.src;
    video.addEventListener("playing", () => {
      video.classList.add("playing");
      if (pause) pause.hidden = false;
    }, { once: true });
    if (pause) {
      pause.addEventListener("click", () => {
        const playing = !video.paused;
        if (playing) video.pause();
        else video.play();
        pause.setAttribute("aria-pressed", String(playing));
        pause.textContent = playing ? "Play the video" : "Pause the video";
      });
    }
    const played = video.play();
    if (played && played.catch) played.catch(() => {});
  };
  if (doc.readyState === "complete") start();
  else win.addEventListener("load", start, { once: true });
}

if (typeof document !== "undefined") {
  lightbox();
  heroVideo();
}
