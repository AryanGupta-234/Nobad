"""Meaning search: a small local model turns text into vectors, so "rent" also finds "lease agreement".

The model (all-MiniLM-L6-v2, 23 MB) is downloaded only when the user asks for it (setting allow_model_download),
from one pinned revision, and every file is checked against its SHA-256 before use. Everything runs on this PC.
"""
import hashlib
import os
import threading
import urllib.request

import numpy as np

from .const import MODEL_DIM, MODEL_DIR, MODEL_FILES, MODEL_REV, MODEL_URL
from .log import log

MAX_TOKENS = 256


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
        """Unit-length float32 vectors, one row per text."""
        if not texts:
            return np.zeros((0, MODEL_DIM), np.float32)
        enc = self.tok.encode_batch(list(texts))
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
    """All chunk vectors in memory as float16 (384 values = 768 bytes per chunk); brute-force cosine search."""

    def __init__(self):
        self.ids = np.zeros(0, np.int64)
        self.mat = np.zeros((0, MODEL_DIM), np.float16)
        self._lock = threading.Lock()

    def load(self, store):
        rows = store.q("SELECT chunk_id, v FROM vecs")
        with self._lock:
            self.ids = np.array([r[0] for r in rows], np.int64)
            self.mat = (np.frombuffer(b"".join(r[1] for r in rows), np.float16).reshape(-1, MODEL_DIM)
                        if rows else np.zeros((0, MODEL_DIM), np.float16))

    def add(self, ids, vecs):
        with self._lock:
            self.ids = np.concatenate([self.ids, np.asarray(ids, np.int64)])
            self.mat = np.vstack([self.mat, np.asarray(vecs, np.float16)])

    def search(self, qvec, k=200):
        with self._lock:
            if not len(self.ids):
                return []
            scores = self.mat.astype(np.float32) @ np.asarray(qvec, np.float32)
            k = min(k, len(scores))
            top = np.argpartition(-scores, k - 1)[:k]
            top = top[np.argsort(-scores[top])]
            return [(int(self.ids[i]), float(scores[i])) for i in top]
