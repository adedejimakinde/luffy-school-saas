/**
 * What the marking and register pages do about having no connection, apart from
 * the outbox: ask for the service worker (`/sw.js`, which never answers `/api/`),
 * and hold the menu's Sign out until the person knows what it deletes. Other
 * pages' sign-out clears nothing here; the copies go when one of these pages
 * next sees, online, that nobody is signed in. `docs/offline.md` S5 (D8, D10).
 */

/** The cache the worker keeps pages in; `sync/worker.js` names the same. */
export const PAGES_CACHE = "luffy-pages";

/** Ask for the worker. Resolves to its registration, or null. */
export async function registerWorker({ navigator = globalThis.navigator } = {}) {
  if (!navigator || !navigator.serviceWorker) return null;
  try {
    return await navigator.serviceWorker.register("/sw.js", { scope: "/" });
  } catch (error) {
    console.error("This browser did not start the offline worker.", error);
    return null;
  }
}

/** Forget the worker's copies of the pages (they hold the signed-in menu). */
export async function forgetPages({ caches = globalThis.caches } = {}) {
  if (!caches) return;
  try {
    await caches.delete(PAGES_CACHE);
  } catch (error) {
    console.error("The cached pages could not be cleared.", error);
  }
}

/** What the warning says. */
export function leavingNote(waiting) {
  const marks = waiting === 1 ? "1 mark or register" : `${waiting} marks or registers`;
  return (
    `${marks} on this phone ${waiting === 1 ? "has" : "have"} not been sent yet. ` +
    "Signing out deletes them. Sign out anyway?"
  );
}

/**
 * Hold the Sign out form until the person has been told what it costs.
 * `waiting()` counts the marks on the phone (held ones too), `clear()` forgets
 * everything, `confirmFn` is asked only when something is waiting. `form.submit()`
 * raises no `submit` event, so this does not meet itself.
 */
export function guardSignOut(target, { waiting, clear, confirmFn }) {
  if (!target) return;
  target.addEventListener(
    "submit",
    async (event) => {
      const form = event.target;
      if (!isSignOut(form)) return;
      event.preventDefault();

      let count = 0;
      try {
        count = await waiting();
      } catch {
        // The phone could not say. Signing out must not depend on it.
      }
      if (count > 0 && !confirmFn(leavingNote(count))) return;
      try {
        await clear();
      } catch (error) {
        console.error("What this phone kept could not be cleared.", error);
      }
      form.submit();
    },
    true,
  );
}

const isSignOut = (form) => Boolean(form) && /\/sign-out\/$/.test(String(form.action));
