"""Changing a school's website draft, publishing it, and reading what was published.

`docs/school-sites.md` §2.3. Every function takes the acting login and the
school, asks `schoolsite.access` first, and writes nothing when the answer is no.
Every one refuses unless the connection is on that school's own schema, so a
school's id cannot be used to write into another school's draft.

**One draft, many editors.** Each part an editor saves carries a `version`: the
settings row for the theme and footer, a page for its own fields and the list of
its sections, a section for its own data. A save names the version it was based
on, and a save based on an older one is refused with `StaleDraft` rather than
quietly overwriting somebody else's change. Integers rather than timestamps, so
two saves in the same instant cannot both look current. Every write locks the
settings row first, so writes and a publish happen one after another.

**Publishing writes an artefact.** `publish_as()` snapshots the whole draft into
a `SiteRevision` the public site reads (PR 3), and nothing about the draft after
that changes what was published. `rollback_as()` publishes an older revision's
snapshot again as a new revision; the draft is left as it is, so the fix is made
there and published in its turn. Both are the principal's alone.

**"Ready for the principal"** is a mark on a draft version: an edit after it
means the draft is not ready again until somebody marks it. The email that
tells the principal arrives with the preview page it links to (PR 4).

**A page is named by its key or its address.** The six fixed pages by their key
(`"about"`); a page the school made by its slug (`"boarding"`), which can never be
a fixed page's key (`sections.REFUSED_SLUGS`). Making one, renaming it, deleting
it and the menu's order are PR 3b (§2.1.1); the menu's order and the list of
pages are site-wide, so they are saved against the settings row's version.
"""

from django.db import transaction
from django.utils import timezone

from . import access, sections, themes
from .errors import (
    NotAllowedToEdit,
    NotAllowedToPublish,
    NotAllowedToReadLog,
    SiteRefused,
    StaleDraft,
)
from .models import (
    CUSTOM_PAGE_SLOTS,
    MOST_SECTIONS,
    SLUG_LENGTH,
    Page,
    PageKey,
    PageKind,
    Section,
    SectionKind,
    SiteDelegationEvent,
    SitePublishEvent,
    SiteRevision,
    SiteSettings,
)

#: How many log rows `publish_log_as()` returns, newest first (§2.3: "the last 20").
LOG_LENGTH = 20

_UNCHANGED = object()


def _name_of(user) -> str:
    return user.full_name or user.get_username()


def _require_edit(actor, school):
    if not access.can_edit(actor, school):
        raise NotAllowedToEdit(
            f"{actor} may not change {school}'s website. That is the principal's, or the "
            f"administrator's when the principal allows it."
        )


def _require_principal(actor, school, what):
    if not access.can_publish(actor, school):
        raise NotAllowedToPublish(f"{actor} may not {what} at {school}. That is the principal's alone.")


def _check(version, current):
    if version != current:
        raise StaleDraft("Somebody else changed this since you opened it. Reload to see their change.")


def _locked_settings() -> SiteSettings:
    return SiteSettings.objects.select_for_update().get(pk=1)


def _touched(settings, *, settings_changed=False):
    """Record one more change to the draft, on the locked settings row."""
    settings.draft_version += 1
    fields = ["draft_version", "updated_at"]
    if settings_changed:
        settings.version += 1
        fields.append("version")
    settings.save(update_fields=fields)


def _page(ref) -> Page:
    """The page named by `ref`, a fixed page's key or a custom page's slug, locked."""
    if ref in PageKey.values:
        return Page.objects.select_for_update().get(kind=PageKind.FIXED, key=ref)
    page = (
        Page.objects.select_for_update().filter(kind=PageKind.CUSTOM, slug=ref).first()
        if isinstance(ref, str) and ref
        else None
    )
    if page is None:
        raise SiteRefused("That is not one of the site's pages.")
    return page


def _allowed_on(page):
    """What `sections.ALLOWED_ON` calls this page, and its name for a refusal."""
    if page.kind == PageKind.CUSTOM:
        return sections.CUSTOM, page.title
    return page.key, None


def _check_links(data):
    """Refuse a link to a custom page the draft does not have (`sections.page_links`)."""
    wanted = sections.page_links(data)
    if wanted:
        have = set(Page.objects.filter(kind=PageKind.CUSTOM, slug__in=wanted).values_list("slug", flat=True))
        missing = sorted(wanted - have)
        if missing:
            raise SiteRefused(f"There is no page at /pages/{missing[0]}/ on this site.")


def _section(section_id) -> Section:
    section = (
        Section.objects.select_for_update(of=("self",)).select_related("page").filter(pk=section_id).first()
        if isinstance(section_id, int) and not isinstance(section_id, bool)
        else None
    )
    if section is None:
        raise SiteRefused("That section is not on this site.")
    return section


def _compact(page):
    """Number the page's sections 0, 1, 2 … in their order, after one was taken out."""
    for position, section in enumerate(page.sections.order_by("position", "id")):
        if section.position != position:
            section.position = position
            section.save(update_fields=["position", "updated_at"])


# -- the draft: pages and sections -------------------------------------------


def save_page_as(actor, school, key, *, version, title=_UNCHANGED, description=_UNCHANGED, enabled=_UNCHANGED):
    """Change a page's title, description or whether it is on. Home is always on.

    `key` is a fixed page's key or a custom page's slug. A custom page's title
    is its name in the menu, so it cannot be emptied.
    """
    _require_edit(actor, school)
    with transaction.atomic():
        settings = _locked_settings()
        page = _page(key)
        _check(version, page.version)
        if title is not _UNCHANGED:
            page.title = sections.clean_page_title(title, required=page.kind == PageKind.CUSTOM)
        if description is not _UNCHANGED:
            page.description = sections.clean_page_description(description)
        if enabled is not _UNCHANGED:
            if not isinstance(enabled, bool):
                raise SiteRefused("Whether a page is on is yes or no.")
            if key == PageKey.HOME and not enabled:
                raise SiteRefused("The home page is always on.")
            page.enabled = enabled
        page.version += 1
        page.save()
        _touched(settings)
        return page


def add_section_as(actor, school, key, *, version, kind, data, variant=None) -> Section:
    """Add a section to a page: last, or first for a hero, which a page has at most one of.

    A page holds at most `MOST_SECTIONS`, and Postgres holds that too.
    """
    _require_edit(actor, school)
    if kind not in SectionKind.values:
        sections.clean_kind(kind, PageKey.HOME)
    with transaction.atomic():
        settings = _locked_settings()
        page = _page(key)
        kind = sections.clean_kind(kind, *_allowed_on(page))
        variant = sections.clean_variant(kind, variant)
        data = sections.clean(kind, data)
        _check(version, page.version)
        _check_links(data)
        existing = list(page.sections.order_by("position", "id"))
        if len(existing) >= MOST_SECTIONS:
            raise SiteRefused(f"A page holds at most {MOST_SECTIONS} sections. Take one off first.")
        if kind == SectionKind.HERO:
            if any(s.kind == SectionKind.HERO for s in existing):
                raise SiteRefused("This page has a hero already.")
            for section in reversed(existing):
                section.position += 1
                section.save(update_fields=["position", "updated_at"])
            position = 0
        else:
            position = len(existing)
        section = Section.objects.create(page=page, kind=kind, variant=variant, data=data, position=position)
        page.version += 1
        page.save(update_fields=["version", "updated_at"])
        _touched(settings)
        return section


def save_section_as(actor, school, section_id, *, version, data, variant=None) -> Section:
    """Change a section's data and, if given, its layout variant. Its kind is fixed."""
    _require_edit(actor, school)
    with transaction.atomic():
        settings = _locked_settings()
        section = _section(section_id)
        _check(version, section.version)
        section.data = sections.clean(section.kind, data)
        _check_links(section.data)
        if variant is not None:
            section.variant = sections.clean_variant(section.kind, variant)
        section.version += 1
        section.save()
        _touched(settings)
        return section


def remove_section_as(actor, school, section_id, *, version):
    """Take a section off its page. `version` is the section's."""
    _require_edit(actor, school)
    with transaction.atomic():
        settings = _locked_settings()
        section = _section(section_id)
        _check(version, section.version)
        page = Page.objects.select_for_update().get(pk=section.page_id)
        section.delete()
        _compact(page)
        page.version += 1
        page.save(update_fields=["version", "updated_at"])
        _touched(settings)


def move_sections_as(actor, school, key, order, *, version):
    """Put a page's sections in this order: every one of its sections, once. A hero stays first."""
    _require_edit(actor, school)
    with transaction.atomic():
        settings = _locked_settings()
        page = _page(key)
        _check(version, page.version)
        existing = {s.pk: s for s in page.sections.all()}
        if not isinstance(order, list) or len(order) != len(existing) or set(order) != set(existing):
            raise SiteRefused("Put every section of the page in order, each once.")
        if any(s.kind == SectionKind.HERO for s in existing.values()) and existing[order[0]].kind != SectionKind.HERO:
            raise SiteRefused("The hero stays at the top of its page.")
        for position, pk in enumerate(order):
            section = existing[pk]
            if section.position != position:
                section.position = position
                section.save(update_fields=["position", "updated_at"])
        page.version += 1
        page.save(update_fields=["version", "updated_at"])
        _touched(settings)


# -- the school's own pages and the menu (PR 3b) -----------------------------


def _compact_menu():
    """Number the pages' menu places 0, 1, 2 … in their order, after one was taken out."""
    for position, page in enumerate(Page.objects.select_for_update().order_by("menu_position", "id")):
        if page.menu_position != position:
            page.menu_position = position
            page.save(update_fields=["menu_position", "updated_at"])


def _custom(ref) -> Page:
    page = _page(ref)
    if page.kind != PageKind.CUSTOM:
        raise SiteRefused(f"The {page} page is one of the six every site has: it cannot be renamed or deleted.")
    return page


def create_page_as(actor, school, *, version, title, slug=None) -> Page:
    """Make a page of the school's own, switched off and empty, last in the menu.

    `version` is the settings row's: the list of pages is site-wide. Its address
    is `/pages/<slug>/`, from `slug` if given, else made from the title; a
    made-up address that another page has already gets `-2`, `-3` … A site has
    at most 20 pages, the six fixed ones and `CUSTOM_PAGE_SLOTS` of its own, and
    Postgres holds that by the slot each page takes.
    """
    _require_edit(actor, school)
    title = sections.clean_page_title(title, required=True)
    given = slug is not None
    slug = sections.clean_slug(slug) if given else sections.slug_from_title(title)
    with transaction.atomic():
        settings = _locked_settings()
        _check(version, settings.version)
        taken = set(Page.objects.filter(kind=PageKind.CUSTOM).values_list("slot", flat=True))
        free = [n for n in range(1, CUSTOM_PAGE_SLOTS + 1) if n not in taken]
        if not free:
            raise SiteRefused(
                f"A site has at most {CUSTOM_PAGE_SLOTS + len(PageKey.values)} pages: the six every site has "
                f"and {CUSTOM_PAGE_SLOTS} of its own. Delete one you no longer use first."
            )
        addresses = set(Page.objects.filter(kind=PageKind.CUSTOM).values_list("slug", flat=True))
        if slug in addresses:
            if given:
                raise SiteRefused(f"Another page is at /pages/{slug}/ already. Choose another address.")
            stem, n = slug, 2
            while slug in addresses:
                suffix = f"-{n}"
                slug = f"{stem[:SLUG_LENGTH - len(suffix)].rstrip('-')}{suffix}"
                n += 1
        last = Page.objects.order_by("-menu_position").values_list("menu_position", flat=True).first()
        page = Page.objects.create(
            kind=PageKind.CUSTOM, slug=slug, slot=free[0], title=title, menu_position=last + 1
        )
        _touched(settings, settings_changed=True)
        return page


def rename_page_as(actor, school, ref, *, version, title=_UNCHANGED, slug=_UNCHANGED) -> Page:
    """Change a custom page's title, or its address while it has never been published.

    `version` is the page's. Once a publish has shown the page, its address is
    fixed: people have it, and so have search engines.
    """
    _require_edit(actor, school)
    with transaction.atomic():
        settings = _locked_settings()
        page = _custom(ref)
        _check(version, page.version)
        if title is not _UNCHANGED:
            page.title = sections.clean_page_title(title, required=True)
        if slug is not _UNCHANGED:
            slug = sections.clean_slug(slug)
            if slug != page.slug:
                if page.ever_published:
                    raise SiteRefused(
                        f"/pages/{page.slug}/ has been published, so its address stays: links to it would break."
                    )
                if Page.objects.filter(kind=PageKind.CUSTOM, slug=slug).exclude(pk=page.pk).exists():
                    raise SiteRefused(f"Another page is at /pages/{slug}/ already. Choose another address.")
                page.slug = slug
        page.version += 1
        page.save()
        _touched(settings, settings_changed=slug is not _UNCHANGED)
        return page


def delete_page_as(actor, school, ref, *, version):
    """Delete a custom page and its sections: one never published, or one switched off.

    `version` is the page's. A page that is live is switched off and published
    first, so a deletion never takes a page off the public site by surprise. The
    published site keeps showing what it showed until the next publish.
    """
    _require_edit(actor, school)
    with transaction.atomic():
        settings = _locked_settings()
        page = _custom(ref)
        _check(version, page.version)
        if page.ever_published and page.enabled:
            raise SiteRefused(f"{page} is on the published site. Switch it off first, then delete it.")
        page.delete()
        _compact_menu()
        _touched(settings, settings_changed=True)


def order_menu_as(actor, school, order, *, version):
    """Put every page in this menu order, Home first. `version` is the settings row's.

    `order` names each page once, by key or slug, switched on or not, so a page
    switched on later already has its place.
    """
    _require_edit(actor, school)
    with transaction.atomic():
        settings = _locked_settings()
        _check(version, settings.version)
        pages = {p.ref: p for p in Page.objects.select_for_update()}
        if not isinstance(order, list) or len(order) != len(pages) or set(order) != set(pages):
            raise SiteRefused("Put every page of the site in order, each once.")
        if order[0] != PageKey.HOME:
            raise SiteRefused("Home stays first in the menu.")
        for position, ref in enumerate(order):
            page = pages[ref]
            if page.menu_position != position:
                page.menu_position = position
                page.save(update_fields=["menu_position", "updated_at"])
        _touched(settings, settings_changed=True)


def save_footer_as(actor, school, footer, *, version) -> SiteSettings:
    """Change the site-wide footer. `version` is the settings row's."""
    _require_edit(actor, school)
    footer = sections.clean_footer(footer)
    with transaction.atomic():
        settings = _locked_settings()
        _check(version, settings.version)
        settings.footer = footer
        settings.save(update_fields=["footer", "updated_at"])
        _touched(settings, settings_changed=True)
        return settings


# -- the principal's: theme, delegation, ready, publish, roll back ----------


def set_theme_as(actor, school, key, options=None, *, version) -> SiteSettings:
    """Choose the theme and, if given, its options. The principal's.

    Options are kept per theme, so switching away and back finds them as they
    were (§3.2). Only allow-listed names and values are kept (`themes.clean_options`).
    """
    _require_principal(actor, school, "change the website's theme")
    themes.theme(key)
    cleaned = themes.clean_options(key, options) if options is not None else None
    with transaction.atomic():
        settings = _locked_settings()
        _check(version, settings.version)
        settings.theme = key
        if cleaned is not None:
            settings.theme_options = {**settings.theme_options, key: cleaned}
        settings.save(update_fields=["theme", "theme_options", "updated_at"])
        _touched(settings, settings_changed=True)
        return settings


def set_delegation_as(actor, school, on) -> SiteDelegationEvent:
    """Let the administrator edit drafts, or stop. The principal's. Never lets them publish."""
    _require_principal(actor, school, "change who edits the website")
    if not isinstance(on, bool):
        raise SiteRefused("Letting the administrator edit is yes or no.")
    with transaction.atomic():
        _locked_settings()
        if access.delegated(school) == on:
            raise SiteRefused(
                "The administrator can already edit the website's drafts." if on
                else "The administrator already cannot edit the website."
            )
        return SiteDelegationEvent.objects.create(on=on, by_id=actor.pk, by_name=_name_of(actor))


def mark_ready_as(actor, school, note="") -> SitePublishEvent:
    """Say the draft as it stands is ready for the principal to publish. Anybody who may edit it."""
    _require_edit(actor, school)
    note = sections.clean_note(note)
    with transaction.atomic():
        settings = _locked_settings()
        if settings.is_ready:
            raise SiteRefused("The draft is marked ready already.")
        if _nothing_new(settings, _latest_snapshot(), snapshot()):
            raise SiteRefused("The draft is the same as the published site. There is nothing to publish.")
        settings.ready_version = settings.draft_version
        settings.ready_by_id = actor.pk
        settings.ready_by_name = _name_of(actor)
        settings.ready_at = timezone.now()
        settings.save(update_fields=["ready_version", "ready_by_id", "ready_by_name", "ready_at", "updated_at"])
        return SitePublishEvent.objects.create(
            kind=SitePublishEvent.Kind.MARKED_READY,
            draft_version=settings.draft_version,
            note=note,
            by_id=actor.pk,
            by_name=_name_of(actor),
            by_role=access.role_of(actor, school),
        )


def publish_as(actor, school, note="") -> SiteRevision:
    """Publish the draft as it stands: a new revision, and a line in the log. The principal's."""
    _require_principal(actor, school, "publish the website")
    note = sections.clean_note(note)
    with transaction.atomic():
        settings = _locked_settings()
        latest = SiteRevision.objects.order_by("-number").first()
        current = snapshot()
        if _nothing_new(settings, latest.snapshot if latest else None, current):
            raise SiteRefused("Nothing has changed since the last publish.")
        revision = _revision(actor, current, latest, note=note)
        _shown(revision.snapshot)
        _clear_ready(settings)
        _logged(actor, school, SitePublishEvent.Kind.PUBLISHED, revision, note)
        return revision


def rollback_as(actor, school, number, note="") -> SiteRevision:
    """Publish an earlier revision again, as a new one naming it. The principal's.

    The draft is not touched: what went wrong is fixed there and published in turn.
    """
    _require_principal(actor, school, "roll the website back")
    note = sections.clean_note(note)
    if isinstance(number, bool) or not isinstance(number, int):
        raise SiteRefused("Name the revision to go back to by its number.")
    with transaction.atomic():
        _locked_settings()
        latest = SiteRevision.objects.order_by("-number").first()
        target = SiteRevision.objects.filter(number=number).first()
        if target is None:
            raise SiteRefused(f"There is no revision {number}.")
        if target.pk == latest.pk or target.snapshot == latest.snapshot:
            raise SiteRefused(f"Revision {number} is what the site shows already.")
        revision = _revision(actor, target.snapshot, latest, note=note, rollback_of=target)
        _shown(revision.snapshot)
        _logged(actor, school, SitePublishEvent.Kind.ROLLED_BACK, revision, note)
        return revision


def _shown(snap):
    """Mark every custom page this publish shows switched on: its address is fixed from now."""
    live = [p["slug"] for p in snap["pages"] if p.get("kind") == PageKind.CUSTOM and p["enabled"]]
    Page.objects.filter(kind=PageKind.CUSTOM, slug__in=live, ever_published=False).update(ever_published=True)


def _revision(actor, snap, latest, *, note, rollback_of=None) -> SiteRevision:
    return SiteRevision.objects.create(
        number=(latest.number + 1) if latest else 1,
        snapshot=snap,
        summary=summary(latest.snapshot if latest else None, snap),
        rollback_of=rollback_of,
        note=note,
        published_by_id=actor.pk,
        published_by_name=_name_of(actor),
    )


def _logged(actor, school, kind, revision, note):
    SitePublishEvent.objects.create(
        kind=kind,
        revision=revision,
        note=note,
        by_id=actor.pk,
        by_name=_name_of(actor),
        by_role=access.role_of(actor, school),
    )


def _clear_ready(settings):
    settings.ready_version = None
    settings.ready_by_id = None
    settings.ready_by_name = ""
    settings.ready_at = None
    settings.save(update_fields=["ready_version", "ready_by_id", "ready_by_name", "ready_at", "updated_at"])


# -- reading -----------------------------------------------------------------


def snapshot() -> dict:
    """The whole draft, as a revision keeps it. Read on the connection's schema."""
    settings = SiteSettings.objects.get(pk=1)
    pages = Page.objects.prefetch_related("sections").order_by("menu_position", "id")
    return {
        "theme": settings.theme,
        "options": settings.theme_options.get(settings.theme, {}),
        "footer": settings.footer,
        "pages": [
            {
                "key": page.key,
                "kind": page.kind,
                "slug": page.slug,
                "menu_position": page.menu_position,
                "enabled": page.enabled,
                "title": page.title,
                "description": page.description,
                "sections": [
                    {"id": s.pk, "kind": s.kind, "variant": s.variant, "data": s.data}
                    for s in page.sections.all()
                ],
            }
            for page in pages
        ],
    }


def _nothing_new(settings, live, current) -> bool:
    """Is there nothing to publish? The draft is what is live, or nobody has touched it yet.

    A school's untouched draft is the six empty pages every school starts with,
    and publishing that would put an empty site where today's page stands.
    """
    if live is None:
        return settings.draft_version == 0
    return live == current


def _latest_snapshot():
    return SiteRevision.objects.order_by("-number").values_list("snapshot", flat=True).first()


def page_ref(page) -> str:
    """A snapshot page's name: its key, or its slug if the school made it. Older snapshots have no kind."""
    return page.get("slug") if page.get("kind") == PageKind.CUSTOM else page["key"]


def summary(before, after) -> dict:
    """What changed from one snapshot to the next, in counts a log line can say."""

    def by_id(snap):
        return {s["id"]: s for p in (snap or {}).get("pages", []) for s in p["sections"]}

    def orders(snap):
        return {page_ref(p): [s["id"] for s in p["sections"]] for p in (snap or {}).get("pages", [])}

    def enabled(snap):
        return {page_ref(p) for p in (snap or {}).get("pages", []) if p["enabled"]}

    old, new = by_id(before), by_id(after)
    common = old.keys() & new.keys()
    old_orders, new_orders = orders(before), orders(after)
    reordered = sorted(
        key for key, ids in new_orders.items()
        if [i for i in old_orders.get(key, []) if i in new] != [i for i in ids if i in old]
    )
    return {
        "added": len(new.keys() - old.keys()),
        "removed": len(old.keys() - new.keys()),
        "changed": sum(1 for i in common if old[i] != new[i]),
        "reordered": reordered,
        "pages_on": sorted(enabled(after) - enabled(before)),
        "pages_off": sorted(enabled(before) - enabled(after)),
        "theme_changed": before is None or (before["theme"], before["options"]) != (after["theme"], after["options"]),
        "footer_changed": before is None or before["footer"] != after["footer"],
    }


def draft_as(actor, school) -> dict:
    """The draft, with the versions a save must name, for whoever may edit it."""
    _require_edit(actor, school)
    settings = SiteSettings.objects.get(pk=1)
    pages = Page.objects.prefetch_related("sections").order_by("menu_position", "id")
    return {
        "theme": settings.theme,
        "theme_options": settings.theme_options,
        "footer": settings.footer,
        "version": settings.version,
        "draft_version": settings.draft_version,
        "ready": settings.is_ready,
        "delegated": access.delegated(school),
        "pages": [
            {
                "key": page.key,
                "kind": page.kind,
                "slug": page.slug,
                "path": page.path,
                "menu_position": page.menu_position,
                "address_fixed": page.kind == PageKind.FIXED or page.ever_published,
                "enabled": page.enabled,
                "title": page.title,
                "description": page.description,
                "version": page.version,
                "sections": [
                    {"id": s.pk, "kind": s.kind, "variant": s.variant, "data": s.data, "version": s.version}
                    for s in page.sections.all()
                ],
            }
            for page in pages
        ],
    }


def publish_log_as(actor, school) -> dict:
    """The last `LOG_LENGTH` publish-log lines and delegation changes, newest first."""
    if not access.can_read_log(actor, school):
        raise NotAllowedToReadLog(
            f"{actor} may not read {school}'s website log. That is the principal's and the administrator's."
        )
    events = SitePublishEvent.objects.select_related("revision__rollback_of").order_by("-id")[:LOG_LENGTH]
    delegations = SiteDelegationEvent.objects.order_by("-id")[:LOG_LENGTH]
    return {
        "events": [
            {
                "kind": e.kind,
                "revision": e.revision.number if e.revision else None,
                "rollback_of": e.revision.rollback_of.number if e.revision and e.revision.rollback_of else None,
                "summary": e.revision.summary if e.revision else None,
                "note": e.note,
                "by": e.by_name,
                "by_role": e.by_role,
                "at": e.at,
            }
            for e in events
        ],
        "delegation": [{"on": d.on, "by": d.by_name, "at": d.at} for d in delegations],
    }


def live_revision(school):
    """What the school's public site shows: its latest revision, or None before the first publish.

    No login asks this: it is what the public pages (PR 3) read. Still only on
    the school's own schema, so one school's id cannot read another's site.
    """
    if not access.here(school):
        return None
    return SiteRevision.objects.order_by("-number").first()


__all__ = [
    "LOG_LENGTH",
    "add_section_as",
    "create_page_as",
    "delete_page_as",
    "draft_as",
    "live_revision",
    "mark_ready_as",
    "move_sections_as",
    "order_menu_as",
    "page_ref",
    "publish_as",
    "publish_log_as",
    "remove_section_as",
    "rename_page_as",
    "rollback_as",
    "save_footer_as",
    "save_page_as",
    "save_section_as",
    "set_delegation_as",
    "set_theme_as",
    "snapshot",
    "summary",
]
