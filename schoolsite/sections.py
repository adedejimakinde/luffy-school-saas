"""What each section may hold, checked on the server before anything is stored.

`docs/school-sites.md` §2.2. A section is a fixed kind, a layout variant from
that kind's own short list, and data: a mapping of known fields, each of a known
type and length. Text is plain text, stored as written (with its paragraph
breaks) and escaped wherever it is drawn; nothing here is markup. A field this
module does not know is refused, not dropped, and so is a value of the wrong
type: the editor is told, rather than finding it missing later.

Links come from structured fields only and are held to `clean_link`: a path
from the fixed page list, a custom page's `/pages/<slug>/`, `https:`, `tel:` or
`mailto:`, and nothing else (§10.2). Whether a custom page at that address exists
is the services' to ask, against the draft; a link to a page that is off or
unpublished is left out when the page is drawn (`schoolsite.render`).

**A custom page's address** (§2.1.1) is a slug the school gives, or one made from
its title (`slug_from_title`): lowercase letters, digits and single hyphens, at
most 40 characters, and never a fixed page's key or a name the platform routes
(`schools.paths`), so `/pages/about/` cannot stand in for About.

**Pictures, albums and news are named by id and checked for shape here**: a
count, an album id, picture ids. Whether that album or picture exists in the
school's draft, and is the right sort (a hero's photo or video, a portrait, a
gallery photo), is `schoolsite.pictures.check_media`'s to ask (PR 5); news is
PR 6. A picture's focal point and alt text live on the picture itself
(`SitePicture`), so every place it is drawn crops it the same way; a hero's old
`focal` field is still accepted and is not used.
"""

import datetime
import re
import unicodedata
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from schools.paths import PORTAL, PUBLIC_SITE, RESERVED

from .errors import SiteRefused
from .models import SLUG_LENGTH, SLUG_PATTERN, PageKey, SectionKind


class SectionRefused(SiteRefused):
    """Section data this platform will not keep. The message is for the person."""


#: Each kind's layout variants, the first being the default. The names are the
#: engine's vocabulary; a theme styles every one of them (§2.2, §3.3).
VARIANTS = {
    SectionKind.HERO: ("image", "video", "split", "plain"),
    SectionKind.CREST_MOTTO: ("default",),
    SectionKind.PRINCIPAL_MESSAGE: ("default",),
    SectionKind.FACTS: ("default",),
    SectionKind.NEWS: ("default",),
    SectionKind.GALLERY: ("grid", "strip"),
    SectionKind.ADMISSIONS_CTA: ("default",),
    SectionKind.CONTACT_MAP: ("default",),
    SectionKind.TEXT: ("default",),
}

#: What `ALLOWED_ON` calls any page a school made itself (§2.1.1).
CUSTOM = "custom"

EVERY_PAGE = frozenset(PageKey.values) | {CUSTOM}

#: Which pages each kind may sit on (§2.2). A custom page takes the hero, text,
#: facts, a gallery, the principal's message and the admissions panel.
ALLOWED_ON = {
    SectionKind.HERO: EVERY_PAGE,
    SectionKind.CREST_MOTTO: frozenset({PageKey.HOME, PageKey.ABOUT}),
    SectionKind.PRINCIPAL_MESSAGE: frozenset({PageKey.HOME, PageKey.ABOUT, CUSTOM}),
    SectionKind.FACTS: frozenset({PageKey.HOME, PageKey.ABOUT, PageKey.ADMISSIONS, CUSTOM}),
    SectionKind.NEWS: frozenset({PageKey.HOME, PageKey.NEWS}),
    SectionKind.GALLERY: frozenset({PageKey.HOME, PageKey.GALLERY, PageKey.ABOUT, CUSTOM}),
    SectionKind.ADMISSIONS_CTA: EVERY_PAGE,
    SectionKind.CONTACT_MAP: frozenset({PageKey.CONTACT, PageKey.HOME}),
    SectionKind.TEXT: frozenset({PageKey.ABOUT, PageKey.ADMISSIONS, CUSTOM}),
}

#: The paths a link may name on the school's own site: its fixed pages (§2.1).
INTERNAL_PATHS = frozenset(
    {"/", "/about/", "/admissions/", "/admissions/enquire/", "/admissions/apply/",
     "/news/", "/gallery/", "/contact/"}
)

#: A link to one of the school's own pages: `/pages/<slug>/`.
_PAGE_LINK = re.compile(r"^/pages/([a-z0-9]+(?:-[a-z0-9]+)*)/$")
_SLUG = re.compile(SLUG_PATTERN)

#: What a custom page's address may never be: a fixed page's key, or a name the
#: platform routes on a school's host, the website's, the portal's or one held.
REFUSED_SLUGS = frozenset(PageKey.values) | PORTAL | PUBLIC_SITE | frozenset(RESERVED)

#: The motto's language, for its `lang` attribute (§11.1).
MOTTO_LANGUAGES = frozenset({"", "en", "la", "yo", "ig", "ha", "ar"})

#: Social networks the footer may link, each with the hosts its links may name.
SOCIAL_HOSTS = {
    "facebook": frozenset({"facebook.com", "www.facebook.com", "m.facebook.com"}),
    "instagram": frozenset({"instagram.com", "www.instagram.com"}),
    "x": frozenset({"x.com", "www.x.com", "twitter.com", "www.twitter.com"}),
    "youtube": frozenset({"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}),
    "tiktok": frozenset({"tiktok.com", "www.tiktok.com"}),
    "linkedin": frozenset({"linkedin.com", "www.linkedin.com"}),
}

#: Where a "maps link" may point.
MAPS_HOSTS = frozenset({"maps.google.com", "maps.app.goo.gl", "goo.gl", "www.google.com", "google.com"})

#: `website.forms`' phone rule: digits, spaces, brackets and dashes, with a leading +.
_PHONE = re.compile(r"^\+?[0-9][0-9 ()-]{5,22}[0-9]$")
_SESSION = re.compile(r"^(\d{4})/(\d{4})$")
#: C0 controls but tab and newline, DEL, and the C1 block.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_BIGGEST_ID = 2**63 - 1


# -- the values --------------------------------------------------------------


def _text(value, label, limit, *, required=False, lines=False):
    """Plain text: a string, trimmed, at most `limit` characters, or `SectionRefused`.

    Single-line text has its runs of whitespace folded to one space. Multi-line
    text keeps its paragraph breaks, with Windows line endings made plain.
    Control characters are refused rather than quietly removed.
    """
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise SectionRefused(f"{label} is text.")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    if _CONTROL.search(value):
        raise SectionRefused(f"{label} has a character in it that is not text.")
    if lines:
        value = "\n".join(line.rstrip() for line in value.strip().split("\n"))
        value = re.sub(r"\n{3,}", "\n\n", value)
    else:
        value = " ".join(value.split())
    if required and not value:
        raise SectionRefused(f"{label} cannot be empty.")
    if len(value) > limit:
        raise SectionRefused(f"{label} can be at most {limit} characters.")
    return value


def _integer(value, label, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise SectionRefused(f"{label} is a whole number from {low} to {high}.")
    return value


def _number(value, label, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise SectionRefused(f"{label} is a number from {low} to {high}.")
    return float(value)


def _id(value, label):
    """An id of something PR 5 or 6 brings: a positive whole number, shape only."""
    return _integer(value, label, 1, _BIGGEST_ID)


def _optional_id(value, label):
    return None if value is None else _id(value, label)


def _choice(value, label, choices):
    if value not in choices:
        raise SectionRefused(f"{label} is not one of the choices.")
    return value


def _list(value, label, most):
    if not isinstance(value, list):
        raise SectionRefused(f"{label} is a list.")
    if len(value) > most:
        raise SectionRefused(f"{label} can have at most {most}.")
    return value


def _fields(data, label, known):
    if not isinstance(data, dict):
        raise SectionRefused(f"{label} is a set of named fields.")
    unknown = set(data) - set(known)
    if unknown:
        name = sorted(str(n) for n in unknown)[0][:40]
        raise SectionRefused(f"{label} has no field called {name!r}.")
    return data


def _https(value, label):
    """An `https://` address with a host and nothing a parser could read two ways."""
    if not value.startswith("https://") or any(c.isspace() or c == "\\" for c in value):
        raise SectionRefused(f"{label} must be a full https:// address.")
    parts = urlsplit(value)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or "@" in parts.netloc or "." not in host:
        raise SectionRefused(f"{label} must be a full https:// address.")
    return parts, host


def clean_link(value, label="A link"):
    """A link a button or a footer may carry, or `SectionRefused`.

    A path from the school's own fixed pages, an `https://` address (WhatsApp's
    `https://wa.me/…` among them), `tel:` with a phone number, or `mailto:` with
    one email address. Never `javascript:`, `data:`, `vbscript:`, a
    protocol-relative `//`, or anything with spaces, backslashes or control
    characters in it, which browsers and parsers read in different ways.
    """
    value = _text(value, label, 300, required=True)
    if value in INTERNAL_PATHS:
        return value
    match = _PAGE_LINK.match(value)
    if match and len(match.group(1)) <= SLUG_LENGTH:
        return value
    if value.startswith("/"):
        raise SectionRefused(f"{label} names a page this site does not have.")
    if value.startswith("tel:"):
        if not _PHONE.match(value[4:]):
            raise SectionRefused(f"{label} has a phone number this cannot call.")
        return value
    if value.startswith("mailto:"):
        address = value[7:]
        try:
            validate_email(address)
        except ValidationError:
            raise SectionRefused(f"{label} has an email address this cannot write to.")
        return value
    _https(value, label)
    return value


def _phone(value, label):
    value = _text(value, label, 30)
    if value and not _PHONE.match(value):
        raise SectionRefused(f"{label} is not a phone number.")
    return value


def _year(value, label):
    return None if value is None else _integer(value, label, 1800, datetime.date.today().year)


def _date(value, label):
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise SectionRefused(f"{label} is a date, like 2027-06-30.")
    try:
        return datetime.date.fromisoformat(value).isoformat()
    except ValueError:
        raise SectionRefused(f"{label} is a date, like 2027-06-30.")


def _session(value, label):
    value = _text(value, label, 9)
    if not value:
        return ""
    match = _SESSION.match(value)
    if not match or int(match.group(2)) != int(match.group(1)) + 1 or not 2000 <= int(match.group(1)) <= 2100:
        raise SectionRefused(f"{label} is two years in a row, like 2027/2028.")
    return value


def _button(value, label):
    value = _fields(value, label, {"label", "link"})
    return {
        "label": _text(value.get("label"), f"{label}'s words", 40, required=True),
        "link": clean_link(value.get("link"), f"{label}'s link"),
    }


# -- each kind ---------------------------------------------------------------


def _hero(data):
    data = _fields(data, "The hero", {"heading", "subheading", "buttons", "image", "focal", "video"})
    buttons = _list(data.get("buttons", []), "The hero's buttons", 2)
    focal = data.get("focal")
    if focal is not None:
        focal = _fields(focal, "The focal point", {"x", "y"})
        focal = {
            "x": _number(focal.get("x"), "The focal point's across", 0, 1),
            "y": _number(focal.get("y"), "The focal point's down", 0, 1),
        }
    image = _optional_id(data.get("image"), "The picture")
    video = _optional_id(data.get("video"), "The video")
    if image is not None and video is not None:
        raise SectionRefused("A hero shows a photo or a video, not both.")
    return {
        "heading": _text(data.get("heading"), "The heading", 120, required=True),
        "subheading": _text(data.get("subheading"), "The line under the heading", 240),
        "buttons": [_button(b, f"Button {i}") for i, b in enumerate(buttons, start=1)],
        "image": image,
        "focal": focal,
        "video": video,
    }


def _crest_motto(data):
    data = _fields(data, "The motto", {"motto", "language", "translation", "founded"})
    return {
        "motto": _text(data.get("motto"), "The motto", 120),
        "language": _choice(data.get("language", ""), "The motto's language", MOTTO_LANGUAGES),
        "translation": _text(data.get("translation"), "The motto's translation", 160),
        "founded": _year(data.get("founded"), "The year founded"),
    }


def _principal_message(data):
    data = _fields(data, "The principal's message", {"portrait", "name", "title", "message", "signature"})
    return {
        "portrait": _optional_id(data.get("portrait"), "The portrait"),
        "name": _text(data.get("name"), "The principal's name", 120),
        "title": _text(data.get("title"), "The principal's title", 80),
        "message": _text(data.get("message"), "The message", 4000, required=True, lines=True),
        "signature": _text(data.get("signature"), "The signature line", 120),
    }


def _fact(value, label):
    value = _fields(value, label, {"figure", "label", "source"})
    return {
        "figure": _text(value.get("figure"), f"{label}'s figure", 16, required=True),
        "label": _text(value.get("label"), f"{label}'s words", 120, required=True),
        "source": _text(value.get("source"), f"{label}'s source", 160),
    }


def _facts(data):
    data = _fields(data, "The facts", {"items"})
    items = _list(data.get("items", []), "The facts", 6)
    if len(items) < 2:
        raise SectionRefused("The facts need at least 2.")
    return {"items": [_fact(item, f"Fact {i}") for i, item in enumerate(items, start=1)]}


def _news(data):
    data = _fields(data, "The news", {"count"})
    return {"count": _integer(data.get("count", 3), "How many posts to show", 3, 6)}


def _gallery(data):
    data = _fields(data, "The gallery", {"album", "count", "photos"})
    album, photos = data.get("album"), data.get("photos")
    if (album is None) == (photos is None):
        raise SectionRefused("A gallery shows one album, or photos chosen one by one.")
    if album is not None:
        return {
            "album": _id(album, "The album"),
            "count": _integer(data.get("count", 6), "How many photos to show", 1, 12),
        }
    if "count" in data:
        raise SectionRefused("Photos chosen one by one are all shown; there is no count to set.")
    photos = _list(photos, "The photos", 12)
    if not photos:
        raise SectionRefused("Choose at least one photo.")
    return {"photos": [_id(p, "A photo") for p in photos]}


def _admissions_cta(data):
    data = _fields(data, "The admissions panel", {"heading", "text", "button", "link", "session", "open", "closes"})
    if "open" in data and not isinstance(data["open"], bool):
        raise SectionRefused("Whether admissions are open is yes or no.")
    link = data.get("link") or ""
    if link:
        link = clean_link(link, "The button's link")
        if not link.startswith("/"):
            raise SectionRefused("The admissions button goes to one of the school's own pages.")
    return {
        "heading": _text(data.get("heading"), "The heading", 120, required=True),
        "text": _text(data.get("text"), "The words", 600, lines=True),
        "button": _text(data.get("button"), "The button's words", 40),
        # Empty: the button goes to the Admissions page, else Contact (`render`).
        "link": link,
        "session": _session(data.get("session"), "The session"),
        "open": data.get("open", True),
        "closes": _date(data.get("closes"), "The closing date"),
    }


def _contact_map(data):
    data = _fields(data, "The contact panel", {"whatsapp", "hours", "latitude", "longitude", "maps_link"})
    latitude, longitude = data.get("latitude"), data.get("longitude")
    if (latitude is None) != (longitude is None):
        raise SectionRefused("A place on the map needs both its latitude and its longitude.")
    maps_link = _text(data.get("maps_link"), "The maps link", 300)
    if maps_link:
        parts, host = _https(maps_link, "The maps link")
        if host not in MAPS_HOSTS or (host.endswith("google.com") and host != "maps.google.com"
                                      and not parts.path.startswith("/maps")):
            raise SectionRefused("The maps link must be a Google Maps address.")
    return {
        "whatsapp": _phone(data.get("whatsapp"), "The WhatsApp number"),
        "hours": _text(data.get("hours"), "The office hours", 200, lines=True),
        "latitude": None if latitude is None else _number(latitude, "The latitude", -90, 90),
        "longitude": None if longitude is None else _number(longitude, "The longitude", -180, 180),
        "maps_link": maps_link,
    }


def _plain_text(data):
    data = _fields(data, "The text", {"heading", "body"})
    return {
        "heading": _text(data.get("heading"), "The heading", 120),
        "body": _text(data.get("body"), "The text", 6000, required=True, lines=True),
    }


_CLEANERS = {
    SectionKind.HERO: _hero,
    SectionKind.CREST_MOTTO: _crest_motto,
    SectionKind.PRINCIPAL_MESSAGE: _principal_message,
    SectionKind.FACTS: _facts,
    SectionKind.NEWS: _news,
    SectionKind.GALLERY: _gallery,
    SectionKind.ADMISSIONS_CTA: _admissions_cta,
    SectionKind.CONTACT_MAP: _contact_map,
    SectionKind.TEXT: _plain_text,
}


def clean_kind(kind, page_key, page_name=None):
    """The kind, if it exists and may sit on this page, or `SectionRefused`.

    `page_key` is a fixed page's key, or `CUSTOM` for a page the school made,
    named in the refusal by `page_name`.
    """
    if kind not in SectionKind.values:
        raise SectionRefused("That is not one of the kinds of section on offer.")
    if page_key not in ALLOWED_ON[kind]:
        name = page_name or (PageKey(page_key).label if page_key in PageKey.values else "this")
        raise SectionRefused(f"A {SectionKind(kind).label.lower()} section cannot go on the {name} page.")
    return kind


def clean_variant(kind, variant):
    """The variant, or the kind's default when none is given, or `SectionRefused`."""
    if variant in (None, ""):
        return VARIANTS[kind][0]
    if variant not in VARIANTS[kind]:
        raise SectionRefused(f"A {SectionKind(kind).label.lower()} section has no such layout.")
    return variant


def clean(kind, data) -> dict:
    """A section's data as it may be stored, or `SectionRefused` saying why not."""
    return _CLEANERS[kind](data)


def clean_footer(data) -> dict:
    """The site-wide footer's data: social links and an address line."""
    data = _fields(data, "The footer", {"social", "address_line"})
    social = []
    seen = set()
    for i, item in enumerate(_list(data.get("social", []), "The social links", len(SOCIAL_HOSTS)), start=1):
        item = _fields(item, f"Social link {i}", {"network", "url"})
        network = _choice(item.get("network"), f"Social link {i}'s network", SOCIAL_HOSTS)
        if network in seen:
            raise SectionRefused(f"The footer already links to {network}.")
        seen.add(network)
        url = _text(item.get("url"), f"Social link {i}", 300, required=True)
        _, host = _https(url, f"Social link {i}")
        if host not in SOCIAL_HOSTS[network]:
            raise SectionRefused(f"Social link {i} is not a {network} address.")
        social.append({"network": network, "url": url})
    return {
        "social": social,
        "address_line": _text(data.get("address_line"), "The footer's address line", 200),
    }


def clean_page_title(value, *, required=False):
    return _text(value, "The page title", 70, required=required)


def page_links(data) -> set:
    """The custom-page slugs a section's data links to: its buttons, and the admissions button."""
    links = [b.get("link", "") for b in data.get("buttons", [])] + [data.get("link") or ""]
    return {m.group(1) for m in map(_PAGE_LINK.match, links) if m}


def clean_slug(value):
    """An address the school gave its page, as given, or `SectionRefused` saying why not."""
    if not isinstance(value, str):
        raise SectionRefused("The page's web address is text.")
    value = value.strip().lower()
    if not value:
        raise SectionRefused("The page needs a web address.")
    if len(value) > SLUG_LENGTH:
        raise SectionRefused(f"The page's web address can be at most {SLUG_LENGTH} characters.")
    if not _SLUG.match(value):
        raise SectionRefused(
            "The page's web address is lowercase letters and numbers, with single hyphens between words."
        )
    if value in REFUSED_SLUGS:
        raise SectionRefused(f"/pages/{value}/ is kept for the site's own pages. Choose another address.")
    return value


def _slugify(title, what):
    """`title` as an address: no tone marks, anything else one hyphen, cut at a hyphen to fit."""
    plain = unicodedata.normalize("NFKD", title or "").encode("ascii", "ignore").decode().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", plain).strip("-")
    if len(slug) > SLUG_LENGTH:
        slug = slug[:SLUG_LENGTH + 1].rsplit("-", 1)[0] if "-" in slug[:SLUG_LENGTH + 1] else slug[:SLUG_LENGTH]
        slug = slug.strip("-")
    if not slug:
        raise SectionRefused(f"The {what}'s title has no letters or numbers to make a web address from. Give it one.")
    return slug


def slug_from_title(title):
    """An address made from a page's title: "Boarding & Hostel" is `boarding-hostel`.

    Letters with tone marks or dots lose them ("Ìmọ̀" is `imo`); anything that is
    not a letter or a digit becomes one hyphen; it is cut at a hyphen to fit in
    40 characters. Checked like a given address, so it may still be refused.
    """
    return clean_slug(_slugify(title, "page"))


def clean_album_slug(value):
    """An album's address under `/gallery/`, as given, or `SectionRefused`.

    Under its own prefix, so no platform name can clash with it; only its shape is checked.
    """
    if not isinstance(value, str):
        raise SectionRefused("The album's web address is text.")
    value = value.strip().lower()
    if not value:
        raise SectionRefused("The album needs a web address.")
    if len(value) > SLUG_LENGTH:
        raise SectionRefused(f"The album's web address can be at most {SLUG_LENGTH} characters.")
    if not _SLUG.match(value):
        raise SectionRefused(
            "The album's web address is lowercase letters and numbers, with single hyphens between words."
        )
    return value


def album_slug_from_title(title):
    """An album's address made from its title, the way a page's is."""
    return clean_album_slug(_slugify(title, "album"))


def clean_album_title(value):
    return _text(value, "The album's title", 120, required=True)


def clean_album_description(value):
    return _text(value, "The album's description", 600, lines=True)


def clean_alt(value, *, required=False):
    """What a picture shows, for people who cannot see it (§11.1)."""
    return _text(value, "The description of the picture", 250, required=required)


def clean_caption(value):
    return _text(value, "The caption", 200)


def clean_focal(value):
    """A focal point, `{"x", "y"}` each from 0 (left, top) to 1 (right, bottom)."""
    value = _fields(value, "The focal point", {"x", "y"})
    return (
        _number(value.get("x"), "The focal point's across", 0, 1),
        _number(value.get("y"), "The focal point's down", 0, 1),
    )


def clean_page_description(value):
    return _text(value, "The page description", 160)


def clean_note(value):
    return _text(value, "The note", 200)


__all__ = [
    "ALLOWED_ON",
    "CUSTOM",
    "INTERNAL_PATHS",
    "REFUSED_SLUGS",
    "SOCIAL_HOSTS",
    "SectionRefused",
    "VARIANTS",
    "album_slug_from_title",
    "clean",
    "clean_album_description",
    "clean_album_slug",
    "clean_album_title",
    "clean_alt",
    "clean_caption",
    "clean_focal",
    "clean_footer",
    "clean_kind",
    "clean_link",
    "clean_note",
    "clean_page_description",
    "clean_page_title",
    "clean_slug",
    "clean_variant",
    "page_links",
    "slug_from_title",
]
