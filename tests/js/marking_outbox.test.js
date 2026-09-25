/**
 * The marking page with its outbox (slice S3): what the teacher sees, and what
 * reaches which school, when a mark does not land at once.
 *
 * `outbox.test.js` holds the queue's rules against the fake servers. This
 * drives the page itself — `mount()`, a blur, a reload — because requirement
 * 8 is about the screen as well as the phone, and because the page is where
 * the host and the signed-in user are read, which is where requirements 5 and
 * 6 are won or lost.
 *
 * Every test runs at two schools, each with its own server (`fake_school.js`),
 * and the same teacher signed in at both.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { mount, storageMayBeCleared } from "../../static/marking/app.js";
import { FLAG_AFTER_MS, HELD, enqueue, openOutbox, outboxName } from "../../static/marking/outbox.js";
import { memoryStore } from "../../static/marking/store.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";
import { GRACE, KEMI, ST_MARYS, TUNDE, school } from "./fake_school.js";

const CHROME_ANDROID =
  "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Mobile Safari/537.36";
const SAFARI_IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Mobile/15E148 Safari/604.1";

const bothSchools = () => [
  school(ST_MARYS, { marks: { 2: { value: 12, version: 4, by: TUNDE } } }),
  school(GRACE, { marks: { 2: { value: 8, version: 2, by: TUNDE } } }),
];

function keys() {
  let n = 0;
  return () => `key-${++n}`;
}

/** The marking page at `server.host`, with its sheet open. */
async function openPage(server, shelf, { now = () => 1_000_000, userAgent = CHROME_ANDROID, openStore } = {}) {
  forgetToken();
  const root = fakeRoot({});
  const timers = [];
  const online = [];
  await mount(root, {
    // Through `server.fetch` as it is when called, so a test can stand in
    // front of it after the page is open.
    fetchImpl: (url, options) => server.fetch(url, options),
    host: server.host,
    openStore: openStore || (async (name) => memoryStore(name, shelf)),
    schedule: (run, ms) => timers.push({ run, ms }),
    whenOnline: (run) => online.push(run),
    mint: keys(),
    now,
    userAgent,
  });
  await root.click({ "data-action": "pick-assessment", "data-assessment": "3" });
  await root.click({ "data-action": "pick-class", "data-class": "11" });
  return { root, timers, online };
}

const versionOf = (server, id) => server.marks.get(id).version;

/** The outbox a page at `host` keeps for `owner`, read straight off the shelf. */
async function onThePhone(shelf, host, owner = KEMI) {
  return openOutbox(memoryStore(outboxName(host, owner), shelf)).read();
}

// -- requirement 8: no refused value is lost -----------------------------------

const REFUSALS = [
  {
    kind: HELD.CONFLICT,
    typed: 17,
    refuse: (s) => s.marks.set(2, { value: 15, version: versionOf(s, 2) + 1, by: TUNDE }),
    // The box is theirs; the teacher's number is in the note.
    shown: /You entered 17/,
  },
  {
    kind: HELD.INVALID,
    typed: 25,
    refuse: () => {},
    // The box is the teacher's, to correct, with the server's sentence.
    shown: /id="mark-2"[^>]*value="25"[\s\S]*25 is more than the 20/,
  },
  {
    kind: HELD.LOCKED,
    typed: 17,
    refuse: (s) => { s.locked = true; },
    shown: /Not saved\. You entered 17\./,
  },
];

for (const { kind, typed, refuse, shown } of REFUSALS) {
  test(`requirement 8: a value refused as ${kind} is on screen after a reload, until it is dismissed`, async () => {
    for (const server of bothSchools()) {
      const shelf = new Map();
      const first = await openPage(server, shelf);
      refuse(server);
      await first.root.blur({ "data-child": "2", "data-version": String(versionOf(server, 2) - (kind === HELD.CONFLICT ? 1 : 0)) }, String(typed));
      assert.match(first.root.innerHTML, shown, `${server.host}: on screen when it was refused`);

      // The tab is closed and opened again.
      const again = await openPage(server, shelf);
      assert.match(again.root.innerHTML, shown, `${server.host}: on screen after the reload`);
      assert.match(again.root.innerHTML, /data-action="dismiss" data-child="2"/, server.host);
      assert.equal(server.puts.length, 1, `${server.host}: and not sent again by the reload`);

      await again.root.click({ "data-action": "dismiss", "data-child": "2" });
      assert.doesNotMatch(again.root.innerHTML, shown, `${server.host}: dismissed`);
      assert.deepEqual(await onThePhone(shelf, server.host), [], `${server.host}: and gone from the phone`);

      const third = await openPage(server, shelf);
      assert.doesNotMatch(third.root.innerHTML, shown, `${server.host}: and it stays gone`);
    }
  });
}

test("requirement 8: a refusal of authority keeps the number on screen, and on the phone", async () => {
  for (const server of bothSchools()) {
    const shelf = new Map();
    const page = await openPage(server, shelf);
    server.revokeBeforeNextPut = true;

    await page.root.blur({ "data-child": "2", "data-version": String(versionOf(server, 2)) }, "17");

    assert.match(page.root.innerHTML, /Not saved\. You entered 17\./, server.host);
    const [kept] = await onThePhone(shelf, server.host);
    assert.equal(kept.held.kind, HELD.FORBIDDEN, server.host);
    assert.equal(kept.value, 17, server.host);
  }
});

// -- sending again ------------------------------------------------------------

test("a mark whose answer was lost is sent again later, with its key, and lands once", async () => {
  for (const server of bothSchools()) {
    const shelf = new Map();
    const page = await openPage(server, shelf);
    const shown = versionOf(server, 2);
    server.loseNextAnswer = true;

    await page.root.blur({ "data-child": "2", "data-version": String(shown) }, "17");

    assert.match(page.root.innerHTML, /id="mark-2"[^>]*value="17"/, `${server.host}: still in the box`);
    assert.match(page.root.innerHTML, /Not sent yet: the connection failed/, server.host);
    assert.deepEqual(page.timers.map((t) => t.ms), [2000], `${server.host}: sent again in two seconds`);

    await page.timers[0].run();

    assert.equal(server.puts.length, 2, server.host);
    assert.equal(server.puts[1].key, server.puts[0].key, `${server.host}: the same key`);
    assert.deepEqual(server.marks.get(2), { value: 17, version: shown + 1, by: KEMI }, `${server.host}: landed once`);
    assert.match(page.root.innerHTML, new RegExp(`id="mark-2"[^>]*data-version="${shown + 1}"`), server.host);
    assert.doesNotMatch(page.root.innerHTML, /Not sent yet/, server.host);
    assert.deepEqual(await onThePhone(shelf, server.host), [], server.host);
  }
});

test("a resent write answered from its receipt does not redraw the cell as it was then", async () => {
  // The review of #160: a replay is answered with what the first arrival was
  // told. By then the teacher may have entered 18 on another device, and a
  // cell redrawn as 17 at the old version would make their next edit a
  // conflict with themselves.
  for (const server of bothSchools()) {
    const shelf = new Map();
    const page = await openPage(server, shelf);
    const shown = versionOf(server, 2);
    server.loseNextAnswer = true;
    await page.root.blur({ "data-child": "2", "data-version": String(shown) }, "17");

    server.marks.set(2, { value: 18, version: shown + 2, by: KEMI });
    await page.timers[0].run();

    assert.equal(server.puts[1].key, server.puts[0].key, server.host);
    assert.match(page.root.innerHTML, /id="mark-2"[^>]*value="18"/, `${server.host}: what the cell holds now`);
    assert.match(page.root.innerHTML, new RegExp(`id="mark-2"[^>]*data-version="${shown + 2}"`), server.host);
  }
});

test("a mark typed with no connection waits, and goes when the browser is back online", async () => {
  for (const server of bothSchools()) {
    const shelf = new Map();
    const page = await openPage(server, shelf);
    server.offline = true;

    await page.root.blur({ "data-child": "1", "data-version": "" }, "9");

    assert.match(page.root.innerHTML, /id="mark-1"[^>]*value="9"/, server.host);
    // Which sentence depends on where the drain found the connection gone:
    // asking who is signed in, or sending. Either way, not sent and kept.
    assert.match(page.root.innerHTML, /Not sent yet/, server.host);
    assert.equal(server.puts.length, 0, server.host);

    server.offline = false;
    await page.online[0]();

    assert.deepEqual(server.puts.map((p) => [p.id, p.value, p.expected_version]), [[1, 9, null]], server.host);
    assert.doesNotMatch(page.root.innerHTML, /Not sent yet/, server.host);
  }
});

test("what an earlier page load left queued is sent when the page opens", async () => {
  for (const server of bothSchools()) {
    const shelf = new Map();
    await openOutbox(memoryStore(outboxName(server.host, KEMI), shelf)).update((entries) =>
      enqueue(entries, { assessmentId: 3, studentMembershipId: 1, value: 11, expectedVersion: null }, { mint: keys() }),
    );

    await openPage(server, shelf);

    assert.deepEqual(server.puts.map((p) => [p.id, p.value]), [[1, 11]], server.host);
    assert.deepEqual(await onThePhone(shelf, server.host), [], server.host);
  }
});

test("tabbing through a cell that holds a kept value does not replace it", async () => {
  for (const server of bothSchools()) {
    const shelf = new Map();
    const page = await openPage(server, shelf);
    server.marks.set(2, { value: 15, version: versionOf(server, 2) + 1, by: TUNDE });
    await page.root.blur({ "data-child": "2", "data-version": String(versionOf(server, 2) - 1) }, "17");
    assert.match(page.root.innerHTML, /Saved as 15 by somebody else\. You entered 17\./, server.host);

    // The box shows their 15; the teacher tabs through it without typing.
    await page.root.blur({ "data-child": "2", "data-version": String(versionOf(server, 2)) }, "15");

    assert.equal(server.puts.length, 1, server.host);
    assert.match(page.root.innerHTML, /You entered 17/, server.host);
    assert.equal((await onThePhone(shelf, server.host))[0].value, 17, server.host);
  }
});

test("tabbing through a cell left as it was drawn queues nothing", async () => {
  // Found in headless Chrome, where Tab moves focus into the next cell and a
  // redraw blurs it. Online the server would shrug; queued, the unchanged mark
  // is a write that can meet somebody else's change as a conflict.
  for (const server of bothSchools()) {
    const shelf = new Map();
    const page = await openPage(server, shelf);
    server.offline = true;

    await page.root.blur({ "data-child": "2", "data-version": String(versionOf(server, 2)) }, String(server.marks.get(2).value));

    assert.deepEqual(await onThePhone(shelf, server.host), [], server.host);
    assert.doesNotMatch(page.root.innerHTML, /Not sent yet/, server.host);
    assert.equal(page.timers.length, 0, `${server.host}: nothing to send again`);
  }
});

test("while offline, one retry waits at a time however many marks are typed", async () => {
  for (const server of bothSchools()) {
    const page = await openPage(server, new Map());
    server.offline = true;

    await page.root.blur({ "data-child": "1", "data-version": "" }, "9");
    await page.root.blur({ "data-child": "2", "data-version": String(versionOf(server, 2)) }, "13");

    assert.equal(page.timers.length, 1, server.host);

    server.offline = false;
    await page.timers[0].run();
    assert.deepEqual(server.puts.map((p) => [p.id, p.value]).sort(), [[1, 9], [2, 13]], server.host);
  }
});

test("a mark a lock stopped is sent again, as first queued, once the sheet is sent back", async () => {
  for (const server of bothSchools()) {
    const shelf = new Map();
    const page = await openPage(server, shelf);
    const shown = versionOf(server, 2);
    server.locked = true;
    await page.root.blur({ "data-child": "2", "data-version": String(shown) }, "17");

    // Sent back, and the teacher opens the sheet again.
    server.locked = false;
    const again = await openPage(server, shelf);
    assert.match(again.root.innerHTML, /id="mark-2"[^>]*value="17"/, `${server.host}: in the box`);
    assert.match(again.root.innerHTML, /data-action="retry" data-child="2"/, server.host);
    assert.doesNotMatch(again.root.innerHTML, /class="locked"/, `${server.host}: the old lock does not close the sheet`);
    assert.equal(server.puts.length, 1, `${server.host}: nothing sent by itself`);

    await again.root.click({ "data-action": "retry", "data-child": "2" });

    assert.deepEqual(server.puts.map((p) => p.expected_version), [shown, shown], server.host);
    assert.equal(server.marks.get(2).value, 17, server.host);
  }
});

test("requirement 2: a mark a lock stopped, sent again after somebody changed it, is a conflict", async () => {
  for (const server of bothSchools()) {
    const shelf = new Map();
    const page = await openPage(server, shelf);
    server.locked = true;
    await page.root.blur({ "data-child": "2", "data-version": String(versionOf(server, 2)) }, "17");

    server.locked = false;
    server.marks.set(2, { value: 15, version: versionOf(server, 2) + 1, by: TUNDE });
    const again = await openPage(server, shelf);
    await again.root.click({ "data-action": "retry", "data-child": "2" });

    assert.equal(server.marks.get(2).value, 15, `${server.host}: theirs stands`);
    assert.match(again.root.innerHTML, /Saved as 15 by somebody else\. You entered 17\./, server.host);
  }
});

test("a drain the browser fails to keep is reported, and does not stop the next one", async () => {
  for (const server of bothSchools()) {
    const shelf = new Map();
    let writes = 0;
    const flaky = async (name) => {
      const store = memoryStore(name, shelf);
      return {
        read: store.read,
        write: async (entries) => {
          writes += 1;
          // The first write is the blur's; the second is the drain marking it
          // sent, and that is the one the browser refuses.
          if (writes === 2) throw new Error("QuotaExceededError");
          return store.write(entries);
        },
      };
    };
    const errors = [];
    const logged = console.error;
    console.error = (...args) => errors.push(args);
    try {
      const page = await openPage(server, shelf, { openStore: flaky });
      await page.root.blur({ "data-child": "1", "data-version": "" }, "9");
      assert.equal(server.puts.length, 0, `${server.host}: nothing went`);
      assert.equal(errors.length, 1, `${server.host}: and it was said`);

      await page.root.click({ "data-action": "retry", "data-child": "1" });
    } finally {
      console.error = logged;
    }
    assert.deepEqual(server.puts.map((p) => p.value), [9], `${server.host}: the next drain ran`);
  }
});

test("a tap made while the opening drain waits on the network is not lost", async () => {
  // Found in headless Chrome: the page used to wait for the drain before it
  // listened for anything, and a teacher's first taps after a reload went
  // nowhere while an earlier page load's queue was on the wire.
  for (const server of bothSchools()) {
    const shelf = new Map();
    await openOutbox(memoryStore(outboxName(server.host, KEMI), shelf)).update((entries) =>
      enqueue(entries, { assessmentId: 3, studentMembershipId: 1, value: 11, expectedVersion: null }, { mint: keys() }),
    );
    let onTheWire = false;
    let release;
    const answered = new Promise((resolve) => { release = resolve; });
    const fetchImpl = async (url, options = {}) => {
      if (options.method === "PUT") {
        onTheWire = true;
        await answered;
      }
      return server.fetch(url, options);
    };
    forgetToken();
    const root = fakeRoot({});
    const mounting = mount(root, {
      fetchImpl,
      host: server.host,
      openStore: async (name) => memoryStore(name, shelf),
      schedule: () => {},
      whenOnline: () => {},
      mint: keys(),
      userAgent: CHROME_ANDROID,
    });
    while (!onTheWire) await new Promise((resolve) => setImmediate(resolve));

    await root.click({ "data-action": "pick-assessment", "data-assessment": "3" });
    await root.click({ "data-action": "pick-class", "data-class": "11" });
    assert.match(root.innerHTML, /id="mark-2"/, `${server.host}: the sheet opened while the drain waited`);

    release();
    await mounting;
    assert.deepEqual(server.puts.map((p) => p.value), [11], server.host);
  }
});

// -- what the review of #163 found -------------------------------------------------

test("a session found lapsed before anything was sent is said on the sheet", async () => {
  for (const server of bothSchools()) {
    const page = await openPage(server, new Map());
    server.signedIn = null;

    await page.root.blur({ "data-child": "2", "data-version": String(versionOf(server, 2)) }, "17");

    assert.equal(server.puts.length, 0, server.host);
    assert.match(page.root.innerHTML, /Your session has ended\./, server.host);
    assert.match(page.root.innerHTML, /id="mark-2"[^>]*value="17"/, server.host);

    server.signedIn = KEMI;
    await page.root.click({ "data-action": "retry", "data-child": "2" });
    assert.equal(server.marks.get(2).value, 17, server.host);
    assert.doesNotMatch(page.root.innerHTML, /Your session has ended/, server.host);
  }
});

test("a number typed while the last one was out is the one on screen when the send fails", async () => {
  for (const server of bothSchools()) {
    const shelf = new Map();
    let gate;
    const held = new Promise((_, reject) => { gate = reject; });
    let onTheWire = false;
    const page = await openPage(server, shelf);
    const fetchImpl = server.fetch;
    server.fetch = async (url, options = {}) => {
      if (options.method === "PUT" && !onTheWire) {
        onTheWire = true;
        await held;
      }
      return fetchImpl(url, options);
    };

    const first = page.root.blur({ "data-child": "2", "data-version": String(versionOf(server, 2)) }, "17");
    while (!onTheWire) await new Promise((resolve) => setImmediate(resolve));
    const second = page.root.blur({ "data-child": "2", "data-version": String(versionOf(server, 2)) }, "18");
    await new Promise((resolve) => setImmediate(resolve));
    gate(new TypeError("Failed to fetch"));
    await Promise.all([first, second]);

    assert.match(page.root.innerHTML, /id="mark-2"[^>]*value="18"/, `${server.host}: the latest, not the one in flight`);
    const [entry] = await onThePhone(shelf, server.host);
    assert.deepEqual([entry.value, entry.next], [17, 18], server.host);
    server.fetch = fetchImpl;
  }
});

test("a sheet that cannot be fetched after a resend keeps what is on screen", async () => {
  for (const server of bothSchools()) {
    const page = await openPage(server, new Map());
    server.loseNextAnswer = true;
    await page.root.blur({ "data-child": "2", "data-version": String(versionOf(server, 2)) }, "17");
    await page.root.blur({ "data-child": "1", "data-version": "" }, "9");

    server.failSheet = true;
    await page.timers[0].run();

    assert.match(page.root.innerHTML, /data-state="sheet"/, `${server.host}: still the sheet`);
    assert.match(page.root.innerHTML, /id="mark-1"[^>]*value="9"/, server.host);
    server.failSheet = false;
  }
});

test("a mark stopped on its way is not offered to be dismissed, since it will still go", async () => {
  for (const server of bothSchools()) {
    const page = await openPage(server, new Map());
    server.loseNextAnswer = true;

    await page.root.blur({ "data-child": "2", "data-version": String(versionOf(server, 2)) }, "17");

    assert.match(page.root.innerHTML, /Not sent yet: the connection failed/, server.host);
    assert.doesNotMatch(page.root.innerHTML, /data-action="dismiss" data-child="2"/, server.host);
  }
});

test("a browser that stops keeping the outbox mid-page says so, and the mark still goes", async () => {
  for (const server of bothSchools()) {
    const shelf = new Map();
    let broken = false;
    const failing = async (name) => {
      const store = memoryStore(name, shelf);
      return {
        read: async () => { if (broken) throw new Error("InvalidStateError"); return store.read(); },
        write: async (entries) => { if (broken) throw new Error("InvalidStateError"); return store.write(entries); },
      };
    };
    const logged = console.error;
    console.error = () => {};
    try {
      const page = await openPage(server, shelf, { openStore: failing });
      broken = true;
      await page.root.blur({ "data-child": "1", "data-version": "" }, "9");

      assert.deepEqual(server.puts.map((p) => p.value), [9], server.host);
      assert.match(page.root.innerHTML, /not keeping marks that have not been sent/, server.host);
    } finally {
      console.error = logged;
    }
  }
});

test("marks typed in quick succession all go, none left waiting for a later kick", async () => {
  for (const server of bothSchools()) {
    const shelf = new Map();
    const page = await openPage(server, shelf);

    await Promise.all([
      page.root.blur({ "data-child": "1", "data-version": "" }, "9"),
      page.root.blur({ "data-child": "2", "data-version": String(versionOf(server, 2)) }, "17"),
    ]);

    assert.deepEqual(server.puts.map((p) => p.value).sort(), [17, 9], server.host);
    assert.deepEqual(await onThePhone(shelf, server.host), [], server.host);
  }
});

// -- requirement 5: only the author sends ---------------------------------------

test("requirement 5: a sign-in as somebody else, in another tab, sends nothing of the teacher's", async () => {
  for (const server of bothSchools()) {
    const shelf = new Map();
    const page = await openPage(server, shelf);

    server.signedIn = TUNDE;
    await page.root.blur({ "data-child": "2", "data-version": String(versionOf(server, 2)) }, "17");

    assert.equal(server.puts.length, 0, server.host);
    assert.match(page.root.innerHTML, /Somebody else is signed in on this browser now/, server.host);
    assert.match(page.root.innerHTML, /id="mark-2"[^>]*value="17"/, `${server.host}: and the 17 is kept`);

    server.signedIn = KEMI;
    await page.root.click({ "data-action": "retry", "data-child": "2" });

    assert.deepEqual(server.puts.map((p) => p.as), [KEMI], server.host);
    assert.equal(server.marks.get(2).by, KEMI, server.host);
    assert.doesNotMatch(page.root.innerHTML, /Somebody else is signed in/, server.host);
  }
});

test("requirement 5: the page opened by somebody else neither sends nor shows the teacher's queue", async () => {
  for (const server of bothSchools()) {
    const shelf = new Map();
    await openOutbox(memoryStore(outboxName(server.host, KEMI), shelf)).update((entries) =>
      enqueue(entries, { assessmentId: 3, studentMembershipId: 1, value: 11, expectedVersion: null }, { mint: keys() }),
    );
    server.signedIn = TUNDE;

    const page = await openPage(server, shelf);

    assert.equal(server.puts.length, 0, server.host);
    assert.doesNotMatch(page.root.innerHTML, /value="11"/, server.host);
    assert.equal((await onThePhone(shelf, server.host, KEMI)).length, 1, `${server.host}: kept for Kemi`);
  }
});

// -- requirement 6: a school's outbox reaches only that school --------------------

test("requirement 6: each school's page sends and draws only that school's queue", async () => {
  const [stMarys, grace] = bothSchools();
  const shelf = new Map();
  const queue = (host, value) =>
    openOutbox(memoryStore(outboxName(host, KEMI), shelf)).update((entries) =>
      enqueue(entries, { assessmentId: 3, studentMembershipId: 1, value, expectedVersion: null }, { mint: keys() }),
    );
  // The same teacher, the same paper id and the same child id at both schools:
  // ids are per schema, so only the host tells the two apart.
  stMarys.offline = true;
  grace.offline = true;
  await queue(ST_MARYS, 13);
  await queue(GRACE, 6);

  stMarys.offline = false;
  const atStMarys = await openPage(stMarys, shelf);

  assert.deepEqual(stMarys.puts.map((p) => p.value), [13]);
  assert.deepEqual(grace.puts, []);
  assert.doesNotMatch(atStMarys.root.innerHTML, /value="6"/);
  assert.equal((await onThePhone(shelf, GRACE)).length, 1, "Grace's still waits for Grace");

  grace.offline = false;
  await openPage(grace, shelf);
  assert.deepEqual(grace.puts.map((p) => p.value), [6]);
  assert.deepEqual(stMarys.puts.map((p) => p.value), [13]);
});

// -- what the page says about keeping --------------------------------------------

test("work kept for more than seven days is flagged on the sheet", async () => {
  for (const server of bothSchools()) {
    const shelf = new Map();
    const typedAt = 1_000_000;
    const first = await openPage(server, shelf, { now: () => typedAt });
    await first.root.blur({ "data-child": "2", "data-version": String(versionOf(server, 2)) }, "25");

    const eightDaysOn = await openPage(server, shelf, { now: () => typedAt + FLAG_AFTER_MS + 86_400_000 });

    assert.match(eightDaysOn.root.innerHTML, /Entered more than seven days ago\./, server.host);
    assert.equal((await onThePhone(shelf, server.host)).length, 1, `${server.host}: flagged, not dropped`);
  }
});

test("Safari is warned that it may delete unsent marks; Chrome on Android is not", async () => {
  for (const server of bothSchools()) {
    const safari = await openPage(server, new Map(), { userAgent: SAFARI_IPHONE });
    const chrome = await openPage(server, new Map(), { userAgent: CHROME_ANDROID });

    assert.match(safari.root.innerHTML, /can be deleted if this site is not opened for seven days/, server.host);
    assert.doesNotMatch(chrome.root.innerHTML, /class="warning"/, server.host);
  }
});

test("a browser that will not keep anything says so, and the page still works", async () => {
  for (const server of bothSchools()) {
    const page = await openPage(server, new Map(), { openStore: async () => null });

    assert.match(page.root.innerHTML, /not keeping marks that have not been sent/, server.host);
    await page.root.blur({ "data-child": "1", "data-version": "" }, "9");
    assert.deepEqual(server.puts.map((p) => p.value), [9], server.host);
  }
});

test("which browsers are told their storage may be cleared", () => {
  assert.equal(storageMayBeCleared(SAFARI_IPHONE), true);
  assert.equal(
    storageMayBeCleared("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.6 Safari/605.1.15"),
    true,
  );
  assert.equal(
    storageMayBeCleared("Mozilla/5.0 (iPhone; CPU iPhone OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/129.0 Mobile/15E148 Safari/604.1"),
    true,
    "Chrome on an iPhone runs Safari's engine",
  );
  assert.equal(storageMayBeCleared(CHROME_ANDROID), false);
});
