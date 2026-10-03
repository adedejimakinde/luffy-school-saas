/**
 * The register page with no connection (slice S5): it opens from the copy the
 * phone kept, says that it is a copy, and **cannot send from one** — queueing a
 * register is slice S6, and until then the taps and the submit are switched off
 * on a copy rather than offered and lost.
 *
 * Two schools throughout, with one snapshot shelf between them.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { mount, registerName, rosterFromEarlier } from "../../static/register/app.js";
import { forgetToken } from "../../static/web/http.js";
import { memorySnapshots } from "./memory_snapshots.js";
import { fakeRoot } from "./fake_dom.js";

const ST_MARYS = "st-marys.example.ng";
const GRACE = "grace.example.ng";
const KEMI = 5;
const TUNDE = 6;
const TODAY = new Date("2025-09-17T07:30:00Z");

function server(host, { names, statuses = {}, user = KEMI }) {
  const s = {
    host,
    offline: false,
    user,
    puts: 0,
    fetch: async (url, options = {}) => {
      if (s.offline) throw new TypeError("Failed to fetch");
      const reply = (status, body) => ({ status, json: async () => body });
      if (url === "/api/csrf/") return reply(200, { csrf_token: "t" });
      if (url === "/api/attendance/where/") {
        return reply(200, {
          term_id: 7,
          term: "2025/2026 First term",
          user_id: s.user,
          classes: [{ id: 11, name: "JSS 1A", level: 1 }],
        });
      }
      const hit = /^\/api\/attendance\/classes\/11\/terms\/7\/([\d-]+)\/$/.exec(url);
      if (hit && options.method === "PUT") {
        s.puts += 1;
        return reply(200, { present: [], absent: [], appeared: [], not_on_the_roster: [] });
      }
      if (hit) {
        const taken = hit[1] in statuses;
        return reply(200, {
          class_group_id: 11,
          class_group: "JSS 1A",
          term_id: 7,
          term: "2025/2026 First term",
          taken_on: hit[1],
          taken,
          rows: names.map((student, i) => ({
            student_membership_id: i + 1,
            student,
            status: taken ? (statuses[hit[1]].includes(i + 1) ? "absent" : "present") : null,
          })),
        });
      }
      throw new Error(`no stub for ${url}`);
    },
  };
  return s;
}

const schools = () => [
  server(ST_MARYS, { names: ["Ada Obi", "Emeka Nwosu"], statuses: { "2025-09-16": [2] } }),
  server(GRACE, { names: ["Funmi Bello", "Gbenga Eze"] }),
];

async function open(s, snapshots, { day = TODAY, pickClass = false } = {}) {
  forgetToken();
  const root = fakeRoot({ timeZone: "Africa/Lagos" });
  const online = [];
  let cleared = 0;
  const forms = [];
  const target = {
    addEventListener: (type, handler) => forms.push({ type, handler }),
  };
  await mount(root, {
    fetchImpl: (url, options) => s.fetch(url, options),
    now: day,
    host: s.host,
    openSnapshots: async () => snapshots,
    whenOnline: (run) => online.push(run),
    signOutTarget: target,
    clearPages: async () => (cleared += 1),
  });
  if (pickClass) await root.click({ "data-action": "open", "data-class": "11" });
  return { root, online, forms, cleared: () => cleared };
}

test("a class list opened online opens again offline, as a copy", async () => {
  for (const s of schools()) {
    const shelf = memorySnapshots(new Map());
    await open(s, shelf);
    s.offline = true;

    const page = await open(s, shelf);

    assert.match(page.root.innerHTML, /This is a copy from today 08:30\. You are not connected\./, s.host);
    assert.match(page.root.innerHTML, /JSS 1A/, s.host);
  }
});

test("a register opened today is a copy of today's, and is to look at", async () => {
  for (const s of schools()) {
    const shelf = memorySnapshots(new Map());
    const live = await open(s, shelf, { pickClass: true });
    assert.doesNotMatch(live.root.innerHTML, /This is a copy/, `${s.host}: live`);
    assert.match(live.root.innerHTML, /data-action="submit"/, `${s.host}: live can submit`);

    s.offline = true;
    const page = await open(s, shelf, { pickClass: true });

    assert.match(page.root.innerHTML, /This is a copy/, s.host);
    assert.match(page.root.innerHTML, /to look at/, s.host);
    assert.doesNotMatch(page.root.innerHTML, /data-action="submit"/, `${s.host}: nothing to send it with`);
    assert.match(page.root.innerHTML, /data-action="toggle"[^>]*disabled/, `${s.host}: taps are off`);
    await page.root.click({ "data-action": "toggle", "data-child": "1" });
    assert.equal(s.puts, 0, s.host);
  }
});

test("a day nobody opened here shows the class from the newest copy, every child unmarked", async () => {
  const [marys] = schools();
  const shelf = memorySnapshots(new Map());
  // Yesterday's register was opened, and Emeka was absent in it.
  await open(marys, shelf, { day: new Date("2025-09-16T07:30:00Z"), pickClass: true });
  marys.offline = true;

  const page = await open(marys, shelf, { day: TODAY, pickClass: true });

  assert.match(page.root.innerHTML, /This is a copy from yesterday 08:30/, "the roster is as old as it is");
  assert.match(page.root.innerHTML, /Ada Obi/);
  assert.match(page.root.innerHTML, /Emeka Nwosu/);
  assert.match(page.root.innerHTML, /2025-09-17/, "filed against the day asked for");
  assert.doesNotMatch(page.root.innerHTML, /already been taken/, "and not yesterday's marks");
  assert.match(page.root.innerHTML, /0 marked absent of 2/);
});

test("two schools: one school's class is never drawn at the other's host", async () => {
  const [marys, grace] = schools();
  const shared = memorySnapshots(new Map());
  await open(marys, shared, { pickClass: true });
  await open(grace, shared, { pickClass: true });

  marys.offline = true;
  const page = await open(marys, shared, { pickClass: true });
  assert.match(page.root.innerHTML, /Ada Obi/);
  assert.doesNotMatch(page.root.innerHTML, /Funmi Bello|Gbenga Eze/);

  const lonely = memorySnapshots(new Map());
  marys.offline = false;
  await open(marys, lonely, { pickClass: true });
  grace.offline = true;
  const strange = await open(grace, lonely);
  assert.doesNotMatch(strange.root.innerHTML, /Ada Obi|This is a copy|JSS 1A/);
});

test("two people: Tunde is not shown a class only Kemi opened", async () => {
  const [marys] = schools();
  const shelf = memorySnapshots(new Map());
  await open(marys, shelf, { pickClass: true }); // Kemi opens JSS 1A today.
  marys.user = TUNDE;
  await open(marys, shelf); // Tunde, online, opens the list.

  marys.offline = true;
  const page = await open(marys, shelf, { pickClass: true });

  assert.doesNotMatch(page.root.innerHTML, /Ada Obi|Emeka Nwosu/);
});

test("the copy is dropped at sign-out, and the cached pages with it", async () => {
  for (const s of schools()) {
    const shelf = memorySnapshots(new Map());
    const page = await open(s, shelf, { pickClass: true });
    const submit = page.forms.find((f) => f.type === "submit").handler;
    const form = { action: "/sign-out/", submitted: 0, submit() { this.submitted += 1; } };

    await submit({ target: form, preventDefault() {} });

    assert.equal(form.submitted, 1, s.host);
    assert.equal(page.cleared(), 1, s.host);
    assert.equal(await shelf.copy(s.host, KEMI, "where"), null, s.host);
    assert.equal(await shelf.copy(s.host, KEMI, registerName(11, 7, "2025-09-17")), null, s.host);
  }
});

test("a roster from an earlier day has no statuses and says when it was seen", () => {
  assert.equal(rosterFromEarlier([], "2025-09-17"), null);
  const found = rosterFromEarlier(
    [{ name: "x", at: "T0", body: { class_group_id: 11, taken: true, rows: [{ student_membership_id: 1, student: "A", status: "absent" }] } }],
    "2025-09-17",
  );
  assert.equal(found.asOf, "T0");
  assert.equal(found.body.taken, false);
  assert.equal(found.body.taken_on, "2025-09-17");
  assert.deepEqual(found.body.rows, [{ student_membership_id: 1, student: "A", status: null }]);
});
