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

from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

from results import look
from schools.hosts import portal_host

from . import themes
from .models import PageKey, SectionKind

#: Where each fixed page answers (§2.1), in the order the menu lists them.
PAGE_PATHS = {
    PageKey.HOME: "/",
    PageKey.ABOUT: "/about/",
    PageKey.ADMISSIONS: "/admissions/",
    PageKey.NEWS: "/news/",
    PageKey.GALLERY: "/gallery/",
    PageKey.CONTACT: "/contact/",
}

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


def enabled_pages(snapshot):
    """The snapshot's switched-on pages, in the menu's order, Home always first."""
    on = {p["key"]: p for p in snapshot.get("pages", []) if p["enabled"]}
    return [on[key] for key in PAGE_PATHS if key in on]


def find_page(snapshot, key):
    for page in snapshot.get("pages", []):
        if page["key"] == key and page["enabled"]:
            return page
    return None


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


def _section(theme, section, pages_on, school, address):
    kind = section["kind"]
    data = dict(section["data"])
    if kind == SectionKind.ADMISSIONS_CTA:
        # The button goes where the school has a page to send a family to.
        data["href"] = (
            PAGE_PATHS[PageKey.ADMISSIONS] if PageKey.ADMISSIONS in pages_on
            else PAGE_PATHS[PageKey.CONTACT] if PageKey.CONTACT in pages_on
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


def draw(school, revision, key, host) -> Drawn | None:
    """The page `key` of this revision, drawn, or None if the school has it switched off."""
    snapshot = revision.snapshot
    page = find_page(snapshot, key)
    if page is None:
        return None
    theme = theme_of(snapshot)
    card = look.for_site(school.name)
    style = style_block(colour_for(snapshot, card["colour"]))
    pages = enabled_pages(snapshot)
    pages_on = {p["key"] for p in pages}
    root = f"https://{host}"
    label = PageKey(key).label
    title = page["title"] or (school.name if key == PageKey.HOME else f"{label} | {school.name}")
    sections = [_section(theme, s, pages_on, school, school.address) for s in page["sections"]]
    context = {
        "indexable": True,
        "school": school,
        "look": card,
        "style": style,
        "title": title,
        "description": page["description"] or school.about[:160],
        "canonical": root + PAGE_PATHS[key],
        "key": key,
        "label": label,
        "nav": [
            {"key": p["key"], "path": PAGE_PATHS[p["key"]], "label": PageKey(p["key"]).label,
             "current": p["key"] == key}
            for p in pages
        ],
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
        f"<url><loc>{root}{PAGE_PATHS[p['key']]}</loc><lastmod>{day}</lastmod></url>"
        for p in enabled_pages(revision.snapshot)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>\n'
    )


__all__ = ["PAGE_PATHS", "Drawn", "csp", "draw", "sitemap", "style_hash", "theme_of"]
