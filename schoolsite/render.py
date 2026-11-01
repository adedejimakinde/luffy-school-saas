"""A school's published revision, drawn as the pages of its public website.

`docs/school-sites.md` §2 and §6, PR 3. What is drawn is the latest
`SiteRevision`'s snapshot and nothing of the draft; the school's name and
contact details are `School`'s, and its crest and colour are the report card's
(`results.look`), as on today's page.

Every page is drawn by `render_to_string` with no request, so nothing on it can
read who is asking: it is the same page for everybody, which is what lets it be
cached and sent with no cookie. Text is escaped by the templates; nothing here
or there is marked safe but the structured data, which `json_ld()` escapes for a
`<script>` element itself.

**One inline `<style>`**, carrying the school's colour and each picture's
focal point and colour (as classes, never a `style` attribute), and nothing
else inline. Its SHA-256 goes into the page's Content-Security-Policy (`csp()`),
so the policy can refuse every other inline style.

**Pictures** (PR 5) are drawn from what the revision recorded about them
(`snapshot["pictures"]`) and from each album as its principal last published it,
as a `<picture>` with AVIF and WebP sizes and a JPEG fallback, `sizes` from the
theme, width and height set, lazy below the hero. A picture whose file is no
longer on the server (deleted after that revision was published, then rolled
back to) is left out, with its section drawn without it. **Script** runs only on
a page that needs it, one module from `static/` (`schoolsite/site-app.js`): the
gallery's tap-to-enlarge, the hero video's loading rules (§9.2), and a hero
slideshow of more than one photo (Modern Campus), whose first photo is drawn
with the page and the rest added after it loads; the CSP then allows `'self'`
scripts and no others.

**Colours** are the school's palette (`palette_for`: its choices, the theme's
own, and the tints `schoolsite.themes` works out), written into the page's one
style as custom properties. **The map** is an outside frame only
on the page a visitor asked for it on (`?map=1`), and only that page's CSP
allows its host.
"""

import base64
import datetime
import hashlib
import json
from dataclasses import dataclass
from urllib.parse import quote
from xml.sax.saxutils import escape

from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

from results import look
from schools.hosts import portal_host

from . import pictures, sections as section_rules, themes
from .models import Album, PageKey, PageKind, SectionKind

#: Where each fixed page answers (§2.1), in the order the menu lists them.
PAGE_PATHS = {
    PageKey.HOME: "/",
    PageKey.ABOUT: "/about/",
    PageKey.ADMISSIONS: "/admissions/",
    PageKey.NEWS: "/news/",
    PageKey.GALLERY: "/gallery/",
    PageKey.CONTACT: "/contact/",
}

#: How many pages the header's bar shows from 1100px, and from 860px; the rest are under
#: "More" (§2.1.1). Under 860px every page is in the menu's panel. `modern.css` holds the same
#: two numbers (`:nth-child(n+6)`, `:nth-child(n+4)`).
MENU_IN_THE_BAR = 5
MENU_IN_A_NARROW_BAR = 3

#: How each network the footer may link to is written.
NETWORK_NAMES = {"facebook": "Facebook", "instagram": "Instagram", "x": "X", "youtube": "YouTube",
                 "tiktok": "TikTok", "linkedin": "LinkedIn"}

#: The colour the school's colour must reach against white to carry white text.
WHITE = "#FFFFFF"


def theme_of(snapshot) -> str:
    """The snapshot's theme, or the default if it names one this platform no longer has.

    A revision published on the starter theme names "starter", which is Modern Campus now.
    """
    key = snapshot.get("theme")
    key = themes.FORMER_THEMES.get(key, key)
    return key if key in themes.THEMES else themes.DEFAULT_THEME


def json_ld(data):
    """`data` as JSON safe to put inside a `<script>` element (`website.views`' rule)."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return mark_safe(text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))


def colour_for(snapshot, report_card_colour) -> str:
    """The school's colour: the theme's primary if it carries white text, else the card's."""
    chosen = (snapshot.get("options") or {}).get("colours", {}).get("primary")
    if chosen and themes.contrast(chosen, WHITE) >= look.MIN_CONTRAST:
        return chosen
    return report_card_colour


#: The colours the page's one style names, as custom properties the stylesheet draws with.
PALETTE_PROPERTIES = ("primary", "accent", "detail", "dark", "text", "surface", "tint", "warm", "mist", "mint")


def palette_for(snapshot, report_card_colour) -> dict:
    """Every colour the page is drawn with: the school's choices, the theme's own, the tints.

    The primary is the school's colour (`colour_for`), so a school that never chose
    one has its report card's, and the tints are worked out from that.
    """
    theme = theme_of(snapshot)
    options = dict(snapshot.get("options") or {})
    colours = {**(options.get("colours") or {}), "primary": colour_for(snapshot, report_card_colour)}
    chosen = themes.palette(theme, {**options, "colours": colours})
    return {name: chosen[name] for name in PALETTE_PROPERTIES if _is_hex(chosen.get(name, ""))}


def _is_hex(value) -> bool:
    return len(value) == 7 and value.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in value[1:])


def style_block(colour, rules=(), palette=None) -> str:
    """The page's one inline style. `colour` is six hex digits, checked twice before here, and
    so is every colour of `palette`; `rules` are the pictures' classes (`picture_rule`), built
    only from numbers and checked hex."""
    names = "".join(f";--{name}:{value}" for name, value in (palette or {}).items() if _is_hex(value))
    return f":root{{--school:{colour}{names}}}" + "".join(sorted(rules))


def style_hash(style) -> str:
    return base64.b64encode(hashlib.sha256(style.encode()).digest()).decode()


#: The one outside host a page may frame, and only on the page a visitor asked for the map on.
MAP_FRAME = "https://www.google.com"


def csp(style, *, script=False, map_frame=False) -> str:
    """The Content-Security-Policy of a public page whose one inline style is `style`.

    `script`: the page runs the site's own module (the gallery or the hero video).
    `map_frame`: a visitor tapped for the map, so this page frames Google Maps.
    """
    return "; ".join(
        (
            "default-src 'self'",
            "img-src 'self' data:",
            "media-src 'self'",
            f"style-src 'self' 'sha256-{style_hash(style)}'",
            "font-src 'self'",
            "script-src 'self'" if script else "script-src 'none'",
            "object-src 'none'",
            f"frame-src {MAP_FRAME}" if map_frame else "frame-src 'none'",
            "form-action 'self'",
            "base-uri 'none'",
            "frame-ancestors 'none'",
        )
    )


# -- pictures ----------------------------------------------------------------------

#: Where pictures are sent from: `/media/` once public, the editor's own route in the preview.
PUBLIC_MEDIA = "/media"
PREVIEW_MEDIA = "/website/pictures"


def picture_rule(entry) -> str:
    """A picture's class: where every crop centres (its focal point) and its colour while it loads."""
    x, y = (float(v) for v in entry.get("focal") or (0.5, 0.5))
    x, y = min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)
    rule = f"object-position:{x * 100:.1f}% {y * 100:.1f}%"
    colour = entry.get("colour") or ""
    if len(colour) == 7 and colour.startswith("#") and all(c in "0123456789abcdefABCDEF" for c in colour[1:]):
        rule += f";background-color:{colour}"
    return f".p{int(entry['id'])}{{{rule}}}"


class Pictures:
    """The pictures one page may draw, and the style rules the ones it does draw need."""

    def __init__(self, entries, available, media, theme_sizes):
        self.entries = entries
        self.available = available
        self.media = media
        self.sizes = theme_sizes or {}
        self.rules = set()
        self.script = False

    def get(self, pid, place, *, eager=False):
        entry = self.entries.get(str(pid)) if pid is not None else None
        return self.draw(entry, place, eager=eager)

    def draw(self, entry, place, *, eager=False):
        if not entry or not entry.get("ready") or entry.get("key") not in self.available or not entry.get("widths"):
            return None
        base = f"{self.media}/{entry['key']}/"
        stem = "poster-" if entry.get("video") else ""
        widths, jpegs = entry["widths"], entry.get("jpegs") or []
        self.rules.add(picture_rule(entry))
        sizes = self.sizes.get(place, "100vw")
        return {
            "id": entry["id"],
            "cls": f"p{int(entry['id'])}",
            "avif": ", ".join(f"{base}{stem}{w}.avif {w}w" for w in widths),
            "webp": ", ".join(f"{base}{stem}{w}.webp {w}w" for w in widths),
            "jpeg": f"{base}{stem}{jpegs[0]}.jpg" if jpegs else f"{base}{stem}{widths[0]}.webp",
            "jpeg_set": ", ".join(f"{base}{stem}{w}.jpg {w}w" for w in jpegs),
            "sizes": sizes,
            "w": entry.get("w") or widths[-1],
            "h": entry.get("h") or widths[-1],
            "alt": entry.get("alt", ""),
            "caption": entry.get("caption", ""),
            "eager": eager,
            "large_avif": f"{base}{stem}{widths[-1]}.avif",
            "large_webp": f"{base}{stem}{widths[-1]}.webp",
            "large_jpeg": f"{base}{stem}{jpegs[-1]}.jpg" if jpegs else f"{base}{stem}{widths[-1]}.webp",
            "loop": f"{base}loop.mp4" if entry.get("video") and entry.get("loop") else "",
        }


def available_keys(keys, *, public) -> set:
    """Which of these files are still on the server, and (for the public) public. One query, or none."""
    from files.models import State, StoredFile
    from django.db import connection

    keys = {k for k in keys if k}
    if not keys:
        return set()
    found = StoredFile.objects.filter(
        schema_name=connection.schema_name, key__in=keys, state__in=[State.READY, State.RETIRED]
    )
    if public:
        found = found.filter(public=True)
    return set(found.values_list("key", flat=True))


def _album_ids(page_sections):
    return {s["data"]["album"] for s in page_sections if s["kind"] == SectionKind.GALLERY and s["data"].get("album")}


def albums_for(ids=None, *, preview, slug=None, every=False) -> dict:
    """Albums as a page draws them, by id: as published for the public, as their draft in the preview."""
    found = Album.objects.all()
    if slug is not None:
        found = found.filter(slug=slug)
    elif not every:
        found = found.filter(pk__in=list(ids or ()))
    if not preview:
        found = found.filter(published__isnull=False)
    out = {}
    for album in found.order_by("-first_published_at", "-id"):
        shown = pictures.album_draft(album) if preview else album.published
        out[album.pk] = {**shown, "id": album.pk, "live": album.published is not None}
    return out


def is_custom(page) -> bool:
    """A page the school made (§2.1.1). A snapshot from before PR 3b has no kind: all fixed."""
    return page.get("kind") == PageKind.CUSTOM


def page_path(page) -> str:
    return f"/pages/{page['slug']}/" if is_custom(page) else PAGE_PATHS[page["key"]]


def page_label(page) -> str:
    """Its name in the menu: a fixed page's own name, or the title the school gave its page."""
    return page["title"] if is_custom(page) else PageKey(page["key"]).label


def _menu_place(page):
    if "menu_position" in page:
        return page["menu_position"]
    # A snapshot from before PR 3b: the order the menu had then.
    return list(PAGE_PATHS).index(page["key"])


def enabled_pages(snapshot):
    """The snapshot's switched-on pages, in the menu's order, Home always first."""
    on = [p for p in snapshot.get("pages", []) if p["enabled"] and (is_custom(p) or p["key"] in PAGE_PATHS)]
    return sorted(on, key=lambda p: (p.get("key") != PageKey.HOME, _menu_place(p)))


def find_page(snapshot, key=None, *, slug=None, include_off=False):
    """The switched-on page with this key, or the switched-on custom page at this slug.

    `include_off` finds it switched off too: the editor's preview shows every page of the draft.
    """
    for page in snapshot.get("pages", []):
        if not page["enabled"] and not include_off:
            continue
        if slug is not None and is_custom(page) and page["slug"] == slug:
            return page
        if slug is None and not is_custom(page) and page["key"] == key:
            return page
    return None


def link_is_live(link, live_paths) -> bool:
    """Whether a button's link may be drawn: anywhere off the site, or a page of it that is on.

    A link to one of the school's own pages that is switched off, or was never
    published, is left out rather than drawn as a way to a 404 (§2.2).
    """
    if not link.startswith("/"):
        return True
    return link in live_paths or any(link.startswith(path) for path in live_paths if path != "/")


def whatsapp_link(number) -> str:
    digits = "".join(c for c in number if c.isdigit())
    if digits.startswith("0"):
        digits = "234" + digits[1:]
    return f"https://wa.me/{digits}" if digits else ""


def maps_link(data, address) -> str:
    """The section's own maps link, else one from its place, else one from the address."""
    if data.get("maps_link"):
        return data["maps_link"]
    if data.get("latitude") is not None and data.get("longitude") is not None:
        return f"https://www.google.com/maps/search/?api=1&query={data['latitude']},{data['longitude']}"
    if address:
        return f"https://www.google.com/maps/search/?api=1&query={quote(address)}"
    return ""


@dataclass
class Drawn:
    html: str
    style: str
    script: bool = False
    map_frame: bool = False

    @property
    def csp(self) -> str:
        return csp(self.style, script=self.script, map_frame=self.map_frame)


#: How many photos a gallery section shows before "See the whole album".
GALLERY_DEFAULT_COUNT = 6


def map_embed(data, address) -> str:
    """The Google Maps frame's address, from the section's place, else the school's address."""
    if data.get("latitude") is not None and data.get("longitude") is not None:
        return f"https://www.google.com/maps?q={data['latitude']},{data['longitude']}&z=16&output=embed"
    if address:
        return f"https://www.google.com/maps?q={quote(address)}&z=16&output=embed"
    return ""


def _section(theme, section, live_paths, school, address, *, pics=None, albums=None, first=False, page_path_=None,
             map_open=False, within=lambda path: path, pill=""):
    kind = section["kind"]
    data = dict(section["data"])
    pics = pics or Pictures({}, set(), PUBLIC_MEDIA, {})
    if kind == SectionKind.HERO:
        data["buttons"] = [b for b in data.get("buttons", []) if link_is_live(b["link"], live_paths)]
        data["slide_list"], data["media"] = [], None
        if section.get("variant") != "plain":
            if data.get("video"):
                media = pics.get(data["video"], "hero", eager=first)
                data["media"] = media
                if media and media["loop"]:
                    pics.script = True
            else:
                # The slideshow: the first photo drawn with the page and fetched first (it
                # is the page's largest paint); the others only after the page has
                # loaded, by the site's script, and never with data saver on.
                drawn = [p for p in (pics.get(pid, "hero") for pid in section_rules.hero_slides(data)) if p]
                if drawn:
                    drawn[0] = pics.get(drawn[0]["id"], "hero", eager=first)
                    data["media"] = drawn[0]
                data["slide_list"] = drawn
                if len(drawn) > 1:
                    pics.script = True
        data["pill"] = pill
    if kind == SectionKind.PRINCIPAL_MESSAGE:
        data["portrait_picture"] = pics.get(data.get("portrait"), "portrait")
    if kind == SectionKind.GALLERY:
        place = "strip" if section.get("variant") == "strip" else "grid"
        shown, link, total, title = [], "", 0, ""
        if data.get("album"):
            album = (albums or {}).get(data["album"])
            if album:
                count = data.get("count") or GALLERY_DEFAULT_COUNT
                drawn = [p for p in (pics.draw(e, place) for e in album["photos"]) if p]
                total, shown, title = len(drawn), drawn[:count], album["title"]
                if shown and place == "grid":
                    # The mosaic draws its first photo tall, so it is fetched at that size.
                    first_entry = next(e for e in album["photos"] if e["id"] == shown[0]["id"])
                    shown[0] = pics.draw(first_entry, "tall")
                gallery = PAGE_PATHS[PageKey.GALLERY]
                if gallery in live_paths and total:
                    link = within(f"{gallery}{album['slug']}/")
        else:
            shown = [p for p in (pics.get(pid, place) for pid in data.get("photos", [])) if p]
            if shown and place == "grid":
                shown[0] = pics.get(shown[0]["id"], "tall")
        data["photo_list"] = shown
        data["album_more"] = max(total - len(shown), 0)
        data["album_title"] = title
        data["album_link"] = link
        data["album_total"] = total
        if shown:
            pics.script = True
    if kind == SectionKind.ADMISSIONS_CTA:
        # The button goes where the school sends it, if that page is on; else
        # where the school has a page to send a family to.
        if data.get("link"):
            data["href"] = data["link"] if link_is_live(data["link"], live_paths) else ""
        else:
            data["href"] = (
                PAGE_PATHS[PageKey.ADMISSIONS] if PAGE_PATHS[PageKey.ADMISSIONS] in live_paths
                else PAGE_PATHS[PageKey.CONTACT] if PAGE_PATHS[PageKey.CONTACT] in live_paths
                else ""
            )
        data["closes_on"] = datetime.date.fromisoformat(data["closes"]) if data.get("closes") else None
    if kind == SectionKind.CONTACT_MAP:
        data["whatsapp_link"] = whatsapp_link(data.get("whatsapp", ""))
        data["maps"] = maps_link(data, address)
        embed = map_embed(data, address)
        data["map_embed"] = embed if map_open else ""
        data["map_tap"] = f"{within(page_path_ or '/')}?map=1#map" if embed and not map_open else ""
    return {
        "kind": kind,
        "variant": section["variant"],
        "data": data,
        "template": f"schoolsite/themes/{theme}/parts/{kind}.html",
    }


def admissions_pill(page_sections) -> str:
    """The hero's small "Admissions open" line, from the page's own admissions panel.

    Drawn only while that panel says admissions are open, with its session when it
    names one; nothing when the page has no panel or admissions are closed.
    """
    panel = next((s["data"] for s in page_sections if s["kind"] == SectionKind.ADMISSIONS_CTA), None)
    if not panel or not panel.get("open", True):
        return ""
    return f"Admissions open for {panel['session']}" if panel.get("session") else "Admissions open"


def apply_href(live_paths) -> str:
    """Where the header's "Apply now" goes: the Admissions page if it is on, else Contact, else nowhere."""
    for key in (PageKey.ADMISSIONS, PageKey.CONTACT):
        if PAGE_PATHS[key] in live_paths:
            return PAGE_PATHS[key]
    return ""


#: Where "Powered by Classnode" goes.
CLASSNODE = "https://classnode.co"


def _footer(footer):
    social = [{**link, "label": NETWORK_NAMES.get(link["network"], link["network"])}
              for link in footer.get("social", [])]
    return {**footer, "social": social}


def structured_data(school, canonical_root, snapshot):
    """Who the school is, as search engines read it: only what the school published."""
    data = {"@context": "https://schema.org", "@type": "EducationalOrganization",
            "name": school.name, "url": canonical_root + "/"}
    if school.address:
        data["address"] = {"@type": "PostalAddress", "streetAddress": school.address, "addressCountry": "NG"}
    if school.phone:
        data["telephone"] = school.phone
    if school.contact_email:
        data["email"] = school.contact_email
    social = [link["url"] for link in (snapshot.get("footer") or {}).get("social", [])]
    if social:
        data["sameAs"] = social
    return json_ld(data)


def draw(school, revision, key, host, *, slug=None, album=None, map_open=False) -> Drawn | None:
    """The fixed page `key`, or the school's own page at `slug`, or an album's page, as published, drawn.

    None if the school has that page switched off, or never published it.
    """
    return draw_snapshot(school, revision.snapshot, key, host, slug=slug, album=album, map_open=map_open)


#: Where the editor's preview of the draft lives (`schoolsite.views.preview`).
PREVIEW_ROOT = "/website/preview"


def preview_path(path) -> str:
    """A path of the site as it is inside the preview: `/about/` is `/website/preview/about/`."""
    return f"{PREVIEW_ROOT}{path}"


def draw_snapshot(school, snapshot, key, host, *, slug=None, preview=False, album=None, map_open=False) -> Drawn | None:
    """A page of `snapshot` drawn: a published revision's, or, for the preview, the draft's.

    `preview` draws the draft for an editor (PR 4): any page of it, switched on or
    off, under a "Preview: not published" bar, with every link to a page of the
    site kept inside the preview, and never indexable. `album` is an album's slug:
    its own page under the Gallery page (PR 5). `map_open`: the visitor tapped for
    the map, so the contact panel frames it.
    """
    if album is not None:
        key, slug = PageKey.GALLERY, None
    page = find_page(snapshot, key, slug=slug, include_off=preview)
    if page is None:
        return None
    key = "" if slug is not None else key
    theme = theme_of(snapshot)
    card = look.for_site(school.name)
    pages = enabled_pages(snapshot)
    live_paths = {page_path(p) for p in pages}
    root = f"https://{host}"
    within = preview_path if preview else (lambda path: path)

    # The albums this page draws: one album's own page, every album on the
    # Gallery page, else those its gallery sections name.
    page_sections = [] if album is not None else page["sections"]
    if album is not None:
        albums = albums_for(preview=preview, slug=album)
        if not albums:
            return None
    elif key == PageKey.GALLERY:
        albums = albums_for(preview=preview, every=True)
    else:
        ids = _album_ids(page_sections)
        albums = albums_for(ids, preview=preview) if ids else {}
    entries = dict(snapshot.get("pictures") or {})
    keys = {e["key"] for e in entries.values()}
    for shown in albums.values():
        keys |= {p["key"] for p in shown["photos"]}
    pics = Pictures(entries, available_keys(keys, public=not preview),
                    PREVIEW_MEDIA if preview else PUBLIC_MEDIA, themes.THEMES[theme].sizes)

    label = page_label(page)
    album_page = None
    if album is not None:
        shown = next(iter(albums.values()))
        drawn = [p for p in (pics.draw(e, "grid") for e in shown["photos"]) if p]
        album_page = {"title": shown["title"], "description": shown["description"], "photos": drawn,
                      "live": shown["live"], "back": within(PAGE_PATHS[PageKey.GALLERY])}
        pics.script = pics.script or bool(drawn)
        title = f"{shown['title']} | {label} | {school.name}"
    elif is_custom(page):
        title = f"{label} | {school.name}"
    else:
        title = page["title"] or (school.name if key == PageKey.HOME else f"{label} | {school.name}")
    pill = admissions_pill(page_sections)
    sections = [
        _section(theme, s, live_paths, school, school.address, pics=pics, albums=albums, first=(i == 0),
                 page_path_=page_path(page), map_open=map_open, within=within, pill=pill)
        for i, s in enumerate(page_sections)
    ]
    album_cards = []
    if key == PageKey.GALLERY and album is None:
        for shown in albums.values():
            drawn = [p for p in (pics.draw(e, "cover") for e in shown["photos"]) if p]
            if drawn:
                album_cards.append({"title": shown["title"], "count": len(drawn), "cover": drawn[0],
                                    "link": within(f"{PAGE_PATHS[PageKey.GALLERY]}{shown['slug']}/"),
                                    "live": shown["live"]})
    if preview:
        for section in sections:
            data = section["data"]
            if "buttons" in data:
                data["buttons"] = [
                    {**b, "link": within(b["link"])} if b["link"].startswith("/") else b for b in data["buttons"]
                ]
            if data.get("href", "").startswith("/"):
                data["href"] = within(data["href"])
    nav = [
        {"path": within(page_path(p)), "label": page_label(p), "current": p is page}
        for p in pages
    ]
    hero = next((s["data"].get("media") for s in sections if s["kind"] == SectionKind.HERO), None)
    palette = palette_for(snapshot, card["colour"])
    style = style_block(palette["primary"], pics.rules, palette)
    apply = apply_href(live_paths)
    canonical = root + page_path(page) + (f"{album}/" if album is not None else "")
    context = {
        "indexable": not preview,
        "preview": {"off": not page["enabled"], "editor": "/website/"} if preview else None,
        "school": school,
        "look": card,
        "style": style,
        "title": title,
        "description": (album_page["description"][:160] if album_page and album_page["description"] else "")
        or page["description"] or school.about[:160],
        "canonical": canonical,
        "key": key,
        "label": album_page["title"] if album_page else label,
        "nav": nav,
        "menu_in_the_bar": MENU_IN_THE_BAR,
        "menu_in_a_narrow_bar": MENU_IN_A_NARROW_BAR,
        "home_path": within("/"),
        "sections": sections,
        "has_hero": any(s["kind"] == SectionKind.HERO for s in sections),
        "hero_preload": hero,
        "album": album_page,
        "album_cards": album_cards,
        "script": pics.script,
        "video_on_phones": themes.THEMES[theme].video_on_phones,
        "motion": themes.animations(snapshot.get("options")),
        "heading_font": themes.THEMES[theme].heading_font,
        "stylesheet": themes.THEMES[theme].stylesheet,
        "apply_href": within(apply) if apply else "",
        "classnode": CLASSNODE,
        "footer": _footer(snapshot.get("footer") or {}),
        "portal_host": portal_host(),
        "structured_data": structured_data(school, root, snapshot) if key == PageKey.HOME and not preview else "",
    }
    html = render_to_string(f"schoolsite/themes/{theme}/page.html", context)
    return Drawn(html=html, style=style, script=pics.script, map_frame=map_open and any(
        s["data"].get("map_embed") for s in sections))


def sitemap(revision, host) -> str:
    root = f"https://{host}"
    day = revision.published_at.date().isoformat()
    pages = enabled_pages(revision.snapshot)
    urls = "".join(
        f"<url><loc>{root}{escape(page_path(p))}</loc><lastmod>{day}</lastmod></url>"
        for p in pages
    )
    if any(not is_custom(p) and p["key"] == PageKey.GALLERY for p in pages):
        for slug, published_at in Album.objects.filter(published__isnull=False).values_list("slug", "published_at"):
            urls += (f"<url><loc>{root}{PAGE_PATHS[PageKey.GALLERY]}{escape(slug)}/</loc>"
                     f"<lastmod>{published_at.date().isoformat()}</lastmod></url>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n'
    )


__all__ = [
    "MAP_FRAME",
    "MENU_IN_A_NARROW_BAR",
    "MENU_IN_THE_BAR",
    "PAGE_PATHS",
    "Drawn",
    "Pictures",
    "albums_for",
    "available_keys",
    "admissions_pill",
    "apply_href",
    "csp",
    "draw",
    "draw_snapshot",
    "enabled_pages",
    "link_is_live",
    "page_label",
    "page_path",
    "palette_for",
    "preview_path",
    "sitemap",
    "style_hash",
    "theme_of",
]
