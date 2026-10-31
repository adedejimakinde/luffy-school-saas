"""HTTP for the website editor at `/website/`. `docs/school-sites.md` §2.3, §2.4, PR 4.

The editor and nothing else reads these. Tenant-host only, with no school in any
path. **Every route asks who is asking before it looks anything up**: the read
asks `access.can_read_log` (the principal and the administrator), and every
write goes through `schoolsite.services`, which asks first and writes nothing
when the answer is no. One sentence for every refusal of a person, so "you may
not" and "there is no such page" read the same.

Every write answers with the whole overview, so the page redraws from the
school's own answer. A refusal of the person is a 403; a save based on a part
somebody else has changed since is a 409, with the sentence to reload; anything
else the site's rules will not keep is a 422, with the sentence to print under
the form it came from.
"""

from typing import List, Optional

from django.http import Http404
from ninja import Router, Schema

from accounts.session import session_auth
from results import look

from . import access, notify, sections, services
from .errors import NotAllowed, NotAllowedToEdit, SiteRefused, StaleDraft
from .models import PageKey, PageKind, SectionKind, SiteRevision, SiteSettings

router = Router(auth=session_auth)

_MAY_NOT = "The school's website is looked after by its principal, and by the administrator when the principal allows it."

#: Kinds whose section has nothing to draw until their own PR: shown, never offered.
COMING_SOON = {
    SectionKind.NEWS: "Coming soon: news arrives in a later update.",
    SectionKind.GALLERY: "Coming soon: photo albums arrive in a later update.",
}


#: Each kind's name in the editor, as `static/site-editor/states.js` writes it too.
KIND_LABELS = {
    SectionKind.HERO: "Hero",
    SectionKind.CREST_MOTTO: "Crest and motto",
    SectionKind.PRINCIPAL_MESSAGE: "Principal's message",
    SectionKind.FACTS: "Facts",
    SectionKind.NEWS: "News",
    SectionKind.GALLERY: "Gallery",
    SectionKind.ADMISSIONS_CTA: "Admissions panel",
    SectionKind.CONTACT_MAP: "Contact and map",
    SectionKind.TEXT: "Text",
}


class MessageOut(Schema):
    detail: str


class PageIn(Schema):
    version: int
    title: str
    slug: Optional[str] = None


class PageChange(Schema):
    version: int
    title: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    slug: Optional[str] = None


class MenuIn(Schema):
    version: int
    order: List[str]


class SectionIn(Schema):
    version: int
    kind: str
    data: dict
    variant: Optional[str] = None


class SectionChange(Schema):
    version: int
    data: dict
    variant: Optional[str] = None


class OrderIn(Schema):
    version: int
    order: List[int]


class FooterIn(Schema):
    version: int
    footer: dict


class ColourIn(Schema):
    version: int
    colour: str = ""


class DelegationIn(Schema):
    on: bool


class NoteIn(Schema):
    note: str = ""


class PublishIn(Schema):
    draft_version: int
    note: str = ""


class RollbackIn(Schema):
    number: int
    note: str = ""


def _school_of(request):
    school = getattr(request, "school", None)
    if school is None:
        raise Http404("No website on this host.")
    return school


def _kinds(page_key, page_name):
    """What 'Add a section' offers on this page: every kind that may sit here, and the ones still to come."""
    offered = []
    for kind in SectionKind:
        try:
            sections.clean_kind(kind, page_key, page_name)
        except SiteRefused:
            continue
        offered.append({
            "kind": kind.value,
            "label": KIND_LABELS[kind],
            "available": kind not in COMING_SOON,
            "hint": COMING_SOON.get(kind, ""),
        })
    return offered


def _page_out(page):
    custom = page["kind"] == PageKind.CUSTOM
    label = page["title"] if custom else PageKey(page["key"]).label
    page_key = sections.CUSTOM if custom else page["key"]
    return {
        **page,
        "ref": page["slug"] if custom else page["key"],
        "label": label,
        "preview": f"/website/preview{page['path']}" if page["path"] != "/" else "/website/preview/",
        "kinds": _kinds(page_key, label if custom else None),
    }


def _overview(request, school):
    user = request.user
    may_edit = access.can_edit(user, school)
    principal = access.can_publish(user, school)
    settings = SiteSettings.objects.get(pk=1)
    live = SiteRevision.objects.order_by("-number").first()
    draft = services.snapshot()
    body = {
        "role": access.role_of(user, school),
        "can_edit": may_edit,
        "can_publish": principal,
        "delegated": access.delegated(school),
        "school": school.name,
        "state": {
            "published": live is not None,
            "revision": live.number if live else None,
            "published_at": live.published_at.isoformat() if live else None,
            "published_by": live.published_by_name if live else "",
            "changes": services.has_changes(settings, live.snapshot if live else None, draft),
            "ready": settings.is_ready,
            "ready_by": settings.ready_by_name,
            "ready_at": settings.ready_at.isoformat() if settings.ready_at else None,
            "draft_version": settings.draft_version,
        },
        "version": settings.version,
        "colour": settings.theme_options.get(settings.theme, {}).get("colours", {}).get("primary", ""),
        "card_colour": look.for_site(school.name)["colour"],
        "footer": settings.footer,
        "networks": sorted(sections.SOCIAL_HOSTS),
        "preview": notify.PREVIEW_PATH,
        "pages": [],
        "log": [
            {**e, "at": e["at"].isoformat()} for e in services.publish_log_as(user, school)["events"]
        ],
    }
    if may_edit:
        body["pages"] = [_page_out(p) for p in services.draft_as(user, school)["pages"]]
    return body


def _doing(act):
    """Run a write, and say what the site's rules said: `None`, or `(status, body)`."""
    try:
        act()
    except NotAllowed:
        return 403, MessageOut(detail=_MAY_NOT)
    except StaleDraft as exc:
        return 409, MessageOut(detail=str(exc))
    except SiteRefused as exc:
        return 422, MessageOut(detail=str(exc))
    return None


_READ = {200: dict, 403: MessageOut}
_WRITE = {200: dict, 403: MessageOut, 409: MessageOut, 422: MessageOut}


def _write(request, act, extra=None):
    school = _school_of(request)
    failed = _doing(lambda: act(school))
    if failed:
        return failed
    body = _overview(request, school)
    if extra:
        body.update(extra(school))
    return 200, body


@router.get("/", response=_READ)
def overview(request):
    school = _school_of(request)
    if not access.can_read_log(request.user, school):
        return 403, MessageOut(detail=_MAY_NOT)
    return 200, _overview(request, school)


@router.post("/pages/", response=_WRITE)
def add_page(request, payload: PageIn):
    def act(school):
        services.create_page_as(request.user, school, version=payload.version, title=payload.title,
                                slug=payload.slug or None)
    return _write(request, act)


@router.put("/pages/{ref}/", response=_WRITE)
def change_page(request, ref: str, payload: PageChange):
    def act(school):
        if payload.slug is not None:
            kwargs = {"slug": payload.slug}
            if payload.title is not None:
                kwargs["title"] = payload.title
            services.rename_page_as(request.user, school, ref, version=payload.version, **kwargs)
            return
        kwargs = {k: v for k, v in (("title", payload.title), ("description", payload.description),
                                    ("enabled", payload.enabled)) if v is not None}
        services.save_page_as(request.user, school, ref, version=payload.version, **kwargs)
    return _write(request, act)


@router.delete("/pages/{ref}/", response=_WRITE)
def remove_page(request, ref: str, version: int):
    return _write(request, lambda school: services.delete_page_as(request.user, school, ref, version=version))


@router.put("/menu/", response=_WRITE)
def order_menu(request, payload: MenuIn):
    return _write(
        request, lambda school: services.order_menu_as(request.user, school, payload.order, version=payload.version)
    )


@router.post("/pages/{ref}/sections/", response=_WRITE)
def add_section(request, ref: str, payload: SectionIn):
    def act(school):
        # Asked of the person first, as every write does, so a refusal says nothing about the page.
        if not access.can_edit(request.user, school):
            raise NotAllowedToEdit(_MAY_NOT)
        if payload.kind in COMING_SOON:
            raise SiteRefused(COMING_SOON[payload.kind])
        services.add_section_as(request.user, school, ref, version=payload.version, kind=payload.kind,
                                data=payload.data, variant=payload.variant)
    return _write(request, act)


@router.put("/pages/{ref}/sections/", response=_WRITE)
def order_sections(request, ref: str, payload: OrderIn):
    return _write(
        request,
        lambda school: services.move_sections_as(request.user, school, ref, payload.order, version=payload.version),
    )


@router.put("/sections/{int:section_id}/", response=_WRITE)
def change_section(request, section_id: int, payload: SectionChange):
    return _write(
        request,
        lambda school: services.save_section_as(request.user, school, section_id, version=payload.version,
                                                data=payload.data, variant=payload.variant),
    )


@router.delete("/sections/{int:section_id}/", response=_WRITE)
def remove_section(request, section_id: int, version: int):
    return _write(
        request, lambda school: services.remove_section_as(request.user, school, section_id, version=version)
    )


@router.put("/footer/", response=_WRITE)
def change_footer(request, payload: FooterIn):
    return _write(
        request, lambda school: services.save_footer_as(request.user, school, payload.footer, version=payload.version)
    )


@router.put("/colour/", response=_WRITE)
def change_colour(request, payload: ColourIn):
    return _write(
        request, lambda school: services.set_colour_as(request.user, school, payload.colour, version=payload.version)
    )


@router.put("/delegation/", response=_WRITE)
def change_delegation(request, payload: DelegationIn):
    return _write(request, lambda school: services.set_delegation_as(request.user, school, payload.on))


@router.post("/ready/", response=_WRITE)
def mark_ready(request, payload: NoteIn):
    def told(school):
        # Who the email goes to, so the editor can say so, or say that nobody has an address.
        return {"told": len(notify.principal_addresses(school))}
    return _write(request, lambda school: services.mark_ready_as(request.user, school, payload.note), told)


@router.post("/publish/", response=_WRITE)
def publish(request, payload: PublishIn):
    return _write(
        request,
        lambda school: services.publish_as(request.user, school, payload.note, draft_version=payload.draft_version),
    )


@router.post("/rollback/", response=_WRITE)
def rollback(request, payload: RollbackIn):
    return _write(request, lambda school: services.rollback_as(request.user, school, payload.number, payload.note))


__all__ = ["COMING_SOON", "router"]
