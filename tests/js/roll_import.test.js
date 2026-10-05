/**
 * The roll import: choose a file, see every row's verdict, admit it whole.
 *
 * What is held here is the page's half of `accounts/bulk.py`'s rule: **the
 * admit button exists only when every row passed**, a row's problems are shown
 * under it by the row number in the office's spreadsheet, and the file that is
 * admitted is the file that was checked.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { CHECK_URL, DOOR_URL, IMPORT_URL, REFUSAL, TEMPLATE_URL, refusalFor } from "../../static/roll-import/api.js";
import { afterCheck, afterImport, htmlFor, mount } from "../../static/roll-import/app.js";
import * as states from "../../static/roll-import/states.js";
import { forgetToken } from "../../static/web/http.js";
import { fakeRoot } from "./fake_dom.js";

const DOOR = { term: "First term 2026/2027", classes: ["JSS 1A", "JSS 1B"] };

function row(line, values = {}, problems = []) {
  return {
    line,
    full_name: "",
    class_group: "",
    reference: "",
    username: "",
    guardian_name: "",
    guardian_contact: "",
    ...values,
    problems,
  };
}

const GOOD = {
  rows: [
    row(2, { full_name: "Ada Obi", class_group: "JSS 1A", reference: "0100" }),
    row(3, { full_name: "Bola Ade", class_group: "JSS 1B", reference: "0101", guardian_name: "Mrs Ade", guardian_contact: "+2348031234567" }),
  ],
  problem_rows: 0,
  admissible: true,
};

const BAD = {
  rows: [
    row(2, { full_name: "Ada Obi", class_group: "JSS 1A", reference: "0100" }),
    row(3, { class_group: "JSS 9Z", reference: "0100" }, [
      { line: 3, column: "full_name", detail: "A name is required." },
      { line: 3, column: "reference", detail: "'0100' appears twice in this file." },
      { line: 3, column: "class_group", detail: "'JSS 9Z' is not a class this school teaches." },
    ]),
  ],
  problem_rows: 1,
  admissible: false,
};

function serve(routes, seen = []) {
  return async (url, options = {}) => {
    seen.push({ url, options });
    if (url === "/api/csrf/") return { status: 200, json: async () => ({ csrf_token: "t" }) };
    for (const [match, answer] of routes) {
      if (url === match) {
        const value = typeof answer === "function" ? answer(options) : answer;
        return { status: value.status, json: async () => value.body };
      }
    }
    throw new Error(`no stub for ${url}`);
  };
}

const FILE = new File(["full_name,class_group\n"], "jss1.xlsx");

// -- refusals --------------------------------------------------------------

test("403, 404 and the two 401s are four different pages", () => {
  assert.equal(refusalFor(403, {}), REFUSAL.NOT_THE_OFFICE);
  assert.equal(refusalFor(404, {}), REFUSAL.WRONG_HOST);
  assert.equal(refusalFor(401, { code: "session_expired" }), REFUSAL.EXPIRED);
  assert.equal(refusalFor(401, {}), REFUSAL.SIGNED_OUT);
  assert.match(htmlFor({ step: REFUSAL.NOT_THE_OFFICE }), /administrator/);
  assert.match(htmlFor({ step: REFUSAL.EXPIRED }, { portal: "app.example" }), /app\.example\/staff-sign-in/);
});

// -- choosing --------------------------------------------------------------

test("the first screen offers the template and a file chooser, and names the classes", () => {
  const html = states.choose(DOOR);

  assert.match(html, new RegExp(`href="${TEMPLATE_URL}" download`));
  assert.match(html, /type="file"[^>]*accept="\.xlsx,\.csv/);
  assert.match(html, /JSS 1A, JSS 1B/);
  assert.doesNotMatch(html, /disabled/);
});

test("with no term open, nothing can be chosen and the page says why", () => {
  const html = states.choose({ ...DOOR, term: null });

  assert.match(html, /No term is open/);
  assert.match(html, /type="file"[^>]* disabled/);
  assert.match(html, /<button type="submit" disabled>/);
});

// -- the verdict -----------------------------------------------------------

test("a clean file shows every row and the one button that admits", () => {
  const html = states.preview({ ...DOOR, fileName: "jss1.xlsx", preview: GOOD });

  assert.match(html, /<span class="label label-ok">Ready<\/span>/);
  assert.match(html, /data-action="admit"[^>]*>Admit 2 children</);
  assert.equal((html.match(/<tr data-line=/g) || []).length, 2);
  assert.match(html, /Made on import/, "a blank username says what happens to it");
});

test("a file with problems has no admit button, and each problem sits under its row", () => {
  const html = states.preview({ ...DOOR, fileName: "jss1.xlsx", preview: BAD });

  assert.doesNotMatch(html, /data-action="admit"/);
  assert.match(html, /1 row to fix/);
  assert.match(html, /Nothing has been saved/);
  const three = html.slice(html.indexOf('data-line="3"'));
  assert.match(three, /<td class="stack-head card-only">Row 3 <span class="label label-stop">Fix<\/span><\/td>/);
  assert.match(three, /<td class="num stack-hide">3<\/td>/);
  assert.match(three, /<strong>Full name:<\/strong> A name is required\./);
  assert.match(three, /<strong>Reference:<\/strong> &#39;0100&#39; appears twice in this file\./);
  assert.match(three, /<td data-label="Class" class="bad">JSS 9Z<\/td>/);
  assert.match(three, /<td class="check stack-full">/, "the problems close the phone's card");
  // Row 2 passed, and says so, in the same table.
  const two = html.slice(html.indexOf('data-line="2"'), html.indexOf('data-line="3"'));
  assert.match(two, /label-ok">Ready/);
});

test("every value from the file is escaped", () => {
  const html = states.preview({
    ...DOOR,
    preview: { rows: [row(2, { full_name: "<img src=x onerror=alert(1)>" })], problem_rows: 0, admissible: true },
  });

  assert.doesNotMatch(html, /<img src=x/);
  assert.match(html, /&lt;img src=x/);
});

test("status colour stays on labels: the preview draws no colour of its own", () => {
  const html = states.preview({ ...DOOR, preview: BAD });

  assert.doesNotMatch(html, /style=/);
});

// -- what each answer does -------------------------------------------------

test("a file that cannot be read goes back to the chooser with the reason", () => {
  const next = afterCheck({ step: "choose", ...DOOR }, { ok: false, rejected: true, body: { detail: "That file is over 2 MB." } }, "big.xlsx");

  assert.equal(next.step, "choose");
  assert.match(htmlFor(next), /Not read<\/span><p>That file is over 2 MB\./);
});

test("an import that meets a changed roll becomes a preview again, re-marked by row", () => {
  const state = { step: "preview", ...DOOR, fileName: "jss1.xlsx", preview: GOOD };
  const next = afterImport(state, {
    ok: true,
    body: {
      admitted: 0,
      problems: [{ line: 3, column: "reference", detail: "'0101' is already an admission number at this school." }],
      generated: {},
      guardian_links: [],
      guardians_pending: 0,
    },
  });

  assert.equal(next.step, "preview");
  assert.equal(next.preview.admissible, false);
  const html = htmlFor(next);
  assert.match(html, /The roll changed since this file was checked\. Nothing was admitted\./);
  assert.doesNotMatch(html, /data-action="admit"/);
  assert.match(html, /already an admission number/);
});

test("done lists the usernames it made, by row and name, and the guardians still to confirm", () => {
  const html = states.done({
    ...DOOR,
    preview: GOOD,
    report: { admitted: 2, problems: [], generated: { 2: "STM/0100" }, guardian_links: [{}], guardians_pending: 1 },
  });

  assert.match(html, /2 children were admitted/);
  assert.match(html, /<td class="num" data-label="Row">2<\/td><td class="stack-head">Ada Obi<\/td><td data-label="Username">STM\/0100<\/td>/);
  assert.match(html, /1 guardian link is waiting/);
  assert.match(html, /href="\/roll\/"/);
});

const GAPS = [
  { line: 3, full_name: "Bola Ade", class_group: "JSS 1B", reference: "0101", guardian_name: "Mrs Ade", guardian_contact: "+2348031234567", why: "A phone number only." },
  { line: 4, full_name: "=Dayo <b>Obi</b>", class_group: "JSS 1A", reference: "0102", guardian_name: "", guardian_contact: "", why: "No guardian was given." },
];

test("done lists who will get no email, why, and offers the list to download", () => {
  const html = states.done({
    ...DOOR,
    preview: GOOD,
    report: { admitted: 3, problems: [], generated: {}, guardian_links: [], guardians_pending: 0, no_email: GAPS },
  });

  assert.match(html, /2 children have no guardian email, so absence alerts and payment receipts will not reach them/);
  assert.match(html, /<td class="stack-head">Bola Ade<\/td><td data-label="Class">JSS 1B<\/td><td data-label="Guardian">Mrs Ade<\/td><td data-label="Why">A phone number only\./);
  assert.match(html, /No guardian was given\./);
  assert.match(html, /=Dayo &lt;b&gt;Obi&lt;\/b&gt;/, "a typed name is escaped");
  assert.match(html, /data-action="download-no-email"/);
});

test("when every guardian has an email the page says so and offers no download", () => {
  const html = states.done({ ...DOOR, preview: GOOD, report: { admitted: 2, no_email: [], generated: {}, guardians_pending: 0 } });

  assert.match(html, /Every guardian has an email address/);
  assert.doesNotMatch(html, /download-no-email/);
});

test("the list as a CSV opens in Excel: a byte-order mark, every cell quoted, formulas made plain", () => {
  const csv = states.noEmailCsv(GAPS);
  const lines = csv.slice(1).split("\r\n");

  assert.equal(csv[0], "\ufeff");
  assert.equal(lines[0], '"Row","Name","Class","Admission number","Guardian","Guardian contact","Why"');
  assert.equal(lines[1], '"3","Bola Ade","JSS 1B","0101","Mrs Ade","+2348031234567","A phone number only."');
  assert.match(lines[2], /^"4","'=Dayo <b>Obi<\/b>","JSS 1A","0102","","","No guardian was given\."$/);
  assert.equal(states.noEmailCsv([]).slice(1), '"Row","Name","Class","Admission number","Guardian","Guardian contact","Why"\r\n');
});

test("Download hands the browser that file, and sends nothing to the school", async () => {
  forgetToken();
  const seen = [];
  const root = fakeRoot({ portal: "app.example" });
  const made = [];
  root.ownerDocument = {
    createElement: () => {
      const link = { click() { made.push(link); }, remove() {} };
      return link;
    },
    body: { append() {} },
  };
  await mount(root, {
    fetchImpl: serve(
      [
        [DOOR_URL, { status: 200, body: DOOR }],
        [CHECK_URL, { status: 200, body: GOOD }],
        [IMPORT_URL, { status: 200, body: { admitted: 2, problems: [], generated: {}, guardian_links: [], guardians_pending: 0, no_email: GAPS } }],
      ],
      seen,
    ),
  });
  await root.submit({ file: { files: [FILE] } });
  await root.click({ "data-action": "admit" });
  const requests = seen.length;

  await root.click({ "data-action": "download-no-email" });

  assert.equal(made.length, 1);
  assert.equal(made[0].download, "students-without-guardian-email.csv");
  assert.match(made[0].href, /^blob:/);
  assert.equal(seen.length, requests, "building the file asks the school nothing");
});

// -- the page, driven ------------------------------------------------------

test("choose, check, admit: the file admitted is the file that was checked", async () => {
  forgetToken();
  const seen = [];
  const root = fakeRoot({ portal: "app.example" });
  await mount(root, {
    fetchImpl: serve(
      [
        [DOOR_URL, { status: 200, body: DOOR }],
        [CHECK_URL, { status: 200, body: GOOD }],
        [IMPORT_URL, { status: 200, body: { admitted: 2, problems: [], generated: {}, guardian_links: [], guardians_pending: 0 } }],
      ],
      seen,
    ),
  });
  assert.match(root.innerHTML, /Choose your file/);

  const prevented = await root.submit({ file: { files: [FILE] } });
  assert.ok(prevented);
  assert.match(root.innerHTML, /Admit 2 children/);

  await root.click({ "data-action": "admit" });
  assert.match(root.innerHTML, /2 children were admitted/);

  const posts = seen.filter((s) => s.options.method === "POST");
  assert.deepEqual(posts.map((s) => s.url), [CHECK_URL, IMPORT_URL]);
  for (const post of posts) {
    const sent = post.options.body.get("file");
    assert.equal(sent.name, "jss1.xlsx", `${post.url} was sent the chosen file`);
    assert.equal(await sent.text(), "full_name,class_group\n");
    assert.equal(post.options.headers["X-CSRFToken"], "t");
  }
});

test("a file with problems cannot be admitted from the page at all", async () => {
  forgetToken();
  const seen = [];
  const root = fakeRoot();
  await mount(root, {
    fetchImpl: serve([[DOOR_URL, { status: 200, body: DOOR }], [CHECK_URL, { status: 200, body: BAD }]], seen),
  });
  await root.submit({ file: { files: [FILE] } });

  // Even a click that the page never drew a button for does nothing.
  await root.click({ "data-action": "admit" });

  assert.ok(!seen.some((s) => s.url === IMPORT_URL));
  assert.match(root.innerHTML, /1 row to fix/);
});

test("somebody who may not import gets the refusal, not the chooser", async () => {
  const root = fakeRoot();
  await mount(root, { fetchImpl: serve([[DOOR_URL, { status: 403, body: { detail: "Children are admitted by an administrator of the school." } }]]) });

  assert.match(root.innerHTML, /You cannot import students/);
  assert.doesNotMatch(root.innerHTML, /type="file"/);
});
