/**
 * `/sit/`: the exam door, the exam screen and the finished screen.
 *
 * `docs/cbt.md`, step 4. The school is the timekeeper and the record; this page is the
 * student's copy of the attempt and its outbox:
 *
 * - **Every choice is kept on this computer first** (`outbox.js`, IndexedDB), then sent,
 *   and resent until the school acknowledges it. A reload, or a power cut, reopens the
 *   attempt from the kept copy, with or without a network.
 * - **The clock counts down to the server's deadline** on this device's monotonic clock
 *   (`clock.js`), resynced by every answer the school sends back; extra time a teacher
 *   gives arrives the same way. At 00:00 it stops taking answers and submits.
 * - **Leaving the exam's tab or window** is told to the student ("This has been
 *   recorded") and sent to the school, which shows the count in the sitting log.
 * - A small service worker (`/sit/sw.js`) keeps this page and its files, and nothing
 *   outside `/sit/`.
 *
 * `mount()` takes everything it touches (fetch, storage, timers, the window), so
 * `tests/js/sit.test.js` drives it with no browser.
 */

import * as api from "./api.js";
import { keyFor, press, START } from "./calculator.js";
import { makeClock, spokenLeft, WARN_MS } from "./clock.js";
import { idbStorage, makeOutbox } from "./outbox.js";
import * as states from "./states.js";

/** Every 20 seconds, as `docs/cbt.md` says the server listens for. */
export const HEARTBEAT_MS = 20_000;
/** A choice is sent this soon after it is kept, so a run of quick clicks is one request. */
export const SEND_SOON_MS = 400;
/** After the time is up and the school cannot be reached, it is asked again this often. */
export const RETRY_MS = 5_000;

/** A short description of this seat for the sitting log: browser, system and width. */
export function seatOf(nav = globalThis.navigator, screen = globalThis.screen) {
  const agent = (nav && nav.userAgent) || "";
  const browser = /Edg\//.test(agent) ? "Edge" : /Chrome\//.test(agent) ? "Chrome" : /Firefox\//.test(agent) ? "Firefox" : /Safari\//.test(agent) ? "Safari" : "A browser";
  const system = /Android/.test(agent) ? "Android" : /iPhone|iPad/.test(agent) ? "iOS" : /Windows/.test(agent) ? "Windows" : /Mac OS/.test(agent) ? "macOS" : /Linux/.test(agent) ? "Linux" : "";
  const width = screen && screen.width ? `, ${screen.width}px` : "";
  return `${browser}${system ? ` on ${system}` : ""}${width}`.slice(0, 80);
}

/**
 * A browser that may delete what this page keeps (`docs/offline.md` OPEN-6): Safari, and
 * every browser on an iPhone or iPad, clear a site's stored data on their own terms, and
 * a browser with no IndexedDB or no service worker keeps nothing through a power cut.
 * `marking/app.js`'s rule, and the door says so.
 */
export function keepsTooLittle(nav = globalThis.navigator, hasStorage = typeof indexedDB !== "undefined") {
  const agent = (nav && nav.userAgent) || "";
  if (/iPhone|iPad|iPod/.test(agent)) return true;
  if (/Safari\//.test(agent) && !/(Chrome|Chromium|CriOS|Edg|OPR|Android)/.test(agent)) return true;
  return !hasStorage || !(nav && nav.serviceWorker);
}

function schoolOf(root) {
  const d = root.dataset || {};
  return { name: d.school || "", crest: d.crest || "", initials: d.initials || "" };
}

export function mount(
  root,
  {
    fetchImpl = (...a) => fetch(...a),
    storage = idbStorage(),
    clock = makeClock(),
    win = typeof window !== "undefined" ? window : null,
    doc = typeof document !== "undefined" ? document : null,
    setTimer = (fn, ms) => setTimeout(fn, ms),
    setTicker = (fn, ms) => setInterval(fn, ms),
    clearTicker = (id) => clearInterval(id),
    onLine = () => (typeof navigator === "undefined" ? true : navigator.onLine !== false),
    monotonic = () => (typeof performance !== "undefined" ? performance.now() : Date.now()),
  } = {},
) {
  const school = schoolOf(root);
  const outbox = makeOutbox(storage);
  let state = { step: "loading", school };
  let ticker = null;
  let beat = null;
  let soon = null;
  let leftAt = null;
  let sending = false;
  let again = false;
  let spoken = "";

  // -- drawing --------------------------------------------------------------------

  const leftMs = () => (state.deadline ? Date.parse(state.deadline) - clock.serverNow() : 0);

  const view = () => ({
    school,
    title: state.paper.title,
    student: state.student,
    items: state.paper.items,
    answers: state.answers,
    flags: state.flags,
    current: state.current,
    leftMs: leftMs(),
    online: state.online,
    calculator: Boolean(state.paper.calculator),
    calcOpen: state.calcOpen,
    calc: state.calc,
    canGoBack: state.paper.can_go_back !== false,
    grid: state.paper.grid !== false,
    asking: state.asking,
    leftWarning: state.leftWarning,
    closed: state.closed,
    timeUp: state.timeUp,
  });

  function htmlFor() {
    switch (state.step) {
      case "door":
        return states.door({ school, code: state.code, number: state.number, detail: state.detail, fragile: keepsTooLittle() });
      case "confirm":
        return states.confirm({ school, ...state.confirm, busy: state.busy, detail: state.detail });
      case "exam":
        return states.exam(view());
      case "finished":
        return states.finished({ school, ...state.finished });
      case "waiting":
        return states.waitingToSend({ school });
      case "replaced":
        return states.replaced({ school });
      case "not-me":
        return states.notMe({ school });
      case "guardian":
        return states.guardian();
      case "broken":
        return states.broken(state.detail);
      default:
        return '<p class="state state-loading">Loading the test&hellip;</p>';
    }
  }

  let shownQuestion = null;

  function draw() {
    const active = doc && doc.activeElement;
    const keep = active && active.dataset ? { action: active.dataset.action, index: active.dataset.index, option: active.dataset.option } : null;
    root.innerHTML = htmlFor();
    if (!root.querySelector) return;
    if (state.step === "exam" && state.asking) {
      const yes = root.querySelector('.sit-dialog [data-action="submit"]');
      if (yes && yes.focus) yes.focus();
      return;
    }
    if (state.step === "exam" && shownQuestion !== state.current) {
      // The phone's strip keeps the question shown in view.
      shownQuestion = state.current;
      const tile = root.querySelector(".sit-strip .current");
      const strip = tile && tile.parentElement;
      if (strip && strip.scrollTo) strip.scrollTo({ left: Math.max(0, tile.offsetLeft - strip.clientWidth / 2 + tile.clientWidth / 2) });
    }
    if (!keep || !keep.action) return;
    const selector = `[data-action="${keep.action}"]${keep.index !== undefined ? `[data-index="${keep.index}"]` : ""}${keep.option !== undefined ? `[data-option="${keep.option}"]` : ""}`;
    const again = root.querySelector(selector);
    if (again && again.focus) again.focus({ preventScroll: true });
  }

  /** The countdown, without drawing the page again. */
  function tick() {
    if (state.step !== "exam") return;
    const left = leftMs();
    const warn = left <= WARN_MS;
    if (warn !== state.warned) {
      state.warned = warn;
      draw();
    } else if (root.querySelectorAll) {
      for (const shown of root.querySelectorAll("[data-timer-value]")) shown.textContent = formatNow(left);
    }
    const said = spokenLeft(left);
    if (said !== spoken && root.querySelector) {
      spoken = said;
      const timer = root.querySelector("[data-timer]");
      if (timer) timer.setAttribute("aria-label", said);
    }
    if (left <= 0 && !state.timeUp) finish({ byClock: true });
  }

  const formatNow = (left) => states.timer(left).match(/data-timer-value>([^<]*)</)[1];

  // -- the school's answers ----------------------------------------------------------

  /** A payload from `start/` or `attempt/`, merged with what this computer still holds. */
  async function enter(payload, sentAt) {
    clock.sync(payload.now, sentAt);
    const kept = await outbox.attempt();
    const sameSession = kept && kept.session === payload.attempt.session;
    const pending = sameSession ? await outbox.pending() : [];
    const answers = { ...payload.answers };
    for (const a of pending) answers[String(a.item)] = a.chosen;
    const attempt = {
      session: payload.attempt.session,
      attemptId: payload.attempt.id,
      paper: payload.paper,
      student: payload.student,
      deadline: payload.deadline,
      lateWindow: payload.late_window,
      answers,
      flags: sameSession ? kept.flags || [] : [],
      current: sameSession ? kept.current || 0 : 0,
      offset: clock.offset(),
      submitting: sameSession ? Boolean(kept.submitting) : false,
    };
    await outbox.keep(attempt);
    if (payload.replaced) return show({ step: "replaced" });
    if (payload.closed) return closedByTheSchool(payload, attempt);
    begin(attempt);
    if (attempt.submitting) finish({ byClock: false });
    return null;
  }

  function begin(attempt) {
    state = {
      step: "exam",
      school,
      paper: attempt.paper,
      student: attempt.student,
      deadline: attempt.deadline,
      answers: attempt.answers || {},
      flags: attempt.flags || [],
      current: Math.min(attempt.current || 0, attempt.paper.items.length - 1),
      online: onLine(),
      calcOpen: false,
      calc: START,
      asking: false,
      leftWarning: false,
      closed: false,
      timeUp: false,
      warned: false,
    };
    draw();
    if (ticker === null) ticker = setTicker(tick, 1000);
    if (beat === null) beat = setTicker(() => flush(), HEARTBEAT_MS);
    tick();
    flush();
  }

  function stop() {
    if (ticker !== null) clearTicker(ticker);
    if (beat !== null) clearTicker(beat);
    ticker = beat = null;
  }

  function show(next) {
    stop();
    state = { school, ...next };
    draw();
    return null;
  }

  async function forget() {
    await outbox.clear();
    if (typeof caches !== "undefined" && caches.delete) {
      try {
        await caches.delete("sit-pictures");
      } catch {
        // Nothing kept, or nothing to clear.
      }
    }
  }

  async function closedByTheSchool(body, kept = null) {
    const attempt = kept || (await outbox.attempt());
    const items = attempt ? attempt.paper.items.length : 0;
    const answered = attempt ? Object.values(attempt.answers || {}).filter((v) => v !== null && v !== undefined).length : 0;
    await forget();
    return show({
      step: "finished",
      finished: {
        name: attempt ? attempt.student.name : "",
        title: attempt ? attempt.paper.title : "",
        submittedAt: body.submitted_at,
        answered,
        questions: items,
        received: body.received ?? null,
        byClock: body.ended_by === "clock",
      },
    });
  }

  function setOnline(online) {
    if (state.step !== "exam" || online === state.online) return;
    state.online = online;
    outbox.note({ kind: online ? "reconnect" : "disconnect", at: Math.round(clock.serverNow()) });
    draw();
  }

  /** Send what the outbox holds; the heartbeat too, when it holds nothing. */
  async function flush() {
    if (state.step !== "exam") return null;
    if (sending) {
      // A send is on its way; what was kept since goes straight after it.
      again = true;
      return null;
    }
    sending = true;
    again = false;
    try {
      const answers = await outbox.pending();
      const events = await outbox.events();
      const sentAt = monotonic();
      const answer = await api.sync({ answers, events, fetchImpl });
      if (answer.status === 0) {
        setOnline(false);
        return null;
      }
      if (answer.status === 401) {
        await forget();
        return show({ step: "door", detail: "", code: "", number: "" });
      }
      if (answer.status !== 200) return null;
      setOnline(true);
      await outbox.acknowledge(answer.body.acks || [], answer.body.event_acks || []);
      clock.sync(answer.body.now, sentAt);
      if (answer.body.deadline && answer.body.deadline !== state.deadline) {
        state.deadline = answer.body.deadline;
        tick();
      }
      await outbox.update(() => ({ offset: clock.offset(), deadline: state.deadline }));
      if (answer.body.replaced) return show({ step: "replaced" });
      if (answer.body.closed) return closedByTheSchool(answer.body);
      return answer.body;
    } finally {
      sending = false;
      if (again && state.step === "exam") {
        again = false;
        await flush();
      }
    }
  }

  function sendSoon() {
    if (soon) return;
    soon = setTimer(() => {
      soon = null;
      flush();
    }, SEND_SOON_MS);
  }

  /** Submit: the outbox, then the close. By the clock at 00:00, or by the student. */
  async function finish({ byClock = false } = {}) {
    if (state.step !== "exam") return null;
    state.closed = true;
    state.asking = false;
    state.timeUp = byClock;
    draw();
    await outbox.update(() => ({ submitting: true }));
    const kept = await outbox.attempt();
    for (;;) {
      while (sending) await new Promise((done) => setTimer(done, 50));
      const answers = await outbox.pending();
      const events = await outbox.events();
      const answer = await api.submit({ answers, events, byClock, fetchImpl });
      if (answer.status === 200) {
        const items = kept ? kept.paper.items.length : 0;
        const answered = kept ? Object.values(kept.answers || {}).filter((v) => v !== null && v !== undefined).length : 0;
        const started = kept && kept.startedAt ? Date.parse(kept.startedAt) : null;
        await forget();
        return show({
          step: "finished",
          finished: {
            name: kept ? kept.student.name : "",
            title: kept ? kept.paper.title : "",
            submittedAt: answer.body.submitted_at,
            answered,
            questions: answer.body.questions || items,
            received: answer.body.received,
            byClock: byClock || answer.body.ended_by === "clock",
            minutes: started ? Math.max(1, Math.round((Date.parse(answer.body.submitted_at) - started) / 60000)) : null,
          },
        });
      }
      if (answer.status === 409 && answer.body.replaced) return show({ step: "replaced" });
      if (answer.status === 401) {
        await forget();
        return show({ step: "door", detail: "", code: "", number: "" });
      }
      if (answer.status !== 0) {
        state.closed = false;
        state.timeUp = false;
        draw();
        return null;
      }
      // Not reachable: the answers stay kept, and the page asks again.
      if (state.step === "exam") show({ step: "waiting" });
      await new Promise((done) => setTimer(done, RETRY_MS));
    }
  }

  // -- what the student does --------------------------------------------------------------

  function item() {
    return state.paper.items[state.current];
  }

  async function choose(optionIndex) {
    if (state.step !== "exam" || state.closed || leftMs() <= 0) return;
    const it = item();
    state.answers = { ...state.answers, [String(it.id)]: Number(optionIndex) };
    draw();
    await outbox.choose(it.id, Number(optionIndex), Math.round(clock.serverNow()));
    sendSoon();
  }

  function go(index) {
    if (state.step !== "exam") return;
    const last = state.paper.items.length - 1;
    const next = Math.max(0, Math.min(last, index));
    if (next < state.current && state.paper.can_go_back === false) return;
    state.current = next;
    draw();
    outbox.update(() => ({ current: next }));
  }

  function flag() {
    if (state.step !== "exam") return;
    const id = item().id;
    state.flags = state.flags.includes(id) ? state.flags.filter((f) => f !== id) : [...state.flags, id];
    draw();
    const flags = state.flags;
    outbox.update(() => ({ flags }));
  }

  function calcPress(key) {
    state.calc = press(state.calc, key);
    if (root.querySelector) {
      const shown = root.querySelector(".sit-calc-shown");
      if (shown) {
        shown.textContent = state.calc.shown;
        return;
      }
    }
    draw();
  }

  function left() {
    if (state.step !== "exam" || leftAt !== null) return;
    leftAt = { server: clock.serverNow(), at: monotonic() };
  }

  function back() {
    if (leftAt === null) return;
    const seconds = Math.max(0, Math.round((monotonic() - leftAt.at) / 1000));
    const at = Math.round(leftAt.server);
    leftAt = null;
    if (state.step !== "exam") return;
    state.leftWarning = true;
    draw();
    outbox.note({ kind: "left_page", at, seconds });
    sendSoon();
  }

  function onKey(event) {
    if (state.step !== "exam" || event.ctrlKey || event.metaKey || event.altKey) return;
    const target = event.target || {};
    if (target.tagName === "INPUT" || target.tagName === "TEXTAREA") return;
    if (state.asking) {
      if (event.key === "Escape") {
        state.asking = false;
        draw();
      }
      return;
    }
    if (state.calcOpen) {
      const key = keyFor(event.key);
      if (key && !/^[a-wyz]$/i.test(event.key)) {
        if (event.preventDefault) event.preventDefault();
        if (event.key === "Escape") {
          state.calcOpen = false;
          draw();
          return;
        }
        calcPress(key);
        return;
      }
    }
    const k = String(event.key || "").toUpperCase();
    const at = states.LETTERS.indexOf(k);
    if (k.length === 1 && at >= 0 && at < item().options.length) {
      if (event.preventDefault) event.preventDefault();
      choose(item().options[at].index);
    } else if (k === "N") go(state.current + 1);
    else if (k === "P") go(state.current - 1);
    else if (k === "F") flag();
  }

  // -- events -----------------------------------------------------------------------

  root.addEventListener("submit", async (event) => {
    const form = event.target;
    if (event.preventDefault) event.preventDefault();
    if (!form || !form.dataset || form.dataset.form !== "door") return;
    const code = form.code.value;
    const number = form.number.value;
    const pin = form.pin.value;
    const answer = await api.door({ code, number, pin, fetchImpl });
    if (answer.status === 200) {
      return show({
        step: "confirm",
        ticket: answer.body.ticket,
        confirm: { who: answer.body.student, test: answer.body.test, resuming: answer.body.resuming, minutesLeft: answer.body.minutes_left },
      });
    }
    const detail = answer.status === 0 ? "This computer cannot reach the school. Check the connection and try again." : answer.body.detail || "That did not work. Try again.";
    return show({ step: "door", code, number, detail });
  });

  root.addEventListener("click", async (event) => {
    const hit = event.target && event.target.closest ? event.target.closest("[data-action]") : null;
    if (!hit) return null;
    const { action } = hit.dataset;
    if (action === "start" && state.step === "confirm") {
      state.busy = true;
      draw();
      const sentAt = monotonic();
      const answer = await api.start({ ticket: state.ticket, seat: seatOf(), syncOffsetMs: 0, fetchImpl });
      if (answer.status === 200) {
        await enter(answer.body, sentAt);
        await outbox.update(() => ({ startedAt: answer.body.attempt.started_at }));
        return null;
      }
      state.busy = false;
      state.detail = answer.status === 0 ? "This computer cannot reach the school. Try again." : answer.body.detail || "That did not work.";
      return draw();
    }
    if (action === "not-me" && state.step === "confirm") {
      await api.notMe({ ticket: state.ticket, fetchImpl });
      await forget();
      return show({ step: "not-me" });
    }
    if (action === "done") {
      await forget();
      return show({ step: "door", code: "", number: "", detail: "" });
    }
    if (state.step !== "exam") return null;
    if (action === "choose") return choose(hit.dataset.option);
    if (action === "next") return go(state.current + 1);
    if (action === "prev") return go(state.current - 1);
    if (action === "go") return go(Number(hit.dataset.index));
    if (action === "flag") return flag();
    if (action === "calculator") {
      state.calcOpen = !state.calcOpen;
      return draw();
    }
    if (action === "calc") return calcPress(hit.dataset.calc);
    if (action === "ask-submit") {
      state.asking = true;
      return draw();
    }
    if (action === "keep") {
      state.asking = false;
      return draw();
    }
    if (action === "submit") return finish({ byClock: false });
    if (action === "dismiss-left") {
      state.leftWarning = false;
      return draw();
    }
    return null;
  });

  if (doc && doc.addEventListener) {
    doc.addEventListener("keydown", onKey);
    doc.addEventListener("visibilitychange", () => (doc.hidden ? left() : back()));
  }
  if (win && win.addEventListener) {
    win.addEventListener("blur", left);
    win.addEventListener("focus", back);
    win.addEventListener("online", () => {
      setOnline(true);
      flush();
    });
    win.addEventListener("offline", () => setOnline(false));
  }

  // -- opening --------------------------------------------------------------------------

  async function open() {
    if (root.dataset && root.dataset.guardian) return show({ step: "guardian" });
    const kept = await outbox.attempt();
    const sentAt = monotonic();
    const answer = await api.attempt({ fetchImpl });
    if (answer.status === 200) return enter(answer.body, sentAt);
    if (answer.status === 409 && answer.body.replaced) return show({ step: "replaced" });
    if (answer.status === 0 && kept) {
      // No network: the kept copy, on the kept offset. The school decides when it hears.
      clock.fromKept(kept.offset);
      begin(kept);
      setOnline(false);
      return null;
    }
    if (kept) await forget();
    return show({ step: "door", code: "", number: "", detail: "" });
  }

  const ready = open();
  return {
    ready,
    state: () => state,
    flush,
    finish,
    choose,
    go,
    flag,
    tick,
    onKey,
    left,
    back,
    outbox,
    stop,
  };
}

/** The page's own worker, scoped to `/sit/`: the page and its files, with no network. */
export function registerWorker(nav = globalThis.navigator) {
  if (!nav || !nav.serviceWorker || !nav.serviceWorker.register) return null;
  return nav.serviceWorker.register("/sit/sw.js", { scope: "/sit/" }).catch(() => null);
}

if (typeof document !== "undefined") {
  const root = document.getElementById("sit");
  if (root) {
    mount(root);
    registerWorker();
  }
}
