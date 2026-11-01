"""Pictures and albums on a school's website: upload, describe, arrange, publish, delete, take down.

`docs/school-sites.md` §2.3, §9, PR 5. The bytes are the upload service's
(`files.service`): every picture is checked, decoded, stripped of metadata and
drawn again in sizes for phones there, against the school's storage quota.
What is here is what the website adds, and who may do what with it:

| | upload, describe, arrange, delete a draft picture | publish or take off an album | take a photo out of a published album | take down now |
| --- | --- | --- | --- | --- |
| Principal | yes | yes | yes | yes |
| Administrator, delegated | yes | no | no | no |
| Anybody else | no | no | no | no |

**Public only once published.** A picture's file is private on the upload
service until the live site (the latest revision) or a published album shows
it, and private again once nothing published does (`sync_public`). Before that
it is sent only to the school's editors, in the preview (`schoolsite.editor`).

**Deleting** (decided 1 November 2026) is for a picture neither the live site,
the draft nor a published album uses: the principal, or a delegated
administrator, deletes it and its file. Older revisions may still name it; going
back to one shows that section without the picture.

**Taking down** is the principal's way to remove a picture *now*, wherever it
is: out of the draft, out of every album, draft and published, and off the live
site by publishing the live revision again without it (never the draft, whose
other changes the principal may not have looked at). The file and every size of
it are deleted from the server's disk, and the school's page cache moves to new
keys, so no cached page shows it. The log says who, when and why. Copies stay in
the encrypted nightly backups until those age out (§9.1).

Every function asks `access` first and writes nothing when the answer is no, and
works only on the connection's own schema, like `schoolsite.services`.
"""

import re

from django.db import transaction
from django.utils import timezone

from files import service as files
from files.kinds import Kind
from files.models import State

from . import access, sections
from .errors import NotAllowedToEdit, NotAllowedToPublish, SiteRefused, StaleDraft
from .models import (
    CONSENT_VERSION,
    CONSENT_WORDING,
    MOST_ALBUMS,
    MOST_PHOTOS,
    Album,
    Page,
    PictureUse,
    Section,
    SectionKind,
    SitePicture,
    SitePublishEvent,
    SiteRevision,
    SiteSettings,
)

#: How many uploads one editor may have being processed at once (§9.1).
UPLOADS_AT_ONCE = 5

_UNCHANGED = object()

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _name_of(user) -> str:
    return user.full_name or user.get_username()


def _require_edit(actor, school):
    if not access.can_edit(actor, school):
        raise NotAllowedToEdit(
            f"{actor} may not change {school}'s website pictures. That is the principal's, or the "
            "administrator's when the principal allows it."
        )


def _require_principal(actor, school, what):
    if not access.can_publish(actor, school):
        raise NotAllowedToPublish(f"{actor} may not {what} at {school}. That is the principal's alone.")


def _check(version, current):
    if version != current:
        raise StaleDraft("Somebody else changed this since you opened it. Reload to see their change.")


def _locked_settings() -> SiteSettings:
    return SiteSettings.objects.select_for_update().get(pk=1)


def _is_id(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _picture(picture_id) -> SitePicture:
    picture = SitePicture.objects.select_for_update().filter(pk=picture_id).first() if _is_id(picture_id) else None
    if picture is None:
        raise SiteRefused("That picture is not on this site.")
    return picture


def _album(album_id) -> Album:
    album = Album.objects.select_for_update().filter(pk=album_id).first() if _is_id(album_id) else None
    if album is None:
        raise SiteRefused("That album is not on this site.")
    return album


# -- what refers to what ---------------------------------------------------------


def refs_in(kind, data) -> list:
    """The picture ids a section's data names."""
    data = data or {}
    if kind == SectionKind.HERO:
        found = [data.get("image"), data.get("video")]
    elif kind == SectionKind.PRINCIPAL_MESSAGE:
        found = [data.get("portrait")]
    elif kind == SectionKind.GALLERY:
        found = list(data.get("photos") or [])
    else:
        found = []
    return [i for i in found if _is_id(i)]


def refs_in_snapshot(snap) -> set:
    """Every picture id a snapshot's sections name."""
    return {i for page in (snap or {}).get("pages", []) for s in page["sections"] for i in refs_in(s["kind"], s["data"])}


def albums_in(kind, data) -> list:
    data = data or {}
    return [data["album"]] if kind == SectionKind.GALLERY and _is_id(data.get("album")) else []


def _live_snapshot():
    return SiteRevision.objects.order_by("-number").values_list("snapshot", flat=True).first()


def where_used(ids=None) -> dict:
    """For each picture (or those in `ids`), where it is used: a dict of lists.

    `draft`: "Hero on Home" and the like; `live`: whether the live site shows it;
    `albums_live`: titles of published albums that show it; `album`: the title of
    the album whose draft holds it.
    """
    pictures = SitePicture.objects.select_related("album")
    if ids is not None:
        pictures = pictures.filter(pk__in=list(ids))
    found = {p.pk: {"draft": [], "live": False, "albums_live": [], "album": p.album.title if p.album_id and not p.removed else ""}
             for p in pictures}
    if not found:
        return found
    for section in Section.objects.select_related("page").filter(
        kind__in=[SectionKind.HERO, SectionKind.PRINCIPAL_MESSAGE, SectionKind.GALLERY]
    ):
        for pid in refs_in(section.kind, section.data):
            if pid in found:
                found[pid]["draft"].append(f"{SectionKind(section.kind).label} on {section.page}")
    live = _live_snapshot()
    for pid in refs_in_snapshot(live):
        if pid in found:
            found[pid]["live"] = True
    for album in Album.objects.filter(published__isnull=False):
        for photo in album.published.get("photos", []):
            if photo["id"] in found:
                found[photo["id"]]["albums_live"].append(album.title)
    return found


# -- what a revision and the editor say about a picture --------------------------


def _numbers(variants, prefix, ext):
    out = []
    for name in variants:
        if name.startswith(prefix) and name.endswith(ext):
            middle = name[len(prefix):-len(ext)]
            if middle.isdigit():
                out.append(int(middle))
    return sorted(out)


def info(picture, stored) -> dict:
    """A picture as a revision or a published album keeps it: enough to draw it with no query.

    `widths` have AVIF and WebP sizes, `jpegs` the JPEG fallbacks; `w` and `h`
    are the largest size's, so the page reserves the right shape before it loads.
    """
    ready = stored is not None and stored.state == State.READY
    variants = (stored.variants or {}) if ready else {}
    prefix = "poster-" if picture.video else ""
    widths = _numbers(variants, prefix, ".avif")
    jpegs = _numbers(variants, prefix, ".jpg")
    largest = variants.get(f"{prefix}{widths[-1]}.avif", {}) if widths else {}
    colour = (stored.colour or "") if ready else ""
    return {
        "id": picture.pk,
        "key": picture.file_key,
        "use": picture.use,
        "video": picture.video,
        "alt": picture.alt,
        "caption": picture.caption,
        "focal": [round(picture.focal_x, 3), round(picture.focal_y, 3)],
        "colour": colour if _HEX.match(colour) else "",
        "w": largest.get("width"),
        "h": largest.get("height"),
        "widths": widths,
        "jpegs": jpegs,
        "loop": ready and "loop.mp4" in variants,
        "ready": ready and bool(widths),
    }


def pictures_for(ids) -> dict:
    """`{str(id): info}` for the pictures with these ids that exist. Two queries."""
    ids = sorted({i for i in ids if _is_id(i)})
    if not ids:
        return {}
    pictures = list(SitePicture.objects.filter(pk__in=ids))
    stored = files.find_many([p.file_key for p in pictures])
    return {str(p.pk): info(p, stored.get(p.file_key)) for p in pictures}


def snapshot_pictures(snap) -> dict:
    """The `pictures` a snapshot of the draft carries: every picture its sections name."""
    return pictures_for(refs_in_snapshot(snap))


def check_publishable(snap):
    """Refuse a publish while a picture the draft shows is missing, unfinished or undescribed (§9.1)."""
    pictures = snap.get("pictures", {})
    for page in snap.get("pages", []):
        if not page["enabled"]:
            continue
        for s in page["sections"]:
            where = f"the {SectionKind(s['kind']).label.lower()} on the {page.get('title') or page['key'] or page['slug']} page"
            for pid in refs_in(s["kind"], s["data"]):
                entry = pictures.get(str(pid))
                if entry is None:
                    raise SiteRefused(f"A picture in {where} has been deleted. Choose another, then publish.")
                if not entry["ready"]:
                    raise SiteRefused(
                        f"A picture in {where} is still being processed, or could not be used. "
                        "Wait a moment, or choose another, then publish."
                    )
                if not entry["alt"]:
                    raise SiteRefused(
                        f"A picture in {where} has no description for people who cannot see it. Add one, then publish."
                    )


def _url(key, variant) -> str:
    return f"/website/pictures/{key}/{variant}"


def status(picture, stored, used=None) -> dict:
    """A picture as the editor shows it: what it is, where it is used, and what may be done with it."""
    if stored is None:
        state, problem = "missing", "This picture's file has gone. Remove it and upload it again."
    elif stored.state == State.PENDING:
        files.nudge(stored)
        state, problem = "processing", ""
    elif stored.state == State.FAILED:
        state, problem = "failed", stored.error
    else:
        state, problem = "ready", ""
    entry = info(picture, stored)
    thumb = preview = ""
    if entry["ready"]:
        prefix = "poster-" if picture.video else ""
        thumb = _url(picture.file_key, f"{prefix}{entry['widths'][0]}.webp")
        # The size the focal-point picker draws: the phone width, or the largest below it.
        middle = max([w for w in entry["widths"] if w <= 828] or entry["widths"][:1])
        preview = _url(picture.file_key, f"{prefix}{middle}.webp")
    used = used or {"draft": [], "live": False, "albums_live": [], "album": ""}
    return {
        "id": picture.pk,
        "use": picture.use,
        "video": picture.video,
        "album": picture.album_id,
        "removed": picture.removed,
        "alt": picture.alt,
        "caption": picture.caption,
        "focal": {"x": picture.focal_x, "y": picture.focal_y},
        "version": picture.version,
        "state": state,
        "problem": problem,
        "thumb": thumb,
        "preview": preview,
        "w": entry["w"],
        "h": entry["h"],
        "uploaded_by": picture.uploaded_by_name,
        "uploaded_at": picture.created_at.isoformat(),
        "used": used,
        "on_public_site": bool(used["live"] or used["albums_live"]),
    }


def statuses(pictures) -> list:
    pictures = list(pictures)
    stored = files.find_many([p.file_key for p in pictures])
    used = where_used([p.pk for p in pictures])
    return [status(p, stored.get(p.file_key), used.get(p.pk)) for p in pictures]


# -- uploading -------------------------------------------------------------------


def _kind_for(use, video):
    if use == PictureUse.HERO:
        return Kind.HERO_VIDEO if video else Kind.HERO_IMAGE
    if video:
        raise SiteRefused("Only the hero can be a video.")
    return Kind.SITE_PORTRAIT if use == PictureUse.PORTRAIT else Kind.GALLERY_IMAGE


def upload_as(actor, school, use, uploads, *, consent, alt="", album_id=None, video=False) -> list:
    """Take one to five uploads for the website. Answers at once with the new pictures, being processed.

    `consent` is the uploader's tick against `CONSENT_WORDING`; nothing is kept
    without it. A hero's photo or video and a portrait take one file and need
    their description (`alt`) now; gallery photos go into `album_id`, up to five
    at a time, and are described before their album is published.
    """
    _require_edit(actor, school)
    if use not in PictureUse.values:
        raise SiteRefused("That is not somewhere a picture can go.")
    if consent is not True:
        raise SiteRefused(f"Tick the box to confirm: {CONSENT_WORDING}")
    uploads = [u for u in (uploads or []) if u is not None]
    if not uploads:
        raise SiteRefused("Choose a photo to upload.")
    single = use != PictureUse.GALLERY
    if single and len(uploads) != 1:
        raise SiteRefused("Choose one file.")
    if len(uploads) > UPLOADS_AT_ONCE:
        raise SiteRefused(f"Upload at most {UPLOADS_AT_ONCE} photos at a time.")
    kind = _kind_for(use, bool(video))
    alt = sections.clean_alt(alt, required=single)
    busy = files.pending_by(actor.pk)
    if busy + len(uploads) > UPLOADS_AT_ONCE:
        raise SiteRefused(
            f"You have {busy} uploads still being processed. Wait for them to finish, then send more."
        )
    for upload in uploads:
        try:
            files.check(kind, upload)
        except files.UploadRefused as exc:
            raise SiteRefused(str(exc))
    made = []
    with transaction.atomic():
        album = None
        if use == PictureUse.GALLERY:
            album = _album(album_id)
            held = album.photos.filter(removed=False).count()
            if held + len(uploads) > MOST_PHOTOS:
                raise SiteRefused(f"An album holds at most {MOST_PHOTOS} photos. Start another album for the rest.")
            next_position = (album.photos.order_by("-position").values_list("position", flat=True).first() or 0) + 1
        elif album_id is not None:
            raise SiteRefused("Only gallery photos go in an album.")
        for upload in uploads:
            try:
                stored = files.accept(kind, upload, by=actor, public=False)
            except files.UploadRefused as exc:
                raise SiteRefused(str(exc))
            picture = SitePicture.objects.create(
                file_key=stored.key,
                use=use,
                video=bool(video),
                album=album,
                position=next_position if album else 0,
                alt=alt,
                consent=True,
                consent_version=CONSENT_VERSION,
                uploaded_by_id=actor.pk,
                uploaded_by_name=_name_of(actor),
            )
            made.append(picture)
            if album:
                next_position += 1
        if album:
            album.version += 1
            album.save(update_fields=["version", "updated_at"])
    return made


# -- describing ------------------------------------------------------------------


def save_picture_as(actor, school, picture_id, *, version, alt=_UNCHANGED, caption=_UNCHANGED,
                    focal=_UNCHANGED) -> SitePicture:
    """Change a picture's description, caption or focal point. The live site changes only on the next publish."""
    _require_edit(actor, school)
    with transaction.atomic():
        settings = _locked_settings()
        picture = _picture(picture_id)
        _check(version, picture.version)
        if alt is not _UNCHANGED:
            picture.alt = sections.clean_alt(alt, required=picture.use != PictureUse.GALLERY)
        if caption is not _UNCHANGED:
            picture.caption = sections.clean_caption(caption)
        if focal is not _UNCHANGED:
            picture.focal_x, picture.focal_y = sections.clean_focal(focal)
        picture.version += 1
        picture.save()
        if where_used([picture.pk])[picture.pk]["draft"]:
            # The draft now draws differently: "ready" and a confirmed publish must see it.
            settings.draft_version += 1
            settings.save(update_fields=["draft_version", "updated_at"])
        return picture


# -- checking a section's pictures and album -------------------------------------


def check_media(kind, data):
    """Refuse a section naming a picture or album the draft does not have, or the wrong sort of picture."""
    ids = refs_in(kind, data)
    if ids:
        found = {p.pk: p for p in SitePicture.objects.filter(pk__in=ids)}
        for pid in ids:
            picture = found.get(pid)
            if picture is None:
                raise SiteRefused("That picture is not on this site. Upload it again.")
            if kind == SectionKind.HERO:
                wanted_video = pid == data.get("video")
                if picture.use != PictureUse.HERO or picture.video != wanted_video:
                    raise SiteRefused("That is not a hero " + ("video." if wanted_video else "picture."))
            elif kind == SectionKind.PRINCIPAL_MESSAGE and picture.use != PictureUse.PORTRAIT:
                raise SiteRefused("That is not a portrait.")
            elif kind == SectionKind.GALLERY and picture.use != PictureUse.GALLERY:
                raise SiteRefused("That is not a gallery photo.")
    for album_id in albums_in(kind, data):
        if not Album.objects.filter(pk=album_id).exists():
            raise SiteRefused("That album is not on this site.")


# -- albums ----------------------------------------------------------------------


def create_album_as(actor, school, *, title, slug=None) -> Album:
    """A new album, empty and not on the website. Its address is `/gallery/<slug>/`."""
    _require_edit(actor, school)
    title = sections.clean_album_title(title)
    given = slug not in (None, "")
    slug = sections.clean_album_slug(slug) if given else sections.album_slug_from_title(title)
    with transaction.atomic():
        _locked_settings()
        if Album.objects.count() >= MOST_ALBUMS:
            raise SiteRefused(f"A site keeps at most {MOST_ALBUMS} albums. Delete one you no longer use first.")
        taken = set(Album.objects.values_list("slug", flat=True))
        if slug in taken:
            if given:
                raise SiteRefused(f"Another album is at /gallery/{slug}/ already. Choose another address.")
            stem, n = slug, 2
            while slug in taken:
                suffix = f"-{n}"
                slug = f"{stem[:40 - len(suffix)].rstrip('-')}{suffix}"
                n += 1
        return Album.objects.create(title=title, slug=slug)


def save_album_as(actor, school, album_id, *, version, title=_UNCHANGED, description=_UNCHANGED,
                  slug=_UNCHANGED) -> Album:
    """Change an album's title, description, or its address while it has never been published."""
    _require_edit(actor, school)
    with transaction.atomic():
        _locked_settings()
        album = _album(album_id)
        _check(version, album.version)
        if title is not _UNCHANGED:
            album.title = sections.clean_album_title(title)
        if description is not _UNCHANGED:
            album.description = sections.clean_album_description(description)
        if slug is not _UNCHANGED:
            slug = sections.clean_album_slug(slug)
            if slug != album.slug:
                if album.ever_published:
                    raise SiteRefused(
                        f"/gallery/{album.slug}/ has been published, so its address stays: links to it would break."
                    )
                if Album.objects.filter(slug=slug).exclude(pk=album.pk).exists():
                    raise SiteRefused(f"Another album is at /gallery/{slug}/ already. Choose another address.")
                album.slug = slug
        album.version += 1
        album.save()
        return album


def order_photos_as(actor, school, album_id, order, *, version) -> Album:
    """Put an album's photos in this order: each photo of its draft, once."""
    _require_edit(actor, school)
    with transaction.atomic():
        _locked_settings()
        album = _album(album_id)
        _check(version, album.version)
        photos = {p.pk: p for p in album.photos.select_for_update().filter(removed=False)}
        if not isinstance(order, list) or len(order) != len(photos) or set(order) != set(photos):
            raise SiteRefused("Put every photo of the album in order, each once.")
        for position, pid in enumerate(order, start=1):
            photo = photos[pid]
            if photo.position != position:
                photo.position = position
                photo.save(update_fields=["position"])
        album.version += 1
        album.save(update_fields=["version", "updated_at"])
        return album


def album_draft(album) -> dict:
    """The album as it would be published now: what the preview draws and a publish writes."""
    photos = list(album.photos.filter(removed=False).order_by("position", "id"))
    stored = files.find_many([p.file_key for p in photos])
    return {
        "title": album.title,
        "description": album.description,
        "slug": album.slug,
        "photos": [info(p, stored.get(p.file_key)) for p in photos],
    }


def album_has_changes(album) -> bool:
    if album.published is None:
        return False
    return album_draft(album) != album.published


def _event(actor, school, kind, *, subject, subject_id, note="", revision=None):
    return SitePublishEvent.objects.create(
        kind=kind,
        revision=revision,
        note=note,
        subject=subject[:255],
        subject_id=subject_id,
        by_id=actor.pk,
        by_name=_name_of(actor),
        by_role=access.role_of(actor, school),
    )


def _gallery_changed(settings):
    settings.gallery_version += 1
    settings.save(update_fields=["gallery_version", "updated_at"])


def publish_album_as(actor, school, album_id, *, version, note="") -> Album:
    """Put an album on the website as its draft stands, or publish its changes. The principal's.

    Every photo must be processed and described. Photos the principal took out of
    the published album are deleted now, unless something else still shows them.
    """
    _require_principal(actor, school, "publish an album")
    note = sections.clean_note(note)
    with transaction.atomic():
        settings = _locked_settings()
        album = _album(album_id)
        _check(version, album.version)
        draft = album_draft(album)
        if not draft["photos"]:
            raise SiteRefused("Add at least one photo before publishing the album.")
        for n, photo in enumerate(draft["photos"], start=1):
            if not photo["ready"]:
                raise SiteRefused(
                    f"Photo {n} is still being processed, or could not be used. Wait a moment, or remove it."
                )
            if not photo["alt"]:
                raise SiteRefused(f"Photo {n} has no description for people who cannot see it. Add one, then publish.")
        if draft == album.published:
            raise SiteRefused("Nothing has changed in this album since it was published.")
        now = timezone.now()
        album.published = draft
        album.published_at = now
        album.first_published_at = album.first_published_at or now
        album.ever_published = True
        album.published_by_id = actor.pk
        album.published_by_name = _name_of(actor)
        album.version += 1
        album.save()
        _forget_removed(album)
        _gallery_changed(settings)
        _event(actor, school, SitePublishEvent.Kind.ALBUM_PUBLISHED, subject=album.title, subject_id=album.pk, note=note)
        sync_public()
        return album


def unpublish_album_as(actor, school, album_id, *, version, note="") -> Album:
    """Take an album off the website. Its draft stays, to publish again. The principal's."""
    _require_principal(actor, school, "take an album off the website")
    note = sections.clean_note(note)
    with transaction.atomic():
        settings = _locked_settings()
        album = _album(album_id)
        _check(version, album.version)
        if album.published is None:
            raise SiteRefused("That album is not on the website.")
        album.published = None
        album.version += 1
        album.save()
        _forget_removed(album)
        _gallery_changed(settings)
        _event(actor, school, SitePublishEvent.Kind.ALBUM_UNPUBLISHED, subject=album.title, subject_id=album.pk,
               note=note)
        sync_public()
        return album


def _forget_removed(album):
    """Delete the photos taken out of this album's draft, now its published copy no longer shows them."""
    removed = list(album.photos.select_for_update().filter(removed=True))
    if not removed:
        return
    used = where_used([p.pk for p in removed])
    for photo in removed:
        u = used[photo.pk]
        if u["draft"] or u["live"] or u["albums_live"]:
            photo.album, photo.removed = None, False
            photo.save(update_fields=["album", "removed"])
        else:
            _delete(photo)


def delete_album_as(actor, school, album_id, *, version):
    """Delete an album that is not on the website, and its photos that nothing else shows."""
    _require_edit(actor, school)
    with transaction.atomic():
        _locked_settings()
        album = _album(album_id)
        _check(version, album.version)
        if album.published is not None:
            raise SiteRefused("This album is on the website. The principal takes it off first, then it can be deleted.")
        for section in Section.objects.select_related("page").filter(kind=SectionKind.GALLERY):
            if album.pk in albums_in(section.kind, section.data):
                raise SiteRefused(
                    f"The gallery on the {section.page} page shows this album. Change or remove that section first."
                )
        photos = list(album.photos.select_for_update())
        used = where_used([p.pk for p in photos])
        for photo in photos:
            u = used[photo.pk]
            if u["draft"] or u["live"] or u["albums_live"]:
                photo.album, photo.removed = None, False
                photo.save(update_fields=["album", "removed"])
            else:
                _delete(photo)
        album.delete()


def _compact(album):
    for position, photo in enumerate(album.photos.filter(removed=False).order_by("position", "id"), start=1):
        if photo.position != position:
            photo.position = position
            photo.save(update_fields=["position"])


def remove_photo_as(actor, school, album_id, picture_id, *, version):
    """Take a photo out of an album's draft.

    A photo the published album shows is the principal's to take out (decided 1
    November 2026); it stays on the website until the album is published again.
    Any other photo is deleted, as `delete_picture_as` would.
    """
    _require_edit(actor, school)
    with transaction.atomic():
        _locked_settings()
        album = _album(album_id)
        _check(version, album.version)
        photo = _picture(picture_id)
        if photo.album_id != album.pk or photo.removed:
            raise SiteRefused("That photo is not in this album.")
        shown = album.published and any(p["id"] == photo.pk for p in album.published.get("photos", []))
        if shown:
            _require_principal(actor, school, "take a photo out of a published album")
            photo.removed = True
            photo.save(update_fields=["removed"])
        else:
            _refuse_if_used(actor, school, photo)
            _delete(photo)
        _compact(album)
        album.version += 1
        album.save(update_fields=["version", "updated_at"])


# -- deleting --------------------------------------------------------------------


def _refuse_if_used(actor, school, picture):
    used = where_used([picture.pk])[picture.pk]
    if used["live"] or used["albums_live"]:
        if access.can_publish(actor, school):
            raise SiteRefused(
                "This picture is on the live website. Use Take down now to remove it from the website at once."
            )
        raise SiteRefused("This picture is on the live website. Only the principal can take it down.")
    if used["draft"]:
        raise SiteRefused(f"The draft uses this picture: {used['draft'][0]}. Take it out there first, then delete it.")


def _delete(picture):
    """The picture's row and its file, every size of it, gone. On the locked transaction."""
    stored = files.find(picture.file_key)
    album_id = picture.album_id
    picture.delete()
    if stored is not None:
        files.discard(stored)
    return album_id


def delete_picture_as(actor, school, picture_id, *, version):
    """Delete a picture that neither the live site, the draft nor a published album uses."""
    _require_edit(actor, school)
    with transaction.atomic():
        _locked_settings()
        picture = _picture(picture_id)
        _check(version, picture.version)
        _refuse_if_used(actor, school, picture)
        album_id = _delete(picture)
        if album_id:
            album = Album.objects.select_for_update().get(pk=album_id)
            _compact(album)
            album.version += 1
            album.save(update_fields=["version", "updated_at"])


# -- taking down -----------------------------------------------------------------


def _strip_data(kind, data, pid):
    """A section's data without picture `pid`, or None if the section should go altogether."""
    data = dict(data)
    if kind == SectionKind.HERO:
        for field in ("image", "video"):
            if data.get(field) == pid:
                data[field] = None
    elif kind == SectionKind.PRINCIPAL_MESSAGE:
        if data.get("portrait") == pid:
            data["portrait"] = None
    elif kind == SectionKind.GALLERY and "photos" in data:
        data["photos"] = [p for p in data["photos"] if p != pid]
        if not data["photos"]:
            return None
    return data


def strip_snapshot(snap, pid) -> dict:
    """A snapshot that shows everything it did except picture `pid`."""
    pages = []
    for page in snap.get("pages", []):
        kept = []
        for s in page["sections"]:
            if pid in refs_in(s["kind"], s["data"]):
                data = _strip_data(s["kind"], s["data"], pid)
                if data is None:
                    continue
                s = {**s, "data": data}
            kept.append(s)
        pages.append({**page, "sections": kept})
    pictures = {k: v for k, v in (snap.get("pictures") or {}).items() if k != str(pid)}
    return {**snap, "pages": pages, "pictures": pictures}


def take_down_as(actor, school, picture_id, *, reason) -> SitePublishEvent:
    """Remove a picture from the draft, every album and the live site at once, and delete it. The principal's.

    The live site is published again from its own revision without the picture,
    so nothing else the draft holds goes live with it. Logged with the reason.
    """
    from . import services

    _require_principal(actor, school, "take a picture down")
    reason = sections.clean_note(reason)
    if not reason:
        raise SiteRefused("Say why it is being taken down, for the history: for example, consent withdrawn.")
    with transaction.atomic():
        settings = _locked_settings()
        picture = _picture(picture_id)
        pid = picture.pk
        subject = picture.alt or picture.get_use_display()

        # The draft.
        touched_pages = set()
        for section in Section.objects.select_for_update(of=("self",)).filter(
            kind__in=[SectionKind.HERO, SectionKind.PRINCIPAL_MESSAGE, SectionKind.GALLERY]
        ):
            if pid not in refs_in(section.kind, section.data):
                continue
            data = _strip_data(section.kind, section.data, pid)
            touched_pages.add(section.page_id)
            if data is None:
                section.delete()
            else:
                section.data = data
                section.version += 1
                section.save(update_fields=["data", "version", "updated_at"])
        for page in Page.objects.select_for_update().filter(pk__in=touched_pages):
            for position, s in enumerate(page.sections.order_by("position", "id")):
                if s.position != position:
                    s.position = position
                    s.save(update_fields=["position", "updated_at"])
            page.version += 1
            page.save(update_fields=["version", "updated_at"])
        if touched_pages:
            settings.draft_version += 1
            settings.save(update_fields=["draft_version", "updated_at"])

        # Every album: its draft, and what the public sees.
        if picture.album_id:
            album = Album.objects.select_for_update().get(pk=picture.album_id)
            album.version += 1
            album.save(update_fields=["version", "updated_at"])
        for album in Album.objects.select_for_update().filter(published__isnull=False):
            photos = album.published.get("photos", [])
            if any(p["id"] == pid for p in photos):
                kept = [p for p in photos if p["id"] != pid]
                album.published = {**album.published, "photos": kept} if kept else None
                album.version += 1
                album.save(update_fields=["published", "version", "updated_at"])

        # The live site, published again from its own revision.
        revision = None
        latest = SiteRevision.objects.order_by("-number").first()
        if latest is not None and pid in refs_in_snapshot(latest.snapshot):
            revision = services._revision(
                actor, strip_snapshot(latest.snapshot, pid), latest, note=f"Taken down: {reason}"[:200]
            )

        event = _event(actor, school, SitePublishEvent.Kind.TAKEN_DOWN, subject=subject, subject_id=pid,
                       note=reason, revision=revision)
        album_id = _delete(picture)
        if album_id:
            _compact(Album.objects.get(pk=album_id))
        # Every cached page of this school moves to a new key, whatever it showed.
        _gallery_changed(settings)
        sync_public()
        return event


# -- public or not ---------------------------------------------------------------


def published_keys() -> set:
    """The file keys the public may be sent: the live site's pictures and the published albums' photos."""
    keys = set()
    live = _live_snapshot()
    if live:
        named = refs_in_snapshot(live)
        keys |= {v["key"] for k, v in (live.get("pictures") or {}).items() if int(k) in named}
    for published in Album.objects.filter(published__isnull=False).values_list("published", flat=True):
        keys |= {p["key"] for p in published.get("photos", [])}
    return keys


def sync_public():
    """Make the website's files public exactly while something published shows them."""
    mine = set(SitePicture.objects.values_list("file_key", flat=True))
    live = published_keys() & mine
    files.set_public(live, True)
    files.set_public(mine - live, False)


__all__ = [
    "UPLOADS_AT_ONCE",
    "album_draft",
    "album_has_changes",
    "check_media",
    "check_publishable",
    "create_album_as",
    "delete_album_as",
    "delete_picture_as",
    "info",
    "order_photos_as",
    "pictures_for",
    "publish_album_as",
    "published_keys",
    "refs_in",
    "refs_in_snapshot",
    "remove_photo_as",
    "save_album_as",
    "save_picture_as",
    "snapshot_pictures",
    "status",
    "statuses",
    "strip_snapshot",
    "sync_public",
    "take_down_as",
    "unpublish_album_as",
    "upload_as",
    "where_used",
]
