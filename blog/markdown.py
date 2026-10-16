"""A post's Markdown, turned into HTML that is safe to put on classnode.co.

Two steps, and the second is the guarantee:

1. **Python-Markdown** turns the writer's text into HTML, with tables and
   fenced code. It lets raw HTML through, as Markdown does.
2. **nh3** (the Rust `ammonia` sanitiser) keeps an allowlist of tags and
   attributes and drops everything else: `<script>` and `<style>` with their
   contents, `<iframe>`, `<object>`, forms, every `on…` handler, `style`,
   `class`, and any link that is not `http`, `https` or `mailto`. What is left
   is what this module returns, and the only markup added after it is our
   own fixed wrapper round a table.

**Pictures are ours only.** A post's picture is written `![what it shows](image:KEY)`,
where KEY is one of *this post's* uploads (`blog.images`). Any other `src`, a
picture from another site included, is dropped with its `<img>`, so every
picture on a post is one we converted to WebP and sized. Each is drawn with
its width and height, so the page does not jump as it loads, and lazily.

**Headings start at h2.** The page's title is its one h1; a `#` in the body
is drawn as an h2.

**Tables scroll inside the article** (`.post-table`), so a wide one never
makes the page scroll sideways; long words and addresses wrap in the
stylesheet (`static/blog/blog.css`).
"""

import re
from html import escape

import markdown as _markdown
import nh3

#: The tags a post may contain.
TAGS = {
    "p", "br", "hr", "h2", "h3", "h4", "strong", "em", "del", "code", "pre",
    "blockquote", "ul", "ol", "li", "a", "img",
    "table", "thead", "tbody", "tr", "th", "td",
}

#: And the attributes each may carry. Nothing else, so no handler and no style.
ATTRIBUTES = {
    "a": {"href", "title"},
    "img": {"src", "alt", "width", "height", "loading", "decoding"},
    "th": {"colspan", "rowspan"},
    "td": {"colspan", "rowspan"},
    "ol": {"start"},
}

#: Dropped along with everything inside them, not just their tags.
DROPPED_WITH_CONTENTS = {
    "script", "style", "iframe", "object", "embed", "template", "noscript",
    "textarea", "select", "svg", "math", "frameset", "noembed", "title",
}

URL_SCHEMES = {"http", "https", "mailto"}

_IMAGE = re.compile(r"image:([0-9a-f]{32})")
_IMG_TAG = re.compile(r"<img\b[^>]*>", re.I)
_SRC = re.compile(r'\bsrc="([^"]*)"', re.I)
_WORD = re.compile(r"[\w'’-]+")


def _markdown_to_html(text: str) -> str:
    return _markdown.markdown(
        text or "",
        extensions=["tables", "fenced_code", "sane_lists"],
        output_format="html",
    )


def _place_images(html: str, images: dict, base: str) -> str:
    """Point each `image:KEY` of this post at its file, with its size; drop any other `<img>`."""

    def one(match):
        tag = match.group(0)
        src = _SRC.search(tag)
        found = _IMAGE.fullmatch(src.group(1)) if src else None
        image = images.get(found.group(1)) if found else None
        if image is None:
            return ""
        alt = re.search(r'\balt="([^"]*)"', tag)
        return (
            f'<img src="{base}{image.key}.webp" alt="{alt.group(1) if alt else ""}" '
            f'width="{image.width}" height="{image.height}" loading="lazy" decoding="async">'
        )

    return _IMG_TAG.sub(one, html)


def sanitise(html: str) -> str:
    """Only `TAGS` and `ATTRIBUTES`, and links on `URL_SCHEMES`. Everything else is gone."""
    return nh3.clean(
        html,
        tags=TAGS,
        attributes=ATTRIBUTES,
        clean_content_tags=DROPPED_WITH_CONTENTS,
        url_schemes=URL_SCHEMES,
        link_rel="noopener noreferrer",
        strip_comments=True,
    )


def render(text: str, *, images=None, base: str = "/blog/images/") -> str:
    """The post's body as safe HTML. `images` maps this post's keys to its `BlogImage`s."""
    html = _markdown_to_html(text)
    # Headings start at h2: the page's title is its one h1.
    html = re.sub(r"<(/?)h1\b", r"<\1h2", html)
    html = _place_images(html, images or {}, base)
    html = sanitise(html)
    # And again on the sanitiser's own markup, which spells every tag one way:
    # whatever survived as an `<img>` and is not one of ours goes.
    ours = re.compile(rf'<img src="{re.escape(base)}[0-9a-f]{{32}}\.webp"')
    html = _IMG_TAG.sub(lambda m: m.group(0) if ours.match(m.group(0)) else "", html)
    # A wrapper of our own round each table, added after the sanitiser so it
    # is the only markup on the page the writer did not type.
    html = html.replace("<table>", '<div class="post-table"><table>').replace(
        "</table>", "</table></div>"
    )
    return html


def words(text: str) -> int:
    """About how many words a reader reads: the rendered text, not the Markdown."""
    plain = re.sub(r"<[^>]+>", " ", sanitise(_markdown_to_html(text)))
    return len(_WORD.findall(plain))


def image_keys(text: str) -> list:
    """Every `image:KEY` the Markdown names, in order, once each."""
    seen = []
    for key in _IMAGE.findall(text or ""):
        if key not in seen:
            seen.append(key)
    return seen


def images_without_alt(text: str) -> list:
    """The keys of pictures written with no description: `![](image:KEY)`."""
    return [
        match.group(2)
        for match in re.finditer(r"!\[([^\]]*)\]\(\s*image:([0-9a-f]{32})", text or "")
        if not match.group(1).strip()
    ]


def plain(text: str) -> str:
    """Escaped plain text, for a place that must not hold markup at all."""
    return escape(text or "")
