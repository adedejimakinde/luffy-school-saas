/**
 * A phone two people sign in to (slice S7, `docs/offline.md` D7's second
 * paragraph and A2).
 *
 * Kemi queues work and leaves it. Tunde signs in on the same phone. His page
 * must not send her work under his name, must say it is there ("Held for Kemi
 * Bello: 2 not sent yet. Sign in as Kemi Bello to send them."), and must not
 * show what it is. When Kemi signs in again it goes, and only then. What Kemi
 * was shown goes from the phone when Tunde opens it online.
 *
 * Every story runs on both pages and at two schools, on one shared phone: one
 * outbox shelf and one snapshot shelf for both schools, as a browser's one
 * database would be per origin but a key without the host would show.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { mount as markingMount } from "../../static/marking/app.js";
import { mount as registerMount } from "../../static/register/app.js";
import { memoryStore, heldElsewhere, outboxesOf } from "../../static/web/store.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";
import { GRACE, KEMI, ST_MARYS, TUNDE, school } from "./fake_school.js";
import { registerSchool } from "./fake_register_school.js";
import { memorySnapshots } from "./memory_snapshots.js";

const NOW = Date.parse("2025-09-17T07:30:00Z");
const keys = () => {
  let n = 0;
  return () => `k${++n}`;
};
const phone = () => ({ outbox: new Map(), snapshots: memorySnapshots(new Map()) });

async function openMarking(server, p) {
  forgetToken();
  const root = fakeRoot({ timeZone: "Africa/Lagos" });
  const online = [];
  await markingMount(root, {
    fetchImpl: (u, o) => server.fetch(u, o),
    host: server.host,
    openStore: async (name) => memoryStore(name, p.outbox),
    openSnapshots: async () => p.snapshots,
    schedule: () => {},
    whenOnline: (run) => online.push(run),
    signOutTarget: null,
    mint: keys(),
    now: () => NOW,
  });
  return { root, online };
}

async function openRegister(server, p) {
  forgetToken();
  const root = fakeRoot({ timeZone: "Africa/Lagos" });
  const online = [];
  await registerMount(root, {
    fetchImpl: (u, o) => server.fetch(u, o),
    host: server.host,
    now: new Date(NOW),
    openStore: async (name) => memoryStore(name, p.outbox),
    openSnapshots: async () => p.snapshots,
    schedule: () => {},
    whenOnline: (run) => online.push(run),
    signOutTarget: null,
    mint: keys(),
  });
  return { root, online };
}

const markers = (host) => school(host, { marks: {}, roster: [{ id: 1, name: "Ada Obi" }, { id: 2, name: "Emeka Nwosu" }] });
const registers = (host) => registerSchool(host, { names: ["Ada Obi", "Emeka Nwosu"] });

const PAGES = [
  {
    name: "marking",
    make: markers,
    open: openMarking,
    // Kemi leaves two marks unsent.
    async leave(server, p) {
      const page = await openMarking(server, p);
      await page.root.click({ "data-action": "pick-assessment", "data-assessment": "3" });
      await page.root.click({ "data-action": "pick-class", "data-class": "11" });
      server.offline = true;
      await page.root.blur({ "data-child": "1", "data-version": "" }, "13");
      await page.root.blur({ "data-child": "2", "data-version": "" }, "15");
      server.offline = false;
    },
    sent: (server) => server.puts.length,
  },
  {
    name: "register",
    make: registers,
    open: openRegister,
    // Kemi leaves a register unsent (and nothing else).
    async leave(server, p) {
      const page = await openRegister(server, p);
      await page.root.click({ "data-action": "open", "data-class": "11" });
      server.offline = true;
      await page.root.click({ "data-action": "toggle", "data-child": "1" });
      await page.root.click({ "data-action": "submit" });
      server.offline = false;
    },
    sent: (server) => server.puts.length,
  },
];

for (const page of PAGES) {
  test(`${page.name}: Tunde is told whose work is held, and sees nothing of it`, async () => {
    for (const host of [ST_MARYS, GRACE]) {
      const server = page.make(host);
      const p = phone();
      await page.leave(server, p);
      server.signedIn = TUNDE;

      const tunde = await page.open(server, p);

      assert.match(tunde.root.innerHTML, /Held for Kemi Bello: \d+ not sent yet\. Sign in as Kemi Bello to send/, host);
      assert.doesNotMatch(tunde.root.innerHTML, /Ada Obi|Emeka Nwosu|>13<|value="1[35]"|Not sent yet\./, `${host}: nothing of it is shown`);
      assert.equal(page.sent(server), 0, `${host}: and nothing was sent under his name`);
    }
  });

  test(`${page.name}: it goes when Kemi signs in again, and only then`, async () => {
    for (const host of [ST_MARYS, GRACE]) {
      const server = page.make(host);
      const p = phone();
      await page.leave(server, p);

      server.signedIn = TUNDE;
      const tunde = await page.open(server, p);
      await tunde.online[0]();
      assert.equal(page.sent(server), 0, `${host}: still held while Tunde is signed in`);

      server.signedIn = KEMI;
      const kemi = await page.open(server, p);
      await kemi.online[0]();

      assert.ok(page.sent(server) > 0, `${host}: sent`);
      assert.doesNotMatch(kemi.root.innerHTML, /Held for/, `${host}: Kemi sees no line about herself`);
      const after = await heldElsewhere(async (n) => memoryStore(n, p.outbox), host, TUNDE);
      assert.deepEqual(after, [], `${host}: and nothing is held any more`);
    }
  });

  test(`${page.name}: what is held at one school is not said at the other`, async () => {
    const marys = page.make(ST_MARYS);
    const grace = page.make(GRACE);
    const p = phone();
    await page.leave(marys, p);
    grace.signedIn = TUNDE;

    const atGrace = await page.open(grace, p);

    assert.doesNotMatch(atGrace.root.innerHTML, /Held for/);
  });
}

test("every write under Kemi's outbox is made as Kemi", async () => {
  for (const host of [ST_MARYS, GRACE]) {
    const server = registers(host);
    const p = phone();
    await PAGES[1].leave(server, p);
    server.signedIn = TUNDE;
    await (await openRegister(server, p)).online[0]();
    server.signedIn = KEMI;
    await (await openRegister(server, p)).online[0]();
    assert.deepEqual(server.puts.map((put) => put.as), [KEMI], host);
  }
});

test("Tunde's own work is not reported to him as held for somebody else", async () => {
  const server = registers(ST_MARYS);
  const p = phone();
  server.signedIn = TUNDE;
  await PAGES[1].leave(server, p);
  const again = await openRegister(server, p);
  assert.doesNotMatch(again.root.innerHTML, /Held for/);
  assert.equal((await heldElsewhere(async (n) => memoryStore(n, p.outbox), ST_MARYS, TUNDE)).length, 0);
  assert.equal(outboxesOf(ST_MARYS, TUNDE).length, 2);
});

test("what Kemi was shown is gone from the phone once Tunde opens it online", async () => {
  for (const page of PAGES) {
    for (const host of [ST_MARYS, GRACE]) {
      const server = page.make(host);
      const p = phone();
      await page.leave(server, p);
      assert.notEqual(await p.snapshots.copy(host, KEMI, "where"), null, `${page.name} ${host}: Kemi's copy`);

      server.signedIn = TUNDE;
      await page.open(server, p);

      assert.equal(await p.snapshots.copy(host, KEMI, "where"), null, `${page.name} ${host}: gone`);
      assert.notEqual(await p.snapshots.copy(host, TUNDE, "where"), null, `${page.name} ${host}: his own`);
    }
  }
});

test("a phone that cannot be read for the line still opens the page", async () => {
  const server = registers(ST_MARYS);
  const root = fakeRoot({});
  await registerMount(root, {
    fetchImpl: (u, o) => server.fetch(u, o),
    host: ST_MARYS,
    now: new Date(NOW),
    openStore: async () => ({ read: async () => [], write: async () => {}, names: async () => { throw new Error("closed"); } }),
    openSnapshots: async () => null,
    whenOnline: () => {},
    signOutTarget: null,
  });
  assert.match(root.innerHTML, /JSS 1A/);
});
