"""A school's own website: the draft its editors change, and what it published.

`docs/school-sites.md` §2 is the design; this is PR 2 of it, the content and the
record, with no page yet. Every table lives in the school's own schema. People
are named by their platform-wide login id, a bare integer with no foreign key, as
everywhere else (`docs/tenancy.md`), and by their names as they read at the time
(operating rule 2), so the record survives a rename.

- **The draft** is `SiteSettings` (one row: theme, theme options, footer), the
  `Page` rows (the six fixed pages and up to 14 of the school's own, PR 3b) and
  their `Section` rows. Editors change it; nobody outside sees it.
- **What is published** is `SiteRevision`: a snapshot of the whole draft written
  at publish time, never changed afterwards. The public site (PR 3) reads the
  latest one and nothing else, the way a family's card is the released row and
  not the marks behind it (operating rule 1).
- **The record** is the revisions themselves plus `SitePublishEvent` (marked
  ready, published, rolled back) and `SiteDelegationEvent` (the principal lets
  the administrator edit drafts, or stops). The delegation log is also the
  state: the latest row decides, and nothing else records it (rule 4).

The three record tables refuse UPDATE and DELETE twice: here, so a developer
reads why, and in Postgres by a trigger each (`migrations/0001`), so a shell, a
bulk `.update()` or an import cannot rewrite them either (rule 3).
"""

from django.db import models
from django.db.models import Deferrable, Q

#: A school's own pages, beside the six fixed ones: 20 pages in all
#: (`docs/school-sites.md` §2.1.1). Each takes a numbered slot, so Postgres
#: refuses a fifteenth however it is written.
CUSTOM_PAGE_SLOTS = 14
#: The most sections a page holds (§2.2), held by Postgres as positions 0 to 14.
MOST_SECTIONS = 15
#: A custom page's address is `/pages/<slug>/`: lowercase letters, digits and
#: single hyphens between them, at most 40 characters.
SLUG_LENGTH = 40
SLUG_PATTERN = r"^[a-z0-9]+(-[a-z0-9]+)*$"


class RecordIsFixed(Exception):
    """A revision or a log row was asked to change. They never do."""


class AppendOnly(models.Model):
    """Saved once and never again; never deleted. The trigger is the real rule."""

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk is not None and not self._state.adding:
            raise RecordIsFixed(f"{self._meta.verbose_name} {self.pk} is a record and does not change.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise RecordIsFixed(f"{self._meta.verbose_name} {self.pk} is a record and is never deleted.")


class PageKey(models.TextChoices):
    """The fixed pages (`docs/school-sites.md` §2.1). A school cannot invent one."""

    HOME = "home", "Home"
    ABOUT = "about", "About"
    ADMISSIONS = "admissions", "Admissions"
    NEWS = "news", "News"
    GALLERY = "gallery", "Gallery"
    CONTACT = "contact", "Contact"


class PageKind(models.TextChoices):
    """A fixed page, at its fixed address, or one the school made, under `/pages/`."""

    FIXED = "fixed", "Fixed"
    CUSTOM = "custom", "The school's own"


class SectionKind(models.TextChoices):
    """The fixed sections (§2.2). The footer is site-wide and lives on `SiteSettings`."""

    HERO = "hero", "Hero"
    CREST_MOTTO = "crest_motto", "Crest and motto"
    PRINCIPAL_MESSAGE = "principal_message", "Principal's message"
    FACTS = "facts", "Facts"
    NEWS = "news", "News"
    GALLERY = "gallery", "Gallery"
    ADMISSIONS_CTA = "admissions_cta", "Admissions call to action"
    CONTACT_MAP = "contact_map", "Contact and map"
    TEXT = "text", "Text"


class SiteSettings(models.Model):
    """The draft's site-wide part, and the counters that say where the draft stands.

    Pinned to 1, like `results.ReportCardSettings`, and seeded by the migration
    for every school. Every draft write locks this row first, so two editors'
    writes and a publish happen one after another, never interleaved.
    """

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    #: A key from `schoolsite.themes.THEMES`, checked on every write.
    theme = models.CharField(max_length=32, default="starter")
    #: Per theme key, that theme's options as `schoolsite.themes.clean_options`
    #: left them: allow-listed names and values only, never markup. Kept per
    #: key so switching back to a theme brings its choices back (§3.2).
    theme_options = models.JSONField(default=dict)
    #: The site-wide footer's data, as `schoolsite.sections.clean_footer` left it.
    footer = models.JSONField(default=dict)
    #: Bumped by every write to the theme, its options or the footer: the
    #: version a stale save of those is refused against.
    version = models.PositiveIntegerField(default=0)
    #: Bumped by every write to any part of the draft. "Ready for the
    #: principal" is a draft version, so an edit after it is not ready again
    #: until somebody marks it.
    draft_version = models.PositiveIntegerField(default=0)
    ready_version = models.PositiveIntegerField(null=True, blank=True)
    ready_by_id = models.PositiveBigIntegerField(null=True, blank=True)
    ready_by_name = models.CharField(max_length=255, blank=True, default="")
    ready_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "site settings"
        verbose_name_plural = "site settings"
        constraints = [
            models.CheckConstraint(condition=Q(id=1), name="a_school_has_one_site_settings_row"),
            models.CheckConstraint(
                condition=(
                    Q(ready_version__isnull=True, ready_by_id__isnull=True, ready_at__isnull=True)
                    | Q(ready_version__isnull=False, ready_by_id__isnull=False, ready_at__isnull=False)
                ),
                name="a_ready_mark_is_recorded_whole",
            ),
        ]

    @property
    def is_ready(self) -> bool:
        return self.ready_version is not None and self.ready_version == self.draft_version


class Page(models.Model):
    """One page of the draft: one of the six fixed pages, or one the school made.

    The fixed six are seeded by the migration and are never made or deleted. A
    school's own page (§2.1.1) has a title, an address under `/pages/` that is
    fixed once it has been published, and a numbered slot; it holds sections of
    the kinds `sections.ALLOWED_ON` lets onto a custom page. Every page has a
    place in the menu, Home first.
    """

    kind = models.CharField(max_length=8, choices=PageKind, default=PageKind.FIXED)
    #: A fixed page's key; empty on a page the school made.
    key = models.CharField(max_length=16, choices=PageKey, blank=True, default="")
    #: A custom page's address, `/pages/<slug>/`; empty on a fixed page.
    slug = models.CharField(max_length=SLUG_LENGTH, blank=True, default="")
    #: A custom page's slot, 1 to `CUSTOM_PAGE_SLOTS`; empty on a fixed page.
    slot = models.PositiveSmallIntegerField(null=True, blank=True)
    #: Its place in the menu, from 0. Home is 0.
    menu_position = models.PositiveSmallIntegerField()
    enabled = models.BooleanField(default=False)
    title = models.CharField(max_length=70, blank=True, default="")
    description = models.CharField(max_length=160, blank=True, default="")
    #: Set by the first publish that showed this page switched on. From then on
    #: its address does not change: people and search engines have it.
    ever_published = models.BooleanField(default=False)
    #: Bumped by every write to this page or to the list of its sections.
    version = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["menu_position", "id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(kind=PageKind.FIXED, key__in=PageKey.values, slug="", slot__isnull=True)
                    | (
                        # `slot__isnull=False` too: a check whose comparison meets a NULL passes.
                        Q(kind=PageKind.CUSTOM, key="", slot__isnull=False, slot__gte=1,
                          slot__lte=CUSTOM_PAGE_SLOTS, slug__regex=SLUG_PATTERN)
                        & ~Q(slug__in=PageKey.values)
                    )
                ),
                name="a_page_is_fixed_or_the_schools_own",
            ),
            models.UniqueConstraint(
                fields=["key"], condition=Q(kind=PageKind.FIXED), name="a_fixed_page_appears_once"
            ),
            models.UniqueConstraint(
                fields=["slug"], condition=Q(kind=PageKind.CUSTOM), name="a_custom_page_has_its_own_address"
            ),
            models.UniqueConstraint(fields=["slot"], name="a_custom_page_takes_its_own_slot"),
            # Deferred, so a reorder can pass through two pages sharing a place
            # on its way to the order it ends in.
            models.UniqueConstraint(
                fields=["menu_position"], name="a_menu_place_holds_one_page", deferrable=Deferrable.DEFERRED
            ),
            models.CheckConstraint(
                condition=~Q(key=PageKey.HOME) | Q(enabled=True), name="the_home_page_is_always_on"
            ),
            models.CheckConstraint(
                condition=~Q(key=PageKey.HOME) | Q(menu_position=0), name="the_home_page_comes_first_in_the_menu"
            ),
        ]

    def __str__(self):
        return self.title if self.kind == PageKind.CUSTOM else self.get_key_display()

    @property
    def ref(self) -> str:
        """How the services name it: a fixed page's key, or a custom page's slug."""
        return self.slug if self.kind == PageKind.CUSTOM else self.key

    @property
    def path(self) -> str:
        return f"/pages/{self.slug}/" if self.kind == PageKind.CUSTOM else ("/" if self.key == PageKey.HOME else f"/{self.key}/")


class Section(models.Model):
    """One section of a page, in the draft: a fixed kind and its checked data."""

    page = models.ForeignKey(Page, related_name="sections", on_delete=models.CASCADE)
    kind = models.CharField(max_length=24, choices=SectionKind)
    variant = models.CharField(max_length=16)
    #: As `schoolsite.sections.clean()` left it: known fields, plain text, no markup.
    data = models.JSONField(default=dict)
    position = models.PositiveSmallIntegerField()
    #: Bumped by every write to this section: the version a stale save is refused against.
    version = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["page_id", "position", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(kind__in=SectionKind.values), name="a_section_is_one_of_the_fixed_kinds"
            ),
            models.UniqueConstraint(
                fields=["page"], condition=Q(kind=SectionKind.HERO), name="a_page_has_at_most_one_hero"
            ),
            models.CheckConstraint(
                condition=~Q(kind=SectionKind.HERO) | Q(position=0), name="a_hero_comes_first"
            ),
            # Deferred, so adding a hero can move every section down one place.
            models.UniqueConstraint(
                fields=["page", "position"], name="a_place_on_a_page_holds_one_section",
                deferrable=Deferrable.DEFERRED,
            ),
            models.CheckConstraint(
                condition=Q(position__lt=MOST_SECTIONS), name="a_page_holds_at_most_fifteen_sections"
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} on {self.page}"


class SiteRevision(AppendOnly):
    """What a school published: the whole draft as it stood, and who, and when.

    `number` counts this school's publishes from 1. A rollback is a new
    revision carrying an older one's snapshot and naming it in `rollback_of`.
    """

    number = models.PositiveIntegerField(unique=True)
    snapshot = models.JSONField()
    #: What changed against the revision before: counts of sections added,
    #: removed and changed, pages turned on or off, and whether the theme moved.
    summary = models.JSONField(default=dict)
    rollback_of = models.ForeignKey(
        "self", null=True, blank=True, related_name="+", on_delete=models.PROTECT
    )
    note = models.CharField(max_length=200, blank=True, default="")
    published_by_id = models.PositiveBigIntegerField()
    published_by_name = models.CharField(max_length=255)
    published_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-number"]
        verbose_name = "site revision"
        constraints = [
            models.CheckConstraint(condition=Q(number__gte=1), name="a_revision_is_numbered_from_one"),
            models.CheckConstraint(
                condition=Q(rollback_of__isnull=True) | ~Q(rollback_of=models.F("id")),
                name="a_rollback_names_an_earlier_revision",
            ),
        ]

    def __str__(self):
        return f"Revision {self.number}"


class SitePublishEvent(AppendOnly):
    """One line of the publish log the principal reads: who, what, when."""

    class Kind(models.TextChoices):
        MARKED_READY = "marked_ready", "Marked ready for the principal"
        PUBLISHED = "published", "Published"
        ROLLED_BACK = "rolled_back", "Rolled back"

    kind = models.CharField(max_length=16, choices=Kind)
    revision = models.ForeignKey(
        SiteRevision, null=True, blank=True, related_name="+", on_delete=models.PROTECT
    )
    #: The draft version a "ready" mark was made on.
    draft_version = models.PositiveIntegerField(null=True, blank=True)
    note = models.CharField(max_length=200, blank=True, default="")
    by_id = models.PositiveBigIntegerField()
    by_name = models.CharField(max_length=255)
    #: Their role here as it read at the time.
    by_role = models.CharField(max_length=16)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at", "-id"]
        verbose_name = "site publish event"
        constraints = [
            models.CheckConstraint(
                condition=Q(kind__in=["marked_ready", "published", "rolled_back"]),
                name="a_publish_event_is_one_of_the_known_kinds",
            ),
            models.CheckConstraint(
                condition=(
                    Q(kind="marked_ready", revision__isnull=True, draft_version__isnull=False)
                    | Q(kind__in=["published", "rolled_back"], revision__isnull=False, draft_version__isnull=True)
                ),
                name="a_publish_event_names_what_it_is_about",
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} by {self.by_name}"


class SiteDelegationEvent(AppendOnly):
    """The principal lets the administrator edit drafts, or stops. The latest row decides."""

    on = models.BooleanField()
    by_id = models.PositiveBigIntegerField()
    by_name = models.CharField(max_length=255)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at", "-id"]
        verbose_name = "site delegation event"

    def __str__(self):
        return f"Delegation {'on' if self.on else 'off'} by {self.by_name}"


__all__ = [
    "CUSTOM_PAGE_SLOTS",
    "MOST_SECTIONS",
    "Page",
    "PageKey",
    "PageKind",
    "RecordIsFixed",
    "Section",
    "SectionKind",
    "SiteDelegationEvent",
    "SitePublishEvent",
    "SiteRevision",
    "SiteSettings",
    "SLUG_LENGTH",
    "SLUG_PATTERN",
]
