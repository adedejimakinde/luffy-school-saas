/**
 * The marking page with no connection (slice S5): it opens from the copy the
 * phone kept, says that it is a copy, queues what is typed over it, and
 * forgets the copy at sign-out.
 *
 * Every test runs at two schools, each with its own server (`fake_school.js`)
 * and its own roster, and **one snapshot shelf and one outbox shelf are shared
 * between them** — a browser gives each origin its own, so a key that did not
 * name the host would be the one thing a shared shelf shows up.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { mount, sheetName } from "../../static/marking/app.js";
import { memoryStore } from "../../static/web/store.js";
import { forgetToken } from "../../static/web/http.js";
import { memorySnapshots } from "./memory_snapshots.js";
import { fakeRoot } from "./fake_dom.js";
import { GRACE, KEMI, ST_MARYS, TUNDE, school } from "./fake_school.js";

const ROSTERS = {
  [ST_MARYS]: [{ id: 1, name: "Ada Obi" }, { id: 2, name: "Emeka Nwosu" }],
  [GRACE]: [{ id: 1, name: "Funmi Bello" }, { id: 2, name: "Gbenga Eze" }],
};

const servers = () => [
  school(ST_MARYS, { roster: ROSTERS[ST_MARYS], marks: { 2: { value: 12, version: 4, by: TUNDE } } }),
  school(GRACE, { roster: ROSTERS[GRACE], marks: { 2: { value: 8, version: 2, by: TUNDE } } }),
];

const NOON = Date.parse("2025-09-17T11:00:00Z");
const keys = () => {
  let n = 0;
  return () => `key-${++n}`;
};

/** A document with one Sign out form, as the menu draws it. */
function fakeDocument() {
  const listeners = {};
  const form = { action: "https://x.example/sign-out/", submitted: 0, submit() { this.submitted += 1; } };
  return {
    form,
    addEventListener: (type, handler) => (listeners[type] = handler),
    async signOut() {
      let prevented = false;
      await listeners.submit({ target: form, preventDefault: () => (prevented = true) });
      return prevented;
    },
  };
}

/** The marking page at `server.host`; the shelves are the phone's. */
async function open(server, phone, { pick = true, now = NOON, confirmFn = () => true } = {}) {
  forgetToken();
  const root = fakeRoot({ timeZone: "Africa/Lagos" });
  const online = [];
  const timers = [];
  const doc = fakeDocument();
  const cleared = [];
  await mount(root, {
    fetchImpl: (url, options) => server.fetch(url, options),
    host: server.host,
    openStore: async (name) => memoryStore(name, phone.outbox),
    openSnapshots: async () => phone.snapshots,
    schedule: (run, ms) => timers.push({ run, ms }),
    whenOnline: (run) => online.push(run),
    signOutTarget: doc,
    confirmFn,
    clearPages: async () => cleared.push(server.host),
    mint: keys(),
    now: () => now,
  });
  if (pick) {
    await root.click({ "data-action": "pick-assessment", "data-assessment": "3" });
    await root.click({ "data-action": "pick-class", "data-class": "11" });
  }
  return { root, online, timers, doc, cleared };
}

const phone = () => ({ outbox: new Map(), snapshots: memorySnapshots(new Map()) });

test("a page opened online opens again with no connection, from its copy, and says so", async () => {
  for (const server of servers()) {
    const mine = phone();
    const first = await open(server, mine);
    assert.doesNotMatch(first.root.innerHTML, /This is a copy/, `${server.host}: live is not a copy`);

    server.offline = true;
    const later = await open(server, mine, { pick: false, now: NOON + 20 * 3600_000 });
    assert.match(later.root.innerHTML, /This is a copy from yesterday 12:00\. You are not connected\./, server.host);
    assert.match(later.root.innerHTML, /First CA/, `${server.host}: the papers`);

    await later.root.click({ "data-action": "pick-assessment", "data-assessment": "3" });
    await later.root.click({ "data-action": "pick-class", "data-class": "11" });
    assert.match(later.root.innerHTML, /This is a copy from/, `${server.host}: the sheet`);
    for (const { name } of ROSTERS[server.host]) assert.match(later.root.innerHTML, new RegExp(name), server.host);
    assert.match(later.root.innerHTML, /id="mark-2"[^>]*value="(12|8)"/, `${server.host}: the marks it was shown`);
  }
});

test("a mark typed over a copy is queued with the version the copy showed, and goes when the browser is back", async () => {
  for (const server of servers()) {
    const mine = phone();
    await open(server, mine);
    const shown = server.marks.get(2).version;
    server.offline = true;
    const page = await open(server, mine);

    await page.root.blur({ "data-child": "2", "data-version": String(shown) }, "17");

    assert.match(page.root.innerHTML, /Not sent yet/, server.host);
    assert.equal(server.puts.length, 0, `${server.host}: nothing sent`);

    server.offline = false;
    await page.online[0]();

    assert.deepEqual(server.puts.map((p) => [p.id, p.value, p.expected_version]), [[2, 17, shown]], server.host);
    assert.doesNotMatch(page.root.innerHTML, /This is a copy/, `${server.host}: live again`);
    assert.doesNotMatch(page.root.innerHTML, /Not sent yet/, server.host);
  }
});

test("coming back online replaces the copy with what the server says now", async () => {
  for (const server of servers()) {
    const mine = phone();
    await open(server, mine);
    server.offline = true;
    const page = await open(server, mine);
    assert.match(page.root.innerHTML, /This is a copy/, server.host);

    server.marks.set(2, { value: 19, version: 9, by: TUNDE });
    server.offline = false;
    await page.online[0]();

    assert.doesNotMatch(page.root.innerHTML, /This is a copy/, server.host);
    assert.match(page.root.innerHTML, /id="mark-2"[^>]*value="19"/, `${server.host}: somebody else's mark, now`);
  }
});

test("two schools: one school's copy is never drawn at the other's host", async () => {
  const [marys, grace] = servers();
  const shared = phone();
  await open(marys, shared);
  await open(grace, shared);

  marys.offline = true;
  const page = await open(marys, shared);
  assert.match(page.root.innerHTML, /Ada Obi/);
  assert.doesNotMatch(page.root.innerHTML, /Funmi Bello|Gbenga Eze/);

  // A host this phone never opened has nothing to show, whatever else it holds.
  const lonely = phone();
  await open(marys, lonely);
  grace.offline = true;
  const strange = await open(grace, lonely, { pick: false });
  assert.doesNotMatch(strange.root.innerHTML, /Ada Obi|First CA|This is a copy/);
});

test("two people: Tunde never sees the sheet only Kemi opened", async () => {
  for (const server of servers()) {
    const mine = phone();
    await open(server, mine); // Kemi, online, opens the sheet.
    server.signedIn = TUNDE;
    await open(server, mine, { pick: false }); // Tunde, online, opens the list only.

    server.offline = true;
    const page = await open(server, mine, { pick: false });
    assert.match(page.root.innerHTML, /This is a copy/, `${server.host}: his list`);

    await page.root.click({ "data-action": "pick-assessment", "data-assessment": "3" });
    await page.root.click({ "data-action": "pick-class", "data-class": "11" });
    assert.doesNotMatch(page.root.innerHTML, new RegExp(ROSTERS[server.host][0].name), `${server.host}: not Kemi's sheet`);
    assert.doesNotMatch(page.root.innerHTML, /state-sheet/, server.host);
  }
});

test("a refusal is shown, never a copy over it", async () => {
  for (const server of servers()) {
    const mine = phone();
    await open(server, mine);

    server.signedIn = null; // the session lapsed: a 401 that says so
    const lapsed = await open(server, mine, { pick: false });
    assert.match(lapsed.root.innerHTML, /session|sign/i, server.host);
    assert.doesNotMatch(lapsed.root.innerHTML, /This is a copy|First CA/, server.host);

    server.signedIn = KEMI;
    server.markers = [TUNDE]; // her authority was withdrawn: a 403
    const refused = await open(server, mine, { pick: false });
    assert.doesNotMatch(refused.root.innerHTML, /This is a copy|First CA/, server.host);
  }
});

test("a server error stands in as no connection: the copy is shown", async () => {
  for (const server of servers()) {
    const mine = phone();
    await open(server, mine);
    const real = server.fetch;
    server.fetch = async (url, options) =>
      url.startsWith("/api/gradebook/where") ? { status: 503, json: async () => ({}) } : real(url, options);

    const page = await open(server, mine, { pick: false });

    assert.match(page.root.innerHTML, /This is a copy/, server.host);
  }
});

// -- sign-out (D8) --------------------------------------------------------------

test("signing out with nothing waiting clears the copies and the cached pages without asking", async () => {
  for (const server of servers()) {
    const mine = phone();
    const page = await open(server, mine);
    let asked = 0;
    const quiet = await open(server, mine, { confirmFn: () => (asked += 1, true) });

    const prevented = await quiet.doc.signOut();

    assert.equal(prevented, true, `${server.host}: held for a moment`);
    assert.equal(asked, 0, `${server.host}: nothing waiting, nothing to ask`);
    assert.equal(quiet.doc.form.submitted, 1, `${server.host}: and then sent on`);
    assert.deepEqual(quiet.cleared, [server.host], `${server.host}: the cached pages`);
    assert.equal(await mine.snapshots.copy(server.host, KEMI, "where"), null, `${server.host}: the copy`);
    assert.equal(await mine.snapshots.copy(server.host, KEMI, sheetName({ assessmentId: 3, classGroupId: 11 })), null);
    assert.ok(page);
  }
});

test("signing out with marks waiting says how many, and deletes them only if the teacher agrees", async () => {
  for (const server of servers()) {
    const mine = phone();
    await open(server, mine);
    server.offline = true;
    const page = await open(server, mine);
    await page.root.blur({ "data-child": "1", "data-version": "" }, "9");
    await page.root.blur({ "data-child": "2", "data-version": String(server.marks.get(2).version) }, "17");

    const said = [];
    page.doc.form.submitted = 0;
    const declined = await open(server, mine, { confirmFn: (text) => (said.push(text), false) });
    await declined.doc.signOut();
    assert.match(said[0], /2 marks or registers on this phone have not been sent yet\. Signing out deletes them\./, server.host);
    assert.equal(declined.doc.form.submitted, 0, `${server.host}: declined, so still signed in`);
    assert.notEqual(await mine.snapshots.copy(server.host, KEMI, "where"), null, `${server.host}: and nothing cleared`);
    const kept = [...mine.outbox].filter(([n]) => !n.endsWith(" who")).flatMap(([, v]) => v);
    assert.equal(kept.length, 2, `${server.host}: the marks are still on the phone`);

    const agreed = await open(server, mine, { confirmFn: () => true });
    await agreed.doc.signOut();
    assert.equal(agreed.doc.form.submitted, 1, server.host);
    const left = [...mine.outbox].filter(([n]) => !n.endsWith(" who")).flatMap(([, v]) => v);
    assert.equal(left.length, 0, `${server.host}: deleted, as the teacher agreed`);
    assert.equal(await mine.snapshots.copy(server.host, KEMI, "where"), null, server.host);
  }
});

test("signing out at one school leaves the other school's outbox alone", async () => {
  const [marys, grace] = servers();
  const mine = phone();
  await open(marys, mine);
  await open(grace, mine);
  grace.offline = true;
  const graces = await open(grace, mine);
  await graces.root.blur({ "data-child": "1", "data-version": "" }, "9");

  const out = await open(marys, mine);
  await out.doc.signOut();

  const names = [...mine.outbox.keys()].filter((n) => !n.endsWith(" who"));
  const stillThere = names.filter((n) => n.startsWith(GRACE)).flatMap((n) => mine.outbox.get(n));
  assert.equal(stillThere.length, 1, "Grace's mark is still on the phone");
});

test("an answer still on its way when the teacher signs out does not bring a copy back", async () => {
  for (const server of servers()) {
    const mine = phone();
    const page = await open(server, mine);
    // The sheet is asked for again (a resent mark landed, say) and the answer
    // is held up on the wire.
    const real = server.fetch;
    let release;
    server.fetch = (url, options) =>
      url.startsWith("/api/gradebook/assessments") && !release
        ? new Promise((resolve) => {
            release = () => resolve(real(url, options));
          })
        : real(url, options);
    const reopened = page.root.click({ "data-action": "pick-class", "data-class": "11" });
    await new Promise((resolve) => setImmediate(resolve));

    await page.doc.signOut();
    release();
    await reopened;

    assert.equal(await mine.snapshots.copy(server.host, KEMI, "where"), null, `${server.host}: where`);
    assert.equal(await mine.snapshots.copy(server.host, KEMI, sheetName({ assessmentId: 3, classGroupId: 11 })), null, `${server.host}: sheet`);
  }
});

test("a copy never takes a teacher's number off the sheet on screen", async () => {
  for (const server of servers()) {
    const mine = phone();
    const page = await open(server, mine);
    const shown = server.marks.get(2).version;
    // The first attempt lands and its answer is lost, so it is sent again; the
    // sheet is then asked for once more, and the connection drops before it.
    server.loseNextAnswer = true;
    await page.root.blur({ "data-child": "2", "data-version": String(shown) }, "17");
    server.failSheet = true;

    await page.online[0]();

    assert.match(page.root.innerHTML, /id="mark-2"[^>]*value="17"/, `${server.host}: still the teacher's number`);
    assert.doesNotMatch(page.root.innerHTML, /This is a copy/, `${server.host}: not put back to an older sheet`);
  }
});

test("signing out from the marking page counts and clears the registers waiting too (S6)", async () => {
  for (const server of servers()) {
    const mine = phone();
    const registers = `${server.host} ${KEMI} register`;
    mine.outbox.set(registers, [{ id: "11:7:2025-09-17" }]);
    const said = [];
    const page = await open(server, mine, { confirmFn: (text) => (said.push(text), true) });

    await page.doc.signOut();

    assert.match(said[0], /^1 mark or register on this phone/, server.host);
    assert.deepEqual(mine.outbox.get(registers), [], `${server.host}: cleared`);
  }
});
