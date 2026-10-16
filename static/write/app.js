/**
 * The blog editor (`blog/templates/blog/write/editor.html`), on /write/ only.
 * Named by that page and no other: never on classnode.co.
 *
 * The page works without it (a form that saves). This adds:
 *
 * - the live preview: the Markdown is sent to the server as it is typed
 *   (`blog.write_views.preview`), which draws and sanitises it exactly as the
 *   published post is, so the preview is never this module's guess;
 * - counters on the fields with a length, and the search result's preview;
 * - the formatting buttons, and the picture box, which uploads a picture
 *   (saved as WebP by the server) and refuses one with no description;
 * - on a phone, the Write, Preview and Details tabs;
 * - the bottom bar kept above the keyboard where the browser does not shrink
 *   the page for it (`--keyboard`);
 * - a warning before leaving with changes not saved.
 */

import { counter, format, insertBlock, keyboardHeight, pictureMarkdown, serpText } from "./tools.js";

const form = document.getElementById("post-form");
if (form) start(form);

function start(form) {
  const token = form.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
  const body = form.querySelector("#id_body");
  const title = form.querySelector("#id_title");
  const preview = document.getElementById("preview");
  const words = form.querySelector("[data-words]");
  const editable = body && !body.disabled;
  let dirty = false;
  let sending = false;

  /* -- the tabs (below 1100px) ------------------------------------------- */
  const tabs = form.querySelector(".ed-tabs");
  if (tabs) {
    tabs.hidden = false;
    form.dataset.tab = "write";
    tabs.addEventListener("click", (event) => {
      const tab = event.target.closest("[data-tab]");
      if (!tab) return;
      form.dataset.tab = tab.dataset.tab;
      for (const each of tabs.querySelectorAll("[data-tab]")) {
        each.setAttribute("aria-selected", String(each === tab));
      }
      if (tab.dataset.tab === "preview") refresh();
    });
  }

  /* -- the live preview ---------------------------------------------------- */
  let timer = 0;
  let asked = 0;
  async function refresh() {
    if (!body || !preview) return;
    const ask = ++asked;
    const data = new FormData();
    data.set("body", body.value);
    try {
      const response = await fetch(form.dataset.preview, {
        method: "POST",
        body: data,
        headers: { "X-CSRFToken": token },
        credentials: "same-origin",
      });
      if (!response.ok || ask !== asked) return;
      const answer = await response.json();
      // Drawn and sanitised by the server (`blog.markdown.render`).
      preview.innerHTML = answer.html;
      if (words) words.textContent = `${answer.words} word${answer.words === 1 ? "" : "s"}`;
    } catch {
      /* The last preview stays; saving does not depend on it. */
    }
  }
  body?.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(refresh, 350);
  });

  /* -- counters and the search result -------------------------------------- */
  for (const shown of form.querySelectorAll("[data-count]")) {
    const field = form.querySelector(`#${shown.dataset.count}`);
    const max = Number(shown.dataset.max);
    const update = () => {
      const { text, over } = counter(field.value.length, max);
      shown.textContent = text;
      shown.classList.toggle("over", over);
    };
    field?.addEventListener("input", update);
    if (field) update();
  }
  const serp = (name) => form.querySelector(`[data-serp="${name}"]`);
  const field = (id) => form.querySelector(`#${id}`);
  function updateSerp() {
    serp("title").textContent = serpText(field("id_seo_title")?.value, title?.value, "SEO title");
    serp("description").textContent = serpText(field("id_seo_description")?.value, field("id_summary")?.value, "SEO description");
    const slug = field("id_slug")?.value.trim();
    if (slug) serp("slug").textContent = slug;
  }
  if (serp("title")) {
    for (const id of ["id_seo_title", "id_seo_description", "id_summary", "id_slug", "id_title"]) {
      field(id)?.addEventListener("input", updateSerp);
    }
  }

  /* -- the title is one line ------------------------------------------------ */
  title?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") event.preventDefault();
  });

  /* -- formatting ----------------------------------------------------------- */
  const toolbar = form.querySelector(".toolbar");
  if (toolbar && editable) {
    toolbar.hidden = false;
    toolbar.addEventListener("click", (event) => {
      const button = event.target.closest("[data-md]");
      if (!button) return;
      if (button.dataset.md === "image") return openPicture();
      const out = format(button.dataset.md, body.value, body.selectionStart, body.selectionEnd);
      put(out);
    });
  }
  function put(out) {
    body.value = out.text;
    body.focus();
    body.setSelectionRange(out.start, out.end);
    body.dispatchEvent(new Event("input", { bubbles: true }));
  }

  /* -- the picture box ------------------------------------------------------ */
  const dialog = document.getElementById("img-dialog");
  const pictureForm = document.getElementById("img-form");
  const error = document.getElementById("img-error");
  let cursor = 0;
  function openPicture() {
    cursor = body.selectionEnd;
    pictureForm.reset();
    error.hidden = true;
    dialog.showModal();
  }
  function refuse(message) {
    error.querySelector("span").textContent = message;
    error.hidden = false;
  }
  dialog?.querySelector("[data-close]")?.addEventListener("click", () => dialog.close());
  pictureForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = pictureForm.querySelector("#img-file").files[0];
    const alt = pictureForm.querySelector("#img-alt").value.trim();
    if (!file) return refuse("Choose a picture.");
    if (!alt) return refuse("Describe the picture. Every picture needs a description.");
    const insert = pictureForm.querySelector("#img-insert");
    insert.disabled = true;
    const data = new FormData();
    data.set("file", file);
    try {
      const response = await fetch(form.dataset.upload, {
        method: "POST",
        body: data,
        headers: { "X-CSRFToken": token },
        credentials: "same-origin",
      });
      const answer = await response.json();
      if (!response.ok) return refuse(answer.detail || "That picture could not be added.");
      dialog.close();
      put(insertBlock(body.value, cursor, pictureMarkdown(alt, answer.key)));
      refresh();
    } catch {
      refuse("That picture could not be sent. Check the connection and try again.");
    } finally {
      insert.disabled = false;
    }
  });

  /* -- the bar above the keyboard ------------------------------------------ */
  const viewport = window.visualViewport;
  if (viewport) {
    const lift = () => {
      const covered = keyboardHeight(window.innerHeight, viewport.height, viewport.offsetTop);
      document.documentElement.style.setProperty("--keyboard", `${covered}px`);
    };
    viewport.addEventListener("resize", lift);
    viewport.addEventListener("scroll", lift);
  }

  /* -- leaving with changes not saved -------------------------------------- */
  form.addEventListener("input", () => { dirty = true; });
  form.addEventListener("submit", () => { sending = true; });
  window.addEventListener("beforeunload", (event) => {
    if (dirty && !sending) event.preventDefault();
  });
}
