/**
 * Just enough element to drive a `mount()`, and deliberately no more.
 *
 * Not a DOM library. The premise of these pages is ES modules with no build
 * step and no dependencies, and `package.json` says so in as many words — a
 * `jsdom` in devDependencies to test four event handlers would cost that
 * premise for every future reader. What `mount()` actually touches is
 * `innerHTML`, `dataset` and `addEventListener`, so those three are what this
 * has.
 *
 * The stub is shared rather than repeated per test file, because the thing it
 * is standing in for — event delegation from the page root — is the same
 * mechanism on all four pages. A copy each would be four stubs to keep in step
 * with one handler shape.
 */

/**
 * The target of a synthetic event: an object that answers `closest()` the way
 * a real element would for the selectors these handlers use.
 *
 * Only attribute selectors, because that is all the handlers pass:
 * `[data-action="sign-out"]`, `[data-guardian]`, and comma-separated unions of
 * the two. Anything else returns null rather than guessing, so a handler that
 * grows a class or tag selector fails loudly here instead of silently matching
 * nothing.
 */
export function fakeTarget(attributes = {}) {
  const dataset = {};
  for (const [name, value] of Object.entries(attributes)) {
    dataset[camel(name.replace(/^data-/, ""))] = value;
  }
  const self = {
    dataset,
    closest(selector) {
      const matched = selector
        .split(",")
        .map((part) => part.trim())
        .some((part) => matches(attributes, part));
      return matched ? self : null;
    },
  };
  return self;
}

function matches(attributes, selector) {
  const exact = /^\[([-\w]+)="([^"]*)"\]$/.exec(selector);
  if (exact) return attributes[exact[1]] === exact[2];
  const bare = /^\[([-\w]+)\]$/.exec(selector);
  if (bare) return attributes[bare[1]] !== undefined;
  throw new Error(`fakeTarget cannot answer the selector ${selector}`);
}

function camel(name) {
  return name.replace(/-([a-z])/g, (_, c) => c.toUpperCase());
}

/**
 * A page root. `dataset` seeds the `data-` attributes the server renders in.
 *
 * `click()` and `submit()` await every handler, because all of them are async
 * — a POST and a redraw — and a test that did not await would assert against
 * the page as it was before the answer came back.
 */
export function fakeRoot(dataset = {}) {
  const listeners = {};
  //: Fields the page would find with `querySelector`, keyed by the attribute
  //: selector that finds them. `type()` seeds this, because a handler reading
  //: `root.querySelector('[data-author="x"]').value` is reading something the
  //: user typed — and a stub with no way to type can only test the paths where
  //: nobody did.
  const fields = {};
  const root = {
    dataset: { ...dataset },
    innerHTML: "",
    addEventListener(type, handler) {
      (listeners[type] = listeners[type] || []).push(handler);
    },
    /** Put a value in the box the page will look for. No event; just state. */
    type(selector, value) {
      fields[selector] = { value, dataset: {} };
      return root;
    },
    querySelector(selector) {
      return fields[selector] || null;
    },
    /**
     * A field whose value was committed — a select being chosen, a checkbox
     * toggled. Distinct from `blur()`: `change` bubbles, so the page listens
     * for it without capture, and a stub that fired one as the other would
     * exercise a listener the browser would not call.
     */
    async change(attributes = {}, value = "") {
      const target = fakeTarget(attributes);
      target.value = value;
      for (const handler of listeners.change || []) await handler({ target });
    },
    async click(attributes = { "data-action": "sign-out" }) {
      const target = fakeTarget(attributes);
      for (const handler of listeners.click || []) await handler({ target });
    },
    /**
     * A field losing focus, which on the marking page **is** the save.
     *
     * Capture-phase, because `blur` does not bubble: `app.js` listens on the
     * root with `capture: true`, and a stub that dispatched it like a click
     * would test a listener the browser would never call. The handler is
     * awaited for the same reason `click()` awaits — the save is a request and
     * a redraw, and a test that did not await would assert against the page as
     * it was before the answer came back.
     */
    async blur(attributes = {}, value = "") {
      const target = fakeTarget(attributes);
      target.value = value;
      for (const handler of listeners.blur || []) await handler({ target });
    },
    async submit(formFields = {}) {
      const form = {};
      for (const [name, value] of Object.entries(formFields)) form[name] = { value };
      let prevented = false;
      for (const handler of listeners.submit || []) {
        await handler({ target: form, preventDefault: () => (prevented = true) });
      }
      return prevented;
    },
  };
  return root;
}
