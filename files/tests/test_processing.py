"""What is kept from an upload: no metadata, the right formats and sizes, and
nothing it should not be (`files.images`, `files.pdf`, `files.video`).

These are pure: bytes in, bytes out, no database. The two-school tests of who
is sent what are in `test_isolation.py`.
"""

import io

from django.test import SimpleTestCase
from PIL import Image

from files import images, pdf, service, video
from files.kinds import Kind, VIDEO_MAX_OUTPUT_BYTES, profile_for

from . import samples


def opened(data):
    return Image.open(io.BytesIO(data))


def no_metadata(test, data, where):
    picture = opened(data)
    test.assertEqual(dict(picture.getexif()), {}, f"{where} carries EXIF")
    test.assertNotIn("icc_profile", picture.info, f"{where} carries a colour profile")
    for secret in (b"SecretPhone", b"PhoneMaker", b"GPS"):
        test.assertNotIn(secret, data, f"{where} carries {secret!r}")


class GpsIsNeverKeptTests(SimpleTestCase):
    def test_the_sample_does_carry_gps_so_the_tests_below_mean_something(self):
        raw = samples.photo()
        self.assertIn(0x8825, opened(raw).getexif())
        self.assertIn(b"SecretPhone", raw)

    def test_every_output_of_every_photo_kind_has_no_exif_gps_or_profile(self):
        for kind in (Kind.STUDENT_PHOTO, Kind.STAFF_PHOTO, Kind.HERO_IMAGE, Kind.GALLERY_IMAGE):
            made = images.PROCESSORS[profile_for(kind).family](samples.photo(), profile_for(kind))
            for name, data in made["data"].items():
                with self.subTest(kind=kind, variant=name):
                    no_metadata(self, data, name)

    def test_a_webp_or_png_upload_with_exif_loses_it_too(self):
        for fmt in ("WEBP", "PNG"):
            made = images.site_photo(samples.photo((1600, 1000), fmt=fmt), profile_for(Kind.GALLERY_IMAGE))
            for name, data in made["data"].items():
                with self.subTest(fmt=fmt, variant=name):
                    no_metadata(self, data, name)

    def test_marks_and_the_blog_keep_none_either(self):
        jpeg_logo = samples.photo((800, 600))
        for kind in (Kind.CREST, Kind.SIGNATURE, Kind.STAMP, Kind.LOGO, Kind.BLOG_IMAGE, Kind.BLOG_COVER):
            profile = profile_for(kind)
            made = images.PROCESSORS[profile.family](jpeg_logo, profile)
            for name, data in made["data"].items():
                with self.subTest(kind=kind, variant=name):
                    no_metadata(self, data, name)


class PhotoSizesTests(SimpleTestCase):
    def test_a_website_photo_keeps_a_2400_master_and_three_widths_in_avif_webp_and_jpeg(self):
        made = images.site_photo(samples.photo((4000, 3000)), profile_for(Kind.HERO_IMAGE))
        variants = made["variants"]

        self.assertEqual((variants["master.jpg"]["width"], variants["master.jpg"]["height"]), (2400, 1800))
        for width in (480, 828, 1920):
            self.assertEqual(opened(made["data"][f"{width}.avif"]).format, "AVIF")
            self.assertEqual(opened(made["data"][f"{width}.webp"]).format, "WEBP")
            self.assertEqual(variants[f"{width}.webp"]["width"], width)
        self.assertEqual(sorted(n for n in variants if n.endswith(".jpg")), ["1920.jpg", "828.jpg", "master.jpg"])
        self.assertRegex(made["colour"], r"^#[0-9A-F]{6}$")

    def test_avif_is_smaller_than_webp_which_is_smaller_than_jpeg(self):
        made = images.site_photo(samples.photo((3000, 2000)), profile_for(Kind.GALLERY_IMAGE))
        sizes = made["variants"]
        self.assertLess(sizes["828.avif"]["bytes"], sizes["828.webp"]["bytes"])
        self.assertLess(sizes["828.webp"]["bytes"], sizes["828.jpg"]["bytes"])

    def test_nothing_is_ever_made_larger_than_it_was_sent(self):
        made = images.site_photo(samples.photo((600, 400)), profile_for(Kind.GALLERY_IMAGE))
        widths = {v["width"] for v in made["variants"].values()}
        self.assertEqual(widths, {480, 600})

    def test_a_portrait_keeps_a_1200_master_and_passport_frames(self):
        made = images.portrait(samples.photo((3000, 4000)), profile_for(Kind.STUDENT_PHOTO))
        variants = made["variants"]
        self.assertEqual(max(variants["master.jpg"]["width"], variants["master.jpg"]["height"]), 1200)
        self.assertEqual(opened(made["data"]["card.jpg"]).size, (280, 360))
        self.assertEqual(opened(made["data"]["card.webp"]).size, (280, 360))
        self.assertEqual(opened(made["data"]["small.webp"]).size, (140, 180))

    def test_a_phone_photo_is_turned_the_right_way_up(self):
        out = io.BytesIO()
        exif = Image.Exif()
        exif[0x0112] = 6  # rotated 90 degrees
        Image.new("RGB", (1600, 800), (10, 20, 30)).save(out, format="JPEG", exif=exif)
        made = images.site_photo(out.getvalue(), profile_for(Kind.GALLERY_IMAGE))
        master = made["variants"]["master.jpg"]
        self.assertEqual((master["width"], master["height"]), (800, 1600))

    def test_an_iphones_heic_is_read(self):
        import pillow_heif

        pillow_heif.register_heif_opener()
        out = io.BytesIO()
        Image.new("RGB", (1200, 900), (90, 140, 200)).save(out, format="HEIF")
        made = images.portrait(out.getvalue(), profile_for(Kind.STUDENT_PHOTO))
        self.assertEqual(opened(made["data"]["card.jpg"]).format, "JPEG")


class MarksAreTrimmedLosslessPngTests(SimpleTestCase):
    def test_a_border_is_trimmed_and_every_output_is_png(self):
        made = images.mark(samples.logo((600, 400), border=60), profile_for(Kind.CREST))
        master = opened(made["data"]["master.png"])
        self.assertEqual(master.format, "PNG")
        self.assertEqual(master.size, (481, 281))
        for name in ("card.png", "site.png"):
            self.assertEqual(opened(made["data"][name]).format, "PNG")

    def test_a_jpeg_scan_on_white_is_trimmed_too(self):
        made = images.mark(samples.logo((900, 300), fmt="JPEG", border=100), profile_for(Kind.SIGNATURE))
        width, height = opened(made["data"]["master.png"]).size
        self.assertLess(width, 900)
        self.assertLess(height, 300)
        self.assertEqual(opened(made["data"]["card.png"]).size, (600, 200))

    def test_the_master_is_lossless_and_a_coloured_edge_is_not_trimmed(self):
        raw = samples.logo((300, 300), border=0)
        made = images.mark(raw, profile_for(Kind.STAMP))
        kept = opened(made["data"]["master.png"]).convert("RGBA")
        sent = opened(raw).convert("RGBA")
        self.assertEqual(kept.size, sent.size)
        # Compared as bytes: a failing list comparison of 90,000 pixels would
        # take unittest minutes to describe.
        self.assertTrue(kept.tobytes() == sent.tobytes(), "the master is not pixel for pixel the upload")


class RefusedByTheirOwnBytesTests(SimpleTestCase):
    """The name and the browser's MIME type are never asked."""

    def check(self, kind, raw):
        return service.check(kind, raw)

    def test_svg_is_refused_everywhere_and_says_so(self):
        for kind in (Kind.CREST, Kind.LOGO, Kind.STUDENT_PHOTO, Kind.GALLERY_IMAGE):
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(service.UploadRefused, "SVG files are not accepted"):
                    self.check(kind, samples.svg())

    def test_a_gif_is_refused_and_pointed_at_video(self):
        with self.assertRaisesRegex(service.UploadRefused, "short video"):
            self.check(Kind.GALLERY_IMAGE, samples.gif())

    def test_a_pdf_renamed_as_a_photo_is_refused(self):
        with self.assertRaisesRegex(service.UploadRefused, "not a picture this can read"):
            self.check(Kind.STUDENT_PHOTO, samples.pdf())

    def test_a_photo_renamed_as_a_pdf_or_a_video_is_refused(self):
        with self.assertRaisesRegex(service.UploadRefused, "A document is a PDF file"):
            self.check(Kind.DOCUMENT, samples.photo((100, 100)))
        with self.assertRaisesRegex(service.UploadRefused, "MP4, MOV or WebM"):
            self.check(Kind.HERO_VIDEO, samples.photo((100, 100)))

    def test_a_decompression_bomb_is_refused_from_its_header(self):
        raw = samples.bomb()
        self.assertLess(len(raw), 2 * 1024 * 1024)
        with self.assertRaisesRegex(service.UploadRefused, "far larger"):
            self.check(Kind.GALLERY_IMAGE, raw)

    def test_an_oversize_file_is_refused_before_it_is_read(self):
        for kind, mb in ((Kind.STUDENT_PHOTO, 15), (Kind.CREST, 5), (Kind.DOCUMENT, 20), (Kind.HERO_VIDEO, 50)):
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(service.UploadRefused, f"at most {mb} MB"):
                    self.check(kind, b"\xff\xd8" + b"0" * (mb * 1024 * 1024))

    def test_an_empty_file_is_a_sentence(self):
        with self.assertRaisesRegex(service.UploadRefused, "Choose a file"):
            self.check(Kind.CREST, b"")


class DocumentTests(SimpleTestCase):
    def test_a_pdf_loses_its_script_and_its_author_and_keeps_its_pages(self):
        import pikepdf

        raw = samples.pdf(pages=3, javascript=True)
        self.assertIn(b"JavaScript", raw)
        made = pdf.optimise(raw, profile_for(Kind.DOCUMENT))
        data = made["data"]["document.pdf"]

        with pikepdf.open(io.BytesIO(data)) as kept:
            self.assertEqual(len(kept.pages), 3)
            self.assertNotIn("/OpenAction", kept.Root)
            self.assertNotIn("/Author", kept.docinfo)
        self.assertNotIn(b"Mrs Secret Author", data)
        self.assertEqual(made["pages"], 3)

    def test_a_dense_scan_is_brought_down_to_200_dpi_and_gets_smaller(self):
        import pikepdf

        raw = samples.pdf(pages=1, scanned=True)
        made = pdf.optimise(raw, profile_for(Kind.DOCUMENT))
        data = made["data"]["document.pdf"]
        self.assertLess(len(data), len(raw))
        with pikepdf.open(io.BytesIO(data)) as kept:
            image = next(iter(kept.pages[0].images.values()))
            # A4 is 8.27 inches wide: 200 dpi is about 1654 px.
            self.assertAlmostEqual(int(image.Width), 1654, delta=2)

    def test_a_jpeg_inside_a_pdf_loses_its_exif(self):
        jpeg = samples.photo((200, 100))
        self.assertIn(b"SecretPhone", jpeg)
        self.assertNotIn(b"SecretPhone", pdf.strip_jpeg_metadata(jpeg))
        self.assertEqual(opened(pdf.strip_jpeg_metadata(jpeg)).size, (200, 100))

    def test_a_password_or_garbage_is_refused(self):
        import pikepdf

        locked = io.BytesIO()
        document = pikepdf.new()
        document.add_blank_page()
        document.save(locked, encryption=pikepdf.Encryption(owner="o", user="u"))
        with self.assertRaisesRegex(images.Refused, "password"):
            pdf.optimise(locked.getvalue(), profile_for(Kind.DOCUMENT))
        with self.assertRaisesRegex(images.Refused, "not a PDF this can read"):
            pdf.optimise(b"%PDF-1.7 and then nonsense", profile_for(Kind.DOCUMENT))


class HeroVideoTests(SimpleTestCase):
    def test_a_short_clip_becomes_a_muted_720p_mp4_under_3_mb_with_a_poster(self):
        import av

        raw = samples.video(seconds=3, size=(1920, 1080), fps=50, audio=True)
        with av.open(io.BytesIO(raw)) as sent:
            self.assertTrue(sent.streams.audio, "the sample has sound, so muting means something")

        made = video.hero_loop(raw, profile_for(Kind.HERO_VIDEO))
        loop = made["data"]["loop.mp4"]

        self.assertLessEqual(len(loop), VIDEO_MAX_OUTPUT_BYTES)
        with av.open(io.BytesIO(loop)) as kept:
            self.assertEqual(len(kept.streams.audio), 0)
            stream = kept.streams.video[0]
            self.assertEqual(stream.codec_context.name, "h264")
            self.assertEqual((stream.codec_context.width, stream.codec_context.height), (1280, 720))
            self.assertLessEqual(float(stream.average_rate), 30)
        self.assertIn("poster-828.avif", made["data"])
        self.assertIn("poster-828.jpg", made["data"])

    def test_more_than_ten_seconds_is_a_link_not_an_upload(self):
        raw = samples.video(seconds=12, size=(320, 240), fps=10)
        with self.assertRaisesRegex(images.Refused, "YouTube or Vimeo"):
            video.hero_loop(raw, profile_for(Kind.HERO_VIDEO))
