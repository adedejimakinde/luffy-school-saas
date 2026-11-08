/**
 * The installed app's page script (`static/web/portal-app.js`, `docs/pwa.md`) against a fake
 * window: the worker it asks for, the Install app button on Android and on an iPhone, and
 * what it never does.
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { mount } from "../../static/web/portal-app.js";

/** A window with the elements the shell draws, and a service worker that records what is asked. */
function page({ userAgent = "Mozilla/5.0 (Linux; Android 14) Chrome/130", platform = "Linux armv8l", standalone = false, displayStandalone = false, menu = true, workers = true } = {}) {
  const asked = { register: [], messages: [] };
  const attributes = {};
  const element = (hidden) => ({ hidden, listeners: {}, addEventListener(type, fn) { this.listeners[type] = fn; }, setAttribute(k, v) { attributes[k] = v; } });
  const box = element(true);
  const button = element(false);
  const howto = element(true);
  const listeners = {};
  const registration = { active: { postMessage: (m) => asked.messages.push(m) } };
  // No `getRegistrations`, no `unregister`: the exam's registration is out of this script's reach.
  const serviceWorker = {
    register: async (url, options) => (asked.register.push([url, options]), registration),
    ready: Promise.resolve(registration),
  };
  const win = {
    navigator: { userAgent, platform, maxTouchPoints: 0, standalone, ...(workers ? { serviceWorker } : {}) },
    matchMedia: (q) => ({ matches: displayStandalone && q === "(display-mode: standalone)" }),
    addEventListener: (type, fn) => (listeners[type] = fn),
  };
  const doc = { getElementById: (id) => (menu ? { install: box, "install-app": button, "install-howto": howto }[id] : null) };
  return { win, doc, box, button, howto, listeners, asked, attributes };
}

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

test("it asks for the portal's worker over the whole host, and for the shell again", async () => {
  const p = page();
  mount(p.win, p.doc);
  await settle();

  assert.deepEqual(p.asked.register, [["/sw.js", { scope: "/" }]]);
  assert.deepEqual(p.asked.messages, [{ type: "prime" }]);
});

test("it never asks for the exam's scope and cannot list or remove a worker", () => {
  const p = page();
  mount(p.win, p.doc);

  for (const [url, options] of p.asked.register) {
    assert.ok(!url.startsWith("/sit/") && options.scope === "/", url);
  }
  assert.equal(p.win.navigator.serviceWorker.getRegistrations, undefined);
  assert.equal(p.win.navigator.serviceWorker.getRegistration, undefined);
});

test("Android: the button stays hidden until the browser says the app can be installed, then asks it", async () => {
  const p = page();
  mount(p.win, p.doc);
  assert.equal(p.box.hidden, true);

  let prompted = 0;
  let prevented = false;
  p.listeners.beforeinstallprompt({ preventDefault: () => (prevented = true), prompt: () => prompted++ });
  assert.ok(prevented, "the browser's own banner is held back");
  assert.equal(p.box.hidden, false);

  p.button.listeners.click();
  assert.equal(prompted, 1);
  assert.equal(p.box.hidden, true, "asked once");
  assert.equal(p.howto.hidden, true, "no how-to on Android");
});

test("Android: once installed the button goes", () => {
  const p = page();
  mount(p.win, p.doc);
  p.listeners.beforeinstallprompt({ preventDefault() {}, prompt() {} });
  p.listeners.appinstalled();
  assert.equal(p.box.hidden, true);
});

test("iPhone: the button is there at once and opens a how-to, Share then Add to Home Screen", () => {
  for (const userAgent of ["Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) Safari/604.1", "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X)"]) {
    const p = page({ userAgent });
    mount(p.win, p.doc);
    assert.equal(p.box.hidden, false, userAgent);

    p.button.listeners.click();
    assert.equal(p.howto.hidden, false);
    assert.equal(p.attributes["aria-expanded"], "true");
    p.button.listeners.click();
    assert.equal(p.howto.hidden, true, "tapped again, it closes");
  }
});

test("an iPad that calls itself a Mac is still an iPad", () => {
  const p = page({ userAgent: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", platform: "MacIntel" });
  p.win.navigator.maxTouchPoints = 5;
  mount(p.win, p.doc);
  assert.equal(p.box.hidden, false);
});

test("a desktop browser that never raises the event never shows the button", () => {
  const p = page({ userAgent: "Mozilla/5.0 (X11; Linux x86_64) Firefox/130", platform: "Linux x86_64" });
  mount(p.win, p.doc);
  assert.equal(p.box.hidden, true);
});

test("opened from the home screen, there is nothing to install", () => {
  for (const options of [{ standalone: true, userAgent: "iPhone" }, { displayStandalone: true }]) {
    const p = page(options);
    mount(p.win, p.doc);
    assert.equal(p.box.hidden, true);
    assert.equal(p.listeners.beforeinstallprompt, undefined, "not even listening");
  }
});

test("a browser with no service workers, or a page without the menu, still runs", () => {
  mount(page({ workers: false }).win, page({ workers: false }).doc);
  const bare = page({ menu: false });
  mount(bare.win, bare.doc);
  assert.deepEqual(bare.asked.register, [["/sw.js", { scope: "/" }]]);
});
