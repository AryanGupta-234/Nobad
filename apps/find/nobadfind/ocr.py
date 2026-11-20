"""Read the words in photos, screenshots and scanned PDFs with the OCR engine built into Windows (offline).

Windows.Media.Ocr ships with Windows 10 and 11 and uses the languages of the user's profile. Nothing is downloaded
and nothing leaves the PC. Runs inside the low-priority text-reading worker processes (indexer.py), like every
other reader here: images are untrusted, so they are size-limited, decoded only by Windows' own image decoders
(the ones Explorer uses for thumbnails) and never opened in another program.
"""
import struct

MAX_IMAGE_BYTES = 40 * 1024 * 1024
MIN_IMAGE_BYTES = 8 * 1024              # smaller files are icons and buttons, not text worth reading
MIN_SIDE = 64                           # pixels
MAX_PIXELS = 50_000_000                # a small file can claim a huge picture: decoding it would take GBs
MAX_PDF_PIXELS = 25_000_000            # raw scan images in PDFs, checked before they're unpacked
OCR_SIDE = 4000                         # plenty for reading text, and much faster than OCR's own limit
MAX_PDF_OCR_PAGES = 60
MAX_PDF_OCR_IMAGES = 80
PDF_OCR_SECONDS = 120                   # time budget for one scanned PDF
OCR_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".gif", ".webp", ".heic", ".heif"}

_engine = None
_missing = None


def _load():
    """The OCR engine for the user's languages, or None when this Windows (or Python) doesn't have it."""
    global _engine, _missing
    if _engine is not None or _missing is not None:
        return _engine
    try:
        # winrt 3.2.1 carries an older C++ runtime (msvcp140.dll). Whichever loads first wins, and onnxruntime
        # (meaning search) can't start on the old one, so onnxruntime must be loaded before winrt.
        # (Only the app's own process runs the model; the text-reading workers skip this.)
        import importlib
        import multiprocessing
        if multiprocessing.parent_process() is None:
            try:
                importlib.import_module("onnxruntime")
            except ImportError:
                pass
        from winrt.windows.media.ocr import OcrEngine
        _engine = OcrEngine.try_create_from_user_profile_languages()
        if _engine is None:
            _missing = "no OCR language installed"
    except MemoryError:                          # the worker job's limit: not a missing OCR, try again later
        raise
    except Exception as e:                       # ImportError, or the WinRT class isn't registered
        _missing = f"OCR not available ({type(e).__name__})"
    return _engine


def available():
    return _load() is not None


def why_missing():
    _load()
    return _missing or ""


def _recognize(data):
    """Decode with Windows' image decoders and run OCR. WinRT calls block in this worker process (.get())."""
    from winrt.windows.graphics.imaging import (BitmapAlphaMode, BitmapDecoder, BitmapInterpolationMode,
                                                 BitmapPixelFormat, BitmapTransform, ColorManagementMode,
                                                 ExifOrientationMode)
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream
    stream = InMemoryRandomAccessStream()
    w = DataWriter(stream)
    w.write_bytes(data)
    w.store_async().get()
    w.flush_async().get()
    w.detach_stream()
    stream.seek(0)
    dec = BitmapDecoder.create_async(stream).get()
    width, height = dec.oriented_pixel_width, dec.oriented_pixel_height
    if min(width, height) < MIN_SIDE or width * height > MAX_PIXELS:
        return ""
    t = BitmapTransform()
    limit = min(OCR_SIDE, OcrEngine.max_image_dimension)
    if max(width, height) > limit:               # scale big photos and long screenshots down to what OCR takes
        f = limit / max(width, height)
        t.scaled_width, t.scaled_height = max(1, int(width * f)), max(1, int(height * f))
        t.interpolation_mode = BitmapInterpolationMode.FANT
    bmp = dec.get_software_bitmap_transformed_async(BitmapPixelFormat.BGRA8, BitmapAlphaMode.PREMULTIPLIED, t,
                                                    ExifOrientationMode.RESPECT_EXIF_ORIENTATION,
                                                    ColorManagementMode.DO_NOT_COLOR_MANAGE).get()
    result = _engine.recognize_async(bmp).get()
    return real_words("\n".join(line.text for line in result.lines))


def real_words(text):
    """OCR on a photo without writing can 'read' a few stray letters ("vzÄ"): keep text only when it has words."""
    import re
    words = re.findall(r"[^\W\d_]{3,}", text)
    return text if len(words) >= 2 or sum(map(len, words)) >= 8 else ""


def image_bytes_text(data):
    """Text in one encoded image (PNG, JPEG, TIFF, BMP, ...). Empty when there are no words or no OCR."""
    if not data or len(data) > MAX_IMAGE_BYTES or _load() is None:
        return ""
    try:
        return _recognize(bytes(data))
    except MemoryError:
        raise
    except Exception:                            # an image Windows can't decode is simply not read
        return ""


def image_text(path, max_bytes):
    with open(path, "rb") as f:
        data = f.read(min(max_bytes, MAX_IMAGE_BYTES) + 1)
    if len(data) > min(max_bytes, MAX_IMAGE_BYTES):
        return ""
    return image_bytes_text(data)


# ---------- scanned PDFs ----------
def gray_bmp(width, height, pixels):
    """An 8-bit grey BMP file (top-down) from width*height bytes of grey pixels."""
    stride = (width + 3) & ~3
    if stride == width:
        rows = bytes(pixels[:width * height])
    else:
        rows = bytearray(stride * height)
        for y in range(height):
            rows[y * stride:y * stride + width] = pixels[y * width:(y + 1) * width]
    palette = b"".join(bytes((i, i, i, 0)) for i in range(256))
    off = 14 + 40 + len(palette)
    head = struct.pack("<2sIHHI", b"BM", off + len(rows), 0, 0, off)
    info = struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 8, 0, len(rows), 2835, 2835, 256, 0)
    return head + info + palette + rows


def _raw_to_gray(data, width, height, bpc, space, decode_inverted=False):
    """Raw PDF image samples -> grey bytes, for the common scan formats (grey or RGB at 8 bits, 1-bit black/white)."""
    import numpy as np
    if bpc == 1:
        row = (width + 7) // 8
        if len(data) < row * height:
            return None
        bits = np.unpackbits(np.frombuffer(data[:row * height], np.uint8).reshape(height, row), axis=1)[:, :width]
        g = (bits * 255).astype(np.uint8)
        if decode_inverted:
            g = 255 - g
        return g.tobytes()
    if bpc != 8:
        return None
    n = {"/DeviceGray": 1, "/CalGray": 1, "/DeviceRGB": 3, "/CalRGB": 3}.get(space)
    if not n or len(data) < width * height * n:
        return None
    a = np.frombuffer(data, np.uint8, count=width * height * n)
    if n == 1:
        return a.tobytes()
    a = a.reshape(-1, 3)
    out = np.empty(len(a), np.uint8)
    step = 1 << 20                                  # a million pixels at a time keeps memory flat
    for i in range(0, len(a), step):
        c = a[i:i + step].astype(np.uint16)
        out[i:i + step] = (c[:, 0] * 77 + c[:, 1] * 150 + c[:, 2] * 29) >> 8
    return out.tobytes()


def pdf_image_payloads(page):
    """Encoded images (JPEG, TIFF or BMP bytes) Windows can decode, from one PDF page's own images."""
    out = []
    try:
        xobjs = page["/Resources"]["/XObject"]
    except (KeyError, TypeError):
        return out
    for name in list(xobjs)[:20]:
        try:
            x = xobjs[name].get_object()
            if x.get("/Subtype") != "/Image":
                continue
            w, h = int(x.get("/Width", 0)), int(x.get("/Height", 0))
            if min(w, h) < MIN_SIDE or w * h > MAX_PDF_PIXELS:
                continue
            filt = x.get("/Filter")
            filt = filt[-1] if isinstance(filt, list) and filt else filt
            if filt == "/DCTDecode":
                out.append(x.get_data())                  # pypdf passes JPEG data through unchanged
            elif filt == "/CCITTFaxDecode":
                out.append(x.get_data())                  # pypdf wraps fax data in a TIFF header
            elif filt in ("/FlateDecode", "/LZWDecode", None):
                space = x.get("/ColorSpace")
                if x.get("/ImageMask"):
                    space = "/DeviceGray"
                elif not isinstance(space, str):
                    continue                              # palette and ICC images: not the usual scan, skipped
                bpc = 1 if x.get("/ImageMask") else int(x.get("/BitsPerComponent", 8))
                dec = x.get("/Decode")
                inverted = bool(dec) and list(dec)[:2] == [1, 0]
                g = _raw_to_gray(x.get_data(), w, h, bpc, space, inverted)
                if g:
                    out.append(gray_bmp(w, h, g))
        except MemoryError:
            raise
        except Exception:
            continue
    return out


def pdf_pages_text(reader, max_pages=MAX_PDF_OCR_PAGES):
    if _load() is None:
        return ""
    import time
    out, done, t0 = [], 0, time.monotonic()
    for i, page in enumerate(reader.pages):
        if i >= max_pages or done >= MAX_PDF_OCR_IMAGES or time.monotonic() - t0 > PDF_OCR_SECONDS:
            break
        for img in pdf_image_payloads(page)[:MAX_PDF_OCR_IMAGES - done]:
            done += 1
            t = image_bytes_text(img)
            if t:
                out.append(t)
    return "\n".join(out)
