/**
 * Colours and animations at `/website/look/` (`static/site-editor/look-app.js`): the principal's
 * screen for the website's four colours and five animated backgrounds
 * (`docs/school-sites-theme-modern.md`). The page says as a colour is picked whether writing will
 * read, by the server's own rules (`schoolsite/themes.py`); the server still judges every save.
 */

import { test } from "node:test";
import assert from "node:assert/strict";

import { REFUSAL } from "../../static/site-editor/api.js";
import { changeFrom, coloursOf, contrast, htmlFor, problems } from "../../static/site-editor/look-app.js";

const LOOK = {
  theme: "Modern Campus",
  chosen: { primary: "", accent: "#FFD66B", detail: "#C9A24A", dark: "#0F1B33" },
  palette: { primary: "#143D8C", accent: "#FFD66B", detail: "#C9A24A", dark: "#0F1B33", text: "#0F1B33", surface: "#FFFFFF",
    tint: "#EEF3FC", warm: "#FFF5DC", mist: "#F1F4F8", mint: "#E8F6EF" },
  theme_colours: { primary: "#143D8C", accent: "#FFD66B", detail: "#C9A24A", dark: "#0F1B33" },
  animations: { hero: true, academics: true, student_life: false, admissions: true, contact: true },
  animation_names: { hero: "Hero: orbits and the node triangle", academics: "Academics", student_life: "Student life",
    admissions: "Admissions band", contact: "Visit us" },
};
const BODY = { can_edit: true, can_publish: true, version: 4, look: LOOK };

test("contrast is WCAG's, and the demo's colours all read", () => {
  assert.equal(Math.round(contrast("#FFFFFF", "#143D8C") * 10) / 10, 10.1);
  assert.deepEqual(problems(coloursOf({}, LOOK)), {});
});

test("each colour that would not read says so, by the server's rules", () => {
  const c = coloursOf({}, LOOK);
  assert.match(problems({ ...c, primary: "#FFD66B" }).primary, /white writing/);
  assert.match(problems({ ...c, accent: "#143D8C" }).accent, /dark writing/);
  assert.match(problems({ ...c, dark: "#AAAAAA" }).dark, /white writing on the band/);
  assert.match(problems({ ...c, detail: "#222222" }).detail, /would not show on the dark band/);
});

test("the screen offers four colours and five switches, as the site draws them now", () => {
  const html = htmlFor({ step: "look", body: BODY });
  for (const role of ["primary", "accent", "detail", "dark"]) assert.match(html, new RegExp(`<input type="color" id="look-${role}" name="${role}"`));
  assert.match(html, /id="look-primary" name="primary" value="#143d8c"/, "the report card's colour, while none is chosen");
  assert.doesNotMatch(html, /name="primary_reset"/, "nothing to go back from");
  assert.match(html, /name="accent_reset"> Go back to the theme&#39;s own/);
  assert.match(html, /<input type="checkbox" name="anim_hero" checked>/);
  assert.match(html, /<input type="checkbox" name="anim_student_life"> Student life/);
  assert.match(html, /<button type="submit">Save<\/button>/);
});

test("a colour that would not read keeps Save from being pressed", () => {
  const html = htmlFor({ step: "look", body: BODY, values: { primary: "#ffd66b" } });
  assert.match(html, /<span class="refused" id="look-primary-issue" aria-live="polite">Too light/);
  assert.match(html, /<button type="submit" disabled>Save<\/button>/);
});

test("a save sends only the colours changed, the ones taken back, and every switch", () => {
  const values = { primary: "#7a1f2b", accent: "#ffd66b", detail: "#c9a24a", dark: "#0f1b33", dark_reset: true,
    anim_hero: true, anim_academics: false, anim_student_life: true, anim_admissions: true, anim_contact: false };
  assert.deepEqual(changeFrom(values, LOOK), {
    colours: { primary: "#7A1F2B", dark: "" },
    animations: { hero: true, academics: false, student_life: true, admissions: true, contact: false },
  });
});

test("only the principal changes the look, and every refusal says what to do", () => {
  assert.match(htmlFor({ step: "look", body: { ...BODY, can_publish: false } }), /Only the principal changes/);
  assert.doesNotMatch(htmlFor({ step: "look", body: { ...BODY, can_publish: false } }), /<form/);
  assert.match(htmlFor({ step: REFUSAL.SIGNED_OUT }), /href="\/staff-sign-in\/\?next=\/website\/look\/"/);
  assert.match(htmlFor({ step: REFUSAL.NOT_YOURS }), /looked after by its principal/);
  assert.match(htmlFor({ step: REFUSAL.BROKEN }), /Try again/);
  assert.match(htmlFor({ step: "look", body: BODY, note: "Somebody changed it.", stale: true }), /role="alert">Somebody changed it. <button type="button" data-action="reload">Reload/);
});
