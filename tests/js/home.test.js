/**
 * The principal's home: four figures, what is waiting, and today.
 *
 * Every state is a pure function of `GET /api/home/`'s body. What is asserted
 * above all is that **nothing here acts**: each waiting row is a link, and the
 * one whose button says Release goes to the results page, where releasing asks
 * first.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { fromHome, htmlFor, mount } from "../../static/home/app.js";
import { REFUSAL, refusalFor } from "../../static/home/api.js";
import * as states from "../../static/home/states.js";
import { fakeRoot } from "./fake_dom.js";

const HOME = {
  school: "Sunrise Demo Academy",
  term_id: 7,
  term: "2026/2027 First term",
  today: "2026-09-23",
  released: { released: 3, classes: 8 },
  fees: { collected_kobo: 1_840_000_000, billed_kobo: 2_610_000_000 },
  absent: { children: 7, threshold_percent: 20, min_marked_days: 5 },
  present: {
    today: { on: "2026-09-23", present: 412, marked: 438 },
    week: [
      { on: "2026-09-21", present: 400, marked: 438 },
      { on: "2026-09-22", present: 405, marked: 438 },
      { on: "2026-09-23", present: 412, marked: 438 },
    ],
    registers: 6,
    classes: 8,
  },
  waiting: [
    { kind: "release", class_group_id: 11, class_group: "JSS 1A", days: 2, missing: null, href: "/results/?class=11" },
    { kind: "remarks", class_group_id: 12, class_group: "JSS 1B", days: 5, missing: 4, href: "/comments/?class=12" },
    { kind: "sent_back", class_group_id: 13, class_group: "SS 1", days: 1, missing: null, href: "/results/?class=13" },
  ],
  happened: {
    registers: 6,
    classes: 8,
    payments: 3,
    steps: [{ at: "10:15", text: "JSS 1A approved" }],
  },
};

// -- the figures ---------------------------------------------------------------

test("a naira figure is short enough never to wrap, and rounds in whole units", () => {
  const cases = [
    [0, "₦0"],
    [95_000, "₦950"],
    [99_960, "₦1k"],
    [100_000, "₦1k"],
    [1_234_500, "₦12.3k"],
    [99_995_000, "₦1m"],
    [1_840_000_000, "₦18.4m"],
    [18_400_000_000, "₦184m"],
    [120_000_000_000, "₦1.2bn"],
    [-1_840_000_000, "₦18.4m"],
  ];
  for (const [kobo, expected] of cases) {
    assert.equal(states.shortNaira(kobo), expected, `${kobo} kobo`);
  }
});

test("fees: the collected figure alone on the value line, billed in the subline", () => {
  const html = states.home(HOME);
  const fees = html.slice(html.indexOf("Fees collected"));

  assert.match(fees, /<span class="stat-value">₦18\.4m<\/span>/);
  assert.match(fees, /<span class="stat-foot">of ₦26\.1m billed<\/span>/);
  // The exact figures are still there, for whoever wants them.
  assert.match(html, /title="₦18,400,000\.00 of ₦26,100,000\.00"/);
});

test("nothing billed says so rather than dividing by it", () => {
  const html = states.home({ ...HOME, fees: { collected_kobo: 0, billed_kobo: 0 } });

  assert.match(html, /Nothing billed this term yet/);
  assert.match(html, /<span style="width: 0%">/);
});

test("present today is out of who was marked, with the week beside it", () => {
  const html = states.home(HOME);

  assert.match(html, /<span class="stat-value">94%<\/span>/);
  assert.match(html, /412 of 438 marked present/);
  assert.equal((html.match(/<div class="minibars"[^>]*>(.*?)<\/div>/)[1].match(/<span/g) || []).length, 3);
  assert.match(html, /<span class="today" style="height: 94%">/);
});

test("no register yet today is a dash, not a zero", () => {
  const html = states.home({
    ...HOME,
    present: { ...HOME.present, today: { on: "2026-09-23", present: 0, marked: 0 }, week: [] },
  });

  assert.match(html, /Present today<\/span><span class="stat-value">—<\/span>/);
  assert.match(html, /No register taken yet today/);
  assert.doesNotMatch(html, /0%<\/span>/);
});

test("with no current term the term's figures are dashes that say why", () => {
  const html = states.home({ ...HOME, term_id: null, term: null, released: null, fees: null, absent: null });

  assert.equal((html.match(/No term is open/g) || []).length, 3);
});

test("absent too often carries its label and its rule", () => {
  assert.match(states.home(HOME), /7 <small>pupils<\/small>.*label-stop">Needs a look/);
  assert.match(states.home(HOME), /Absent on 20% or more of marked days/);
  assert.match(
    states.home({ ...HOME, absent: { ...HOME.absent, children: 0 } }),
    /label-ok">None/,
  );
});

// -- waiting for you ------------------------------------------------------------

test("every row's action is a link, and nothing on the page releases", () => {
  const html = states.waiting(HOME.waiting);

  assert.doesNotMatch(html, /<button/);
  assert.doesNotMatch(html, /data-action/);
  assert.match(
    html,
    /<a class="btn row-btn primary" href="\/results\/\?class=11"><span>Release<\/span>/,
  );
});

test("remarks missing opens the remarks page for that class, and says how many", () => {
  const html = states.waiting(HOME.waiting);

  assert.match(html, /Remarks missing <span class="label label-warn">4 pupils<\/span>/);
  assert.match(html, /<a class="btn row-btn" href="\/comments\/\?class=12"><span>Open<\/span>/);
});

test("sent back opens that class's results", () => {
  const html = states.waiting(HOME.waiting);

  assert.match(html, /Sent back by you/);
  assert.match(html, /href="\/results\/\?class=13"><span>Open<\/span>/);
});

test("each row carries the parts a phone stacks: class, days, what, button", () => {
  // Below 640px `home.css` lays these out as class and days, then what, then
  // the button across the row. The days' unit is in the markup for that
  // layout, where no column header is left to name it.
  const html = states.waiting(HOME.waiting);
  const first = html.slice(html.indexOf("<tr data-kind"), html.indexOf("</tr>", html.indexOf("<tr data-kind")));

  for (const cell of ['class="class"', 'class="what"', 'class="num days"', 'class="act"']) {
    assert.match(first, new RegExp(cell), cell);
  }
  assert.match(first, /2<span class="unit"> days<\/span>/);
  assert.match(states.waiting([{ ...HOME.waiting[0], days: 1 }]), /1<span class="unit"> day<\/span>/);
});

test("a button names its class to a screen reader", () => {
  assert.match(states.waiting(HOME.waiting), /<span class="sr"> JSS 1A<\/span>/);
});

test("nothing waiting says so, and where the work is", () => {
  const html = states.waiting([]);

  assert.match(html, /Nothing waiting/);
  assert.match(html, /<a class="btn" href="\/results\/">Open results<\/a>/);
  assert.doesNotMatch(html, /<table/);
});

test("a class name typed into the admin cannot execute here", () => {
  const html = states.waiting([{ ...HOME.waiting[0], class_group: '<img src=x onerror="alert(1)">' }]);

  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
});

// -- today ----------------------------------------------------------------------

test("today: registers, payments, and each step with its time", () => {
  const html = states.today(HOME.happened, HOME.today);

  assert.match(html, /Registers: 6 of 8 classes taken <span class="label label-warn">2 left<\/span>/);
  assert.match(html, /3 payments recorded/);
  assert.match(html, /<time>10:15<\/time><span>JSS 1A approved<\/span>/);
});

test("a weekend with no register does not nag about registers", () => {
  const saturday = states.today({ ...HOME.happened, registers: 0 }, "2026-09-26");
  const wednesday = states.today({ ...HOME.happened, registers: 0 }, "2026-09-23");

  assert.doesNotMatch(saturday, /Registers:/);
  assert.match(wednesday, /Registers: 0 of 8 classes taken/);
});

// -- the door -------------------------------------------------------------------

test("each answer is its own state", () => {
  assert.equal(refusalFor(403, {}), REFUSAL.NOT_YOURS);
  assert.equal(refusalFor(404, {}), REFUSAL.WRONG_HOST);
  assert.equal(refusalFor(401, { code: "session_expired" }), REFUSAL.EXPIRED);
  assert.equal(refusalFor(401, {}), REFUSAL.SIGNED_OUT);
  assert.equal(refusalFor(500, {}), REFUSAL.BROKEN);
});

test("a bursar is told the page is not theirs, in the server's sentence", () => {
  const html = htmlFor(fromHome({ ok: false, refusal: REFUSAL.NOT_YOURS, body: { detail: "This page is the principal's and the vice principal's." } }));

  assert.match(html, /This page is not yours/);
  assert.match(html, /principal&#39;s and the vice principal&#39;s|principal's and the vice principal's/);
  assert.doesNotMatch(html, /staff-sign-in/);
});

test("mount draws the home from one fetch", async () => {
  const root = fakeRoot({ portal: "portal.example.test" });
  const seen = [];
  await mount(root, {
    fetchImpl: async (url) => {
      seen.push(url);
      return { status: 200, json: async () => HOME };
    },
  });

  assert.deepEqual(seen, ["/api/home/"]);
  assert.match(root.innerHTML, /<h1>Home<\/h1>/);
  assert.match(root.innerHTML, /Sunrise Demo Academy &middot; 2026\/2027 First term/);
  assert.match(root.innerHTML, /Waiting for you/);
});

test("on the portal the page says where it lives, and offers no sign-out", async () => {
  const root = fakeRoot({ portal: "portal.example.test" });
  await mount(root, { fetchImpl: async () => ({ status: 404, json: async () => ({ detail: "No school on this host." }) }) });

  assert.match(root.innerHTML, /school's own web address/);
  assert.doesNotMatch(root.innerHTML, /sign-out/);
});

test("no em dash in any sentence the home draws", () => {
  // `docs/design.md`: a dash is allowed only as "nothing to show".
  const html = states.home(HOME) + states.notYours({}) + states.wrongHost() + states.signedOut({}) + states.broken();
  assert.doesNotMatch(html.replace(/<span class="stat-value">—<\/span>/g, ""), /—/);
});
