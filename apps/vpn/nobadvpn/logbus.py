"""Event bus (SSE fan-out), in-memory log ring and the rotating log file."""
import collections
import json
import logging
import os
import queue
import re
import threading
import time

_subs = []
_subs_lock = threading.Lock()
_log_ring = collections.deque(maxlen=200)
_file_logger = None
_LEVELS = {"ok": logging.INFO, "info": logging.INFO, "warn": logging.WARNING, "bad": logging.ERROR}
_SECRET = re.compile(r"((?:private|preshared)key\s*[=:]\s*)\S+", re.I)
# A raw WireGuard key (32 bytes, base64: 43 characters + "="), with no label around it, e.g. inside an exception
# message (#18). Only a value labelled "PublicKey" is kept (it identifies the server and isn't secret).
_RAW_KEY = re.compile(r"(publickey\s*[=:]\s*)?(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{42}[AEIMQUYcgkosw048]=(?![A-Za-z0-9+/=])",
                      re.I)


def scrub(text):
    """Never let key material reach a log, a toast, a crash report or a diagnostics bundle."""
    return _RAW_KEY.sub(lambda m: m.group(0) if m.group(1) else "(hidden key)", _SECRET.sub(r"\1(hidden)", str(text)))


def has_subscribers():
    return bool(_subs)


def broadcast(kind, payload):
    msg = json.dumps({"type": kind, "payload": payload})
    with _subs_lock:
        for q in list(_subs):
            try:
                q.put_nowait(msg)
            except queue.Full:
                pass


def subscribe(maxsize=300):
    q = queue.Queue(maxsize=maxsize)
    with _subs_lock:
        _subs.append(q)
    return q


def unsubscribe(q):
    with _subs_lock:
        if q in _subs:
            _subs.remove(q)


def init_file_logging(directory, max_bytes=1_000_000, backups=5):
    """Rotating log in ProgramData (1 MB x 6 files). Safe to call twice."""
    global _file_logger
    if _file_logger is not None:
        return _file_logger
    try:
        os.makedirs(directory, exist_ok=True)
        lg = logging.getLogger("nobad")
        lg.setLevel(logging.INFO)
        lg.propagate = False
        from logging.handlers import RotatingFileHandler   # lazy: pulls in socket/pickle
        h = RotatingFileHandler(os.path.join(directory, "nobad.log"), maxBytes=max_bytes,
                                                 backupCount=backups, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
        lg.addHandler(h)
        _file_logger = lg
    except OSError:
        _file_logger = None
    return _file_logger


def log(msg, level="info"):
    msg = scrub(msg)
    entry = {"ts": time.strftime("%H:%M:%S"), "msg": msg, "level": level}
    _log_ring.append(entry)
    broadcast("log", entry)
    if _file_logger is not None:
        try:
            _file_logger.log(_LEVELS.get(level, logging.INFO), msg)
        except Exception:
            pass


def recent_log():
    return list(_log_ring)
