/**
 * The installed app's page script, loaded by the menu's shell (`docs/pwa.md`): ask for the
 * portal's worker, and run the "Install app" button. It imports nothing, so it needs no place
 * in a page's import map. Sign-out is the worker's (`sync/worker.js`).
 *
 * Nothing here lists or unregisters workers or touches a cache: `/sit/` keeps its own.
 * Android raises `beforeinstallprompt`; iPhone has no such event, so the button opens the
 * how-to instead. Opened from the home screen, neither shows.
 */
export function mount(win, doc) {
  const nav = win.navigator;
  const box = doc.getElementById("install");
  const button = doc.getElementById("install-app");
  const howto = doc.getElementById("install-howto");
  let saved = null;

  if (nav.serviceWorker) {
    nav.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {});
    // After a sign-out emptied the shell, the next page with the menu keeps it again.
    nav.serviceWorker.ready.then((r) => r.active.postMessage({ type: "prime" })).catch(() => {});
  }
  if (!box || nav.standalone || win.matchMedia("(display-mode: standalone)").matches) return;

  if (/iP(hone|ad|od)/.test(nav.userAgent) || (nav.platform === "MacIntel" && nav.maxTouchPoints > 1)) box.hidden = false;
  win.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    saved = event;
    box.hidden = false;
  });
  win.addEventListener("appinstalled", () => {
    saved = null;
    box.hidden = true;
  });
  button.addEventListener("click", () => {
    if (saved) {
      saved.prompt();
      saved = null;
      box.hidden = true;
    } else {
      howto.hidden = !howto.hidden;
      button.setAttribute("aria-expanded", String(!howto.hidden));
    }
  });
}

if (typeof document !== "undefined") mount(window, document);
