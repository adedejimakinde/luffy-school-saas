/**
 * `/sit/`: the exam door, the exam screen, the outbox and the clock. `docs/cbt.md`, step 4.
 *
 * The page is driven against a fake school (`fakeSchool()` below) that answers as
 * `cbt/sit_views.py` does: it acknowledges answers by `(session, seq)`, counts what it
 * receives, and can be cut off to stand for a lost network. What the real school does
 * with them, the deadline and the late window included, is `cbt/tests/test_sitting.py`'s.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { press, START } from "../../static/sit/calculator.js";
import { formatLeft, makeClock, spokenLeft, WARN_MS } from "../../static/sit/clock.js";
import { makeOutbox, memoryStorage } from "../../static/sit/outbox.js";
import * as states from "../../static/sit/states.js";
import { keepsTooLittle, mount, seatOf } from "../../static/sit/app.js";
import { fakeRoot } from "./fake_dom.js";

// -- the clock -------------------------------------------------------------------------

test("the countdown reads minutes and seconds, and hours past an hour", () => {
  assert.equal(formatLeft(24 * 60_000 + 37_000), "24:37");
  assert.equal(formatLeft(72 * 60_000 + 40_000), "1:12:40");
  assert.equal(formatLeft(400), "00:01");
  assert.equal(formatLeft(-5000), "00:00");
  assert.equal(spokenLeft(24 * 60_000 + 1), "25 minutes left");
  assert.equal(spokenLeft(61 * 60_000), "1 hour 1 minute left");
});

test("the clock is the server's, carried on the monotonic clock, never the wall clock", () => {
  let mono = 1000;
  let wall = 5_000_000; // an hour off, and it will jump
  const clock = makeClock({ now: () => mono, wall: () => wall });
  const sentAt = mono;
  mono += 200; // a 200ms round trip
  clock.sync("2026-11-09T09:00:00.000Z", sentAt);
  assert.equal(clock.serverNow(), Date.parse("2026-11-09T09:00:00.100Z"));
  mono += 60_000;
  wall -= 3_600_000; // somebody changes the computer's clock
  assert.equal(clock.serverNow(), Date.parse("2026-11-09T09:01:00.100Z"));
});

test("after a reload with no network the clock starts from the kept offset", () => {
  const wall = 1_000_000;
  const clock = makeClock({ now: () => 0, wall: () => wall });
  clock.fromKept(2500);
  assert.equal(clock.serverNow(), wall + 2500);
});

// -- the calculator -------------------------------------------------------------------

const keys = (sequence) => sequence.reduce((s, k) => press(s, k), START).shown;

test("the calculator adds, takes away, multiplies and divides, with decimals", () => {
  assert.equal(keys(["2", "+", "3", "="]), "5");
  assert.equal(keys(["1", ".", "5", "*", "4", "="]), "6");
  assert.equal(keys(["1", "0", "/", "4", "="]), "2.5");
  assert.equal(keys(["0", ".", "1", "+", "0", ".", "2", "="]), "0.3");
  assert.equal(keys(["9", "-", "1", "2", "="]), "-3");
  assert.equal(keys(["2", "+", "3", "*", "4", "="]), "20", "one operation at a time, as a pocket calculator");
  assert.equal(keys(["7", "/", "0", "="]), "Error");
  assert.equal(keys(["7", "/", "0", "=", "3"]), "3", "a key after an error starts again");
  assert.equal(keys(["1", "2", "3", "back"]), "12");
  assert.equal(keys(["1", ".", ".", "5"]), "1.5");
  assert.equal(keys(["4", "+", "C"]), "0");
});

// -- the outbox -----------------------------------------------------------------------

test("each choice is kept, queued in order and numbered, and leaves when acknowledged", async () => {
  const outbox = makeOutbox(memoryStorage());
  await outbox.keep({ session: 7, answers: {}, paper: { items: [] } });
  const a = await outbox.choose(11, 2, 1000);
  const b = await outbox.choose(12, 0, 2000);
  const c = await outbox.choose(11, 3, 3000);
  assert.deepEqual([a.seq, b.seq, c.seq], [1, 2, 3]);
  assert.deepEqual((await outbox.pending()).map((x) => [x.seq, x.item, x.chosen]), [[1, 11, 2], [2, 12, 0], [3, 11, 3]]);
  assert.deepEqual((await outbox.attempt()).answers, { 11: 3, 12: 0 });
  await outbox.acknowledge([1, 3]);
  assert.deepEqual((await outbox.pending()).map((x) => x.seq), [2]);
  await outbox.clear();
  assert.equal(await outbox.attempt(), null);
  assert.deepEqual(await outbox.pending(), []);
});

// -- the screens ----------------------------------------------------------------------

const PAPER = {
  title: "JSS 2 Mathematics",
  duration: 40,
  can_go_back: true,
  grid: true,
  calculator: true,
  items: Array.from({ length: 20 }, (_, i) => ({
    id: 100 + i,
    number: i + 1,
    stem: `Question text ${i + 1} <b>bold?</b>`,
    image: null,
    image_alt: "",
    marks: 1,
    options: [3, 1, 0, 2].map((index) => ({ index, text: `Option ${index}` })),
  })),
};

function examView(over = {}) {
  return {
    school: { name: "St Mary's", crest: "", initials: "SM" },
    title: PAPER.title,
    student: { name: "Ada Obi", admission_number: "SM/001", class_name: "JSS 2A" },
    items: PAPER.items,
    answers: {},
    flags: [],
    current: 6,
    leftMs: 24 * 60_000 + 37_000,
    online: true,
    calculator: true,
    calcOpen: false,
    calc: START,
    canGoBack: true,
    grid: true,
    asking: false,
    leftWarning: false,
    closed: false,
    timeUp: false,
    ...over,
  };
}

test("the exam screen: question 7 of 20, the timer, the student, the grid and the summary", () => {
  const answers = Object.fromEntries(PAPER.items.slice(0, 6).map((i) => [String(i.id), 0]));
  const html = states.exam(examView({ answers, flags: [101, 105] }));
  assert.match(html, /Question 7 of 20/);
  assert.match(html, /Time left<\/span> <span class="sit-timer-value" data-timer-value>24:37</);
  assert.match(html, /Ada Obi/);
  assert.match(html, /SM\/001/);
  assert.match(html, /JSS 2A/);
  assert.match(html, /Flag for review/);
  assert.match(html, /Answered <strong>6<\/strong> of 20/);
  assert.match(html, /Flagged <strong>2<\/strong>/);
  assert.match(html, /Calculator/);
  assert.match(html, /Submit test/);
  assert.match(html, /aria-label="Question 2, answered, flagged for review"/);
  assert.match(html, /aria-label="Question 7, not answered, the one shown" aria-current="true"/);
  assert.match(html, /<span class="kbd">F<\/span> flag/);
  assert.doesNotMatch(html, /<b>bold/, "a question is text, never markup");
  assert.equal((html.match(/class="tile/g) || []).length, 40, "the grid and the phone's strip");
});

test("the chosen option is marked, its saved state is said, and the letters follow the student's order", () => {
  const item = PAPER.items[6];
  const html = states.exam(examView({ answers: { [String(item.id)]: 0 } }));
  // The paper's third option on screen is the original option 0: letter C.
  assert.match(html, /class="sit-option chosen" role="radio" aria-checked="true" data-action="choose" data-option="0" data-key="C"/);
  assert.match(html, /Answer saved/);
  assert.match(states.exam(examView()), /Not answered yet/);
});

test("under five minutes the timer turns amber and says the answers submit by themselves", () => {
  const html = states.exam(examView({ leftMs: WARN_MS - 1000 }));
  assert.match(html, /sit-timer warn/);
  assert.match(html, /Less than 5 minutes left\. Your answers submit by themselves at 00:00\./);
  assert.doesNotMatch(states.exam(examView({ leftMs: WARN_MS + 1000 })), /Less than 5 minutes/);
});

test("offline, and leaving the page, are said in plain words", () => {
  assert.match(states.exam(examView({ online: false })), /You&#39;re offline\. Your answers are saved on this device and will send when you reconnect\.|You're offline\. Your answers are saved on this device and will send when you reconnect\./);
  assert.match(states.exam(examView({ leftWarning: true })), /This has been recorded\./);
});

test("the submit question counts unanswered and flagged", () => {
  const answers = Object.fromEntries(PAPER.items.slice(0, 17).map((i) => [String(i.id), 1]));
  const html = states.submitQuestion(examView({ answers, flags: [100, 101] }));
  assert.match(html, /You have 3 unanswered and 2 flagged questions\. Submit anyway\?/);
  const all = Object.fromEntries(PAPER.items.map((i) => [String(i.id), 1]));
  assert.match(states.submitQuestion(examView({ answers: all })), /Submit your test\?/);
});

test("the calculator is drawn only for a test that allows it", () => {
  assert.doesNotMatch(states.exam(examView({ calculator: false })), /Calculator/);
  assert.match(states.exam(examView({ calcOpen: true })), /role="dialog" aria-label="Calculator"/);
});

test("going back can be turned off", () => {
  const html = states.exam(examView({ canGoBack: false }));
  assert.match(html, /data-action="prev" disabled/);
  assert.match(html, /aria-label="Question 1, not answered" disabled/);
});

test("the finished screen shows no score", () => {
  const html = states.finished({ name: "Ada Obi", title: "JSS 2 Mathematics", submittedAt: "2026-11-09T09:40:00Z", answered: 17, questions: 20, received: 17 });
  assert.match(html, /Well done, Ada/);
  assert.match(html, /17 of 20/);
  assert.match(html, /All 17/);
  assert.match(html, /Your score will show when your teacher releases it/);
  assert.doesNotMatch(html, /score:|\d+%|marks? out of/i);
});

test("the door keeps the code and number and never the PIN", () => {
  const html = states.door({ code: "KMT", number: "SM/001", detail: "That test code, admission number and PIN do not open a test here." });
  assert.match(html, /value="KMT"/);
  assert.match(html, /value="SM\/001"/);
  assert.match(html, /<input id="pin"[^>]*>/);
  assert.doesNotMatch(html.match(/<input id="pin"[^>]*>/)[0], /value=/);
  assert.match(html, /role="alert"/);
});

test("a seat is described by browser, system and width", () => {
  assert.equal(seatOf({ userAgent: "Mozilla/5.0 (Windows NT 10.0) AppleWebKit Chrome/130 Safari/537" }, { width: 1366 }), "Chrome on Windows, 1366px");
});

// -- the page, against a fake school -------------------------------------------------------

const DEADLINE = "2026-11-09T09:40:00.000Z";
const NOW = "2026-11-09T09:00:00.000Z";

/** A school that answers `/sit/api/` as `cbt/sit_views.py` does, or is unreachable. */
function fakeSchool() {
  const school = {
    online: true,
    received: new Map(), // `${session}:${seq}` -> answer, as the unique key keeps them
    order: [],
    events: [],
    submitted: null,
    session: 1,
    replaced: false,
    calls: [],
    deadline: DEADLINE,
  };
  school.fetch = async (url, init = {}) => {
    const path = url.replace("/sit/api/", "");
    school.calls.push(path);
    if (!school.online) throw new TypeError("Failed to fetch");
    const body = init.body ? JSON.parse(init.body) : {};
    const answers = () => Object.fromEntries([...school.received.values()].map((a) => [String(a.item), a.chosen]));
    const reply = (status, json) => ({ status, json: async () => json });
    const state = () => ({ now: NOW, deadline: school.deadline, late_window: 120, closed: Boolean(school.submitted), replaced: school.replaced, submitted_at: school.submitted, ended_by: school.submitted ? school.endedBy : "" });
    const take = () => {
      const acks = [];
      for (const a of body.answers || []) {
        const key = `${school.session}:${a.seq}`;
        if (!school.received.has(key)) {
          school.received.set(key, a);
          school.order.push(a.seq);
        }
        acks.push(a.seq);
      }
      for (const e of body.events || []) if (!school.events.find((x) => x.seq === e.seq)) school.events.push(e);
      return { acks, refused: [], event_acks: (body.events || []).map((e) => e.seq) };
    };
    const payload = () => ({
      attempt: { id: 9, number: 1, session: school.session, started_at: NOW },
      student: { name: "Ada Obi", admission_number: "SM/001", class_name: "JSS 2A" },
      paper: PAPER,
      answers: answers(),
      test: { id: 3, title: PAPER.title, calculator: true },
      ...state(),
    });
    switch (path) {
      case "door/":
        if (body.pin !== "12345678") return reply(404, { detail: "That test code, admission number and PIN do not open a test here." });
        return reply(200, { ticket: "t", student: payload().student, test: { title: PAPER.title, duration: 40, questions: 20, calculator: true }, resuming: false, minutes_left: null });
      case "start/":
        return reply(200, { ...payload(), resumed: false });
      case "attempt/":
        return school.started ? reply(200, payload()) : reply(401, { detail: "You are not signed in." });
      case "sync/":
        return reply(200, { ...take(), ...state() });
      case "submit/": {
        const out = take();
        if (school.replaced) return reply(409, { detail: "Replaced", replaced: true });
        school.submitted = NOW;
        school.endedBy = body.by_clock ? "clock" : "student";
        return reply(200, { ...out, ...state(), received: Object.values(answers()).filter((v) => v !== null).length, questions: 20 });
      }
      case "not-me/":
        return reply(200, {});
      default:
        return reply(404, {});
    }
  };
  return school;
}

/** Timers the test runs by hand. `run()` fires every one due, and lets every send land. */
function manualTimers() {
  const due = [];
  const timers = {
    setTimer: (fn) => due.push(fn),
    setTicker: () => 1,
    clearTicker: () => {},
    async run() {
      for (let round = 0; round < 20; round++) {
        while (due.length) await due.shift()();
        await new Promise((r) => setImmediate(r));
      }
    },
  };
  return timers;
}

async function signedIn({ school = fakeSchool(), storage = memoryStorage(), clock } = {}) {
  const root = fakeRoot({ school: "St Mary's" });
  const timers = manualTimers();
  let mono = 0;
  const page = mount(root, {
    fetchImpl: school.fetch,
    storage,
    clock: clock || makeClock({ now: () => mono, wall: () => Date.parse(NOW) }),
    win: null,
    doc: null,
    onLine: () => school.online,
    monotonic: () => mono,
    ...timers,
  });
  await page.ready;
  assert.equal(page.state().step, "door");
  await root.submit({ code: "KMTRWX", number: "SM/001", pin: "12345678" }, { form: "door" });
  assert.equal(page.state().step, "confirm");
  assert.match(root.innerHTML, /Is this you\?/);
  await root.click({ "data-action": "start" });
  school.started = true;
  assert.equal(page.state().step, "exam");
  await timers.run();
  return { root, page, school, storage, timers, advance: (ms) => (mono += ms) };
}

test("a wrong PIN is said in one sentence and the PIN box is emptied", async () => {
  const school = fakeSchool();
  const root = fakeRoot();
  const page = mount(root, { fetchImpl: school.fetch, storage: memoryStorage(), win: null, doc: null, ...manualTimers() });
  await page.ready;
  await root.submit({ code: "KMTRWX", number: "SM/001", pin: "00000000" }, { form: "door" });
  assert.match(root.innerHTML, /do not open a test here/);
  assert.match(root.innerHTML, /value="SM\/001"/);
});

test("a choice is kept and sent once, and keys A to D, N, P and F work", async () => {
  const { root, page, school, timers } = await signedIn();
  await root.click({ "data-action": "choose", "data-option": "1" });
  await timers.run();
  page.onKey({ key: "n", target: {} });
  page.onKey({ key: "a", target: {} });
  await new Promise((r) => setImmediate(r));
  await timers.run();
  page.onKey({ key: "f", target: {} });
  page.onKey({ key: "n", target: {} });
  page.onKey({ key: "p", target: {} });
  assert.equal(page.state().current, 1);
  assert.deepEqual(page.state().flags, [101]);
  await page.flush();
  // The first question's option 1, and the second question's first letter (original 3).
  assert.deepEqual([...school.received.values()].map((a) => [a.item, a.chosen]), [[100, 1], [101, 3]]);
  assert.deepEqual(await page.outbox.pending(), []);
});

test("offline: answers are queued in order, sent once when back, and duplicates are ignored", async () => {
  const { root, page, school, timers } = await signedIn();
  school.online = false;
  for (const option of ["0", "2", "3"]) {
    await root.click({ "data-action": "choose", "data-option": option });
    await timers.run();
  }
  assert.equal(page.state().online, false);
  assert.match(root.innerHTML, /You're offline|You&#39;re offline/);
  assert.equal((await page.outbox.pending()).length, 3);
  school.online = true;
  await page.flush();
  await page.flush(); // a second send of nothing, and a resend would be ignored
  assert.deepEqual(school.order, [1, 2, 3], "in the order chosen");
  assert.equal(school.received.size, 3, "each once");
  assert.deepEqual(await page.outbox.pending(), []);
  assert.deepEqual(school.events.map((e) => e.kind), ["disconnect", "reconnect"]);
  assert.equal(page.state().answers["100"], 3);
});

test("a reload restores the answers, the question and the time left, with or without a network", async () => {
  const { root, page, school, storage, timers } = await signedIn();
  await root.click({ "data-action": "choose", "data-option": "2" });
  await root.click({ "data-action": "go", "data-index": "4" });
  await root.click({ "data-action": "flag" });
  await timers.run();
  page.stop();

  // A reload with the network: the school's answers, and this computer's place and flags.
  const again = mount(fakeRoot(), { fetchImpl: school.fetch, storage, win: null, doc: null, ...manualTimers(), clock: makeClock({ now: () => 0, wall: () => Date.parse(NOW) }) });
  await again.ready;
  assert.equal(again.state().step, "exam");
  assert.equal(again.state().answers["100"], 2);
  assert.equal(again.state().current, 4);
  assert.deepEqual(again.state().flags, [104]);
  assert.equal(again.state().deadline, DEADLINE);
  again.stop();

  // And after a power cut with no network: the kept copy, on the kept offset.
  school.online = false;
  const offline = mount(fakeRoot(), { fetchImpl: school.fetch, storage, win: null, doc: null, ...manualTimers(), onLine: () => false, clock: makeClock({ now: () => 0, wall: () => Date.parse(NOW) + 60_000 }) });
  await offline.ready;
  assert.equal(offline.state().step, "exam");
  assert.equal(offline.state().answers["100"], 2);
  assert.equal(offline.state().online, false);
  offline.stop();
});

test("an answer chosen offline and not yet sent survives a reload and is sent after", async () => {
  const { root, page, school, storage, timers } = await signedIn();
  school.online = false;
  await root.click({ "data-action": "choose", "data-option": "3" });
  await timers.run();
  page.stop();
  school.online = true;
  const again = mount(fakeRoot(), { fetchImpl: school.fetch, storage, win: null, doc: null, ...manualTimers(), clock: makeClock({ now: () => 0, wall: () => Date.parse(NOW) }) });
  await again.ready;
  assert.equal(again.state().answers["100"], 3, "the unsent answer beats the school's older copy");
  await again.flush();
  for (let i = 0; i < 20; i++) await new Promise((r) => setImmediate(r));
  assert.equal([...school.received.values()].at(-1).chosen, 3);
  again.stop();
});

test("at 00:00 the page stops taking answers and submits by the clock", async () => {
  let mono = 0;
  const clock = makeClock({ now: () => mono, wall: () => Date.parse(NOW) });
  const { root, page, school } = await signedIn({ clock });
  mono += 40 * 60_000 + 1;
  await page.tick();
  await new Promise((r) => setImmediate(r));
  for (let i = 0; i < 5 && page.state().step !== "finished"; i++) await new Promise((r) => setImmediate(r));
  assert.equal(school.endedBy, "clock");
  assert.equal(page.state().step, "finished");
  assert.match(root.innerHTML, /Time is up\. Your test is in\./);
  await page.choose(1);
  assert.equal(school.received.size, 0);
});

test("submitting asks first, then sends the outbox and clears this computer", async () => {
  const { root, page, school, storage } = await signedIn();
  await root.click({ "data-action": "choose", "data-option": "0" });
  await root.click({ "data-action": "ask-submit" });
  assert.match(root.innerHTML, /You have 19 unanswered questions\. Submit anyway\?/);
  await root.click({ "data-action": "submit" });
  assert.equal(school.endedBy, "student");
  assert.equal(page.state().step, "finished");
  assert.match(root.innerHTML, /Received by the school<\/dt><dd>All 1</);
  assert.equal(storage.data.size, 0, "nothing about this test is left on this computer");
});

test("a computer that has been replaced says so and cannot submit", async () => {
  const { root, page, school } = await signedIn();
  school.replaced = true;
  await page.flush();
  assert.equal(page.state().step, "replaced");
  assert.match(root.innerHTML, /open on another computer/);
});

test("leaving the page is told to the student and sent to the school", async () => {
  let mono = 0;
  const clock = makeClock({ now: () => mono, wall: () => Date.parse(NOW) });
  const school = fakeSchool();
  const root = fakeRoot();
  const timers = manualTimers();
  const page = mount(root, { fetchImpl: school.fetch, storage: memoryStorage(), clock, win: null, doc: null, monotonic: () => mono, ...timers });
  await page.ready;
  await root.submit({ code: "K", number: "SM/001", pin: "12345678" }, { form: "door" });
  await root.click({ "data-action": "start" });
  page.left();
  mono += 14_000;
  page.back();
  await new Promise((r) => setImmediate(r));
  await timers.run();
  assert.match(root.innerHTML, /You left the test&#39;s page\. This has been recorded\./);
  assert.deepEqual(school.events.map((e) => [e.kind, e.seconds]), [["left_page", 14]]);
});

test("no screen draws an answer key, because none is sent", () => {
  const html = states.exam(examView()) + states.finished({ answered: 1, questions: 20, received: 1 });
  assert.doesNotMatch(html, /correct|explanation/i);
});

test("Safari, an iPhone, and a browser that keeps nothing are warned at the door (OPEN-6)", () => {
  const sw = { serviceWorker: {} };
  assert.equal(keepsTooLittle({ ...sw, userAgent: "Mozilla/5.0 (Macintosh) AppleWebKit Version/17 Safari/605" }, true), true);
  assert.equal(keepsTooLittle({ ...sw, userAgent: "Mozilla/5.0 (iPhone) CriOS/120 Safari/604" }, true), true);
  assert.equal(keepsTooLittle({ ...sw, userAgent: "Mozilla/5.0 (Linux; Android 14) Chrome/130 Mobile Safari/537" }, true), false);
  assert.equal(keepsTooLittle({ userAgent: "Mozilla/5.0 (Windows) Chrome/130 Safari/537" }, true), true, "no service worker");
  assert.match(states.door({ fragile: true }), /This browser may not keep your answers if the power goes off/);
  assert.doesNotMatch(states.door({}), /may not keep your answers/);
});
