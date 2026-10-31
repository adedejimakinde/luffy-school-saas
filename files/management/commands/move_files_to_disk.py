"""`manage.py move_files_to_disk`: the files already in Postgres, onto the disk.

Before the upload service, three things were kept as bytes in a column: each
school's crest (`ReportCardSettings.crest`), each child's passport photo
(`StudentDetails.photo`) and the blog's pictures (`BlogImage.data`/`small`).
This copies each through the same processing a new upload gets (redrawn,
compressed, no metadata) into the service's storage.

    move_files_to_disk                     # dry run: what would move, nothing written
    move_files_to_disk --apply             # move it
    move_files_to_disk --rollback          # dry run of the rollback
    move_files_to_disk --rollback --apply  # roll back

**A dry run is the default**, and it processes every file in memory, so it
reports what each would become and any that would be refused, before anything
is written.

**The columns are left as they are.** The readers prefer the new file and fall
back to the column, so a school is never without its crest at any point, and a
later release drops the columns once a backup cycle has run with the files on
disk. Running this twice moves nothing twice: a slot that already has a file is
skipped.

**The rollback** makes the previous release show exactly what this one shows,
then removes the files: it copies every current crest, photo and blog picture
(including ones uploaded since the deploy) back into its column, and only then
removes those files and their rows. After `--rollback --apply` the previous
commit can be deployed with nothing lost. Other kinds of file (signatures,
website pictures, documents) have no column to go back to and are left alone;
no screen uploads them yet.
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.test.utils import override_settings
from django_tenants.utils import schema_context

from files import images, service
from files.kinds import Kind, profile_for
from schools.models import School


def _mb(n):
    return f"{n / 1024 ** 2:,.2f} MB"


class Tally:
    def __init__(self):
        self.count = self.before = self.after = self.refused = 0

    def add(self, before, after=0, refused=False):
        self.count += 1
        self.before += before
        self.after += after
        self.refused += int(refused)


class Command(BaseCommand):
    help = "Move crests, photos and blog pictures from Postgres onto the disk. A dry run unless --apply."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Write. Without it, nothing is changed.")
        parser.add_argument("--rollback", action="store_true", help="Copy the files back into Postgres, then remove them.")
        parser.add_argument("--school", help="One school, by its subdomain.")

    # -- what there is -------------------------------------------------------

    def _legacy(self, schema):
        """`(kind, slot, bytes, label, on_done)` for each column value not yet on disk."""
        if schema == "public":
            from blog.models import BlogImage

            for image in BlogImage.objects.filter(file__isnull=True).exclude(data=None).select_related("post"):
                kind = Kind.BLOG_COVER if image.is_cover else Kind.BLOG_IMAGE

                def done(stored, image=image):
                    type(image).objects.filter(pk=image.pk).update(file=stored)

                yield kind, "", bytes(image.data), f"blog picture {image.key}", done
            return

        from academics.models import StudentDetails
        from results.models import ReportCardSettings

        row = ReportCardSettings.objects.filter(pk=1).exclude(crest=None).first()
        if row is not None and service.current("crest") is None:
            yield Kind.CREST, "crest", bytes(row.crest), "crest", None
        for details in StudentDetails.objects.exclude(photo=None).only("student_membership_id", "photo"):
            slot = f"student_photo:{details.student_membership_id}"
            if service.current(slot) is None:
                yield Kind.STUDENT_PHOTO, slot, bytes(details.photo), f"photo of child {details.student_membership_id}", None

    def _move(self, schema, apply, tallies):
        for kind, slot, raw, label, done in self._legacy(schema):
            profile = profile_for(kind)
            tally = tallies.setdefault(str(kind), Tally())
            if not apply:
                try:
                    made = (images.PROCESSORS[profile.family])(raw, profile)
                    tally.add(len(raw), sum(v["bytes"] for v in made["variants"].values()))
                except images.Refused as exc:
                    tally.add(len(raw), refused=True)
                    self.stdout.write(f"  {schema}: {label} would be REFUSED: {exc}")
                continue
            with transaction.atomic():
                stored = service.accept(kind, raw, slot=slot, origin="migrated",
                                        public=False if schema == "public" else None)
                if stored.state != "ready":
                    tally.add(len(raw), refused=True)
                    self.stdout.write(f"  {schema}: {label} was REFUSED and left in Postgres: {stored.error}")
                    continue
                if done is not None:
                    done(stored)
                tally.add(len(raw), stored.bytes)

    # -- the rollback --------------------------------------------------------

    def _roll_back(self, schema, apply, tallies):
        from files.models import StoredFile

        if schema == "public":
            from blog.models import BlogImage

            for image in BlogImage.objects.filter(file__isnull=False).select_related("file"):
                tally = tallies.setdefault("blog", Tally())
                tally.add(image.file.bytes)
                if apply:
                    with transaction.atomic():
                        data = service.read(image.file, "full.webp") if image.file.is_ready else image.data
                        small = service.read(image.file, "small.webp") if image.file.is_ready else image.small
                        stored = image.file
                        BlogImage.objects.filter(pk=image.pk).update(data=data, small=small, file=None)
                        service.discard(stored)
            return

        from academics.models import StudentDetails
        from results.models import ReportCardSettings

        here = StoredFile.objects.filter(schema_name=schema)
        for stored in here.filter(kind=Kind.CREST, slot="crest"):
            tallies.setdefault("crest", Tally()).add(stored.bytes)
            if apply:
                with transaction.atomic():
                    if stored.is_ready:
                        row, _ = ReportCardSettings.objects.get_or_create(pk=1)
                        row.crest = service.read(stored, "card.png")
                        row.save(update_fields=["crest", "updated_at"])
                    service.discard(stored)
        for stored in here.filter(kind=Kind.STUDENT_PHOTO, slot__startswith="student_photo:"):
            tallies.setdefault("student_photo", Tally()).add(stored.bytes)
            if apply:
                with transaction.atomic():
                    if stored.is_ready:
                        membership_id = int(stored.slot.split(":", 1)[1])
                        row, _ = StudentDetails.objects.get_or_create(student_membership_id=membership_id)
                        row.photo = service.read(stored, "card.jpg")
                        row.save(update_fields=["photo", "updated_at"])
                    service.discard(stored)

    # -- the run -------------------------------------------------------------

    def handle(self, *args, **options):
        apply, rollback = options["apply"], options["rollback"]
        schools = School.objects.exclude(schema_name="public").order_by("name")
        if options["school"]:
            schools = schools.filter(slug=options["school"])
        schemas = [s.schema_name for s in schools]
        if not options["school"]:
            schemas = ["public", *schemas]

        what = "ROLLBACK" if rollback else "MOVE"
        mode = "APPLYING" if apply else "DRY RUN, nothing will be written"
        self.stdout.write(f"move_files_to_disk: {what}, {mode}. Files go to {settings.FILES_ROOT}.")

        totals = {}
        with override_settings(FILES_PROCESS_INLINE=True):
            for schema in schemas:
                tallies = {}
                with schema_context(schema):
                    (self._roll_back if rollback else self._move)(schema, apply, tallies)
                for kind, tally in tallies.items():
                    total = totals.setdefault(kind, Tally())
                    total.count += tally.count
                    total.before += tally.before
                    total.after += tally.after
                    total.refused += tally.refused
                    if rollback:
                        self.stdout.write(f"  {schema}: {tally.count} {kind} file(s), {_mb(tally.before)} on disk"
                                          f"{' copied back to Postgres and removed' if apply else ' would be copied back and removed'}")
                    else:
                        self.stdout.write(f"  {schema}: {tally.count} {kind}, {_mb(tally.before)} in Postgres -> "
                                          f"{_mb(tally.after)} on disk{f', {tally.refused} refused' if tally.refused else ''}")

        if not totals:
            self.stdout.write("Nothing to do." if not rollback else "Nothing to roll back.")
        for kind, tally in totals.items():
            if rollback:
                self.stdout.write(f"TOTAL {kind}: {tally.count} file(s)")
            else:
                self.stdout.write(f"TOTAL {kind}: {tally.count}, {_mb(tally.before)} -> {_mb(tally.after)}"
                                  f"{f', {tally.refused} refused' if tally.refused else ''}")
        if not apply:
            self.stdout.write("Dry run: nothing was written. Run again with --apply to do it.")
        elif not rollback:
            self.stdout.write("Done. The old columns still hold their bytes; a later release removes them.")
        else:
            self.stdout.write("Rolled back. The previous release can now be deployed and shows the same files.")
