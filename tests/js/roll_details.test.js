/**
 * A child's details, in a panel on the roll: learner's ID, sex, date of birth
 * and passport photo (`accounts/enrolment_api.py`'s details and photo routes).
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { applyDetails, mount } from "../../static/roll/app.js";
import { SAVE } from "../../static/roll/api.js";
import * as states from "../../static/roll/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const ROLL = {
  term_id: 7,
  term: "2025/2026 First term",
  children: [
    {
      student_membership_id: 1, student: "Ada Obi", username: "STM/1", reference: "0042",
      class_group_id: 11, class_group: "JSS 1A", learner_id: "OG/ABS/0042",
    },
  ],
  classes: [{ class_group_id: 11, name: "JSS 1A" }],
  may_admit: true,
  may_place: true,
};

const DETAILS = {
  student_membership_id: 1,
  student: "Ada Obi",
  learner_id: "OG/ABS/0042",
  sex: "female",
  date_of_birth: "2013-05-02",
  has_photo: true,
  photo_version: "171",
  may_edit: true,
};

function serve(routes) {
  return async (url, options = {}) => {
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    for (const [match, answer] of routes) {
      if (url.includes(match)) {
        const value = typeof answer === "function" ? answer(options, url) : answer;
        return { status: value.status, json: async () => value.body };
      }
    }
    throw new Error(`no stub for ${url}`);
  };
}

test("each row offers its details and shows the learner's ID", () => {
  const html = states.roll(ROLL);

  assert.match(html, /data-action="details" data-child="1"/);
  assert.match(html, /data-label="Learner ID">OG\/ABS\/0042</);
});

test("the office sees the forms, filled in, and the photo", () => {
  const html = states.detailsPanel({ body: DETAILS });

  assert.match(html, /Details of Ada Obi/);
  assert.match(html, /name="learner_id" value="OG\/ABS\/0042"/);
  assert.match(html, /<option value="female" selected>Female<\/option>/);
  assert.match(html, /name="date_of_birth" type="date" value="2013-05-02"/);
  assert.match(html, /src="\/api\/enrolment\/roll\/1\/photo\/\?v=171"/);
  assert.match(html, /data-action="remove-photo"/);
});

test("with no photo it says so and offers no remove", () => {
  const html = states.detailsPanel({ body: { ...DETAILS, has_photo: false } });

  assert.match(html, /No photo yet/);
  assert.doesNotMatch(html, /data-action="remove-photo"/);
});

test("a reader who may not edit sees the details as text and no form", () => {
  const html = states.detailsPanel({ body: { ...DETAILS, may_edit: false } });

  assert.doesNotMatch(html, /data-form="details"/);
  assert.doesNotMatch(html, /data-form="photo"/);
  assert.match(html, /<dd>OG\/ABS\/0042<\/dd>/);
  assert.match(html, /<dd>Female<\/dd>/);
});

test("what a school typed is escaped", () => {
  const html = states.detailsPanel({ body: { ...DETAILS, learner_id: '"><script>x</script>' } });

  assert.doesNotMatch(html, /<script>/);
});

test("a refused save keeps what was typed and says why, under that form", () => {
  const state = applyDetails(
    { step: "roll", details: { childId: 1, body: DETAILS } },
    1,
    { ok: false, outcome: SAVE.REJECTED, body: { detail: "A date of birth cannot be in the future." } },
    { form: "details", typed: { learner_id: "OG/9", sex: "male", date_of_birth: "2099-01-01" } },
  );

  const html = states.detailsPanel(state.details);

  assert.match(html, /value="OG\/9"/);
  assert.match(html, /<option value="male" selected>/);
  assert.match(html, /value="2099-01-01"/);
  assert.match(html, /form class="child-details rejected"/);
  assert.match(html, /cannot be in the future/);
});

test("opening details fetches that child's and closes the guardians panel", async () => {
  forgetToken();
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/1/details/", { status: 200, body: DETAILS }],
      ["/1/guardians/", { status: 200, body: { student: "Ada Obi", guardians: [], may_link: true, relationships: [] } }],
      ["/api/enrolment/roll/", { status: 200, body: ROLL }],
    ]),
  });

  await root.click({ "data-action": "guardians", "data-child": "1" });
  await root.click({ "data-action": "details", "data-child": "1" });

  assert.match(root.innerHTML, /Details of Ada Obi/);
  assert.doesNotMatch(root.innerHTML, /Guardians of Ada Obi/);
});

test("saving sends the three values and reads the roll again", async () => {
  forgetToken();
  const sent = [];
  let rollReads = 0;
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/1/details/", (o) => {
        if (o.method === "PUT") {
          sent.push(JSON.parse(o.body));
          return { status: 200, body: { ...DETAILS, learner_id: "OG/2" } };
        }
        return { status: 200, body: DETAILS };
      }],
      ["/api/enrolment/roll/", () => {
        rollReads += 1;
        return { status: 200, body: ROLL };
      }],
    ]),
  });
  await root.click({ "data-action": "details", "data-child": "1" });

  await root.submit({
    dataset: { form: "details" },
    learner_id: "OG/2",
    sex: "female",
    date_of_birth: "",
  });

  assert.deepEqual(sent, [{ learner_id: "OG/2", sex: "female", date_of_birth: null }]);
  assert.equal(rollReads, 2);
  assert.match(root.innerHTML, /value="OG\/2"/);
});

test("a photo goes up as a file, multipart", async () => {
  forgetToken();
  const bodies = [];
  const root = fakeRoot({});
  await mount(root, {
    fetchImpl: serve([
      ["/1/photo/", (o) => {
        bodies.push(o.body);
        return { status: 200, body: DETAILS };
      }],
      ["/1/details/", { status: 200, body: { ...DETAILS, has_photo: false } }],
      ["/api/enrolment/roll/", { status: 200, body: ROLL }],
    ]),
  });
  await root.click({ "data-action": "details", "data-child": "1" });

  const file = new Blob(["jpeg"], { type: "image/jpeg" });
  await root.submit({ dataset: { form: "photo" }, photo: { files: [file] } });

  assert.equal(bodies.length, 1);
  assert.ok(bodies[0] instanceof FormData);
  assert.ok(bodies[0].get("photo"));
  assert.match(root.innerHTML, /data-action="remove-photo"/);
});
