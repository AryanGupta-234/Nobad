"""Meaning search: a small local model turns text into vectors, so "rent" also finds "lease agreement".

The model (all-MiniLM-L6-v2, 23 MB) is downloaded only when the user asks for it (setting allow_model_download),
from one pinned revision, and every file is checked against its SHA-256 before use. Everything runs on this PC.
"""
import hashlib
import os
import re
import threading
import urllib.request

import numpy as np

from .const import MODEL_DIM, MODEL_DIR, MODEL_FILES, MODEL_REV, MODEL_URL
from .log import log

MAX_TOKENS = 256
VEC_VERSION = "2"          # how vectors are made (titles in chunks, name vectors); a change recomputes them
BATCH = 64

# Words in file names that say nothing about what the file is
NAME_NOISE = {"img", "dsc", "dscn", "dcim", "pxl", "vid", "mvimg", "screenshot", "scan", "copy", "final", "new",
              "old", "v", "ver", "version", "draft", "file", "doc", "untitled", "document", "image", "photo",
              "edited", "export", "output", "tmp", "temp", "backup", "bak", "the", "and", "of", "for", "to", "in",
              "a", "an", "my", "with", "wa", "pic", "picture", "rev", "fwd", "re",
              # folders that say where a file is, not what it is
              "downloads", "download", "desktop", "documents", "pictures", "videos", "music", "onedrive", "users",
              "folder", "files", "misc", "stuff", "data", "camera", "roll", "uploads", "attachments", "inbox",
              "personal", "work", "shared", "public", "home", "tmp", "dropbox", "drive", "google", "icloud"}
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])")


def name_words(name):
    """'IMG_20250612_goa-beach_sunset.jpg' -> 'goa beach sunset'; '' when nothing meaningful is left."""
    stem = os.path.splitext(name)[0] if "." in name[1:] else name
    words = re.findall(r"[^\W\d_]{2,}", _CAMEL.sub(" ", stem))
    words = [w.lower() for w in words]
    keep = [w for w in words if w not in NAME_NOISE and not re.fullmatch(r"[a-f]{6,}", w)]
    return " ".join(keep[:16])


def name_text(name, folder):
    """What a file's name (and its folder's name) says it is: the text a name vector is made from."""
    words = name_words(name)
    parent = name_words(os.path.basename(folder.rstrip("\\/"))) if folder else ""
    if not words:
        return parent                    # DSC0001.jpg in "Holiday photos" is about the holiday
    return f"{words} ({parent})" if parent and parent != words else words


def chunk_text(title, body):
    """A chunk is embedded with its file's name in front: "contract final: This agreement is made..." """
    t = name_words(title)
    return f"{t}: {body}" if t else body


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def model_ready(model_dir=MODEL_DIR):
    for name, (_path, size, sha) in MODEL_FILES.items():
        p = os.path.join(model_dir, name)
        if not os.path.isfile(p) or os.path.getsize(p) != size:
            return False
    return True


def download_model(model_dir=MODEL_DIR, progress=None):
    """Fetch the pinned model files over HTTPS and verify each SHA-256. Raises on any mismatch."""
    os.makedirs(model_dir, exist_ok=True)
    for name, (path, size, sha) in MODEL_FILES.items():
        dest = os.path.join(model_dir, name)
        if os.path.isfile(dest) and os.path.getsize(dest) == size and _sha256(dest) == sha:
            continue
        url = MODEL_URL.format(rev=MODEL_REV, path=path)
        tmp = dest + ".part"
        h = hashlib.sha256()
        got = 0
        req = urllib.request.Request(url, headers={"User-Agent": "NOBAD-Find"})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            if not r.geturl().startswith("https://"):
                raise IOError("model download left HTTPS")
            while True:
                b = r.read(1 << 16)
                if not b:
                    break
                got += len(b)
                if got > size:
                    raise IOError(f"{name}: bigger than expected")
                h.update(b)
                f.write(b)
                if progress:
                    progress(name, got, size)
        if got != size or h.hexdigest() != sha:
            os.remove(tmp)
            raise IOError(f"{name}: checksum mismatch, download rejected")
        os.replace(tmp, dest)
        log(f"model file {name} verified")


class Embedder:
    def __init__(self, model_dir=MODEL_DIR, threads=None):
        if not model_ready(model_dir):
            raise RuntimeError("model not downloaded")
        import onnxruntime as ort
        from tokenizers import Tokenizer
        self.tok = Tokenizer.from_file(os.path.join(model_dir, "tokenizer.json"))
        self.tok.enable_truncation(MAX_TOKENS)
        self.tok.enable_padding(pad_id=0, pad_token="[PAD]")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads or max(1, (os.cpu_count() or 2) // 2)
        opts.log_severity_level = 3
        providers = [p for p in ("DmlExecutionProvider", "CPUExecutionProvider") if p in ort.get_available_providers()]
        self.sess = ort.InferenceSession(os.path.join(model_dir, "model.onnx"), opts, providers=providers)
        self.inputs = {i.name for i in self.sess.get_inputs()}
        self.device = "GPU" if providers and providers[0] == "DmlExecutionProvider" else "CPU"
        self._lock = threading.Lock()

    def encode(self, texts):
        """Unit-length float32 vectors, one row per text. Similar lengths are batched together (less padding)."""
        texts = list(texts)
        if not texts:
            return np.zeros((0, MODEL_DIM), np.float32)
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        out = np.zeros((len(texts), MODEL_DIM), np.float32)
        for i in range(0, len(order), BATCH):
            part = order[i:i + BATCH]
            out[part] = self._encode([texts[j] for j in part])
        return out

    def _encode(self, texts):
        enc = self.tok.encode_batch(texts)
        ids = np.array([e.ids for e in enc], np.int64)
        mask = np.array([e.attention_mask for e in enc], np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self.inputs:
            feed["token_type_ids"] = np.zeros_like(ids)
        with self._lock:
            out = self.sess.run(None, feed)[0]                       # (batch, tokens, dim)
        m = mask[..., None].astype(np.float32)
        v = (out * m).sum(1) / np.maximum(m.sum(1), 1e-9)          # mean pooling
        return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)


def to_blob(v):
    return np.asarray(v, np.float16).tobytes()


class VectorIndex:
    """Every vector in memory as float16 (384 values = 768 bytes each); brute-force cosine search.

    Keys: chunk vectors use the chunk id, name vectors use -file_id (see name_key / is_name)."""

    BLOCK = 65536                 # rows scored at a time: memory stays flat however big the index gets

    def __init__(self):
        self._ids = np.zeros(1024, np.int64)
        self._mat = np.zeros((1024, MODEL_DIM), np.float16)
        self.n = 0
        self._coarse = None               # n x PCA_DIMS float32 summary (big indexes only)
        self._proj = None
        self._fitted_at = 0
        self._lock = threading.Lock()

    @property
    def ids(self):
        return self._ids[:self.n]

    def load(self, store):
        rows = store.q("SELECT chunk_id, v FROM vecs") + store.q("SELECT -file_id, v FROM nvecs WHERE length(v) > 0")
        with self._lock:
            self.n = 0
            self._coarse, self._proj, self._fitted_at = None, None, 0
            self._ids = np.zeros(len(rows) + 1024, np.int64)
            self._mat = np.zeros((len(rows) + 1024, MODEL_DIM), np.float16)
            for i, (key, blob) in enumerate(rows):
                self._ids[i] = key
                self._mat[i] = np.frombuffer(blob, np.float16)
            self.n = len(rows)

    # Big indexes are searched in two steps: a compact 64-number summary of every vector (PCA, learned from the
    # vectors themselves) picks a few thousand candidates fast, then the full vectors rank those exactly.
    # Measured on real embeddings: with 4x the needed candidates, 98% of the exact top 50 are kept.
    FAST_FROM = 20_000
    PCA_DIMS = 64
    MIN_CANDIDATES = 4000

    def _grow(self, extra):
        need = self.n + extra
        if need <= len(self._ids):
            return
        cap = max(need, len(self._ids) * 3 // 2)       # growing by half: adding stays cheap on average
        ids, mat = np.zeros(cap, np.int64), np.zeros((cap, MODEL_DIM), np.float16)
        ids[:self.n], mat[:self.n] = self._ids[:self.n], self._mat[:self.n]
        self._ids, self._mat = ids, mat
        if self._coarse is not None:
            c = np.zeros((cap, self.PCA_DIMS), np.float32)
            c[:self.n] = self._coarse[:self.n]
            self._coarse = c

    def _fit(self):
        """Learn the summary from (a sample of) the vectors; done again whenever the index has doubled."""
        rng = np.random.default_rng(0)
        pick = rng.choice(self.n, min(self.n, 8000), replace=False)
        sample = self._mat[np.sort(pick)].astype(np.float32)
        _u, _s, vt = np.linalg.svd(sample - sample.mean(0), full_matrices=False)
        self._proj = vt[:self.PCA_DIMS].T.astype(np.float32).copy()
        self._coarse = np.zeros((len(self._ids), self.PCA_DIMS), np.float32)
        for i in range(0, self.n, self.BLOCK):
            j = min(self.n, i + self.BLOCK)
            self._coarse[i:j] = self._mat[i:j].astype(np.float32) @ self._proj
        self._fitted_at = self.n

    def add(self, ids, vecs):
        ids = np.asarray(ids, np.int64)
        if not len(ids):
            return
        with self._lock:
            self._grow(len(ids))
            a, b = self.n, self.n + len(ids)
            self._ids[a:b] = ids
            self._mat[a:b] = np.asarray(vecs, np.float16)
            if self._coarse is not None:
                self._coarse[a:b] = self._mat[a:b].astype(np.float32) @ self._proj
            self.n = b

    def search(self, qvec, k=200):
        q = np.asarray(qvec, np.float32)
        with self._lock:
            if not self.n:
                return []
            k = min(k, self.n)
            if self.n >= self.FAST_FROM:
                if self._coarse is None or self.n >= 2 * self._fitted_at:
                    self._fit()
                cand = min(self.n, max(self.MIN_CANDIDATES, 10 * k))
                rough = self._coarse[:self.n] @ (self._proj.T @ q)
                rows = np.argpartition(-rough, cand - 1)[:cand]
                scores = self._mat[rows].astype(np.float32) @ q
            else:
                rows = None
                scores = np.empty(self.n, np.float32)
                for i in range(0, self.n, self.BLOCK):
                    scores[i:i + self.BLOCK] = self._mat[i:min(self.n, i + self.BLOCK)].astype(np.float32) @ q
            top = np.argpartition(-scores, k - 1)[:k]
            top = top[np.argsort(-scores[top])]
            at = rows[top] if rows is not None else top
            return [(int(self._ids[i]), float(s)) for i, s in zip(at, scores[top])]


def name_key(file_id):
    return -int(file_id)


def is_name(key):
    return key < 0
