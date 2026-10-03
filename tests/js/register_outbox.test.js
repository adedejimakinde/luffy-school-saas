/**
 * The register page with its outbox (slice S6): a register taken with no
 * connection is kept on the phone and sent later with its base; the school
 * merges it child by child (D4); a child two people answered differently comes
 * back for the teacher to decide (D5); and nothing is sent anywhere but the
 * school, or under anybody but the person, that queued it (D7, D8).
 *
 * Every story runs at two schools, each with its own fake server
 * (`fake_register_school.js`), and the phone's outbox shelf is shared between
 * them, so a key that did not name the host would be the first thing it shows.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { mount } from "../../static/register/app.js";
import { HELD, REPORT, enqueue, keepTheirs, registerId, settle, useMine, dismiss } from "../../static/register/outbox.js";
import { forgetToken } from "../../static/web/http.js";
import { memoryStore, outboxesOf } from "../../static/web/store.js";
import { fakeRoot } from "./fake_dom.js";
import { DAY, GRACE, KEMI, ST_MARYS, TUNDE, registerSchool } from "./fake_register_school.js";

const schools = () => [
  registerSchool(ST_MARYS, { names: ["Ada Obi", "Emeka Nwosu", "Bisi Ade"] }),
  registerSchool(GRACE, { names: ["Funmi Bello", "Gbenga Eze"] }),
];
const MORNING = new Date(`${DAY}T07:30:00Z`);

function keys() {
  let n = 0;
  return () => `key-${++n}`;
}

async function open(server, shelf, { classOpen = true, confirmFn = () => true } = {}) {
  forgetToken();
  const root = fakeRoot({ timeZone: "Africa/Lagos" });
  const online = [];
  const timers = [];
  const submitted = [];
  let guard = null;
  await mount(root, {
    fetchImpl: (url, options) => server.fetch(url, options),
    now: MORNING,
    host: server.host,
    openStore: async (name) => memoryStore(name, shelf),
    openSnapshots: async () => null,
    whenOnline: (run) => online.push(run),
    schedule: (run, ms) => timers.push({ run, ms }),
    signOutTarget: { addEventListener: (type, handler) => (guard = handler) },
    confirmFn,
    clearPages: async () => {},
    mint: keys(),
  });
  if (classOpen) await root.click({ "data-action": "open", "data-class": "11" });
  const signOut = async () => {
    const form = { action: "/sign-out/", submit: () => submitted.push(1) };
    await guard({ target: form, preventDefault() {} });
    return submitted.length;
  };
  return { root, online, timers, signOut };
}

const onThePhone = (shelf, host, owner = KEMI) => shelf.get(outboxesOf(host, owner)[1]) || [];

// -- online it is the same thirty seconds -------------------------------------

test("online, a submit lands at once with the base the screen showed", async () => {
  for (const server of schools()) {
    const shelf = new Map();
    server.office({ 1: "present", 2: "present" });
    const page = await open(server, shelf);
    await page.root.click({ "data-action": "toggle", "data-child": "2" });
    await page.root.click({ "data-action": "submit" });

    assert.match(page.root.innerHTML, /Register taken/, server.host);
    const [put] = server.puts;
    assert.deepEqual(put.base, { absent_ids: [], present_ids: [1, 2] }, server.host);
    assert.equal(server.marks.get(2).status, "absent", server.host);
    assert.deepEqual(onThePhone(shelf, server.host), [], `${server.host}: nothing left on the phone`);
  }
});

// -- requirement 3: nothing the teacher did not touch is written ---------------

test("a register taken offline and sent a day late leaves the office's correction alone", async () => {
  for (const server of schools()) {
    const shelf = new Map();
    server.office({ 1: "present", 2: "present" });
    server.offline = true;
    // The roster had to come from somewhere offline: the phone opened it online.
    server.offline = false;
    const page = await open(server, shelf);
    server.offline = true;
    await page.root.click({ "data-action": "toggle", "data-child": "1" });
    await page.root.click({ "data-action": "submit" });
    assert.match(page.root.innerHTML, /Kept on this phone/, server.host);
    assert.equal(server.puts.length, 0, server.host);

    // Meanwhile the office marks the second child absent.
    server.office({ 2: "absent" }, "2025-09-17T09:12:00Z");
    server.offline = false;
    await page.online[0]();

    assert.equal(server.marks.get(1).status, "absent", `${server.host}: the teacher's change`);
    assert.equal(server.marks.get(2).status, "absent", `${server.host}: the office's correction stands`);
    assert.deepEqual(onThePhone(shelf, server.host), [], server.host);
  }
});

// -- requirement 2 and D5: a conflict is the teacher's to decide ---------------

async function aConflict(server, shelf) {
  // 8am: nobody has taken it. The teacher marks the first child absent, offline.
  const page = await open(server, shelf);
  server.offline = true;
  await page.root.click({ "data-action": "toggle", "data-child": "1" });
  await page.root.click({ "data-action": "submit" });
  // 10:12: the office takes it, everybody present.
  server.office({ 1: "present", 2: "present" }, "2025-09-17T09:12:00Z");
  server.offline = false;
  await page.online[0]();
  await page.root.click({ "data-action": "back" });
  return page;
}

test("a child both answered is shown with both answers, and nothing is written for them", async () => {
  for (const server of schools()) {
    const shelf = new Map();
    const page = await aConflict(server, shelf);
    const name = server.names[0];

    assert.match(page.root.innerHTML, new RegExp(`You marked ${name} absent; the school has them present, marked today 10:12`), server.host);
    assert.match(page.root.innerHTML, /Keep the school's/, server.host);
    assert.equal(server.marks.get(1).status, "present", `${server.host}: the school's answer stands`);
    assert.equal(onThePhone(shelf, server.host)[0].held.kind, REPORT, server.host);
  }
});

test("the conflict survives a reload until the teacher answers it", async () => {
  for (const server of schools()) {
    const shelf = new Map();
    await aConflict(server, shelf);
    const again = await open(server, shelf, { classOpen: false });
    assert.match(again.root.innerHTML, /You marked .* absent; the school has them present/, server.host);
  }
});

test("keeping the school's answer clears it and sends nothing", async () => {
  for (const server of schools()) {
    const shelf = new Map();
    const page = await aConflict(server, shelf);
    const sent = server.puts.length;

    await page.root.click({ "data-action": "keep-theirs", "data-entry": registerId(11, 7, DAY), "data-child": "1" });

    assert.equal(server.puts.length, sent, server.host);
    assert.equal(server.marks.get(1).status, "present", server.host);
    assert.deepEqual(onThePhone(shelf, server.host), [], server.host);
  }
});

test("using the teacher's answer writes it over the school's, for that child alone", async () => {
  for (const server of schools()) {
    const shelf = new Map();
    const page = await aConflict(server, shelf);

    await page.root.click({ "data-action": "use-mine", "data-entry": registerId(11, 7, DAY), "data-child": "1" });

    assert.equal(server.marks.get(1).status, "absent", server.host);
    assert.equal(server.marks.get(2).status, "present", `${server.host}: the other child untouched`);
    const last = server.puts.at(-1);
    assert.deepEqual(last.shown_ids, [1], server.host);
    assert.deepEqual(last.base, { absent_ids: [], present_ids: [1] }, `${server.host}: based on the school's answer`);
    assert.deepEqual(onThePhone(shelf, server.host), [], server.host);
  }
});

// -- requirement 1: a resend lands once ---------------------------------------

test("a register whose answer was lost is sent again with the same key", async () => {
  for (const server of schools()) {
    const shelf = new Map();
    server.office({ 1: "present", 2: "present" });
    const page = await open(server, shelf);
    await page.root.click({ "data-action": "toggle", "data-child": "1" });
    server.loseNextAnswer = true;
    await page.root.click({ "data-action": "submit" });
    assert.match(page.root.innerHTML, /Kept on this phone/, server.host);

    // 10am, between the two attempts: the office puts the first child back.
    server.office({ 1: "present" });
    await page.online[0]();

    assert.equal(server.puts.length, 2, server.host);
    assert.equal(server.puts[0].key, server.puts[1].key, `${server.host}: the same key`);
    assert.equal(server.marks.get(1).status, "present", `${server.host}: answered from the receipt, not applied again`);
  }
});

// -- requirement 8: a refusal is kept until dismissed ---------------------------

test("a refused register is kept, said, and offered again until it is dismissed", async () => {
  for (const server of schools()) {
    const shelf = new Map();
    const page = await open(server, shelf);
    server.refuseWith = [422, "2025-09-17 is not inside 2025/2026 First term."];
    await page.root.click({ "data-action": "submit" });
    assert.match(page.root.innerHTML, /not inside/, server.host);

    const again = await open(server, shelf, { classOpen: false });
    assert.match(again.root.innerHTML, /not sent\. 2025-09-17 is not inside/, server.host);
    assert.equal(onThePhone(shelf, server.host)[0].held.kind, HELD.INVALID, server.host);

    await again.root.click({ "data-action": "dismiss", "data-entry": registerId(11, 7, DAY) });
    assert.deepEqual(onThePhone(shelf, server.host), [], server.host);
  }
});

// -- requirements 5 and 6: whose, and where --------------------------------------

test("a register queued by Kemi is never sent under Tunde's session", async () => {
  for (const server of schools()) {
    const shelf = new Map();
    const page = await open(server, shelf);
    server.offline = true;
    await page.root.click({ "data-action": "submit" });

    server.offline = false;
    server.signedIn = TUNDE;
    await page.online[0]();

    assert.equal(server.puts.length, 0, server.host);
    assert.equal(onThePhone(shelf, server.host).length, 1, `${server.host}: still Kemi's`);

    server.signedIn = KEMI;
    await page.online[0]();
    assert.deepEqual(server.puts.map((p) => p.as), [KEMI], server.host);
  }
});

test("two schools: each queued register goes to its own school and no other", async () => {
  const [marys, grace] = schools();
  const shelf = new Map();
  const atMarys = await open(marys, shelf);
  const atGrace = await open(grace, shelf);
  marys.offline = true;
  grace.offline = true;
  await atMarys.root.click({ "data-action": "toggle", "data-child": "3" });
  await atMarys.root.click({ "data-action": "submit" });
  await atGrace.root.click({ "data-action": "toggle", "data-child": "2" });
  await atGrace.root.click({ "data-action": "submit" });

  marys.offline = false;
  grace.offline = false;
  await atMarys.online[0]();
  await atGrace.online[0]();

  assert.deepEqual(marys.puts.map((p) => p.absent_ids), [[3]]);
  assert.deepEqual(grace.puts.map((p) => p.absent_ids), [[2]]);
});

// -- sign-out (D8) ---------------------------------------------------------------

test("signing out with a register waiting asks, and keeps it if the teacher says no", async () => {
  for (const server of schools()) {
    const shelf = new Map();
    const page = await open(server, shelf);
    server.offline = true;
    await page.root.click({ "data-action": "submit" });
    // A mark is waiting too: sign-out counts every outbox this person has here.
    await memoryStore(outboxesOf(server.host, KEMI)[0], shelf).write([{ cell: "3:1" }]);
    // Back online, and the school's server failing: the register stays queued.
    server.offline = false;
    server.refuseWith = [503, "Down."];

    const said = [];
    const declined = await open(server, shelf, { classOpen: false, confirmFn: (t) => (said.push(t), false) });
    assert.equal(await declined.signOut(), 0, server.host);
    assert.match(said[0], /^2 marks or registers on this phone/, server.host);
    assert.equal(onThePhone(shelf, server.host).length, 1, server.host);

    server.refuseWith = [503, "Down."];
    const agreed = await open(server, shelf, { classOpen: false });
    assert.equal(await agreed.signOut(), 1, server.host);
    assert.deepEqual(onThePhone(shelf, server.host), [], server.host);
    assert.deepEqual(shelf.get(outboxesOf(server.host, KEMI)[0]), [], `${server.host}: the marks too`);
  }
});

// -- the queue's own rules ---------------------------------------------------------

const write = (absentIds, base = { absent_ids: [], present_ids: [1, 2] }) => ({
  classGroupId: 11, termId: 7, on: DAY, absentIds, shownIds: [1, 2], base,
});

test("taking a register again before it is sent keeps the first base (D2)", () => {
  const first = enqueue([], write([1]), { mint: keys() });
  const again = enqueue(first, write([2], { absent_ids: [2], present_ids: [1] }), { mint: () => "k2" });
  assert.equal(again.length, 1);
  assert.deepEqual(again[0].absentIds, [2]);
  assert.deepEqual(again[0].base, { absent_ids: [], present_ids: [1, 2] });
  assert.equal(again[0].key, "k2");
});

test("a retake waiting behind a conflict keeps the conflict's base, so it comes back", () => {
  let entries = enqueue([], write([1], { absent_ids: [], present_ids: [] }), { mint: keys() });
  entries = entries.map((e) => ({ ...e, sent: true, next: [1, 2] }));
  entries = settle(entries, registerId(11, 7, DAY), {
    landed: true,
    taken: { conflicts: [{ student_membership_id: 1, yours: "absent", was: null, now: "present" }], appeared: [], not_on_the_roster: [] },
  }, { mint: () => "k9" });

  assert.deepEqual(entries[0].absentIds, [1, 2]);
  assert.deepEqual(entries[0].base, { absent_ids: [], present_ids: [2] }, "child 1 keeps its original, unmarked, base");
});

test("a report with a conflict left cannot be dismissed; answered, it goes", () => {
  const id = registerId(11, 7, DAY);
  let entries = [{ ...enqueue([], write([1]))[0], held: { kind: REPORT, conflicts: [{ student_membership_id: 1, yours: "absent", was: "present", now: null }], appeared: [], notOnTheRoster: [] } }];
  assert.equal(dismiss(entries, id).length, 1);
  assert.deepEqual(keepTheirs(entries, id, 1), []);
  const mine = useMine(entries, id, 1, { mint: () => "k" });
  assert.equal(mine.length, 1);
  assert.deepEqual(mine[0].base, { absent_ids: [], present_ids: [] }, "the school had no mark, so the base is unmarked");
});
