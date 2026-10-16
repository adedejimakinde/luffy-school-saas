"""Small things the blog's templates draw: a writer's initials, a picture's `srcset`."""

from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def initials(name: str) -> str:
    """"Kemi Oladipo" is KO; one name is its first letter."""
    parts = [part for part in (name or "").split() if part[:1].isalpha()]
    if not parts:
        return ""
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()


@register.simple_tag
def cover(image, alt, sizes, eager=False, base="/blog/images/"):
    """A post's cover, at both of its widths, sized so the page does not jump.

    `base` is where the pictures are served: classnode.co's `/blog/images/`,
    or the portal's `/write/images/` for a post that is not published yet.
    """
    if image is None:
        return ""
    return format_html(
        '<img class="cover" src="{}{}.webp" srcset="{}{}-small.webp {}w, {}{}.webp {}w" sizes="{}" '
        'alt="{}" width="{}" height="{}" {}decoding="async">',
        base, image.key,
        base, image.key, image.small_width,
        base, image.key, image.width,
        sizes,
        alt,
        image.width,
        image.height,
        mark_safe('fetchpriority="high" ') if eager else mark_safe('loading="lazy" '),
    )
