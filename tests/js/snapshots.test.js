/**
 * The copy a page keeps of what it was shown (`static/web/snapshots.js`).
 *
 * `docs/offline.md` slice S5, D8 and D10. The rules that matter are about
 * whose a copy is and when it may be offered, so every test is about a second
 * school or a second person, and the shelf is shared between them on purpose:
 * a browser gives each origin its own database, and a key that did not name the
 * host would be the first thing a shared shelf shows up.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { asOfText, copyNote, indexedDbSnapshots, liveOrCopy } from "../../static/web/snapshots.js";
import { memorySnapshots } from "./memory_snapshots.js";

const ST_MARYS = "st-marys.example.ng";
const GRACE = "grace.example.ng";
const KEMI = 5;
const TUNDE = 6;

const live = (body) => ({ ok: true, body });
const GONE = { ok: false, refusal: "broken", offline: true, body: { detail: "TypeError: Failed to fetch" } };

test("a live answer is kept, and handed back as it came", async () => {
  const shelf = memorySnapshots();
  const answer = live({ user_id: KEMI, classes: ["JSS 1A"] });

  const back = await liveOrCopy({ shelf, host: ST_MARYS, name: "where", answer, at: "2025-09-17T08:00:00Z" });

  assert.equal(back, answer);
  assert.deepEqual(await shelf.copy(ST_MARYS, KEMI, "where"), { at: "2025-09-17T08:00:00Z", body: answer.body });
});

test("when the server cannot be reached the copy comes back, with the time it was taken", async () => {
  const shelf = memorySnapshots();
  await liveOrCopy({ shelf, host: ST_MARYS, name: "where", answer: live({ user_id: KEMI, n: 1 }), at: "T1" });

  const back = await liveOrCopy({ shelf, host: ST_MARYS, name: "where", answer: GONE });

  assert.equal(back.ok, true);
  assert.equal(back.asOf, "T1");
  assert.deepEqual(back.body, { user_id: KEMI, n: 1 });
});

test("with no copy the failure is handed back as it was", async () => {
  const shelf = memorySnapshots();

  assert.equal(await liveOrCopy({ shelf, host: ST_MARYS, name: "where", answer: GONE }), GONE);
});

test("two schools: one host's copy is never offered at the other", async () => {
  const shelf = memorySnapshots();
  await liveOrCopy({ shelf, host: ST_MARYS, name: "where", answer: live({ user_id: KEMI, school: "St Mary's" }), at: "T1" });
  await liveOrCopy({ shelf, host: GRACE, name: "where", answer: live({ user_id: KEMI, school: "Grace" }), at: "T2" });

  const marys = await liveOrCopy({ shelf, host: ST_MARYS, name: "where", answer: GONE });
  const grace = await liveOrCopy({ shelf, host: GRACE, name: "where", answer: GONE });

  assert.equal(marys.body.school, "St Mary's");
  assert.equal(grace.body.school, "Grace");

  const alone = memorySnapshots();
  await liveOrCopy({ shelf: alone, host: ST_MARYS, name: "where", answer: live({ user_id: KEMI, school: "St Mary's" }), at: "T1" });
  assert.equal(await liveOrCopy({ shelf: alone, host: GRACE, name: "where", answer: GONE }), GONE, "no copy for a host never opened");
});

test("two people: one person's copy is never offered as another's", async () => {
  const shelf = memorySnapshots();
  await liveOrCopy({ shelf, host: ST_MARYS, name: "where", answer: live({ user_id: KEMI, who: "Kemi" }), at: "T1" });
  await liveOrCopy({ shelf, host: ST_MARYS, userId: KEMI, name: "sheet:3:11", answer: live({ rows: ["Kemi's sheet"] }), at: "T1" });
  // Tunde signs in on the same phone, online, and opens nothing else.
  await liveOrCopy({ shelf, host: ST_MARYS, name: "where", answer: live({ user_id: TUNDE, who: "Tunde" }), at: "T2" });

  // Offline, the page reads whoever last opened this host.
  const where = await liveOrCopy({ shelf, host: ST_MARYS, name: "where", answer: GONE });
  assert.equal(where.body.who, "Tunde");

  // And a sheet only Kemi opened is not Tunde's to be shown.
  const sheet = await liveOrCopy({ shelf, host: ST_MARYS, userId: TUNDE, name: "sheet:3:11", answer: GONE });
  assert.equal(sheet, GONE);
  assert.deepEqual((await shelf.copy(ST_MARYS, KEMI, "sheet:3:11")).body.rows, ["Kemi's sheet"]);
});

test("an answer from the server is never replaced by a copy", async () => {
  const shelf = memorySnapshots();
  await liveOrCopy({ shelf, host: ST_MARYS, name: "where", answer: live({ user_id: KEMI }), at: "T1" });

  for (const refusal of ["expired", "signed-out", "not-a-marker", "wrong-host"]) {
    const answer = { ok: false, refusal, body: {} };
    assert.equal(await liveOrCopy({ shelf, host: ST_MARYS, name: "where", answer }), answer, refusal);
  }
});

test("a server error is no answer, so the copy stands in; a 4xx is one", async () => {
  const shelf = memorySnapshots();
  await liveOrCopy({ shelf, host: ST_MARYS, name: "where", answer: live({ user_id: KEMI }), at: "T1" });

  const down = { ok: false, refusal: "broken", offline: true, body: {} };
  assert.equal((await liveOrCopy({ shelf, host: ST_MARYS, name: "where", answer: down })).asOf, "T1");
  const refused = { ok: false, refusal: "broken", body: {} };
  assert.equal(await liveOrCopy({ shelf, host: ST_MARYS, name: "where", answer: refused }), refused);
});

test("nobody signed in drops that host's copies and no other's", async () => {
  const shelf = memorySnapshots();
  await liveOrCopy({ shelf, host: ST_MARYS, name: "where", answer: live({ user_id: KEMI }), at: "T1" });
  await liveOrCopy({ shelf, host: GRACE, name: "where", answer: live({ user_id: KEMI }), at: "T1" });

  const out = { ok: false, refusal: "signed-out", signedOut: true, body: {} };
  assert.equal(await liveOrCopy({ shelf, host: ST_MARYS, name: "where", answer: out }), out);

  assert.equal(await shelf.copy(ST_MARYS, KEMI, "where"), null);
  assert.equal(await shelf.last(ST_MARYS), null);
  assert.notEqual(await shelf.copy(GRACE, KEMI, "where"), null);
});

test("a store that fails never fails the page", async () => {
  const broken = {
    keep: async () => { throw new Error("quota"); },
    copy: async () => { throw new Error("closed"); },
    last: async () => { throw new Error("closed"); },
    clearHost: async () => { throw new Error("closed"); },
  };
  const quiet = console.error;
  console.error = () => {};
  try {
    const answer = live({ user_id: KEMI });
    assert.equal(await liveOrCopy({ shelf: broken, host: ST_MARYS, name: "where", answer }), answer);
    assert.equal(await liveOrCopy({ shelf: broken, host: ST_MARYS, name: "where", answer: GONE }), GONE);
  } finally {
    console.error = quiet;
  }
});

test("copies of one class's registers come newest first, for that person and host only", async () => {
  const shelf = memorySnapshots();
  await shelf.keep(ST_MARYS, KEMI, "register:11:7:2025-09-16", { day: 16 }, "2025-09-16T08:00:00Z");
  await shelf.keep(ST_MARYS, KEMI, "register:11:7:2025-09-17", { day: 17 }, "2025-09-17T08:00:00Z");
  await shelf.keep(ST_MARYS, KEMI, "register:12:7:2025-09-17", { other: "class" }, "2025-09-17T09:00:00Z");
  await shelf.keep(ST_MARYS, TUNDE, "register:11:7:2025-09-18", { tunde: true }, "2025-09-18T08:00:00Z");
  await shelf.keep(GRACE, KEMI, "register:11:7:2025-09-18", { grace: true }, "2025-09-18T08:00:00Z");

  const found = await shelf.copiesBeginning(ST_MARYS, KEMI, "register:11:7:");

  assert.deepEqual(found.map((c) => c.body), [{ day: 17 }, { day: 16 }]);
});

test("clearing forgets every copy", async () => {
  const shelf = memorySnapshots();
  await shelf.keep(ST_MARYS, KEMI, "where", {}, "T1");
  await shelf.keep(GRACE, TUNDE, "where", {}, "T1");

  await shelf.clearAll();

  assert.equal(await shelf.copy(ST_MARYS, KEMI, "where"), null);
  assert.equal(await shelf.copy(GRACE, TUNDE, "where"), null);
  assert.equal(await shelf.last(ST_MARYS), null);
});

test("no IndexedDB, no database: the page falls back to memory", async () => {
  assert.equal(await indexedDbSnapshots({ indexedDB: undefined }), null);
  const refusing = { open: () => { const req = {}; setImmediate(() => req.onerror && req.onerror()); return req; } };
  assert.equal(await indexedDbSnapshots({ indexedDB: refusing }), null);
});

// -- when, in the school's day -----------------------------------------------

test("a copy is dated in the school's day, not the phone's or Greenwich's", () => {
  const now = new Date("2025-09-17T15:00:00Z"); // 16:00 in Lagos
  assert.equal(asOfText("2025-09-17T07:40:00Z", { now }), "today 08:40");
  assert.equal(asOfText("2025-09-16T15:40:00Z", { now }), "yesterday 16:40");
  // The month's spelling ("Sep" or "Sept") is the browser's own.
  assert.match(asOfText("2025-09-12T07:00:00Z", { now }), /^Fri,? 12 Sep\w* 08:00$/);
});

test("half past midnight in Lagos is already the next day", () => {
  // 23:30 UTC on the 16th is 00:30 on the 17th in Lagos.
  const now = new Date("2025-09-17T09:00:00Z");
  assert.equal(asOfText("2025-09-16T23:30:00Z", { now }), "today 00:30");
  assert.equal(asOfText("2025-09-16T22:30:00Z", { now }), "yesterday 23:30");
});

test("a time that is not a time is not guessed at", () => {
  assert.equal(asOfText("later", {}), "an earlier time");
});

test("the note says it is a copy and escapes what it is given", () => {
  assert.equal(copyNote(null), "");
  const html = copyNote("2025-09-17T07:40:00Z", { now: new Date("2025-09-17T15:00:00Z"), saying: "<b>x</b>" });
  assert.match(html, /This is a copy from today 08:40\. You are not connected\./);
  assert.match(html, /&lt;b&gt;x&lt;\/b&gt;/);
});
