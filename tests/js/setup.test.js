/**
 * School setup: the calendar and the class groups.
 *
 * Every state is a pure function of an API body, so the flow is walked without
 * a browser. What it walks is `academics/api.py`'s answer set: a 201, a 200
 * for making a term current, a 422 for a calendar that disagrees with itself,
 * a 403, and a 401 that is two states.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { applyWrite, fromSetup, htmlFor, mount } from "../../static/setup/app.js";
import { REFUSAL, SAVE, refusalFor } from "../../static/setup/api.js";
import * as states from "../../static/setup/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const SHAPE = {
  terms: [
    { term_id: 1, session: "2025/2026", name: "first", name_label: "First term", starts_on: "2025-09-15", ends_on: "2025-12-12", school_days: 62, is_current: true },
    { term_id: 2, session: "2025/2026", name: "second", name_label: "Second term", starts_on: "2026-01-12", ends_on: "2026-04-02", school_days: null, is_current: false },
  ],
  classes: [
    { class_group_id: 11, name: "JSS 1A", level: 1, is_active: true },
    { class_group_id: 12, name: "JSS 1B", level: 1, is_active: false },
  ],
  may_set_up: true,
};

const state = () => fromSetup({ ok: true, body: SHAPE });

function serve(routes) {
  return async (url, options = {}) => {
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    for (const [match, answer] of routes) {
      if (url.includes(match)) {
        const value = typeof answer === "function" ? answer(options) : answer;
        return { status: value.status, json: async () => value.body };
      }
    }
    throw new Error(`no stub for ${url}`);
  };
}

// -- the shape ---------------------------------------------------------------

test("exactly one term reads as current, and the others offer to become it", () => {
  const html = states.shape(SHAPE);

  assert.equal((html.match(/>Current</g) || []).length, 1);
  assert.match(html, /data-action="make-current"[^>]*data-term="2"/);
  assert.doesNotMatch(html, /data-action="make-current"[^>]*data-term="1"/);
});

test("a term with no declared length is blank, not nought", () => {
  // `school_days` nought and `school_days` undeclared are different answers,
  // and truthiness cannot tell them apart.
  const html = states.shape({
    ...SHAPE,
    terms: [
      { ...SHAPE.terms[0], school_days: 0 },
      { ...SHAPE.terms[1], school_days: null },
    ],
  });

  assert.match(html, /0 school days/);
  assert.match(html, /&mdash; school days/);
});

test("a class no longer taught is listed and says so", () => {
  // Kept, because old placements name it.
  const html = states.shape(SHAPE);

  assert.match(html, /JSS 1B/);
  assert.match(html, /No longer taught/);
});

test("opening a term does not offer to make it current in the same breath", () => {
  // Two decisions. A school opening next term's record while this one is being
  // taught is the ordinary case, so a checkbox defaulting either way is wrong
  // for somebody.
  const html = states.shape(SHAPE);

  assert.match(html, /data-form="term"/);
  assert.doesNotMatch(html, /name="is_current"/);
});

test("a school with nothing set up yet is told so rather than shown blank lists", () => {
  const html = states.shape({ terms: [], classes: [], may_set_up: true });

  assert.match(html, /No terms yet/);
  assert.match(html, /No class groups yet/);
  assert.match(html, /data-form="term"/);
});

// -- the writes --------------------------------------------------------------

test("a rejected term keeps the form open with the server's sentence", () => {
  // The calendar disagreeing with itself is retypable; clearing the form would
  // make them type all of it again to fix one date.
  const { state: after, reload } = applyWrite(state(), "term", {
    ok: false,
    outcome: SAVE.REJECTED,
    body: { detail: "A term cannot end before it starts." },
  });

  assert.equal(reload, false);
  assert.match(htmlFor(after), /cannot end before it starts/);
  assert.match(htmlFor(after), /data-form="term"/);
});

test("a successful write asks for the shape again rather than patching a row", async () => {
  // Making a term current changes *another* row — the one that stops being
  // current — so a page that patched only what it POSTed would show two as
  // current until somebody refreshed.
  forgetToken();
  let shapeReads = 0;
  const root = fakeRoot({ portal: "portal.example.test" });
  await mount(root, {
    fetchImpl: serve([
      ["/api/academics/terms/2/current/", { status: 200, body: { ...SHAPE.terms[1], is_current: true } }],
      ["/api/academics/setup/", () => {
        shapeReads += 1;
        return {
          status: 200,
          body: shapeReads === 1
            ? SHAPE
            : { ...SHAPE, terms: [{ ...SHAPE.terms[0], is_current: false }, { ...SHAPE.terms[1], is_current: true }] },
        };
      }],
    ]),
  });
  assert.equal(shapeReads, 1);

  await root.click({ "data-action": "make-current", "data-term": "2" });

  assert.equal(shapeReads, 2, "the shape was not re-read after a write");
  assert.equal((root.innerHTML.match(/>Current</g) || []).length, 1, "two terms read as current");
});

test("submitting the term form sends what was typed", async () => {
  forgetToken();
  const sent = [];
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/api/academics/terms/", (o) => {
        sent.push(JSON.parse(o.body));
        return { status: 201, body: SHAPE.terms[1] };
      }],
      ["/api/academics/setup/", { status: 200, body: SHAPE }],
    ]),
  });

  await root.submit({
    session: "2026/2027",
    name: "first",
    starts_on: "2026-09-14",
    ends_on: "2026-12-11",
  });

  assert.deepEqual(sent, [{
    session: "2026/2027",
    name: "first",
    starts_on: "2026-09-14",
    ends_on: "2026-12-11",
  }]);
});

test("submitting the class form sends the level the school gave it", async () => {
  // Not derived from the name: "JSS 1A" sorts before "JSS 10A" as text.
  forgetToken();
  const sent = [];
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/api/academics/classes/", (o) => {
        sent.push(JSON.parse(o.body));
        return { status: 201, body: SHAPE.classes[0] };
      }],
      ["/api/academics/setup/", { status: 200, body: SHAPE }],
    ]),
  });

  await root.submit({ name: "JSS 10A", level: "10" });

  assert.deepEqual(sent, [{ name: "JSS 10A", level: 10 }]);
});

// -- the school's contact email (docs/messaging.md D17) ----------------------

test("the contact email box holds what the school has set, blank if it has not", () => {
  const set = states.shape({ ...SHAPE, contact_email: "office@stmarys.example" });
  const unset = states.shape({ ...SHAPE, contact_email: "" });

  assert.match(set, /value="office@stmarys\.example"/);
  assert.match(unset, /id="contact_email"[^>]*value=""/);
});

test("submitting the contact email form sends what was typed", async () => {
  forgetToken();
  const sent = [];
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/api/academics/contact-email/", (o) => {
        sent.push(JSON.parse(o.body));
        return { status: 200, body: { contact_email: "office@stmarys.example" } };
      }],
      ["/api/academics/setup/", { status: 200, body: SHAPE }],
    ]),
  });

  await root.submit({ dataset: { form: "contact-email" }, contact_email: "office@stmarys.example" });

  assert.deepEqual(sent, [{ contact_email: "office@stmarys.example" }]);
});

test("an address that does not look like one keeps the form open with the server's sentence", () => {
  const { state: after, reload } = applyWrite(state(), "contact_email", {
    ok: false,
    outcome: SAVE.REJECTED,
    body: { detail: "'not-an-email' does not look like an email address." },
  });

  assert.equal(reload, false);
  assert.match(htmlFor(after), /does not look like an email address/);
  assert.match(htmlFor(after), /data-form="contact-email"/);
});

// -- refusals and hosts ------------------------------------------------------

test("403 and 404 are different page-level refusals", () => {
  assert.equal(refusalFor(403, {}), REFUSAL.NOT_THE_OFFICE);
  assert.equal(refusalFor(404, {}), REFUSAL.WRONG_HOST);
});

test("the refusal a teacher reads does not offer her the staff door", () => {
  const html = states.notTheOffice({ detail: "The calendar is set up by…" });

  assert.doesNotMatch(html, /staff-sign-in/);
  assert.match(html, /can arrange it/);
});

test("on the portal the page says where the work is", async () => {
  const root = fakeRoot({ portal: "portal.example.test" });
  await mount(root, {
    fetchImpl: serve([["/api/academics/setup/", { status: 404, body: { detail: "No calendar on this host." } }]]),
  });

  assert.match(root.innerHTML, /school's own web address/i);
  assert.doesNotMatch(root.innerHTML, /data-action="sign-out"/, "a 404 proved a session it cannot prove");
});

test("an expired session and no session are different sentences", () => {
  const expired = htmlFor({ step: REFUSAL.EXPIRED }, { portal: "portal.example.test" });
  const never = htmlFor({ step: REFUSAL.SIGNED_OUT }, { portal: "portal.example.test" });

  assert.match(expired, /session has ended/i);
  assert.match(never, /Please sign in/i);
  for (const html of [expired, never]) {
    assert.match(html, /\/\/portal\.example\.test\/staff-sign-in\//);
  }
});

test("with no portal domain there is a sentence and no link", () => {
  const html = htmlFor({ step: REFUSAL.SIGNED_OUT }, { portal: "" });

  assert.doesNotMatch(html, /<a /);
  assert.match(html, /go back to the sign-in page/i);
});

test("a class name typed into the admin cannot execute in the next reader's browser", () => {
  const html = states.shape({
    ...SHAPE,
    classes: [{ class_group_id: 11, name: '<img src=x onerror="alert(1)">', level: 1, is_active: true }],
  });

  assert.doesNotMatch(html, /<img/);
  assert.match(html, /&lt;img/);
});

// -- the school's public page ------------------------------------------------

test("the public page form holds what the school has written, and escapes it", () => {
  const html = states.shape({ ...SHAPE, about: "We <b>teach</b>.", address: "1 Ring Rd", phone: "0803 555 0100" });

  assert.match(html, /data-form="public-page"/);
  assert.match(html, /<textarea id="about"[^>]*>We &lt;b&gt;teach&lt;\/b&gt;\.<\/textarea>/);
  assert.match(html, /id="address"[^>]*value="1 Ring Rd"/);
  assert.match(html, /id="phone"[^>]*value="0803 555 0100"/);
});

test("submitting the public page form sends the three boxes", async () => {
  forgetToken();
  const sent = [];
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/api/academics/public-page/", (o) => {
        sent.push(JSON.parse(o.body));
        return { status: 200, body: { about: "Hi", address: "1 Ring Rd", phone: "0803" } };
      }],
      ["/api/academics/setup/", { status: 200, body: SHAPE }],
    ]),
  });

  await root.submit({ dataset: { form: "public-page" }, about: "Hi", address: "1 Ring Rd", phone: "0803" });

  assert.deepEqual(sent, [{ about: "Hi", address: "1 Ring Rd", phone: "0803" }]);
});

test("a refused public page keeps the form open with the server's sentence", () => {
  const { state: after, reload } = applyWrite(state(), "public_page", {
    ok: false,
    outcome: SAVE.REJECTED,
    body: { detail: "A phone number is digits, spaces and + - ( ) only." },
  });

  assert.equal(reload, false);
  assert.match(htmlFor(after), /A phone number is digits/);
});

// -- the local government area -------------------------------------------------

test("the local government area box holds the school's and offers Ogun's twenty", () => {
  const html = states.shape({ ...SHAPE, lga: "Abeokuta South", lga_choices: ["Abeokuta North", "Abeokuta South"] });

  assert.match(html, /data-form="lga"/);
  assert.match(html, /id="lga_input"[^>]*value="Abeokuta South"[^>]*list="lga_choices"/);
  assert.match(html, /<datalist id="lga_choices"><option value="Abeokuta North"><option value="Abeokuta South"><\/datalist>/);
});

test("submitting the local government area sends it", async () => {
  forgetToken();
  const sent = [];
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/api/academics/lga/", (o) => {
        sent.push(JSON.parse(o.body));
        return { status: 200, body: { lga: "Ifo" } };
      }],
      ["/api/academics/setup/", { status: 200, body: SHAPE }],
    ]),
  });

  await root.submit({ dataset: { form: "lga" }, lga: "Ifo" });

  assert.deepEqual(sent, [{ lga: "Ifo", school_code: "" }]);
});

// -- the report card template ---------------------------------------------------

const CARD = { colour: "#143D8C", default_colour: "#143D8C", has_crest: false, initials: "SM", template: "standard" };

test("the template choice says which card the school prints", () => {
  const html = states.shape({ ...SHAPE, card: { ...CARD, template: "ogun" } });

  assert.match(html, /data-form="template"/);
  assert.match(html, /value="ogun" checked/);
  assert.doesNotMatch(html, /value="standard" checked/);
  assert.match(html, /Nothing already marked or rated is changed/);
});

test("choosing Ogun sends it and says what was set up and what was kept", async () => {
  forgetToken();
  const sent = [];
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/api/academics/card/template/", (o) => {
        sent.push(JSON.parse(o.body));
        return {
          status: 200,
          body: {
            template: "ogun",
            applied: {
              assessments_set: ["English, First term 2025/2026"],
              assessments_kept: ["Mathematics, First term 2025/2026"],
              traits_added: ["Self-Control"],
              traits_renamed: [],
              traits_hidden: ["Attendance"],
              traits_kept: ["Politeness"],
            },
          },
        };
      }],
      ["/api/academics/setup/", { status: 200, body: { ...SHAPE, card: { ...CARD, template: "ogun" } } }],
    ]),
  });

  await root.submit({ dataset: { form: "template" }, template: "ogun" });

  assert.deepEqual(sent, [{ template: "ogun" }]);
  assert.match(root.innerHTML, /Report cards use the Ogun State template/);
  assert.match(root.innerHTML, /Papers set for English, First term 2025\/2026/);
  assert.match(root.innerHTML, /because marks are in: Mathematics, First term 2025\/2026/);
  assert.match(root.innerHTML, /because they have been rated: Politeness/);
});

test("a refused choice keeps the form with the server's sentence", async () => {
  forgetToken();
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/api/academics/card/template/", { status: 403, body: { detail: "The report card template is chosen by a principal." } }],
      ["/api/academics/setup/", { status: 200, body: { ...SHAPE, card: CARD } }],
    ]),
  });

  await root.submit({ dataset: { form: "template" }, template: "ogun" });

  assert.match(root.innerHTML, /template-form not-allowed/);
  assert.match(root.innerHTML, /chosen by a principal/);
});

// -- the position in class ---------------------------------------------------------

test("the position box is ticked as the school has it", () => {
  assert.match(states.shape({ ...SHAPE, card: { ...CARD, show_position: true } }), /name="show_position" checked/);
  assert.doesNotMatch(states.shape({ ...SHAPE, card: CARD }), /name="show_position" checked/);
});

test("saving the position box sends what is ticked", async () => {
  forgetToken();
  const sent = [];
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/api/academics/card/position/", (o) => {
        sent.push(JSON.parse(o.body));
        return { status: 200, body: { ...CARD, show_position: true } };
      }],
      ["/api/academics/setup/", { status: 200, body: { ...SHAPE, card: CARD } }],
    ]),
  });

  await root.submit({ dataset: { form: "position" }, show_position: { checked: true } });

  assert.deepEqual(sent, [{ show_position: true }]);
});

// -- the Ogun card's school code and subject departments -------------------------

test("the school code sits with the LGA and is sent with it", async () => {
  forgetToken();
  const sent = [];
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/api/academics/lga/", (o) => {
        sent.push(JSON.parse(o.body));
        return { status: 200, body: { lga: "Ifo", school_code: "B13003" } };
      }],
      ["/api/academics/setup/", { status: 200, body: { ...SHAPE, school_code: "B1" } }],
    ]),
  });
  assert.match(root.innerHTML, /id="school_code"[^>]*value="B1"/);

  await root.submit({ dataset: { form: "lga" }, lga: "Ifo", school_code: "B13003" });

  assert.deepEqual(sent, [{ lga: "Ifo", school_code: "B13003" }]);
});

test("an Ogun school is offered a department per subject; a Standard one is not", () => {
  const body = {
    ...SHAPE,
    subjects: [{ subject_id: 4, name: "Economics", department: "business" }],
    departments: [{ value: "general", label: "General" }, { value: "business", label: "Business" }],
  };
  const ogun = states.shape({ ...body, card: { ...CARD, template: "ogun" } });
  assert.match(ogun, /Subject departments/);
  assert.match(ogun, /data-subject="4"/);
  assert.match(ogun, /<option value="business" selected>Business<\/option>/);
  assert.doesNotMatch(states.shape({ ...body, card: CARD }), /Subject departments/);
});

test("choosing a department saves it", async () => {
  forgetToken();
  const sent = [];
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/api/academics/subjects/4/department/", (o) => {
        sent.push(JSON.parse(o.body));
        return { status: 200, body: { subject_id: 4, name: "Economics", department: "business" } };
      }],
      ["/api/academics/setup/", { status: 200, body: SHAPE }],
    ]),
  });

  await root.change({ "data-subject": "4" }, "business");

  assert.deepEqual(sent, [{ department: "business" }]);
});
