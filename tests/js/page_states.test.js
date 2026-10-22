/**
 * What every data page says when it cannot draw, what it shows while it waits,
 * and how Back works on the pages that swap views in place.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { brokenState, skeleton } from "../../static/web/html.js";
import { connectionDropped, getJson } from "../../static/web/http.js";
import { broken as fees } from "../../static/fees/states.js";
import { broken as marking } from "../../static/marking/states.js";
import { broken as signIn } from "../../static/signin/states.js";
import { followBack } from "../../static/web/trail.js";

test("a request that never arrived says the connection dropped, not that it was our side", async () => {
  await assert.rejects(getJson("/api/x/", { fetchImpl: async () => { throw new TypeError("Failed to fetch"); } }));
  assert.equal(connectionDropped(), true);

  const html = fees();
  assert.match(html, /Your connection dropped/);
  assert.match(html, /data-cause="connection"/);
  assert.doesNotMatch(html, /on our side/);
  assert.match(html, /data-action="reload"/);
});

test("an answer, even a 500, is a fault on our side and says so", async () => {
  await getJson("/api/x/", { fetchImpl: async () => ({ status: 500, json: async () => ({}) }) });
  assert.equal(connectionDropped(), false);

  const html = fees();
  assert.match(html, /This page is not working/);
  assert.match(html, /Something went wrong on our side/);
  assert.match(html, /tell whoever runs this system for your school/);
  assert.doesNotMatch(html, /connection dropped/);
  assert.match(html, /<button type="button" data-action="reload">Try again<\/button>/);
});

test("every page's broken state has Try again, and the pages keep their own words", () => {
  assert.match(marking(), /tell your school if it keeps happening/);
  assert.match(brokenState(false, "", { extra: "Nothing was saved. " }), /Nothing was saved\. Please try again in a few minutes\./);
  // The doors keep Start again, in their own markup.
  assert.match(signIn(), /data-action="restart"/);
  assert.match(signIn(), /Sign-in is not working/);
});

test("a loading page is the grey bars, read out as what it is loading", () => {
  const html = skeleton("Loading your school");
  assert.match(html, /class="skeleton state-loading" role="status"/);
  assert.match(html, /<span class="sr">Loading your school&hellip;<\/span>/);
  assert.equal((html.match(/<i><\/i>/g) || []).length, 4);
  assert.match(skeleton("<b>"), /&lt;b&gt;/);
});

/** A window with a history, enough for `followBack()`. */
function fakeWindow() {
  const listeners = [];
  const stack = [{ depth: 0 }];
  let at = 0;
  const fire = () => listeners.forEach((fn) => fn({ state: stack[at] }));
  globalThis.addEventListener = (type, fn) => type === "popstate" && listeners.push(fn);
  globalThis.history = {
    pushState: (state) => { stack.splice(at + 1); stack.push(state); at = stack.length - 1; },
    go: (n) => { at = Math.max(0, Math.min(stack.length - 1, at + n)); fire(); },
    back: () => globalThis.history.go(-1),
    get state() { return stack[at]; },
  };
  return { stack, at: () => at };
}

test("a view that is up from the list gets a history entry, and Back presses its way up", () => {
  const win = fakeWindow();
  let up = null;
  let level = 0;
  const root = { querySelector: () => (level ? up : null) };
  up = { dataset: { up: "1" }, click: () => { level = 0; follow(); } };
  const follow = followBack(root);

  level = 1; follow();
  assert.equal(win.at(), 1);

  globalThis.history.back();  // the phone's Back key
  assert.equal(level, 0, "Back took the page up one view");
  assert.equal(win.at(), 0, "and left the page where it was");
});

test("the on-screen way up takes the extra history entry with it", () => {
  const win = fakeWindow();
  let level = 0;
  const root = { querySelector: () => (level ? { dataset: { up: String(level) } } : null) };
  const follow = followBack(root);

  level = 2; follow();
  assert.equal(win.at(), 2, "two levels, two entries");
  level = 1; follow();
  assert.equal(win.at(), 1);
  level = 0; follow();
  assert.equal(win.at(), 0);
});

test("without a window there is nothing to follow", () => {
  delete globalThis.history;
  delete globalThis.addEventListener;
  assert.equal(typeof followBack({}), "function");
});
