/**
 * `node:test`'s `test`, `before` and `after`, each with a time limit, so a step
 * that never settles (a `waitFor` that cannot resolve, a dialog left open, a
 * page whose request stays open) fails by name after `TEST_MS` instead of
 * holding the job until its own `timeout-minutes` cancels it with nothing to
 * say about which test it was.
 *
 * `node --test-timeout` is no substitute: it limits a whole file, not a test,
 * and names the file. Every file here imports from this module and not from
 * `node:test`.
 *
 * The slowest test measured is about 25 seconds, on a quiet machine; a CI runner
 * is slower, and 120 seconds is far past both while still ending a hang in two
 * minutes. A hook gets the same: `before` launches Chromium.
 */

import * as nodeTest from "node:test";

export const TEST_MS = 120_000;
export const HOOK_MS = 120_000;

export const describe = nodeTest.describe;
export const test = (name, fn) => nodeTest.test(name, { timeout: TEST_MS }, fn);
export const before = (fn) => nodeTest.before(fn, { timeout: HOOK_MS });
export const after = (fn) => nodeTest.after(fn, { timeout: HOOK_MS });
