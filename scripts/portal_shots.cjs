// The portal polish's before and after photographs (docs/screens/polish-pr1/).
//
//   node scripts/portal_shots.cjs <outdir>
//
// Against the demo served as the screens job serves it (PLATFORM_DOMAIN=classnode.test,
// seed_demo, then manage.py crestfield create), on :8000, and a second server with
// DEMO_SINGLE_HOST=1 on :8001 for the door on Crestfield's own host. Signs in as
// Crestfield's principal and teacher with CRESTFIELD_PRINCIPAL_PASSWORD and
// CRESTFIELD_TEACHER_PASSWORD. Uses the preinstalled playwright (require), at 2x.
const { chromium } = require("playwright");
const fs = require("fs"), path = require("path");
const OUT = process.argv[2];
const D = "classnode.test";
const PORTAL = `http://app.${D}:8000`, CF = `http://crestfield.${D}:8000`, CF1 = `http://crestfield.${D}:8001`;
const PW = { "cfc.principal": process.env.CRESTFIELD_PRINCIPAL_PASSWORD, "cfc.teacher": process.env.CRESTFIELD_TEACHER_PASSWORD };
const SHOTS = [
  { name: "sign-in-crestfield", as: null, url: `${CF1}/staff-sign-in/` },
  { name: "sign-in-portal", as: null, url: `${PORTAL}/staff-sign-in/` },
  { name: "dashboard-principal", as: "cfc.principal", url: `${CF}/home/` },
  { name: "dashboard-teacher", as: "cfc.teacher", url: `${CF}/home/` },
  { name: "list-fees", as: "cfc.principal", url: `${CF}/fees/` },
  { name: "form-setup", as: "cfc.principal", url: `${CF}/setup/` },
];
(async () => {
  const browser = await chromium.launch({ args: [`--host-resolver-rules=MAP *.${D} 127.0.0.1, MAP ${D} 127.0.0.1`, "--font-render-hinting=full"] });
  const ctx = {};
  async function context(as) {
    if (ctx[as]) return ctx[as];
    const c = await browser.newContext({ deviceScaleFactor: 2 });
    await c.addInitScript(() => {
      if (typeof crypto.randomUUID !== "function") {
        crypto.randomUUID = () => "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (ch) =>
          (ch ^ (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (ch / 4)))).toString(16));
      }
    });
    if (as) {
      const p = await c.newPage();
      await p.goto(`${PORTAL}/staff-sign-in/`);
      const st = await p.evaluate(async ({ identifier, password }) => {
        const { csrf_token } = await (await fetch("/api/csrf/")).json();
        const r = await fetch("/api/login/", { method: "POST", headers: { "content-type": "application/json", "X-CSRFToken": csrf_token }, body: JSON.stringify({ identifier, password }) });
        return r.status;
      }, { identifier: as, password: PW[as] });
      if (st !== 200) throw new Error(`sign in ${as}: ${st}`);
      await p.close();
    }
    return (ctx[as] = c);
  }
  fs.mkdirSync(OUT, { recursive: true });
  for (const s of SHOTS) {
    const page = await (await context(s.as)).newPage();
    for (const width of [390, 1280]) {
      await page.setViewportSize({ width, height: 844 });
      const r = await page.goto(s.url);
      await page.waitForLoadState("networkidle");
      await page.waitForFunction(() => !document.querySelector(".state-loading"), null, { timeout: 60000 }).catch(() => console.log("still loading", s.name));
      await page.evaluate(() => new Promise((d) => requestAnimationFrame(() => setTimeout(d, 300))));
      const file = path.join(OUT, `${s.name}-${width}.png`);
      const h = await page.evaluate(() => document.documentElement.scrollHeight);
      await page.screenshot({ path: file, fullPage: true, clip: { x: 0, y: 0, width, height: Math.min(h, 2200) } });
      console.log(r.status(), file);
    }
    await page.close();
  }
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
