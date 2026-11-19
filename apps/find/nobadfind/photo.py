"""Photo meaning: find photos by what's in them ("dog on a beach"), even when their name and text say nothing.

A local image-text model, SigLIP base (Google, Apache-2.0; ONNX export by Xenova, 8-bit), turns each photo and
each question into vectors in the same space. The model (about 211 MB) is downloaded only when the user allows it
(setting allow_photo_model_download), from one pinned revision, every file checked by size and SHA-256.

Photos are untrusted: they're decoded by Windows' own image decoders (the ones Explorer uses for thumbnails) in a
separate low-priority worker process, never opened in another program, and size-limited. Only the 224 x 224
picture the model needs is ever made.
"""
import os
import re
import threading

import numpy as np

from .const import DATA_DIR

PHOTO_DIR = os.path.join(DATA_DIR, "photo-model")
PHOTO_REV = "4649052661e53c7000355844105f8a1792088239"
PHOTO_URL = "https://huggingface.co/Xenova/siglip-base-patch16-224/resolve/{rev}/{path}"
PHOTO_FILES = {   # local name: (path in the repository, size in bytes, SHA-256)
    "vision.onnx": ("onnx/vision_model_quantized.onnx", 99499129,
                    "ef14a954f3d57e1806666432bd9785004c1dc27100aa260eee0cb0f10a5de058"),
    "text.onnx": ("onnx/text_model_quantized.onnx", 111475220,
                  "ad0329b1f35acc66d8953ff2559ce358da8eb0a7011794cf951523d63a4dbce2"),
    "tokenizer.json": ("tokenizer.json", 2398744,
                       "4a17c975210be5ab4c36b47d8dae4eefb866dbfb1e676e394aad85dc30a3ae08"),
}
PHOTO_DIM = 768
SIDE = 224
TEXT_LEN = 64
EOS = 1                                   # "</s>": SigLIP pads with it too
OUT_OF_MEMORY = "out of memory"           # the worker job's limit: read again (as extract.OUT_OF_MEMORY)
MAX_PHOTO_BYTES = 60 * 1024 * 1024
MIN_PHOTO_BYTES = 12 * 1024               # smaller files are icons, buttons and thumbnails
MAX_PIXELS = 80_000_000                   # a small file may claim a huge picture: not decoded
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp", ".tif", ".tiff", ".gif"}


def model_ready(model_dir=PHOTO_DIR):
    for name, (_path, size, _sha) in PHOTO_FILES.items():
        p = os.path.join(model_dir, name)
        if not os.path.isfile(p) or os.path.getsize(p) != size:
            return False
    return True


def download_model(model_dir=PHOTO_DIR, progress=None):
    """Same checks as the text model (embed.download_model): HTTPS only, exact size, SHA-256 before use."""
    from .embed import _fetch_verified
    os.makedirs(model_dir, exist_ok=True)
    for name, (path, size, sha) in PHOTO_FILES.items():
        _fetch_verified(PHOTO_URL.format(rev=PHOTO_REV, path=path), os.path.join(model_dir, name), size, sha,
                        name, progress)


# ---------- images (in the worker process) ----------
def decode_224(data):
    """Encoded image bytes -> float32 (3, 224, 224) in the model's range, or None if it isn't a usable photo.
    Windows decodes and scales it (BitmapDecoder + BitmapTransform), turned the way the camera held it."""
    from winrt.windows.graphics.imaging import (BitmapAlphaMode, BitmapDecoder, BitmapInterpolationMode,
                                                 BitmapPixelFormat, BitmapTransform, ColorManagementMode,
                                                 ExifOrientationMode)
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
    if min(width, height) < 64 or width * height > MAX_PIXELS:
        return None
    t = BitmapTransform()
    t.scaled_width, t.scaled_height = SIDE, SIDE      # SigLIP squeezes to 224 x 224 (no crop)
    t.interpolation_mode = BitmapInterpolationMode.FANT
    px = dec.get_pixel_data_transformed_async(BitmapPixelFormat.RGBA8, BitmapAlphaMode.IGNORE, t,
                                              ExifOrientationMode.RESPECT_EXIF_ORIENTATION,
                                              ColorManagementMode.COLOR_MANAGE_TO_S_RGB).get()
    raw = np.frombuffer(bytes(px.detach_pixel_data()), np.uint8)
    if raw.size != SIDE * SIDE * 4:
        return None
    rgb = raw.reshape(SIDE, SIDE, 4)[:, :, :3].astype(np.float32)
    return ((rgb / 255.0 - 0.5) / 0.5).transpose(2, 0, 1)


_vision = None
_threads = [2]                                        # set by init_worker from the level (indexer._photo_vectors)
QUESTION_THREADS = 4                                  # a photo question while you type: 45 ms on 2 threads, 28 on 4


def _vision_session(model_dir):
    global _vision
    if _vision is None:
        import onnxruntime as ort
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = _threads[0]       # 2.4 photos/s on 2 threads, 7.1 on 8 (CPU-capped by level)
        opts.log_severity_level = 3
        _vision = ort.InferenceSession(os.path.join(model_dir, "vision.onnx"), opts,
                                       providers=["CPUExecutionProvider"])
    return _vision


def _unit(v):
    return v / np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-9)


def embed_photo(job):
    """Worker entry: (file_id, path, mtime, model_dir) -> (file_id, mtime, float16 bytes or b"", error)."""
    file_id, path, mtime, model_dir = job
    try:
        if os.path.getsize(path) > MAX_PHOTO_BYTES:
            return file_id, mtime, b"", "too big"
        with open(path, "rb") as f:
            data = f.read(MAX_PHOTO_BYTES + 1)
        pixels = decode_224(data)
        if pixels is None:
            return file_id, mtime, b"", "not a photo"
        out = _vision_session(model_dir).run(["pooler_output"], {"pixel_values": pixels[None]})[0]
        return file_id, mtime, _unit(out[0]).astype(np.float16).tobytes(), None
    except MemoryError:
        return file_id, mtime, b"", OUT_OF_MEMORY
    except Exception as e:                            # one bad photo never stops the others
        return file_id, mtime, b"", f"unreadable ({type(e).__name__})"


_mode = [True]


def embed_photos(jobs, fast=False):
    """Worker entry for a batch: [(file_id, path, mtime, model_dir), ...] -> results like embed_photo.
    fast: you're away from the PC, so the worker runs at normal priority for this batch."""
    if fast == _mode[0]:
        from . import winapi
        winapi.worker_priority(not fast)
        _mode[0] = not fast
    return [embed_photo(j) for j in jobs]


def init_worker(threads=2):
    from . import jobs, winapi
    _threads[0] = max(1, int(threads))
    jobs.join_workers()            # into Find's worker group (CPU-capped, ends with the app)
    winapi.worker_priority()
    # winrt carries an older C++ runtime; onnxruntime must be loaded first (see ocr._load)
    import importlib
    importlib.import_module("onnxruntime")


# ---------- questions (in the app) ----------
_CANON = re.compile(r"[^\w\s]", re.UNICODE)


PAD2 = 0                                  # SigLIP 2 (Gemma tokenizer): <pad>; <eos> is 1 there too


def question_ids(tok, text, style="siglip"):
    """TEXT_LEN token ids for a question. SigLIP learned from lower-case text without punctuation, padded with
    </s>; SigLIP 2 from lower-case text ending in <eos>, padded with <pad> (its tokenizer.json adds both)."""
    if style == "siglip2":
        ids = list(tok.encode(text.lower()).ids)[:TEXT_LEN]
        if EOS not in ids:
            ids[-1:] = [EOS]
        return ids + [PAD2] * (TEXT_LEN - len(ids))
    clean = " ".join(_CANON.sub(" ", text.lower()).split())
    ids = tok.encode(clean).ids[:TEXT_LEN]
    if ids and ids[-1] != EOS:
        ids[-1] = EOS
    return ids + [EOS] * (TEXT_LEN - len(ids))


class TextEncoder:
    """The text half of SigLIP / SigLIP 2: a question -> a vector comparable with that model's photo vectors."""

    def __init__(self, model_dir=PHOTO_DIR, threads=None, style="siglip"):
        if not os.path.isfile(os.path.join(model_dir, "text.onnx")):
            raise RuntimeError("photo model not downloaded")
        self.style = style
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self.tok = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads or QUESTION_THREADS
        opts.log_severity_level = 3
        self.sess = ort.InferenceSession(os.path.join(model_dir, "text.onnx"), opts, providers=["CPUExecutionProvider"])
        self._lock = threading.Lock()

    def encode(self, text):
        ids = question_ids(self.tok, text, self.style)
        with self._lock:
            out = self.sess.run(["pooler_output"], {"input_ids": np.array([ids], np.int64)})[0]
        return _unit(out[0]).astype(np.float32)
