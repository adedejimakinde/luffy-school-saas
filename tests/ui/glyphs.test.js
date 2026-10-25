/**
 * A Nigerian name and a naira amount, drawn in the design's own typeface, in a real browser.
 *
 * `tests/test_design.py` holds the stylesheet's `@font-face` rules to the font
 * files, and `tests/glyphs.py` asks which face would draw each letter; this asks
 * Chromium which fonts it actually used. A letter the design's faces cannot draw
 * is not an error: the browser quietly draws it in whatever the phone has, and a
 * child's name comes out in two typefaces. The DevTools protocol will say so
 * (`CSS.getPlatformFontsForNode`: each font a node's text was drawn with, and
 * whether it was a web font the page loaded or a system one), so the test
 * fails on the second typeface, not on a guess about it.
 *
 * On the portal's staff sign-in and on a school's own website (Harbour's, in the
 * starter theme, and Sunrise's), a specimen is put on the page: Yoruba, Igbo and
 * Hausa names with their tone marks and underdots, at regular and at bold, and
 * the amounts the fee pages print. It is built with the DOM and no style
 * attribute, because a school's page refuses inline style (its CSP).
 *
 * - **Yoruba and Igbo names and ₦ amounts** are drawn by Hanken Grotesk and nothing else.
 * - **Hausa names** by Hanken Grotesk and Noto Sans, for the hooked letters only.
 * - **No system font** draws any of it, at any weight.
 * - **Noto Sans is not fetched** by a page that has no hooked letter, and is fetched, at
 *   the weights used and no other, when one is added.
 * - **Nothing scrolls sideways** at 360px.
 *
 * Each is photographed at 360 and 1280 into `<SCREENS_OUT>/glyphs/<width>/`.
 * Served as `screens.test.js` says.
 */

import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";
import { join } from "node:path";
import { after, before, describe, test } from "node:test";

import { chromium } from "playwright";

const DOMAIN = process.env.SCREENS_DOMAIN || "classnode.test";
const PORT = process.env.SCREENS_PORT || "8000";
const OUT = join(process.env.SCREENS_OUT || "screens", "glyphs");

const PORTAL = `http://app.${DOMAIN}:${PORT}`;
const HARBOUR = `http://harbour-demo.${DOMAIN}:${PORT}`;
const SUNRISE = `http://sunrise-demo.${DOMAIN}:${PORT}`;

const PAGES = [
  { name: "portal-staff-sign-in", url: `${PORTAL}/staff-sign-in/` },
  { name: "harbour-home", url: `${HARBOUR}/` },
  { name: "sunrise-home", url: `${SUNRISE}/` },
];

const WIDTHS = [360, 1280];

/** Names as a school writes them, with tones and underdots, as typed. */
const YORUBA_AND_IGBO = ["Ọláòlúwa Adéṣínà", "Ìfẹ́olúwa Ọ̀ṣọ́", "Ṣadé Ẹ̀kọ́", "Ịfeanyị Ụgọchukwụ Ṅwa"];
const HAUSA = ["Ɓatsari Ɗanjuma Ƙasim Ƴar’adua", "Ƙaramar Hukumar Ɗanbatta"];
const AMOUNTS = ["₦125,000", "₦48,620,500", "Day fees: ₦125,000 per term"];

/** What the design's own faces call themselves, as Chromium reports a web font's family. */
const HANKEN = /^Hanken Grotesk/;
const NOTO = /^Noto Sans/;

let browser;

before(async () => {
  browser = await chromium.launch({
    args: [`--host-resolver-rules=MAP *.${DOMAIN} 127.0.0.1, MAP ${DOMAIN} 127.0.0.1`],
  });
});

after(async () => {
  await browser?.close();
});

/** Put the specimen at the end of `<main>` (or `<body>`), as plain elements with a `data-specimen` for each line. */
async function addSpecimen(page, { hausa }) {
  await page.evaluate(
    ({ lines, withHausa }) => {
      const host = document.querySelector("main") || document.body;
      const section = document.createElement("section");
      section.id = "glyph-specimen";
      const heading = document.createElement("h2");
      heading.textContent = "Names and amounts";
      section.append(heading);
      for (const [group, bold, text] of lines) {
        if (group === "hausa" && !withHausa) continue;
        const p = document.createElement("p");
        p.dataset.specimen = group;
        const inner = document.createElement(bold ? "strong" : "span");
        inner.dataset.specimen = group;
        inner.textContent = text;
        p.append(inner);
        section.append(p);
      }
      host.append(section);
    },
    {
      lines: [
        ...YORUBA_AND_IGBO.flatMap((n) => [["names", false, n], ["names", true, n]]),
        ...AMOUNTS.flatMap((n) => [["amounts", false, n], ["amounts", true, n]]),
        ...HAUSA.flatMap((n) => [["hausa", false, n], ["hausa", true, n]]),
      ],
      withHausa: hausa,
    },
  );
  await page.evaluate(() => document.fonts.ready);
}

/** Every font Chromium drew each specimen element's text with: [{group, text, fonts: [{familyName, isCustomFont, glyphCount}]}]. */
async function platformFonts(page) {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("DOM.enable");
  await cdp.send("CSS.enable");
  const { root } = await cdp.send("DOM.getDocument", { depth: 0 });
  const { nodeIds } = await cdp.send("DOM.querySelectorAll", { nodeId: root.nodeId, selector: "span[data-specimen], strong[data-specimen]" });
  const found = [];
  for (const nodeId of nodeIds) {
    const { attributes } = await cdp.send("DOM.getAttributes", { nodeId });
    const group = attributes[attributes.indexOf("data-specimen") + 1];
    const { outerHTML } = await cdp.send("DOM.getOuterHTML", { nodeId });
    const { fonts } = await cdp.send("CSS.getPlatformFontsForNode", { nodeId });
    found.push({ group, text: outerHTML.replace(/<[^>]*>/g, ""), bold: outerHTML.startsWith("<strong"), fonts });
  }
  await cdp.detach();
  return found;
}

const names = (fonts) => fonts.map((f) => f.familyName);

describe("Nigerian names and naira amounts are drawn in the design's own typeface", () => {
  for (const page of PAGES) {
    test(`${page.name}: Yoruba, Igbo and the naira sign in Hanken Grotesk alone; Hausa in Hanken and Noto Sans; no system font`, async () => {
      const context = await browser.newContext({ viewport: { width: 360, height: 740 }, deviceScaleFactor: 2 });
      const tab = await context.newPage();
      const fontFiles = [];
      tab.on("request", (request) => {
        if (/\.woff2(\?|$)/.test(request.url())) fontFiles.push(request.url().split("/").pop().split("?")[0].replace(/\.[0-9a-f]{8,}\./, "."));
      });
      await tab.goto(page.url, { waitUntil: "load" });
      await tab.evaluate(() => document.fonts.ready);

      // A page with no hooked letter never asks for Noto Sans.
      assert.deepEqual(fontFiles.filter((f) => f.startsWith("noto-sans")), [], "Noto Sans fetched by a page that has no Hausa on it");

      await addSpecimen(tab, { hausa: false });
      assert.deepEqual(fontFiles.filter((f) => f.startsWith("noto-sans")), [], "Noto Sans fetched for Yoruba, Igbo and ₦");
      for (const { group, text, bold, fonts } of await platformFonts(tab)) {
        assert.ok(fonts.length > 0, `no font reported for ${text}`);
        const system = fonts.filter((f) => !f.isCustomFont);
        assert.deepEqual(system, [], `${text} (${bold ? "bold" : "regular"}) was drawn in a system font`);
        assert.ok(names(fonts).every((n) => HANKEN.test(n)), `${group} ${text} was drawn in ${names(fonts).join(", ")}`);
      }

      // The hooked letters bring Noto Sans, at the two weights, and only for themselves.
      await tab.evaluate(() => document.getElementById("glyph-specimen").remove());
      await addSpecimen(tab, { hausa: true });
      const asked = [...new Set(fontFiles.filter((f) => f.startsWith("noto-sans")))].sort();
      assert.deepEqual(asked, ["noto-sans-hausa-400.woff2", "noto-sans-hausa-700.woff2"]);
      let noto = 0;
      for (const { group, text, bold, fonts } of await platformFonts(tab)) {
        const system = fonts.filter((f) => !f.isCustomFont);
        assert.deepEqual(system, [], `${text} (${bold ? "bold" : "regular"}) was drawn in a system font`);
        const families = names(fonts);
        assert.ok(families.every((n) => HANKEN.test(n) || NOTO.test(n)), `${group} ${text} was drawn in ${families.join(", ")}`);
        if (group === "hausa") noto += fonts.filter((f) => NOTO.test(f.familyName)).reduce((sum, f) => sum + f.glyphCount, 0);
        else assert.ok(families.every((n) => HANKEN.test(n)), `${group} ${text} took a hooked-letter font`);
      }
      assert.ok(noto > 0, "the Hausa lines never used Noto Sans");

      for (const width of WIDTHS) {
        await tab.setViewportSize({ width, height: 900 });
        const sideways = await tab.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
        assert.equal(sideways, false, `the specimen made the page scroll sideways at ${width}px`);
        mkdirSync(join(OUT, String(width)), { recursive: true });
        await tab.locator("#glyph-specimen").screenshot({ path: join(OUT, String(width), `${page.name}.png`) });
      }
      await context.close();
    });
  }
});
