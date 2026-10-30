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

**One inline `<style>`**, carrying the school's colour, and nothing else
inline. Its SHA-256 goes into the page's Content-Security-Policy (`csp()`), so
the policy can refuse every other inline style and every script.
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

from . import themes
from .models import PageKey, PageKind, SectionKind

#: Where each fixed page answers (§2.1), in the order the menu lists them.
PAGE_PATHS = {
    PageKey.HOME: "/",
    PageKey.ABOUT: "/about/",
    PageKey.ADMISSIONS: "/admissions/",
    PageKey.NEWS: "/news/",
    PageKey.GALLERY: "/gallery/",
    PageKey.CONTACT: "/contact/",
}

#: On a phone, the menu shows this many links and puts the rest under "More" (§2.1.1).
MENU_ON_A_PHONE = 5

#: How each network the footer may link to is written.
NETWORK_NAMES = {"facebook": "Facebook", "instagram": "Instagram", "x": "X", "youtube": "YouTube",
                 "tiktok": "TikTok", "linkedin": "LinkedIn"}

#: The colour the school's colour must reach against white to carry white text.
WHITE = "#FFFFFF"


def theme_of(snapshot) -> str:
    """The snapshot's theme, or the default if it names one this platform no longer has."""
    key = snapshot.get("theme")
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


def style_block(colour) -> str:
    """The page's one inline style. `colour` is six hex digits, checked twice before here."""
    return f":root{{--school:{colour}}}"


def style_hash(style) -> str:
    return base64.b64encode(hashlib.sha256(style.encode()).digest()).decode()


def csp(style) -> str:
    """The Content-Security-Policy of a public page whose one inline style is `style`."""
    return "; ".join(
        (
            "default-src 'self'",
            "img-src 'self' data:",
            f"style-src 'self' 'sha256-{style_hash(style)}'",
            "font-src 'self'",
            "script-src 'none'",
            "object-src 'none'",
            "frame-src 'none'",
            "form-action 'self'",
            "base-uri 'none'",
            "frame-ancestors 'none'",
        )
    )


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


def find_page(snapshot, key=None, *, slug=None):
    """The switched-on page with this key, or the switched-on custom page at this slug."""
    for page in snapshot.get("pages", []):
        if not page["enabled"]:
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


def _section(theme, section, live_paths, school, address):
    kind = section["kind"]
    data = dict(section["data"])
    if kind == SectionKind.HERO:
        data["buttons"] = [b for b in data.get("buttons", []) if link_is_live(b["link"], live_paths)]
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
    return {
        "kind": kind,
        "variant": section["variant"],
        "data": data,
        "template": f"schoolsite/themes/{theme}/parts/{kind}.html",
    }


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


def draw(school, revision, key, host, *, slug=None) -> Drawn | None:
    """The fixed page `key`, or the school's own page at `slug`, as published, drawn.

    None if the school has that page switched off, or never published it.
    """
    snapshot = revision.snapshot
    page = find_page(snapshot, key, slug=slug)
    if page is None:
        return None
    key = "" if slug is not None else key
    theme = theme_of(snapshot)
    card = look.for_site(school.name)
    style = style_block(colour_for(snapshot, card["colour"]))
    pages = enabled_pages(snapshot)
    live_paths = {page_path(p) for p in pages}
    root = f"https://{host}"
    label = page_label(page)
    if is_custom(page):
        title = f"{label} | {school.name}"
    else:
        title = page["title"] or (school.name if key == PageKey.HOME else f"{label} | {school.name}")
    sections = [_section(theme, s, live_paths, school, school.address) for s in page["sections"]]
    nav = [
        {"path": page_path(p), "label": page_label(p), "current": p is page}
        for p in pages
    ]
    context = {
        "indexable": True,
        "school": school,
        "look": card,
        "style": style,
        "title": title,
        "description": page["description"] or school.about[:160],
        "canonical": root + page_path(page),
        "key": key,
        "label": label,
        "nav": nav,
        "nav_more": nav[MENU_ON_A_PHONE:],
        "menu_on_a_phone": MENU_ON_A_PHONE,
        "sections": sections,
        "has_hero": any(s["kind"] == SectionKind.HERO for s in sections),
        "footer": _footer(snapshot.get("footer") or {}),
        "portal_host": portal_host(),
        "structured_data": structured_data(school, root, snapshot) if key == PageKey.HOME else "",
    }
    html = render_to_string(f"schoolsite/themes/{theme}/page.html", context)
    return Drawn(html=html, style=style)


def sitemap(revision, host) -> str:
    root = f"https://{host}"
    day = revision.published_at.date().isoformat()
    urls = "".join(
        f"<url><loc>{root}{escape(page_path(p))}</loc><lastmod>{day}</lastmod></url>"
        for p in enabled_pages(revision.snapshot)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n'
    )


__all__ = [
    "MENU_ON_A_PHONE",
    "PAGE_PATHS",
    "Drawn",
    "csp",
    "draw",
    "enabled_pages",
    "link_is_live",
    "page_label",
    "page_path",
    "sitemap",
    "style_hash",
    "theme_of",
]
