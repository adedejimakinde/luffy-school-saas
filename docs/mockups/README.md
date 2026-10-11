# Phase 1 mockups

Static pages for review before the real work starts. Nothing here is served by
Django, and the folder is deleted when Phase 2 moves each design into its
template.

- `homepage.html`, `homepage.css`: the new classnode.co homepage.
- `staff-sign-in-*.html`, `staff-sign-in.css`: the staff sign-in flow, as
  four screens: the form, the form after a refusal, the school picker and the
  empty state.

They link `../../static/web/design.css`, the fonts and the slider's WebP shots
in `static/website/shots/` (`slide-{home,report,register,fees}-{desk,phone}-*`), so serve
the repository root to view them, for example `npx http-server -p 8090 .` and
open `http://127.0.0.1:8090/docs/mockups/homepage.html`.

The shots are Sunrise Demo Academy from `seed_demo`, on a local demo with
one week of registers added (so the attendance chart is not empty), the Ogun
State template switched on, and Friday's JSS 1A register left open so it could
be photographed being taken.

The three photo spots are marked placeholders until licensed photos arrive.
Every name and figure is made up.
