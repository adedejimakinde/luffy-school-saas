/**
 * The public site's one module: the hero's slides, the fade-up as sections
 * come into view, and closing the phone menu after a tap.
 *
 * Every page on the site reads in full without it (`website/base.html`):
 * the first slide is drawn showing, and every section and drawing is drawn
 * finished. Under `prefers-reduced-motion: reduce` nothing here moves: the
 * slides change only when a dot is pressed, with no fade, and `html.motion`,
 * which every animation in `website.css` hangs on, is never set.
 *
 * No imports, so no import map: `{% static %}` hashes this file's own name.
 */

const ADVANCE_MS = 6000;
const motion = window.matchMedia("(prefers-reduced-motion: no-preference)");

/** Sections and drawings fade up, or draw themselves, once, on first sight. */
function reveal(root) {
  if (!motion.matches || !("IntersectionObserver" in window)) return;
  root.classList.add("motion");
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        entry.target.classList.add("is-in");
        observer.unobserve(entry.target);
      }
    },
    { rootMargin: "0px 0px -10% 0px", threshold: 0.15 },
  );
  for (const el of root.querySelectorAll(".reveal, .flow")) observer.observe(el);
}

/**
 * The hero's slides: on to the next every 6 seconds, held while a pointer is
 * over them, focus is inside them, or a finger has touched them (until it
 * touches somewhere else). The dots jump to a slide and start the 6 seconds
 * again. Never advances under reduced motion.
 */
function carousel(root) {
  const slides = [...root.querySelectorAll(".slide")];
  const dots = [...root.querySelectorAll("[data-go]")];
  const held = new Set();
  let current = slides.findIndex((s) => s.classList.contains("is-active"));
  let timer = null;
  if (current < 0) current = 0;

  const show = (index) => {
    current = (index + slides.length) % slides.length;
    slides.forEach((slide, n) => {
      const on = n === current;
      slide.classList.toggle("is-active", on);
      slide.toggleAttribute("inert", !on);
      if (on) slide.removeAttribute("aria-hidden");
      else slide.setAttribute("aria-hidden", "true");
    });
    dots.forEach((dot, n) => dot.setAttribute("aria-current", String(n === current)));
    root.dataset.current = String(current);
  };

  const schedule = () => {
    clearTimeout(timer);
    timer = null;
    if (!motion.matches || held.size) return;
    timer = setTimeout(() => {
      show(current + 1);
      schedule();
    }, ADVANCE_MS);
  };
  const hold = (why) => {
    held.add(why);
    schedule();
  };
  const release = (why) => {
    if (held.delete(why)) schedule();
  };

  for (const dot of dots) {
    dot.addEventListener("click", () => {
      show(Number(dot.dataset.go));
      schedule();
    });
  }
  root.addEventListener("pointerenter", (e) => e.pointerType !== "touch" && hold("hover"));
  root.addEventListener("pointerleave", (e) => e.pointerType !== "touch" && release("hover"));
  root.addEventListener("focusin", () => hold("focus"));
  root.addEventListener("focusout", (e) => {
    if (!root.contains(e.relatedTarget)) release("focus");
  });
  document.addEventListener("pointerdown", (e) => {
    if (e.pointerType !== "touch") return;
    if (root.contains(e.target)) hold("touch");
    else release("touch");
  });
  motion.addEventListener?.("change", schedule);

  root.querySelector(".dots")?.removeAttribute("hidden");
  show(current);
  schedule();
}

/** The phone menu is a popover; a tap on one of its links should close it. */
function menu(root) {
  const panel = root.querySelector("#site-menu");
  if (!panel || typeof panel.hidePopover !== "function") return;
  panel.addEventListener("click", (e) => {
    if (e.target.closest("a")) panel.hidePopover();
  });
}

reveal(document.documentElement);
menu(document);
const hero = document.querySelector("[data-carousel]");
if (hero) carousel(hero);
