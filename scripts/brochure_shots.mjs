/**
 * The printed brochure's screenshots, taken from Crestfield College, the demo school.
 *
 * Phone screens at 390 CSS pixels wide and twice the pixels (780 by 1688), one
 * screen each, and one desk-width shot of the report card. Run against a local
 * server, never production: the shots print a result checker PIN and press
 * "Print again" on the exam slips, which mints new PINs. `docs/demo-school.md`
 * ("Brochure screenshots") is the whole recipe; in short:
 *
 *   PLATFORM_DOMAIN=classnode.test python manage.py setup_portal
 *   PLATFORM_DOMAIN=classnode.test python manage.py crestfield create   # CRESTFIELD_*_PASSWORD set
 *   PLATFORM_DOMAIN=classnode.test python manage.py runserver 0.0.0.0:8000
 *   PLATFORM_DOMAIN=classnode.test node scripts/brochure_shots.mjs      # same CRESTFIELD_*_PASSWORD
 *
 * For the result check it prints one lost slip for the demo parent's JSS 2A
 * child itself (`python manage.py shell`, on the same database as the server),
 * which is how a school replaces a lost slip and the only way to hold a PIN.
 *
 * Writes PNGs to `SHOTS_OUT` (default `docs/brochure/`).
 */

import { execFileSync } from "node:child_process";
import { mkdirSync, rmSync } from "node:fs";
import { join } from "node:path";

import { chromium } from "playwright";

// classnode.co, served from this machine (the browser is told the names are
// 127.0.0.1), so the address printed on a slip is the one a school would see.
const DOMAIN = process.env.SCREENS_DOMAIN || "classnode.co";
const PORT = process.env.SCREENS_PORT || "80";
const OUT = process.env.SHOTS_OUT || "docs/brochure";
const HOST_PORT = PORT === "80" ? "" : `:${PORT}`;
const PORTAL = `http://app.${DOMAIN}${HOST_PORT}`;
const SCHOOL = `http://crestfield.${DOMAIN}${HOST_PORT}`;
const PASSWORDS = {
  "cfc.principal": process.env.CRESTFIELD_PRINCIPAL_PASSWORD,
  "cfc.teacher": process.env.CRESTFIELD_TEACHER_PASSWORD,
  "cfc.parent": process.env.CRESTFIELD_PARENT_PASSWORD,
};

const LOST_SLIP = `
import json
from accounts.models import Membership, Role
from django_tenants.utils import schema_context
from results import checker
from results.models import ResultSheet
from schools import crestfield
school = crestfield.find()
child = Membership.objects.get(school=school, role=Role.STUDENT, user__full_name="Ifeoluwa Bamidele")
principal = Membership.objects.get(school=school, role=Role.PRINCIPAL).user
with schema_context(school.schema_name):
    sheet = ResultSheet.objects.get(class_group__name="JSS 2A", term__is_current=True)
    slip = checker.print_slips(sheet, actor=principal, admission_number=child.reference).slips[0]
print(json.dumps({"number": slip.admission_number, "pin": slip.printed_pin}))
`;
const CHECKER = JSON.parse(
  execFileSync(process.env.PYTHON || "python", ["manage.py", "shell", "-c", LOST_SLIP], { encoding: "utf8" })
    .trim().split("\n").pop(),
);

const PHONE = { width: 390, height: 844 };
const DESK = { width: 1280, height: 900 };

const browser = await chromium.launch({ args: [`--host-resolver-rules=MAP *.${DOMAIN} 127.0.0.1`] });

// The fee pages ask `crypto.randomUUID()`, which a browser gives only to a
// secure context: production's https is one, this plain http is not. Lent here.
const RANDOM_UUID = `if (!crypto.randomUUID) crypto.randomUUID = () =>
  "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) =>
    (c ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (c / 4)))).toString(16));`;
mkdirSync(OUT, { recursive: true });

async function open(size, who) {
  const context = await browser.newContext({ viewport: size, deviceScaleFactor: 2, acceptDownloads: true });
  await context.addInitScript(RANDOM_UUID);
  const page = await context.newPage();
  if (who) {
    await page.goto(`${PORTAL}/staff-sign-in/`);
    const status = await page.evaluate(async ({ identifier, password }) => {
      const { csrf_token: token } = await (await fetch("/api/csrf/")).json();
      const response = await fetch("/api/login/", {
        method: "POST",
        headers: { "content-type": "application/json", "X-CSRFToken": token },
        body: JSON.stringify({ identifier, password }),
      });
      return response.status;
    }, { identifier: who, password: PASSWORDS[who] });
    if (status !== 200) throw new Error(`signing in as ${who}: ${status}`);
  }
  return { context, page };
}

async function settle(page) {
  await page.waitForLoadState("networkidle");
  await page.waitForFunction(() => !/Loading/.test(document.body.innerText.slice(0, 400)), null, { timeout: 15000 });
  await page.mouse.move(0, 0);
  await page.waitForTimeout(500);
}

async function shot(page, name, options = {}) {
  await settle(page);
  await page.screenshot({ path: join(OUT, `${name}.png`), ...options });
  console.log(`${name}.png`);
}

try {
  // 1. The principal's home.
  {
    const { context, page } = await open(PHONE, "cfc.principal");
    await page.goto(`${SCHOOL}/home/`);
    await shot(page, "01-home");
    // 5. The fees list: the bursar's page as the principal reads it, JSS 2A.
    await page.goto(`${SCHOOL}/fees/`);
    await settle(page);
    const jss2a = page.getByText("JSS 2A", { exact: true }).first();
    if (await jss2a.count()) {
      await jss2a.click();
    }
    await shot(page, "05-fees");
    // 7b. The exam slips page, JSS 3A printed.
    await page.goto(`${SCHOOL}/exam-slips/`);
    await settle(page);
    await page.getByText("JSS 3A", { exact: true }).first().scrollIntoViewIfNeeded();
    await page.evaluate(() => window.scrollBy(0, -120));
    await shot(page, "08-exam-slips-page");
    // 8. One printed sheet of slips: JSS 3A printed again, its PDF's first page.
    await page.getByRole("button", { name: "Print again" }).first().click();
    const download = page.waitForEvent("download");
    await page.locator('[data-action="print-class"]').click();
    const pdf = join(OUT, "slips.pdf");
    await (await download).saveAs(pdf);
    execFileSync("pdftoppm", ["-png", "-r", "300", "-f", "1", "-l", "1", "-singlefile", pdf, join(OUT, "09-exam-slip")]);
    rmSync(pdf);
    console.log("09-exam-slip.png");
    await context.close();
  }
  // 2. The marking sheet: JSS 2B's mathematics exam, still open.
  {
    const { context, page } = await open(PHONE, "cfc.teacher");
    await page.goto(`${SCHOOL}/marking/`);
    await settle(page);
    await page.getByText(/Mathematics · Exam, JSS 2B/).first().click();
    await settle(page);
    await page.evaluate(() => { document.activeElement?.blur(); window.scrollTo(0, 0); });
    await shot(page, "02-marking-sheet");
    // 6. The register: JSS 2B, today's, already taken.
    await page.goto(`${SCHOOL}/register/`);
    await settle(page);
    const open2b = page.locator('[data-action="open"]').filter({ hasText: /JSS 2B/ }).first();
    if (await open2b.count()) await open2b.click();
    await shot(page, "06-attendance-register");
    await context.close();
  }
  // 3. The Ogun State report card, as the parent opens it, on a phone and a desk.
  for (const [size, name] of [[PHONE, "03-report-card-ogun"], [DESK, "10-report-card-desktop"]]) {
    const { context, page } = await open(size, "cfc.parent");
    await page.goto(`${SCHOOL}/cards/`);
    await settle(page);
    await page.locator("a", { hasText: "First term" }).first().click();
    if (size === PHONE) {
      // The subjects and their marks, under the learner's box.
      await settle(page);
      await page.getByText("Subjects", { exact: true }).first().evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 8));
    }
    await shot(page, name, size === DESK ? { fullPage: true } : {});
    await context.close();
  }
  // 4. The parent's result check: a slip's admission number and PIN, no account.
  {
    const { context, page } = await open(PHONE, null);
    await page.goto(`${SCHOOL}/check/`);
    await settle(page);
    const fields = page.locator("input:visible");
    await fields.nth(0).fill(CHECKER.number);
    await fields.nth(1).fill(CHECKER.pin);
    await shot(page, "04-result-check");
    await page.getByRole("button", { name: "Open the report card" }).click();
    await shot(page, "04b-result-check-card");
    await context.close();
  }
  // 7. The CBT question bank: not built (CBT step 3), so there is no screen to take.
  // 11. The school's website home, signed out.
  {
    const { context, page } = await open(PHONE, null);
    await page.goto(`${SCHOOL}/`);
    await shot(page, "07-school-website");
    await context.close();
  }
} finally {
  await browser.close();
}
