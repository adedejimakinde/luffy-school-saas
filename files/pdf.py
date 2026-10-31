"""Documents: a PDF, rewritten losslessly, with what could run or tell removed.

What is done, in order:

1. **It must be a PDF**: `%PDF-` at the start, and pikepdf (qpdf) must open it.
   A password-protected file is refused: it cannot be checked.
2. **Nothing that runs**: document- and page-level actions (`/OpenAction`,
   `/AA`), JavaScript, launch actions and embedded files are removed. A
   document goes to a school office; it has no need to do anything when opened.
3. **No hidden metadata**: the document information dictionary (author,
   software, dates) and XMP are removed, and so are the EXIF and XMP blocks
   inside any JPEG drawn on a page, where a phone's scan keeps its GPS.
4. **Scanned pages are brought down safely**: a colour or grey image denser
   than `PDF_DOWNSAMPLE_ABOVE_DPI` against the page's width is redrawn at
   `PDF_TARGET_DPI` as JPEG, and only if that is smaller. Black-and-white
   scans (1 bit, CCITT, JBIG2), images with masks, indexed or CMYK colour, and
   JPEG 2000 are left exactly as they are.
5. **Lossless rewrite**: streams recompressed, object streams generated, unused
   resources dropped. The page count must be unchanged afterwards.
"""

import io

from .images import Refused
from .kinds import PDF_DOWNSAMPLE_ABOVE_DPI, PDF_MAX_PAGES, PDF_TARGET_DPI, Profile


def looks_like_pdf(head: bytes) -> bool:
    return b"%PDF-" in head[:1024]


def strip_jpeg_metadata(data: bytes) -> bytes:
    """A JPEG with its APP1–APP13 and comment segments removed, losslessly.

    APP0 (JFIF) and APP14 (Adobe, which says how to read its colour) stay.
    The compressed image itself is not touched.
    """
    if data[:2] != b"\xff\xd8":
        return data
    out = bytearray(b"\xff\xd8")
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            return data  # not a marker where one should be: leave it alone
        marker = data[i + 1]
        if marker == 0xDA:  # start of scan: the rest is image data
            out += data[i:]
            return bytes(out)
        length = int.from_bytes(data[i + 2: i + 4], "big")
        segment = data[i: i + 2 + length]
        if not (0xE1 <= marker <= 0xED or marker == 0xFE):
            out += segment
        i += 2 + length
    return data


def _remove_actions(pdf):
    import pikepdf

    root = pdf.Root
    for name in ("/OpenAction", "/AA"):
        if name in root:
            del root[name]
    if "/Names" in root:
        for name in ("/JavaScript", "/EmbeddedFiles"):
            if name in root.Names:
                del root.Names[name]
    if "/Metadata" in root:
        del root["/Metadata"]
    for page in pdf.pages:
        if "/AA" in page.obj:
            del page.obj["/AA"]
        for annot in list(page.obj.get("/Annots", [])):
            action = annot.get("/A")
            if action is not None and action.get("/S") in (
                pikepdf.Name.JavaScript, pikepdf.Name.Launch, pikepdf.Name.ImportData,
                pikepdf.Name.SubmitForm,
            ):
                del annot["/A"]
            if "/AA" in annot:
                del annot["/AA"]
            if annot.get("/Subtype") == pikepdf.Name.FileAttachment:
                if "/FS" in annot:
                    del annot["/FS"]
    if "/AcroForm" in root and "/XFA" in root.AcroForm:
        del root.AcroForm["/XFA"]
    try:
        del pdf.trailer["/Info"]
    except KeyError:
        pass


def _downsample(pdf) -> int:
    """Redraw over-dense scanned images. Returns how many were redrawn."""
    import pikepdf
    from PIL import Image

    redrawn = 0
    seen = set()
    for page in pdf.pages:
        box = page.mediabox
        page_inches = max(float(box[2]) - float(box[0]), 1.0) / 72.0
        for _, image_obj in page.images.items():
            if image_obj.objgen in seen:
                continue
            seen.add(image_obj.objgen)
            filters = image_obj.get("/Filter")
            names = list(filters) if isinstance(filters, pikepdf.Array) else ([filters] if filters else [])
            if any(f not in (pikepdf.Name.DCTDecode, pikepdf.Name.FlateDecode) for f in names):
                continue
            if "/SMask" in image_obj or "/Mask" in image_obj or "/Decode" in image_obj:
                continue
            if int(image_obj.get("/BitsPerComponent", 8)) != 8:
                continue
            space = image_obj.get("/ColorSpace")
            if space not in (pikepdf.Name.DeviceRGB, pikepdf.Name.DeviceGray):
                continue
            width = int(image_obj.Width)
            dpi = width / page_inches
            if dpi <= PDF_DOWNSAMPLE_ABOVE_DPI:
                continue
            try:
                picture = pikepdf.PdfImage(image_obj).as_pil_image()
            except Exception:  # noqa: BLE001 — an image we cannot read is left as it is
                continue
            scale = PDF_TARGET_DPI / dpi
            size = (max(1, round(picture.width * scale)), max(1, round(picture.height * scale)))
            mode = "L" if space == pikepdf.Name.DeviceGray else "RGB"
            smaller = picture.convert(mode).resize(size, Image.LANCZOS)
            out = io.BytesIO()
            smaller.save(out, format="JPEG", quality=85, optimize=True)
            data = out.getvalue()
            if len(data) >= len(image_obj.read_raw_bytes()):
                continue
            image_obj.write(data, filter=pikepdf.Name.DCTDecode)
            image_obj.Width, image_obj.Height = size
            image_obj.BitsPerComponent = 8
            image_obj.ColorSpace = pikepdf.Name.DeviceGray if mode == "L" else pikepdf.Name.DeviceRGB
            if "/DecodeParms" in image_obj:
                del image_obj["/DecodeParms"]
            redrawn += 1
    return redrawn


def _strip_embedded_jpegs(pdf):
    import pikepdf

    for page in pdf.pages:
        for _, image_obj in page.images.items():
            if image_obj.get("/Filter") == pikepdf.Name.DCTDecode:
                raw = image_obj.read_raw_bytes()
                clean = strip_jpeg_metadata(raw)
                if clean != raw:
                    image_obj.write(clean, filter=pikepdf.Name.DCTDecode)


def optimise(raw: bytes, profile: Profile):
    import pikepdf

    if len(raw) > profile.max_bytes:
        raise Refused(f"{profile.noun} can be at most {profile.max_mb} MB. Save it smaller and try again.")
    if not looks_like_pdf(raw):
        raise Refused("A document is a PDF file.")
    try:
        pdf = pikepdf.open(io.BytesIO(raw))
    except pikepdf.PasswordError:
        raise Refused("That PDF has a password. Save a copy without one and upload that.")
    except pikepdf.PdfError:
        raise Refused("That file is not a PDF this can read.")
    with pdf:
        pages = len(pdf.pages)
        if pages == 0:
            raise Refused("That PDF has no pages.")
        if pages > PDF_MAX_PAGES:
            raise Refused(f"A document can have at most {PDF_MAX_PAGES} pages.")
        _remove_actions(pdf)
        _strip_embedded_jpegs(pdf)
        _downsample(pdf)
        pdf.remove_unreferenced_resources()
        out = io.BytesIO()
        pdf.save(
            out,
            compress_streams=True,
            recompress_flate=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
            deterministic_id=True,
        )
    data = out.getvalue()
    with pikepdf.open(io.BytesIO(data)) as check:
        if len(check.pages) != pages:
            raise Refused("That PDF could not be saved safely. Try saving it again from the program that made it.")
    return {
        "variants": {"document.pdf": {"bytes": len(data)}},
        "data": {"document.pdf": data},
        "master": "document.pdf",
        "pages": pages,
    }


__all__ = ["looks_like_pdf", "optimise", "strip_jpeg_metadata"]
