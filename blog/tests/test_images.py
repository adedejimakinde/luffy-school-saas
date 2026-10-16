"""A picture is drawn again as WebP, sized and small (`blog.images`)."""

import io

from django.test import SimpleTestCase
from PIL import Image

from blog import images

from .fixtures import picture


def opened(data):
    return Image.open(io.BytesIO(bytes(data)))


class DrawnAgainTests(SimpleTestCase):
    def test_a_cover_is_cut_to_1200_by_630_and_written_as_webp(self):
        full, small = images.draw(picture(3000, 2000, "JPEG"), cover=True)
        self.assertEqual(full.size, (1200, 630))
        self.assertEqual(small.size, (600, 315))
        data = images._webp(full)
        self.assertEqual(opened(data).format, "WEBP")

    def test_a_body_picture_is_at_most_1600_wide_and_never_made_larger(self):
        full, small = images.draw(picture(4000, 2000), cover=False)
        self.assertEqual(full.size, (1600, 800))
        self.assertEqual(small.size, (800, 400))
        full, _ = images.draw(picture(800, 600), cover=False)
        self.assertEqual(full.size, (800, 600))

    def test_webp_in_is_webp_out_and_compressed(self):
        raw = picture(2400, 1600, "PNG")
        full, _ = images.draw(raw, cover=False)
        data = images._webp(full)
        self.assertLess(len(data), len(raw))

    def test_nothing_of_the_original_file_is_kept(self):
        source = Image.new("RGB", (800, 600), (10, 20, 30))
        out = io.BytesIO()
        exif = Image.Exif()
        exif[0x010E] = "a secret description"
        source.save(out, format="JPEG", exif=exif)
        full, _ = images.draw(out.getvalue(), cover=False)
        data = images._webp(full)
        self.assertNotIn(b"a secret description", data)
        self.assertNotIn(b"Exif", data)

    def test_a_phone_photo_is_turned_the_right_way_up(self):
        source = Image.new("RGB", (800, 400), (10, 20, 30))
        out = io.BytesIO()
        exif = Image.Exif()
        exif[0x0112] = 6  # rotated 90 degrees
        source.save(out, format="JPEG", exif=exif)
        full, _ = images.draw(out.getvalue(), cover=False)
        self.assertEqual(full.size, (400, 800))


class RefusedTests(SimpleTestCase):
    def test_what_is_not_a_picture_this_reads(self):
        for raw, words in (
            (b"", "Choose a picture"),
            (b"<?php echo 1; ?>", "not a picture"),
            (picture(100, 100, "GIF"), "JPG, PNG or WebP"),
            (b"x" * (images.MAX_UPLOAD_BYTES + 1), "at most 10 MB"),
        ):
            with self.subTest(words=words):
                with self.assertRaisesRegex(images.ImageRefused, words):
                    images.draw(raw, cover=False)

    def test_a_picture_with_too_many_pixels_is_refused_from_its_header(self):
        raw = picture(8000, 6000, "PNG", colour=(0, 0, 0))
        with self.assertRaisesRegex(images.ImageRefused, "far larger"):
            images.draw(raw, cover=False)
