/**
 * The marks outbox (`static/marking/outbox.js`), slice S3 of `docs/offline.md`.
 *
 * Two halves. The first walks the pure rules — one entry per cell, a body that
 * is fixed once it has left, which answers hold an entry — because each is a
 * sentence in the design and each is cheap to pin. The second drives
 * `drain()` against a fake of each school's server, and holds the correctness
 * requirements this slice owns: 2, 4, 5, 6 and 8.
 *
 * **Every requirement test runs at two schools.** The fake server is one per
 * host, with its own marks, versions and receipts, and the teacher is signed in
 * at both. An outbox that forgot which host it belonged to would pass every
 * one-school test here and send St Mary's marks to Grace.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  FLAG_AFTER_MS,
  HELD,
  STOPPED,
  cellOf,
  dismiss,
  drain,
  enqueue,
  isOverdue,
  markSent,
  newKey,
  nextToSend,
  openOutbox,
  outboxName,
  release,
  retryDelay,
  settle,
} from "../../static/marking/outbox.js";
import { sendQueued, whoIsSignedIn } from "../../static/marking/api.js";
import { memoryStore } from "../../static/marking/store.js";
import { forgetToken } from "../../static/web/http.js";
import { GRACE, KEMI, ST_MARYS, TUNDE, school } from "./fake_school.js";


function keys() {
  let n = 0;
  return () => `key-${++n}`;
}

const write = (studentMembershipId, value, expectedVersion = null, assessmentId = 3) => ({
  assessmentId,
  studentMembershipId,
  value,
  expectedVersion,
});

// -- one entry per cell (D2) --------------------------------------------------

test("a mark corrected before it was sent is one write, claiming the version first shown", () => {
  const mint = keys();
  let entries = enqueue([], write(1, 15, 4), { mint });
  // The sheet was drawn again since, and shows somebody else's version 5. The
  // 15 was typed over version 4, and the write still claims 4: it is the same
  // decision corrected, and whatever made version 5 is for the server to show.
  entries = enqueue(entries, write(1, 17, 5), { mint });

  assert.equal(entries.length, 1);
  assert.equal(entries[0].value, 17);
  assert.equal(entries[0].expectedVersion, 4);
  // The body changed, so the key did: a key names one write.
  assert.equal(entries[0].key, "key-2");
});

test("two cells are two entries, sent in the order they were typed", () => {
  let entries = enqueue([], write(2, 12), { mint: keys() });
  entries = enqueue(entries, write(1, 9), { mint: keys() });

  assert.deepEqual(entries.map((e) => e.studentMembershipId), [2, 1]);
  assert.equal(nextToSend(entries).studentMembershipId, 2);
});

test("once an attempt has left, its body is fixed and a new value waits", () => {
  const mint = keys();
  let entries = enqueue([], write(1, 15, 4), { mint });
  entries = markSent(entries, cellOf(3, 1));
  entries = enqueue(entries, write(1, 17, 4), { mint });

  assert.equal(entries[0].value, 15);
  assert.equal(entries[0].key, "key-1");
  assert.equal(entries[0].next, 17);
});

test("the value typed while an attempt was out is sent on the version that attempt made", () => {
  const mint = keys();
  let entries = enqueue([], write(1, 15, 4), { mint });
  entries = markSent(entries, cellOf(3, 1));
  entries = enqueue(entries, write(1, 17, 4), { mint });

  entries = settle(entries, cellOf(3, 1), { landed: true, cell: { value: 15, version: 5 } }, { mint });

  assert.equal(entries.length, 1);
  assert.deepEqual(
    { value: entries[0].value, expectedVersion: entries[0].expectedVersion, sent: entries[0].sent, key: entries[0].key },
    { value: 17, expectedVersion: 5, sent: false, key: "key-2" },
  );
});

test("a write that landed with nothing typed since leaves the outbox", () => {
  let entries = enqueue([], write(1, 15, 4), { mint: keys() });
  entries = markSent(entries, cellOf(3, 1));

  assert.deepEqual(settle(entries, cellOf(3, 1), { landed: true, cell: { version: 5 } }), []);
});

test("a failed connection leaves the entry exactly as it went, key and all", () => {
  let entries = enqueue([], write(1, 15, 4), { mint: keys() });
  entries = markSent(entries, cellOf(3, 1));

  assert.equal(settle(entries, cellOf(3, 1), { stop: STOPPED.OFFLINE }), entries);
});

// -- what holds an entry (D6) --------------------------------------------------

for (const kind of [HELD.CONFLICT, HELD.LOCKED, HELD.INVALID, HELD.FORBIDDEN]) {
  test(`an answer of ${kind} holds the entry: kept, and never picked to send again`, () => {
    let entries = enqueue([], write(1, 25, 4), { mint: keys() });
    entries = markSent(entries, cellOf(3, 1));
    entries = settle(entries, cellOf(3, 1), { held: kind, detail: "the server's sentence" });

    assert.equal(entries.length, 1);
    assert.equal(entries[0].value, 25);
    assert.equal(entries[0].held.kind, kind);
    assert.equal(entries[0].held.detail, "the server's sentence");
    assert.equal(nextToSend(entries), null);
  });
}

test("a 422 judged only the number sent, so a number typed since is sent", () => {
  const mint = keys();
  let entries = enqueue([], write(1, 25, 4), { mint });
  entries = markSent(entries, cellOf(3, 1));
  entries = enqueue(entries, write(1, 18, 4), { mint });
  entries = settle(entries, cellOf(3, 1), { held: HELD.INVALID, detail: "25 is more than 20." }, { mint });

  assert.equal(entries[0].held, null);
  assert.equal(entries[0].value, 18);
  assert.equal(entries[0].expectedVersion, 4);
  assert.equal(entries[0].sent, false);
});

test("typing over a held value is a new write, on the version the cell now shows", () => {
  const mint = keys();
  let entries = enqueue([], write(1, 17, 4), { mint });
  entries = markSent(entries, cellOf(3, 1));
  entries = settle(entries, cellOf(3, 1), { held: HELD.CONFLICT, current: { value: 15, version: 5 } });

  entries = enqueue(entries, write(1, 17, 5), { mint });

  assert.equal(entries.length, 1);
  assert.equal(entries[0].held, null);
  assert.equal(entries[0].expectedVersion, 5);
  assert.equal(entries[0].key, "key-2");
});

test("dismissing forgets a held value, and nothing else can", () => {
  let entries = enqueue([], write(1, 25), { mint: keys() });
  entries = enqueue(entries, write(2, 9), { mint: keys() });
  entries = settle(entries, cellOf(3, 1), { held: HELD.LOCKED });

  assert.deepEqual(dismiss(entries, cellOf(3, 2)), entries, "an entry still to send is not dismissable");
  assert.deepEqual(dismiss(entries, cellOf(3, 1)).map((e) => e.studentMembershipId), [2]);
});

test("sending a held value again is the same write as first queued, under a new key", () => {
  const mint = keys();
  let entries = enqueue([], write(1, 17, 4), { mint });
  entries = markSent(entries, cellOf(3, 1));
  entries = settle(entries, cellOf(3, 1), { held: HELD.LOCKED, detail: "Submitted." });

  entries = release(entries, cellOf(3, 1), { mint });

  assert.deepEqual(
    { value: entries[0].value, expectedVersion: entries[0].expectedVersion, held: entries[0].held, sent: entries[0].sent, key: entries[0].key },
    { value: 17, expectedVersion: 4, held: null, sent: false, key: "key-2" },
  );
  assert.equal(release(entries, cellOf(3, 1), { mint }), entries, "only a held value is released");
});

test("work older than seven days is flagged, not dropped", () => {
  const [entry] = enqueue([], write(1, 15), { now: 0, mint: keys() });

  assert.equal(isOverdue(entry, FLAG_AFTER_MS), false);
  assert.equal(isOverdue(entry, FLAG_AFTER_MS + 1), true);
});

test("sending again after a failed connection backs off, to a minute at most", () => {
  assert.deepEqual([1, 2, 3, 4, 5, 6, 7, 10].map(retryDelay), [2000, 4000, 8000, 16000, 32000, 60000, 60000, 60000]);
});

test("a key is a version 4 UUID, with or without a secure context", () => {
  const uuid4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
  assert.match(newKey(), uuid4);
  // Plain HTTP: no `randomUUID()`, only `getRandomValues()`.
  const insecure = { getRandomValues: (bytes) => bytes.fill(0xff) };
  assert.match(newKey(insecure), uuid4);
});

test("an outbox is one person's at one school", () => {
  assert.notEqual(outboxName(ST_MARYS, KEMI), outboxName(GRACE, KEMI));
  assert.notEqual(outboxName(ST_MARYS, KEMI), outboxName(ST_MARYS, TUNDE));
});

test("a blur queued while a drain waits on the network is not lost", async () => {
  const shelf = new Map();
  const outbox = openOutbox(memoryStore("o", shelf));
  const mint = keys();
  await outbox.update((entries) => enqueue(entries, write(1, 15, 4), { mint }));

  let release;
  const onTheWire = new Promise((resolve) => { release = resolve; });
  const draining = drain({
    outbox,
    owner: KEMI,
    whoIsSignedIn: async () => ({ userId: KEMI }),
    send: async (entry) => {
      if (entry.value === 15) {
        await onTheWire;
        return { landed: true, cell: { value: 15, version: 5 } };
      }
      return { landed: true, cell: { value: entry.value, version: 6 } };
    },
    mint,
  });
  await new Promise((resolve) => setImmediate(resolve));
  await outbox.update((entries) => enqueue(entries, write(1, 17, 4), { mint }));
  release();

  assert.equal(await draining, STOPPED.EMPTY);
  assert.deepEqual(await outbox.read(), []);
});

// -- the correctness requirements, against two schools' servers --------------

/** The page at `server.host`, draining the outbox `shelf` keeps for it. */
function pageAt(server, shelf, { owner = KEMI, mint = keys() } = {}) {
  const outbox = openOutbox(memoryStore(outboxName(server.host, owner), shelf));
  return {
    outbox,
    queue: (w) => outbox.update((entries) => enqueue(entries, w, { mint })),
    drain: () => {
      forgetToken();
      return drain({
        outbox,
        owner,
        whoIsSignedIn: () => whoIsSignedIn({ fetchImpl: server.fetch }),
        send: (entry) => sendQueued(entry, { fetchImpl: server.fetch }),
        mint,
      });
    },
  };
}

const bothSchools = () => [
  school(ST_MARYS, { marks: { 1: { value: 12, version: 4, by: TUNDE } } }),
  school(GRACE, { marks: { 1: { value: 8, version: 2, by: TUNDE } } }),
];

test("requirement 2: a mark changed by somebody else since it was shown is a conflict, not a write", async () => {
  for (const server of bothSchools()) {
    const shelf = new Map();
    const page = pageAt(server, shelf);
    const shown = server.marks.get(1).version;
    await page.queue(write(1, 17, shown));

    // Somebody else moves the mark while the teacher is offline.
    server.marks.set(1, { value: 15, version: shown + 1, by: TUNDE });

    assert.equal(await page.drain(), STOPPED.EMPTY, server.host);
    assert.deepEqual(server.puts.map((p) => p.expected_version), [shown], server.host);
    assert.equal(server.marks.get(1).value, 15, `${server.host}: theirs stands`);
    const [held] = await page.outbox.read();
    assert.equal(held.held.kind, HELD.CONFLICT, server.host);
    assert.equal(held.held.current.value, 15, server.host);
    assert.equal(held.value, 17, `${server.host}: the teacher's 17 is kept beside it`);
  }
});

test("requirement 4: one 423 and the entry stops; nothing sends it again", async () => {
  for (const server of bothSchools()) {
    server.locked = true;
    const page = pageAt(server, new Map());
    await page.queue(write(1, 17, server.marks.get(1).version));

    await page.drain();
    await page.drain();
    await page.drain();

    assert.equal(server.puts.length, 1, server.host);
    const [held] = await page.outbox.read();
    assert.equal(held.held.kind, HELD.LOCKED, server.host);
    assert.match(held.held.detail, /sent back/, server.host);
  }
});

test("requirement 4, for 422 and 403 too: final answers are asked once", async () => {
  for (const server of bothSchools()) {
    server.revokeBeforeNextPut = true;
    const forbidden = pageAt(server, new Map());
    await forbidden.queue(write(1, 17, server.marks.get(1).version));
    await forbidden.drain();
    await forbidden.drain();

    server.markers = [KEMI];
    const invalid = pageAt(server, new Map());
    await invalid.queue(write(1, 25, server.marks.get(1).version));
    await invalid.drain();
    await invalid.drain();

    assert.deepEqual(server.puts.map((p) => p.value), [17, 25], server.host);
    assert.equal((await forbidden.outbox.read())[0].held.kind, HELD.FORBIDDEN, server.host);
    assert.equal((await invalid.outbox.read())[0].held.kind, HELD.INVALID, server.host);
  }
});

test("requirement 5: Kemi's outbox is never sent under Tunde's session", async () => {
  for (const server of bothSchools()) {
    const shelf = new Map();
    const kemis = pageAt(server, shelf, { owner: KEMI });
    await kemis.queue(write(1, 17, server.marks.get(1).version));

    server.signedIn = TUNDE;

    assert.equal(await kemis.drain(), STOPPED.NOT_THE_AUTHOR, server.host);
    assert.equal(server.puts.length, 0, server.host);
    assert.equal((await kemis.outbox.read()).length, 1, `${server.host}: left for Kemi`);
  }
});

test("requirement 5: after a lapsed session, the drain asks again who signed back in", async () => {
  for (const server of bothSchools()) {
    const page = pageAt(server, new Map(), { owner: KEMI });
    await page.queue(write(1, 17, server.marks.get(1).version));
    await page.queue(write(2, 9, null));

    server.signedIn = null;
    assert.equal(await page.drain(), STOPPED.SESSION, server.host);

    // Tunde signs in on the same phone. Nothing of Kemi's goes under his name.
    server.signedIn = TUNDE;
    assert.equal(await page.drain(), STOPPED.NOT_THE_AUTHOR, server.host);
    assert.deepEqual(server.puts, [], server.host);

    // Kemi signs back in, and her writes go, under her name.
    server.signedIn = KEMI;
    assert.equal(await page.drain(), STOPPED.EMPTY, server.host);
    assert.deepEqual(server.puts.map((p) => p.as), [KEMI, KEMI], server.host);
    assert.equal(server.marks.get(1).by, KEMI, server.host);
  }
});

test("somebody who cannot mark here now sends nothing, and nothing queued is dropped", async () => {
  // Their own changed role, or somebody else on the phone: `/where/` refuses
  // either before saying who they are, so the queue waits as it is.
  for (const server of bothSchools()) {
    const page = pageAt(server, new Map());
    await page.queue(write(1, 17, server.marks.get(1).version));
    server.markers = [];

    assert.equal(await page.drain(), STOPPED.NOT_A_MARKER, server.host);
    assert.equal(server.puts.length, 0, server.host);
    const [waiting] = await page.outbox.read();
    assert.equal(waiting.held, null, `${server.host}: not held as final on somebody's behalf`);

    server.markers = [KEMI];
    assert.equal(await page.drain(), STOPPED.EMPTY, server.host);
    assert.equal(server.marks.get(1).value, 17, server.host);
  }
});

test("requirement 6: a school's outbox reaches only that school", async () => {
  const [stMarys, grace] = bothSchools();
  const shelf = new Map();
  await pageAt(stMarys, shelf).queue(write(1, 17, 4));
  await pageAt(grace, shelf).queue(write(1, 6, 2));

  // Only St Mary's page is open, and it is the same teacher at both.
  assert.equal(await pageAt(stMarys, shelf).drain(), STOPPED.EMPTY);

  assert.deepEqual(stMarys.puts.map((p) => p.value), [17]);
  assert.deepEqual(grace.puts, []);
  assert.equal((await pageAt(grace, shelf).outbox.read()).length, 1, "Grace's is still queued for Grace");

  assert.equal(await pageAt(grace, shelf).drain(), STOPPED.EMPTY);
  assert.deepEqual(grace.puts.map((p) => p.value), [6]);
  assert.deepEqual(stMarys.puts.map((p) => p.value), [17]);
});

test("requirement 8: a refused value stays on the device until it is dismissed", async () => {
  const refusals = [
    [HELD.CONFLICT, (s) => s.marks.set(1, { value: 15, version: s.marks.get(1).version + 1, by: TUNDE })],
    [HELD.INVALID, () => {}, 25],
    [HELD.LOCKED, (s) => { s.locked = true; }],
    [HELD.FORBIDDEN, (s) => { s.revokeBeforeNextPut = true; }],
  ];
  for (const [kind, refuse, value = 17] of refusals) {
    for (const server of bothSchools()) {
      const shelf = new Map();
      await pageAt(server, shelf).queue(write(1, value, server.marks.get(1).version));
      refuse(server);
      await pageAt(server, shelf).drain();

      // A new page load: what is on the device is what the store kept.
      const reloaded = pageAt(server, shelf);
      const [kept] = await reloaded.outbox.read();
      assert.equal(kept.held.kind, kind, `${server.host} ${kind}`);
      assert.equal(kept.value, value, `${server.host} ${kind}`);

      await reloaded.outbox.update((entries) => dismiss(entries, kept.cell));
      assert.deepEqual(await pageAt(server, shelf).outbox.read(), [], `${server.host} ${kind}`);
    }
  }
});

test("requirement 1, from the device: a write whose answer was lost is sent again with its key", async () => {
  for (const server of bothSchools()) {
    const page = pageAt(server, new Map());
    const shown = server.marks.get(1).version;
    await page.queue(write(1, 17, shown));

    server.loseNextAnswer = true;
    assert.equal(await page.drain(), STOPPED.OFFLINE, server.host);
    // Landed, and the device does not know.
    assert.equal(server.marks.get(1).value, 17, server.host);

    // On another device the teacher has since made it 18.
    server.marks.set(1, { value: 18, version: shown + 2, by: KEMI });

    assert.equal(await page.drain(), STOPPED.EMPTY, server.host);
    assert.equal(server.puts[0].key, server.puts[1].key, server.host);
    assert.equal(server.marks.get(1).value, 18, `${server.host}: the replay wrote nothing`);
    assert.deepEqual(await page.outbox.read(), [], `${server.host}: and it was not a conflict`);
  }
});
