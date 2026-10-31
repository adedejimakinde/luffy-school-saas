"""Files to upload in tests, made here so nothing binary is committed."""

import io
import os
import tempfile
from fractions import Fraction


def photo(size=(3000, 2000), fmt="JPEG", gps=True, colour=None, **save):
    """A photo with something to compress, and (by default) a GPS EXIF block."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", size, colour or (180, 120, 60))
    draw = ImageDraw.Draw(image)
    step = max(8, size[0] // 40)
    for x in range(0, size[0], step):
        draw.line([(x, 0), (size[0] - x, size[1])], fill=((x * 7) % 255, 90, (x * 3) % 255), width=3)
    draw.ellipse([size[0] // 4, size[1] // 4, size[0] // 2, size[1] // 2], fill=(20, 40, 160))
    if gps and fmt in ("JPEG", "WEBP", "PNG"):
        exif = Image.Exif()
        exif[0x010F] = "PhoneMaker"          # Make
        exif[0x0110] = "SecretPhone 12"      # Model
        exif[0x8825] = {                     # GPSInfo
            1: "N", 2: (6.0, 27.0, 18.0), 3: "E", 4: (3.0, 23.0, 40.0),
        }
        save["exif"] = exif
    out = io.BytesIO()
    image.save(out, format=fmt, **save)
    return out.getvalue()


def logo(size=(600, 400), fmt="PNG", border=60):
    """A crest-like mark on a plain border, to be trimmed."""
    from PIL import Image, ImageDraw

    image = Image.new("RGBA" if fmt == "PNG" else "RGB", size, (255, 255, 255, 0) if fmt == "PNG" else (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle([border, border, size[0] - border, size[1] - border], fill=(20, 61, 140, 255) if fmt == "PNG" else (20, 61, 140))
    draw.ellipse([border + 20, border + 20, border + 120, border + 120], fill=(230, 180, 20, 255) if fmt == "PNG" else (230, 180, 20))
    out = io.BytesIO()
    image.save(out, format=fmt)
    return out.getvalue()


def svg():
    return b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"><rect width="10" height="10"/></svg>'


def gif():
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (40, 40), (1, 2, 3)).save(out, format="GIF")
    return out.getvalue()


def bomb():
    """A PNG whose header claims 30,000 x 30,000 pixels: a few KB on disk."""
    from PIL import Image

    out = io.BytesIO()
    Image.new("1", (30000, 30000)).save(out, format="PNG")
    return out.getvalue()


def pdf(pages=2, scanned=False, javascript=False):
    """A PDF, optionally with a dense scanned page and a script that runs on open."""
    import pikepdf
    from PIL import Image

    document = pikepdf.new()
    for number in range(pages):
        document.add_blank_page(page_size=(595, 842))
    if scanned:
        page = document.pages[0]
        picture = Image.frombytes("RGB", (2480, 3508), os.urandom(2480 * 3508 * 3)).resize((2480, 3508))
        smooth = Image.new("RGB", (2480, 3508), (240, 240, 235))
        smooth.paste(picture.resize((620, 877)).resize((2480, 3508)).convert("L").convert("RGB").point(lambda v: 200 + v // 8))
        data = io.BytesIO()
        smooth.save(data, format="JPEG", quality=95)
        image = pikepdf.Stream(document, data.getvalue())
        image.Type, image.Subtype = pikepdf.Name.XObject, pikepdf.Name.Image
        image.Width, image.Height = 2480, 3508
        image.ColorSpace, image.BitsPerComponent = pikepdf.Name.DeviceRGB, 8
        image.Filter = pikepdf.Name.DCTDecode
        page.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im0=image))
        page.Contents = pikepdf.Stream(document, b"q 595 0 0 842 0 0 cm /Im0 Do Q")
    document.docinfo["/Author"] = "Mrs Secret Author"
    if javascript:
        document.Root.OpenAction = pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS=pikepdf.String("app.alert('hi')"))
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def video(seconds=2.0, size=(640, 360), fps=25, audio=False, fmt="mp4"):
    """A short clip with moving colour, made with PyAV."""
    import av
    from PIL import Image, ImageDraw

    with tempfile.TemporaryDirectory() as work:
        path = os.path.join(work, f"clip.{fmt}")
        with av.open(path, "w", format=fmt) as out:
            stream = out.add_stream("libx264" if fmt == "mp4" else "libvpx-vp9", rate=fps)
            stream.width, stream.height = size
            stream.pix_fmt = "yuv420p"
            sound = None
            if audio:
                sound = out.add_stream("aac", rate=44100)
            for index in range(int(seconds * fps)):
                image = Image.new("RGB", size, (index * 5 % 255, 80, 160))
                ImageDraw.Draw(image).rectangle([index * 4 % size[0], 40, index * 4 % size[0] + 60, 120], fill=(255, 255, 255))
                frame = av.VideoFrame.from_image(image)
                frame.pts = index
                frame.time_base = Fraction(1, fps)
                for packet in stream.encode(frame):
                    out.mux(packet)
            for packet in stream.encode():
                out.mux(packet)
            if sound is not None:
                silence = av.AudioFrame(format="fltp", layout="stereo", samples=1024)
                for plane in silence.planes:
                    plane.update(bytes(plane.buffer_size))
                silence.sample_rate = 44100
                for i in range(int(seconds * 44100 / 1024)):
                    silence.pts = i * 1024
                    for packet in sound.encode(silence):
                        out.mux(packet)
                for packet in sound.encode():
                    out.mux(packet)
        with open(path, "rb") as handle:
            return handle.read()
