"""NOBAD Find measurement harness (ROADMAP Phase 0). Dev only: never shipped, never imported by the app.

    cd apps/find
    python tools/measure.py                     # gentle (all scenarios) + full and light (indexing only)
    python tools/measure.py --files 1000 --levels gentle --out C:/somewhere

What it does, per level:
1. Makes a fixed corpus (same seed, same files every time) and an empty data folder, both in a temp folder.
2. Starts the engine from source, `python -m nobadfind --engine`, with NOBAD_FIND_DATA_DIR (its own index and
   lock), NOBAD_FIND_MEASURE_PIPE (its own pipe, so it runs next to another engine) and NOBAD_FIND_MEASURE_LEVEL
   (the governor keeps that level). See engine.measure_overrides.
3. Samples every process of the engine's tree (the engine and everything it started, all inside its job) once a
   second: working set, private bytes, CPU %, I/O, handles, threads, and GPU % from the performance counters.
4. Scenarios: cold start (to "engine ready" and to the first pipe answer), idle with no UI, indexing at the level,
   idle with a UI connected (a small pipe client that says ui_shown), search typing over the pipe (round trip and
   the engine's own ms), window closed (ui_hidden: the engine's idle state).
5. Writes samples.csv, searches.csv and summary.md into --out (default: the temp folder) and prints the summary.

It stops only the processes it started, by PID (quit over the pipe first; the engine's job ends its workers).
"""
import argparse
import csv
import ctypes
import json
import os
import random
import shutil
import statistics
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
import zlib
from ctypes import wintypes

import psutil

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MB = 1024 * 1024

WORDS = ("invoice tax receipt budget holiday report meeting notes project plan travel ticket insurance policy "
         "contract salary bank statement school homework recipe garden car service warranty manual photo family "
         "birthday wedding doctor appointment health energy bill rent lease house moving checklist music guitar "
         "lesson python script server backup network router password reset account order delivery parcel "
         "kitchen paint window door furniture library book chapter summary thesis lecture exam grade").split()
QUERIES = ("invoice", "tax 2024", "holiday photos", "bank statement", "meeting notes", "guitar", "pdf from last week",
           "warranty manual", "zzzz no match", "recipe")


# ---------- the corpus ----------
def _text(rng, n):
    return " ".join(rng.choice(WORDS) for _ in range(n))


def _pdf(text):
    """A one-page PDF with a real text layer (pypdf reads it back)."""
    safe = text.replace("\\", "").replace("(", "").replace(")", "")
    lines = [safe[i:i + 80] for i in range(0, len(safe), 80)][:40]
    ops = "BT /F1 11 Tf 50 780 Td 14 TL " + " ".join(f"({ln}) '" for ln in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] /Contents 4 0 R "
            "/Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(ops)} >>\nstream\n{ops}\nendstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for o in offs:
        out += f"{o:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def _docx(path, text):
    body = "".join(f"<w:p><w:r><w:t>{text[i:i + 200]}</w:t></w:r></w:p>" for i in range(0, len(text), 200))
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
                   'package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/'
                   'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("word/document.xml", '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats'
                   f'.org/wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>')


def _png(rng, w, h, noisy):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    rows = b"".join(b"\x00" + (bytes(rng.getrandbits(8) for _ in range(w * 3)) if noisy else bytes([200]) * w * 3)
                    for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b""))


MIX = (("txt", 25), ("md", 8), ("csv", 8), ("json", 5), ("py", 10), ("html", 5), ("eml", 4), ("docx", 10),
       ("pdf", 12), ("png", 13))


def make_corpus(root, files, seed=7):
    """`files` files in 60 folders; the same bytes for the same (files, seed). Returns {ext: count}."""
    rng = random.Random(seed)
    exts = [e for e, w in MIX for _ in range(w)]
    counts = {}
    for i in range(files):
        ext = exts[i % len(exts)]
        folder = os.path.join(root, f"{rng.choice(WORDS)}-{i % 60:02d}")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"{rng.choice(WORDS)} {rng.choice(WORDS)} {i:05d}.{ext}")
        text = _text(rng, rng.randint(30, 600))
        if ext == "docx":
            _docx(path, text)
        elif ext == "pdf":
            data = _pdf(text)
        elif ext == "png":
            data = _png(rng, 64, 64, noisy=i % 2 == 0)        # half are over OCR's 8 KB floor
        elif ext == "html":
            data = f"<html><head><title>{text[:40]}</title></head><body><p>{text}</p></body></html>".encode()
        elif ext == "eml":
            data = (f"From: a@example.com\nTo: b@example.com\nSubject: {text[:50]}\n"
                    f"Date: Mon, 1 Jan 2024 10:00:00 +0000\n\n{text}\n").encode()
        elif ext == "json":
            data = json.dumps({"title": text[:40], "body": text}).encode()
        elif ext == "csv":
            data = "\n".join(",".join(text.split()[j:j + 6]) for j in range(0, len(text.split()), 6)).encode()
        elif ext == "py":
            data = "\n".join(f"def {w}_{k}():\n    return '{w}'" for k, w in enumerate(text.split()[:40])).encode()
        else:
            data = text.encode()
        if ext != "docx":
            with open(path, "wb") as f:
                f.write(data)
        counts[ext] = counts.get(ext, 0) + 1
    return counts


SCENES = ("sunset over the sea", "snowy mountains", "green field with a red barn", "city at night",
          "beach with palm trees", "desert dunes", "forest lake", "foggy morning hills")


def make_photos(root, n, seed=11):
    """n varied photo-like JPEGs (sky gradient, sun, hills, shapes, grain), named the way cameras name them.
    Returns the number made (0 without Pillow)."""
    try:
        from PIL import Image, ImageDraw, ImageFilter
    except ImportError:
        return 0
    rng = random.Random(seed)
    folder = os.path.join(root, "Pictures", "Camera Roll")
    os.makedirs(folder, exist_ok=True)
    for i in range(n):
        w, h = rng.choice(((800, 600), (1024, 768), (640, 480), (600, 800)))
        top = tuple(rng.randint(0, 255) for _ in range(3))
        bottom = tuple(rng.randint(0, 255) for _ in range(3))
        img = Image.new("RGB", (w, h))
        px = ImageDraw.Draw(img)
        for y in range(h):
            f = y / h
            px.line([(0, y), (w, y)], fill=tuple(int(a + (b - a) * f) for a, b in zip(top, bottom)))
        r = rng.randint(20, 90)
        cx, cy = rng.randint(0, w), rng.randint(0, h // 2)
        px.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, rng.randint(150, 240), rng.randint(0, 120)))
        for _ in range(rng.randint(2, 6)):                      # hills, houses, trees
            pts = [(rng.randint(-50, w + 50), rng.randint(h // 2, h)) for _ in range(rng.randint(3, 6))]
            px.polygon(pts, fill=tuple(rng.randint(0, 200) for _ in range(3)))
        for _ in range(rng.randint(0, 4)):
            x, y = rng.randint(0, w - 60), rng.randint(h // 3, h - 60)
            px.rectangle([x, y, x + rng.randint(30, 160), y + rng.randint(30, 120)],
                         fill=tuple(rng.randint(0, 255) for _ in range(3)))
        noise = Image.effect_noise((w, h), rng.randint(10, 40)).convert("RGB")
        img = Image.blend(img, noise, 0.12).filter(ImageFilter.GaussianBlur(rng.random() * 1.2))
        img.save(os.path.join(folder, f"IMG_2024{rng.randint(1, 12):02d}{rng.randint(1, 28):02d}_{i:05d}.jpg"),
                 quality=rng.randint(80, 92))
    return n


def make_text_images(root, n, seed=13):
    """n screenshots / scans with real words in them, for OCR. Returns the number made (0 without Pillow)."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return 0
    rng = random.Random(seed)
    folder = os.path.join(root, "Pictures", "Screenshots")
    os.makedirs(folder, exist_ok=True)
    font_path = os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "arial.ttf")
    for i in range(n):
        size = rng.choice((22, 28, 34))
        try:
            font = ImageFont.truetype(font_path, size)
        except OSError:
            font = ImageFont.load_default()
        img = Image.new("RGB", (1100, 60 + 9 * (size + 12)), (250, 250, 248))
        d = ImageDraw.Draw(img)
        for k in range(9):
            d.text((40, 30 + k * (size + 12)), _text(rng, rng.randint(5, 9)).capitalize(), fill=(20, 20, 30), font=font)
        img.save(os.path.join(folder, f"Screenshot {2024 + i % 2}-{rng.randint(1, 12):02d}-{i:04d}.png"))
    return n


# ---------- GPU per process (PDH) ----------
class _PdhValue(ctypes.Structure):
    _fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]


class _PdhItem(ctypes.Structure):
    _fields_ = [("szName", wintypes.LPWSTR), ("FmtValue", _PdhValue)]


class GpuByPid:
    """Sum of every GPU engine's utilisation per process id, from the "GPU Engine" counters. {} if unavailable."""

    def __init__(self):
        self.pdh = None
        try:
            pdh = ctypes.WinDLL("pdh")
            q, c = ctypes.c_void_p(), ctypes.c_void_p()
            if pdh.PdhOpenQueryW(None, None, ctypes.byref(q)) != 0:
                return
            if pdh.PdhAddEnglishCounterW(q, "\\GPU Engine(*)\\Utilization Percentage", None, ctypes.byref(c)) != 0:
                return
            pdh.PdhCollectQueryData(q)
            self.pdh, self.q, self.c = pdh, q, c
        except OSError:
            pass

    def read(self):
        if self.pdh is None or self.pdh.PdhCollectQueryData(self.q) != 0:
            return {}
        size, count = wintypes.DWORD(0), wintypes.DWORD(0)
        self.pdh.PdhGetFormattedCounterArrayW(self.c, 0x200, ctypes.byref(size), ctypes.byref(count), None)
        if not size.value:
            return {}
        buf = ctypes.create_string_buffer(size.value)
        if self.pdh.PdhGetFormattedCounterArrayW(self.c, 0x200, ctypes.byref(size), ctypes.byref(count), buf) != 0:
            return {}
        items = ctypes.cast(buf, ctypes.POINTER(_PdhItem))
        out = {}
        for i in range(count.value):
            name, v = items[i].szName or "", items[i].FmtValue
            if v.CStatus in (0, 1) and name.startswith("pid_"):
                try:
                    pid = int(name[4:].split("_", 1)[0])
                except ValueError:
                    continue
                out[pid] = out.get(pid, 0.0) + v.doubleValue
        return out


# ---------- priorities per process ----------
class _Throttle(ctypes.Structure):
    _fields_ = [("Version", wintypes.DWORD), ("ControlMask", wintypes.DWORD), ("StateMask", wintypes.DWORD)]


_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.OpenProcess.restype = wintypes.HANDLE
_k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.GetProcessInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]


def priorities(p):
    """(eco 0/1, memory priority 0-5, I/O priority 0-3) of one process; "" where it can't be read."""
    eco = mem = ""
    h = _k32.OpenProcess(0x1000, False, p.pid)            # PROCESS_QUERY_LIMITED_INFORMATION
    if h:
        try:
            m = wintypes.ULONG()
            if _k32.GetProcessInformation(h, 0, ctypes.byref(m), 4):          # ProcessMemoryPriority
                mem = m.value
            t = _Throttle(1, 0, 0)
            if _k32.GetProcessInformation(h, 4, ctypes.byref(t), ctypes.sizeof(t)):   # ProcessPowerThrottling
                eco = int(bool(t.ControlMask & t.StateMask & 1))
        finally:
            _k32.CloseHandle(h)
    try:
        io = int(p.ionice())
    except (psutil.Error, OSError, ValueError):
        io = ""
    return eco, mem, io


# ---------- sampling ----------
class Sampler(threading.Thread):
    """Once a second: every process in the engine's tree. Rows go to self.rows; self.scenario labels them."""

    def __init__(self, root_pid, run, every=1.0):
        super().__init__(daemon=True, name="sampler")
        self.root = psutil.Process(root_pid)
        self.run_name, self.every = run, every
        self.scenario = "cold_start"
        self.rows, self.seen = [], {}          # seen: pid -> create_time (only these may ever be stopped)
        self._halt = threading.Event()
        self._last = {}                        # pid -> (t, cpu_s, read, write)
        self.gpu = GpuByPid()
        self.t0 = time.monotonic()
        self.names = {}                        # pid -> the engine's own name for it (status_full), see Watcher

    def tree(self):
        try:
            procs = [self.root] + self.root.children(recursive=True)
        except psutil.Error:
            return []
        for p in procs:
            try:
                self.seen.setdefault(p.pid, p.create_time())
            except psutil.Error:
                pass
        return procs

    def run(self):
        while not self._halt.is_set():
            self.sample()
            self._halt.wait(self.every)

    def stop(self):
        self._halt.set()

    def sample(self):
        now = time.monotonic()
        gpu = self.gpu.read()
        for p in self.tree():
            try:
                with p.oneshot():
                    mem, cpu, io = p.memory_info(), p.cpu_times(), p.io_counters()
                    row = {"run": self.run_name, "scenario": self.scenario, "t": round(now - self.t0, 2),
                           "pid": p.pid, "role": self.names.get(p.pid) or role(p, self.root.pid), "ws_mb": round(mem.rss / MB, 1),
                           "private_mb": round(mem.private / MB, 1), "handles": p.num_handles(),
                           "threads": p.num_threads(), "gpu_pct": round(gpu.get(p.pid, 0.0), 1)}
                row["eco"], row["mem_prio"], row["io_prio"] = priorities(p)
            except psutil.Error:
                continue
            cpu_s = cpu.user + cpu.system
            last = self._last.get(p.pid)
            self._last[p.pid] = (now, cpu_s, io.read_bytes, io.write_bytes)
            if last and now > last[0]:
                dt = now - last[0]
                row["cpu_pct"] = round((cpu_s - last[1]) / dt * 100, 1)       # of one core
                row["read_mb_s"] = round((io.read_bytes - last[2]) / dt / MB, 3)
                row["write_mb_s"] = round((io.write_bytes - last[3]) / dt / MB, 3)
            else:
                row.update(cpu_pct=0.0, read_mb_s=0.0, write_mb_s=0.0)
            self.rows.append(row)


def role(p, root_pid):
    if p.pid == root_pid:
        return "Main"
    try:
        name, cmd = p.name().lower(), " ".join(p.cmdline())
    except psutil.Error:
        return "?"
    if "--multiprocessing-fork" in cmd:
        return "worker"
    return name.rsplit(".", 1)[0]


# ---------- the pipe client ----------
class Pipe:
    """The smallest UI: JSON-RPC lines over the engine's pipe. Events are counted and skipped."""

    def __init__(self, name, timeout=20):
        deadline = time.monotonic() + timeout
        while True:
            try:
                self.f = open(name, "r+b", buffering=0)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.05)
        self.buf, self.n, self.events = b"", 0, 0

    def _line(self):
        while b"\n" not in self.buf:
            data = self.f.read(65536)
            if not data:
                raise EOFError("pipe closed")
            self.buf += data
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line)

    def call(self, method, params=None):
        self.n += 1
        msg = {"jsonrpc": "2.0", "id": self.n, "method": method}
        if params is not None:
            msg["params"] = params
        self.f.write((json.dumps(msg) + "\n").encode())
        while True:
            m = self._line()
            if m.get("id") == self.n:
                if "error" in m:
                    raise RuntimeError(f"{method}: {m['error']}")
                return m["result"]
            self.events += 1

    def close(self):
        try:
            self.f.close()
        except OSError:
            pass


class Watcher(threading.Thread):
    """A second pipe connection that asks status_full every `every` s (what the Indexing page does): process
    names for the sampler, the phase timeline (for files/s per phase) and which models are loaded."""

    def __init__(self, name, sampler, every=2.0):
        super().__init__(daemon=True, name="watcher")
        self.pipe, self.sampler, self.every = Pipe(name), sampler, every
        self.timeline, self.last = [], {}
        self.halt = threading.Event()

    def run(self):
        while not self.halt.is_set():
            try:
                st = self.pipe.call("status_full")
            except (OSError, EOFError, RuntimeError, ValueError):
                return
            for pr in (st.get("resources") or {}).get("processes") or []:
                self.sampler.names[pr["pid"]] = pr["name"]
            self.last = st
            self.timeline.append({"t": round(time.monotonic() - self.sampler.t0, 1), "phase": st.get("phase"),
                                  "scenario": self.sampler.scenario, "texts": st.get("texts", 0),
                                  "vectors": (st.get("vectors") or 0), "photos": st.get("photos", 0) or 0,
                                  "photo_vectors": st.get("photo_vectors", 0) or 0,
                                  "models": ",".join(st.get("models_loaded") or [])})
            self.halt.wait(self.every)

    def stop(self):
        self.halt.set()
        self.pipe.close()


def phase_rates(timeline):
    """[(phase, seconds, items, items/s)] from the watcher's timeline: texts for text/images, vectors for
    meaning, photo vectors for photos."""
    key = {"text": "texts", "images": "texts", "meaning": "vectors", "photos": "photos"}
    out, start = [], None
    for a, b in zip(timeline, timeline[1:] + [None]):
        if start is None:
            start = a
        if b is None or b["phase"] != a["phase"]:
            end = b or a
            k = key.get(a["phase"])
            if k and a["scenario"].startswith("indexing"):
                secs = max(0.1, end["t"] - start["t"])
                n = (end.get(k) or 0) - (start.get(k) or 0)
                out.append((a["phase"], round(secs, 1), n, round(n / secs, 1)))
            start = None
    return out


def pipe_base():
    sys.path.insert(0, APP_DIR)
    from nobadfind.rpc.server import pipe_name
    return pipe_name()


# ---------- one run ----------
def settings_for(corpus, models=False):
    return {"roots": [corpus], "semantic": models, "photo_meaning": models, "ocr": True,
            "allow_model_download": models, "allow_photo_model_download": models, "bar": False,
            "hotkey": "ctrl+alt+shift+f9", "keep_background": False, "autostart": False, "bg_notice_seen": True}


MODEL_SUBDIRS = ("model", "photo-model")       # const.MODEL_DIR and photo.PHOTO_DIR inside a data folder


def place_models(cache, data):
    """Hard-link (or copy) the downloaded models from the cache data folder into a fresh one."""
    for sub in MODEL_SUBDIRS:
        src, dst = os.path.join(cache, sub), os.path.join(data, sub)
        os.makedirs(dst, exist_ok=True)
        for name in os.listdir(src):
            if name.endswith(".part"):
                continue
            try:
                os.link(os.path.join(src, name), os.path.join(dst, name))
            except OSError:
                shutil.copy2(os.path.join(src, name), os.path.join(dst, name))


TEXT_QUERIES = ("notes about the budget meeting", "tax receipt", "holiday travel plan", "guitar lesson")
PHOTO_QUERIES = ("sunset over the sea", "snowy mountains", "red barn in a field", "city at night")


def timed_search(pipe, text, level, kind, searches):
    t = time.perf_counter()
    r = pipe.call("search", {"text": text})
    searches.append({"run": level, "kind": kind, "query": text,
                     "rt_ms": round((time.perf_counter() - t) * 1000, 2), "engine_ms": r.get("ms"),
                     "results": len(r.get("results") or []),
                     "top": (r.get("results") or [{}])[0].get("name", "")})
    return r


def type_query(pipe, q, level, kind, searches):
    for i in range(1, len(q) + 1):                # typed one letter at a time, like the box sends them
        timed_search(pipe, q[:i], level, kind, searches)
        time.sleep(0.12)


def wait_models(watcher, loaded, timeout):
    """Wait until models are (loaded=True) or aren't (False) in the engine's memory. Seconds waited."""
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        time.sleep(1)
        if bool(watcher.last.get("models_loaded")) == loaded:
            break
    return round(time.monotonic() - t, 1)


def run_level(level, corpus, work, full, args, searches):
    tag = f"{level}-{os.getpid()}"
    data = os.path.join(work, f"data-{level}")
    shutil.rmtree(data, ignore_errors=True)
    os.makedirs(data)
    with open(os.path.join(data, "settings.json"), "w", encoding="utf-8") as f:
        json.dump(settings_for(corpus, bool(args.models)), f)
    if args.models:
        place_models(args.models, data)
    env = dict(os.environ, NOBAD_FIND_DATA_DIR=data, NOBAD_FIND_MEASURE_LEVEL=level, NOBAD_FIND_MEASURE_PIPE=tag)
    env.pop("NOBAD_FIND_UI_DEMO", None)
    if args.entry == "launch":
        env["PYTHONPATH"] = APP_DIR                    # a script's own folder is on the path, not apps/find
    marks = {"run": level}
    t0 = time.monotonic()
    entry = ["-m", "nobadfind"] if args.entry == "module" else [os.path.join(APP_DIR, "packaging", "launch.py")]
    proc = subprocess.Popen([sys.executable] + entry + ["--engine"], cwd=APP_DIR, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    sampler = Sampler(proc.pid, level, every=args.every)
    sampler.start()
    ready = threading.Event()
    out_lines = []

    def drain():
        for raw in proc.stdout:
            line = raw.decode("utf-8", "replace").rstrip()
            out_lines.append(line)
            if "engine ready" in line:
                marks["ready_s"] = round(time.monotonic() - t0, 2)
                ready.set()
    threading.Thread(target=drain, daemon=True).start()
    pipe = watcher = None
    try:
        if not ready.wait(60):
            raise RuntimeError("engine did not start: " + " | ".join(out_lines[-5:]))
        pipe = Pipe(f"{pipe_base()}-measure-{tag}")
        pipe.call("hello")
        marks["hello_s"] = round(time.monotonic() - t0, 2)
        watcher = Watcher(f"{pipe_base()}-measure-{tag}", sampler)
        watcher.start()
        hold(sampler, "cold_start", max(0.0, 5 - (time.monotonic() - t0)))
        hold(sampler, "idle_no_ui", args.idle)

        sampler.scenario = f"indexing_{level}"
        pipe.call("ui_shown", {"window": "main"})
        t_ix = time.monotonic()
        seen_work, st = False, {}
        while time.monotonic() - t_ix < args.index_timeout:
            time.sleep(1)
            st = pipe.call("status")
            seen_work = seen_work or st.get("phase") not in ("starting", "watching")
            if seen_work and st.get("phase") == "watching":
                break
        full_st = pipe.call("status_full")
        marks.update(index_s=round(time.monotonic() - t_ix, 1), index_phase=st.get("phase"),
                     files=full_st.get("files"), texts=full_st.get("with_text"), chunks=full_st.get("chunks"),
                     errors=full_st.get("errors"), finished=st.get("phase") == "watching")
        if not full:
            return marks
        if not args.models:
            hold(sampler, "idle_ui", args.idle)
            sampler.scenario = "search"
            for q in QUERIES:
                type_query(pipe, q, level, "words", searches)
            pipe.call("ui_hidden", {"window": "main"})
            hold(sampler, "closed", args.closed)
            return marks
        # with the models: loaded and idle, warm searches, released after Lazy.IDLE, cold searches, closed
        sampler.scenario = "search_warm"
        timed_search(pipe, "warm", level, "warm-up", searches)
        for q in TEXT_QUERIES:
            type_query(pipe, q, level, "meaning", searches)
        for q in PHOTO_QUERIES:
            type_query(pipe, q, level, "photo", searches)
        hold(sampler, "idle_ui_models_loaded", args.idle)
        sampler.scenario = "idle_ui_waiting_release"
        marks["release_after_s"] = wait_models(watcher, False, args.release_timeout)
        hold(sampler, "idle_ui_models_released", args.idle)
        sampler.scenario = "search_cold"
        timed_search(pipe, "holiday budget", level, "cold (models load)", searches)
        for q in TEXT_QUERIES[:2]:
            type_query(pipe, q, level, "meaning", searches)
        pipe.call("ui_hidden", {"window": "main"})
        hold(sampler, "closed", 5)
        sampler.scenario = "closed"
        marks["closed_release_s"] = wait_models(watcher, False, 30)
        hold(sampler, "closed", args.closed)
        sampler.scenario = "reopen_cold"
        pipe.call("ui_shown", {"window": "main"})          # the window opens and the user types at once
        timed_search(pipe, "sunset", level, "reopen (models load)", searches)
        hold(sampler, "reopen_cold", 3)
        return marks
    finally:
        sampler.scenario = "quitting"
        if watcher is not None:
            marks["phases"] = phase_rates(watcher.timeline)
            args.timeline.extend(dict(x, run=level) for x in watcher.timeline)
            watcher.stop()
        if pipe is not None:
            try:
                pipe.call("quit", {"confirm": "QUIT"})
            except (OSError, EOFError, RuntimeError):
                pass
            pipe.close()
        try:
            proc.wait(20)
        except subprocess.TimeoutExpired:
            pass
        sampler.stop()
        sampler.join(3)
        stop_ours(sampler.seen)
        sampler.rows_done = True
        args.rows.extend(sampler.rows)


def hold(sampler, scenario, secs):
    sampler.scenario = scenario
    time.sleep(secs)


def stop_ours(seen):
    """End what is still running of the processes this harness started (same pid AND same start time)."""
    for pid, created in seen.items():
        try:
            p = psutil.Process(pid)
            if abs(p.create_time() - created) < 0.01:
                p.kill()
        except psutil.Error:
            pass


# ---------- summary ----------
def summarize(rows):
    """Per (run, scenario): totals over the tree per sample, then mean / max over the samples."""
    by = {}
    for r in rows:
        by.setdefault((r["run"], r["scenario"]), {}).setdefault(r["t"], []).append(r)
    out = []
    for (run, sc), samples in by.items():
        if sc == "quitting":
            continue
        tot = [{"procs": len(ps), "ws": sum(p["ws_mb"] for p in ps), "priv": sum(p["private_mb"] for p in ps),
                "cpu": sum(p["cpu_pct"] for p in ps), "rd": sum(p["read_mb_s"] for p in ps),
                "wr": sum(p["write_mb_s"] for p in ps), "h": sum(p["handles"] for p in ps),
                "th": sum(p["threads"] for p in ps), "gpu": sum(p["gpu_pct"] for p in ps),
                "eng_ws": sum(p["ws_mb"] for p in ps if p["role"] == "Main"),
                "eng_priv": sum(p["private_mb"] for p in ps if p["role"] == "Main")}
               for _t, ps in sorted(samples.items())]
        if len(tot) > 2 and sc != "cold_start":
            tot = tot[1:]                      # the first sample of a scenario still belongs to the one before

        def mean(k):
            return statistics.fmean(x[k] for x in tot)

        def top(k):
            return max(x[k] for x in tot)
        out.append({"run": run, "scenario": sc, "n": len(tot), "procs": top("procs"),
                    "ws": (mean("ws"), top("ws")), "priv": (mean("priv"), top("priv")),
                    "eng": (mean("eng_ws"), mean("eng_priv")),
                    "cpu": (mean("cpu"), top("cpu")), "rd": mean("rd"), "wr": mean("wr"), "h": top("h"),
                    "th": top("th"), "gpu": top("gpu")})
    return out


def by_role(rows):
    """Per (run, scenario, role): processes alive at once, private / working set mean and max per process, handles."""
    acc = {}
    for r in rows:
        if r["scenario"] == "quitting":
            continue
        role = r["role"]
        acc.setdefault((r["run"], r["scenario"], role), []).append(r)
    out = []
    for (run, sc, role), rs in acc.items():
        per_t = {}
        for r in rs:
            per_t.setdefault(r["t"], []).append(r)
        out.append({"run": run, "scenario": sc, "role": role, "at_once": max(len(v) for v in per_t.values()),
                    "pids": len({r["pid"] for r in rs}),
                    "priv": (statistics.fmean(r["private_mb"] for r in rs), max(r["private_mb"] for r in rs)),
                    "ws": (statistics.fmean(r["ws_mb"] for r in rs), max(r["ws_mb"] for r in rs)),
                    "h": round(statistics.fmean(r["handles"] for r in rs)),
                    "cpu": statistics.fmean(r["cpu_pct"] for r in rs)})
    return out


def pct(vals, p):
    vals = sorted(vals)
    return vals[min(len(vals) - 1, int(round(p / 100 * (len(vals) - 1))))] if vals else 0


def report(summary, marks, searches, meta):
    lines = [f"Commit `{meta['commit']}`, {meta['pc']}, corpus {meta['files']} files ({meta['corpus']}), "
             f"entry `{meta['entry']}`, samples every {meta['every']} s. CPU % is of one core (100 = one full core), summed over the tree.", "",
             "| Run | Scenario | Samples | Procs | Working set MB (mean / max) | Private MB (mean / max) | "
             "Engine process WS / private MB | CPU % (mean / max) | Read / write MB/s | Handles | Threads | GPU % max |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in summary:
        lines.append(f"| {s['run']} | {s['scenario']} | {s['n']} | {s['procs']} | {s['ws'][0]:.0f} / {s['ws'][1]:.0f} "
                     f"| {s['priv'][0]:.0f} / {s['priv'][1]:.0f} | {s['eng'][0]:.0f} / {s['eng'][1]:.0f} "
                     f"| {s['cpu'][0]:.1f} / {s['cpu'][1]:.1f} | {s['rd']:.2f} / {s['wr']:.2f} | {s['h']} "
                     f"| {s['th']} | {s['gpu']:.1f} |")
    lines += ["", "| Run | Engine ready s | First pipe answer s | Indexing s | Finished | Files | With text | "
              "Chunks | Errors |", "|---|---|---|---|---|---|---|---|---|"]
    for m in marks:
        lines.append(f"| {m.get('run')} | {m.get('ready_s', '')} | {m.get('hello_s', '')} | {m.get('index_s', '')} "
                     f"| {m.get('finished', '')} | {m.get('files', '')} | {m.get('texts', '')} | {m.get('chunks', '')} "
                     f"| {m.get('errors', '')} |")
    lines += ["", "Every process (per process: private and working set mean / max, handles mean, CPU % mean):", "",
              "| Run | Scenario | Process | At once (pids) | Private MB | Working set MB | Handles | CPU % |",
              "|---|---|---|---|---|---|---|---|"]
    for r in sorted(meta.get("roles", []), key=lambda r: (r["run"], r["scenario"], r["role"])):
        lines.append(f"| {r['run']} | {r['scenario']} | {r['role']} | {r['at_once']} ({r['pids']}) "
                     f"| {r['priv'][0]:.0f} / {r['priv'][1]:.0f} | {r['ws'][0]:.0f} / {r['ws'][1]:.0f} | {r['h']} "
                     f"| {r['cpu']:.1f} |")
    phases = [(m["run"], ph) for m in marks for ph in m.get("phases") or []]
    if phases:
        lines += ["", "| Run | Phase | Seconds | Items | Items/s |", "|---|---|---|---|---|"]
        lines += [f"| {run} | {ph[0]} | {ph[1]} | {ph[2]} | {ph[3]} |" for run, ph in phases]
    kinds = sorted({s.get("kind", "words") for s in searches})
    if len(kinds) > 1:
        lines += ["", "| Run | Search | Keystrokes | p50 ms | p90 ms | max ms | engine p50 / max |", "|---|---|---|---|---|---|---|"]
        for run in sorted({s["run"] for s in searches}):
            for k in kinds:
                rt = [s["rt_ms"] for s in searches if s["run"] == run and s.get("kind") == k]
                en = [s["engine_ms"] for s in searches if s["run"] == run and s.get("kind") == k]
                if rt:
                    lines.append(f"| {run} | {k} | {len(rt)} | {pct(rt, 50):.1f} | {pct(rt, 90):.1f} | {max(rt):.1f} "
                                 f"| {pct(en, 50)} / {max(en)} |")
    if searches:
        rt = [s["rt_ms"] for s in searches]
        en = [s["engine_ms"] for s in searches if isinstance(s["engine_ms"], (int, float))]
        lines += ["", f"Search typing over the pipe ({len(rt)} keystrokes, {len(QUERIES)} questions): round trip "
                  f"median {pct(rt, 50):.1f} ms, 90th percentile {pct(rt, 90):.1f} ms, max {max(rt):.1f} ms; "
                  f"engine `ms` median {pct(en, 50)}, 90th {pct(en, 90)}, max {max(en) if en else ''}; "
                  f"over 80 ms: {sum(1 for x in rt if x > 80)}."]
    return "\n".join(lines)


def git_commit():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=APP_DIR, capture_output=True,
                              text=True, timeout=10).stdout.strip() + (
            "+dirty" if subprocess.run(["git", "status", "--porcelain", "--", "nobadfind"], cwd=APP_DIR,
                                       capture_output=True, text=True, timeout=10).stdout.strip() else "")
    except OSError:
        return "?"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--files", type=int, default=3000)
    ap.add_argument("--levels", default="gentle,full,light",
                    help="comma list; the first runs every scenario, the others indexing only")
    ap.add_argument("--idle", type=float, default=20, help="seconds for each idle scenario")
    ap.add_argument("--closed", type=float, default=30, help="seconds with the window closed")
    ap.add_argument("--index-timeout", type=float, default=300)
    ap.add_argument("--every", type=float, default=1.0)
    ap.add_argument("--entry", choices=("module", "launch"), default="module",
                    help="module: python -m nobadfind --engine; launch: packaging/launch.py --engine, which starts "
                         "workers the way NobadFind.exe does (each runs the entry script again)")
    ap.add_argument("--out", default="")
    ap.add_argument("--keep", action="store_true", help="keep the temp corpus and data folders")
    ap.add_argument("--models", default="", help="a data folder with both models downloaded (model/, photo-model/): "
                    "meaning, photo meaning and OCR on, models linked into each run's fresh index")
    ap.add_argument("--photos", type=int, default=0, help="extra camera-style JPEGs (needs Pillow)")
    ap.add_argument("--text-images", type=int, default=0, help="extra screenshots with words, for OCR (Pillow)")
    ap.add_argument("--release-timeout", type=float, default=300, help="seconds to wait for idle models to leave")
    args = ap.parse_args(argv)
    args.rows, args.timeline = [], []
    work = tempfile.mkdtemp(prefix="nobadfind-measure-")
    out = args.out or work
    os.makedirs(out, exist_ok=True)
    corpus = os.path.join(work, "corpus")
    counts = make_corpus(corpus, args.files)
    if args.photos:
        counts["jpg (photos)"] = make_photos(corpus, args.photos)
    if args.text_images:
        counts["png (text)"] = make_text_images(corpus, args.text_images)
    size = sum(os.path.getsize(os.path.join(d, f)) for d, _s, fs in os.walk(corpus) for f in fs)
    print(f"corpus: {args.files} files, {size / MB:.1f} MB in {corpus}", flush=True)
    marks, searches = [], []
    levels = [x.strip() for x in args.levels.split(",") if x.strip()]
    try:
        for i, level in enumerate(levels):
            print(f"run {level} ...", flush=True)
            marks.append(run_level(level, corpus, work, i == 0, args, searches))
            print(f"  {marks[-1]}", flush=True)
    finally:
        if args.rows:
            with open(os.path.join(out, "samples.csv"), "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(args.rows[0]))
                w.writeheader()
                w.writerows(args.rows)
        if args.timeline:
            with open(os.path.join(out, "timeline.csv"), "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(args.timeline[0]))
                w.writeheader()
                w.writerows(args.timeline)
        if searches:
            with open(os.path.join(out, "searches.csv"), "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(searches[0]))
                w.writeheader()
                w.writerows(searches)
    meta = {"commit": git_commit(), "pc": f"{os.cpu_count()} threads, {psutil.virtual_memory().total / 2**30:.1f} GB",
            "files": args.files, "corpus": ", ".join(f"{v} {k}" for k, v in sorted(counts.items())),
            "every": args.every, "entry": args.entry, "roles": by_role(args.rows)}
    text = report(summarize(args.rows), marks, searches, meta)
    with open(os.path.join(out, "summary.md"), "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(text)
    print(f"\nfiles in {out}")
    if not args.keep:
        shutil.rmtree(corpus, ignore_errors=True)
        for level in levels:
            shutil.rmtree(os.path.join(work, f"data-{level}"), ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
