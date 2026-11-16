"""Config files on disk: list, view (keys hidden), validated save, delete, import (file / URL / QR text),
and the DPAPI encrypt-at-rest migration."""
import os
import re
import urllib.parse
import urllib.request

from . import confparse, dpapi
from .confparse import EXT_ENC, EXT_PLAIN, KEY_MASK
from .const import NAME_RE
from .ctx import ctx
from .engine import config_dir, ensure_dirs
from .logbus import log
from .syscmd import spawn

MAX_BYTES = 100_000


def _safe(name):
    """Only plain config names (NAME_RE) may become paths — rejects '..', separators, drive letters, etc."""
    name = str(name or "")
    return name if NAME_RE.fullmatch(name) and name.strip(".") == name and ".." not in name else None


def _find(name):
    name = _safe(name)
    if not name:
        return None
    d = config_dir()
    for ext in (EXT_ENC, EXT_PLAIN):
        p = os.path.join(d, name + ext)
        if os.path.exists(p):
            return p
    return None


def clean_name(raw):
    name = str(raw or "").strip()
    name = re.sub(r"\.dpapi$", "", name, flags=re.I)
    name = re.sub(r"\.conf$", "", name, flags=re.I)
    name = re.sub(r"[^A-Za-z0-9_=+.\-]", "_", name)
    name = re.sub(r"\.{2,}", "_", name)[:32].strip(".")
    return name


def read(name):
    p = _find(name)
    if not p:
        return {"ok": False, "error": "unknown config"}
    try:
        text = confparse.read_conf_text(p)
    except (OSError, dpapi.DpapiError) as e:
        return {"ok": False, "error": f"can't read this config: {e}"}
    return {"ok": True, "name": name, "text": confparse.redact_conf(text), "encrypted": confparse.is_encrypted(p),
            "validation": {k: v for k, v in confparse.validate_conf(text).items() if k != "info"}}


def validate(name, text):
    """Live validation for the editor (keys shown as (hidden) are restored first)."""
    p = _find(name) if name else None
    if p:
        try:
            text = confparse.restore_masked(text, confparse.read_conf_text(p))
        except (OSError, dpapi.DpapiError):
            pass
    r = confparse.validate_conf(text)
    return {"ok": True, "valid": r["ok"], "errors": r["errors"], "warnings": r["warnings"]}


def _want_encrypted(existing_enc=None):
    s = ctx.settings
    if s.get("encrypt_configs") and dpapi.available():
        return True
    return bool(existing_enc) and dpapi.available()


def save(name, text, create=False, untrusted=False):
    ensure_dirs()
    name = clean_name(name)
    if not name:
        return {"ok": False, "error": "file name must be 1–32 chars: letters, digits, _ = + . -"}
    old = _find(name)
    if create and old:
        return {"ok": False, "error": f"{name} already exists"}
    if not create and not old:
        return {"ok": False, "error": "unknown config"}
    text = str(text or "")
    if len(text.encode("utf-8", "replace")) > MAX_BYTES:
        return {"ok": False, "error": "config is too large"}
    if old and not create:
        try:
            text = confparse.restore_masked(text, confparse.read_conf_text(old))
        except (OSError, dpapi.DpapiError):
            pass
    if KEY_MASK in text:
        return {"ok": False, "error": "a key is still shown as (hidden) — paste the real key or leave the line untouched"}
    res = confparse.validate_conf(text, untrusted_source=untrusted)
    if not res["ok"]:
        return {"ok": False, "error": res["errors"][0], "errors": res["errors"], "warnings": res["warnings"]}
    enc = _want_encrypted(old is not None and confparse.is_encrypted(old))
    path = os.path.join(config_dir(), name + (EXT_ENC if enc else EXT_PLAIN))
    try:
        confparse.write_conf_text(path, text, encrypted=enc)
    except (OSError, dpapi.DpapiError) as e:
        return {"ok": False, "error": f"couldn't write the config: {e}"}
    if old and os.path.abspath(old) != os.path.abspath(path):
        dpapi.wipe_and_remove(old)
    ctx.tunnel.rescan()
    ctx.tunnel.push()
    spawn(ctx.tunnel.geo_refresh)
    log(("imported " if create else "saved ") + name + (" (encrypted)" if enc else ""), "ok")
    note = "Reconnect to apply the change." if (ctx.tunnel.active == name and ctx.tunnel.connected) else ""
    return {"ok": True, "name": name, "warnings": res["warnings"], "note": note}


def import_text(name, content, untrusted=False):
    return save(name, content, create=True, untrusted=untrusted)


INBOX_MAX = 64 * 1024
DOWNLOADS_DAYS = 14          # only recent downloads are offered
_PROTON = re.compile(r"#\s*([A-Z]{2}(?:-[A-Z]{2})?)-FREE#(\d{1,4})")
COUNTRY_HINT = {"JP": "Japan", "US": "United States", "NL": "Netherlands", "PL": "Poland", "RO": "Romania",
                "MX": "Mexico", "CA": "Canada", "NO": "Norway", "SG": "Singapore", "CH": "Switzerland"}


def _downloads_dir():
    from .const import known_folder
    d = known_folder("Downloads") if os.name == "nt" else os.path.expanduser("~/Downloads")
    return d if d and os.path.isdir(d) else None


def _read_small(path):
    """Read a file from a user-writable folder: no links, no folders, at most INBOX_MAX bytes. None if refused."""
    from .syscmd import _is_reparse
    if _is_reparse(path) or not os.path.isfile(path):
        return None
    with open(path, "rb") as f:
        raw = f.read(INBOX_MAX + 1)
    if len(raw) > INBOX_MAX:
        return None
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def _suggest_name(fn, text):
    m = _PROTON.search(text)
    return clean_name(f"{m.group(1)}-FREE-{m.group(2)}") if m else clean_name(fn)


def downloads_scan(now=None):
    """WireGuard configs downloaded in the last DOWNLOADS_DAYS days (top level of the Downloads folder), each with a
    suggested name, the server it connects to and whether NOBAD already has that server. Read-only: the Downloads
    folder belongs to the user, so nothing there is written, moved or deleted."""
    import time as _t
    from .syscmd import _is_reparse
    d = _downloads_dir()
    if not d or _is_reparse(d):
        return {"ok": True, "folder": d, "files": []}
    now = now or _t.time()
    have = {(r.get("host"), r.get("port")) for r in (getattr(ctx.tunnel, "_regions", None) or [])}
    names = {confparse.stem_of(f) for f in os.listdir(config_dir())} if os.path.isdir(config_dir()) else set()
    out = []
    try:
        entries = sorted(os.scandir(d), key=lambda e: -e.stat().st_mtime)[:400]
    except OSError:
        return {"ok": True, "folder": d, "files": []}
    for e in entries:
        if not e.name.lower().endswith(EXT_PLAIN) or now - e.stat().st_mtime > DOWNLOADS_DAYS * 86400:
            continue
        try:
            text = _read_small(e.path)
        except OSError:
            text = None
        if not text or "[Interface]" not in text or "[Peer]" not in text:
            continue
        info = confparse.parse_conf_text(text)
        if not info.get("host"):
            continue
        m = _PROTON.search(text)
        name = _suggest_name(e.name, text)
        out.append({"file": e.name, "name": name, "host": info["host"], "port": info.get("port"),
                    "provider": "Proton VPN Free" if m else None,
                    "country": COUNTRY_HINT.get(m.group(1).split("-")[0]) if m else None,
                    "already": (info["host"], info.get("port")) in have, "name_taken": name in names,
                    "mtime": e.stat().st_mtime})
        if len(out) >= 40:
            break
    return {"ok": True, "folder": d, "files": out}


def downloads_import(files):
    """Import the chosen files from Downloads like any picked file (validated, no script hooks). Returns per-file
    results; servers NOBAD already has are skipped."""
    d = _downloads_dir()
    if not d or not isinstance(files, list):
        return {"ok": False, "error": "Downloads folder not found"}
    scan = {f["file"]: f for f in downloads_scan()["files"]}
    done, errors = [], []
    for fn in [str(x) for x in files[:40]]:
        item = scan.get(fn)
        if not item or os.path.basename(fn) != fn:          # only files the scan offered, by bare name
            errors.append(f"{fn}: not found")
            continue
        if item["already"]:
            errors.append(f"{fn}: you already have this server")
            continue
        try:
            text = _read_small(os.path.join(d, fn))
        except OSError:
            text = None
        if not text:
            errors.append(f"{fn}: couldn't read it")
            continue
        name, n = item["name"] or "server", 2
        while _find(name):
            name = clean_name(f"{item['name']}-{n}")
            n += 1
        r = import_text(name, text, untrusted=True)
        (done if r.get("ok") else errors).append(name if r.get("ok") else f"{fn}: {r.get('error')}")
    if done:
        log(f"imported {len(done)} server(s) from Downloads: {', '.join(done)}", "ok")
    return {"ok": bool(done) or not errors, "imported": done, "errors": errors}


def import_inbox():
    """Rescan: import .conf files the user dropped into the import folder, exactly like a picked file (validated,
    no script hooks). The folder is user-writable, so NOBAD only reads it: links are skipped, nothing there is ever
    written or deleted, and a name that already exists in NOBAD is left alone. Returns {imported, skipped, errors}."""
    from .const import INBOX_DIR
    from .syscmd import _is_reparse
    out = {"imported": [], "skipped": [], "errors": []}
    if not os.path.isdir(INBOX_DIR) or _is_reparse(INBOX_DIR):
        return out
    have = {confparse.stem_of(f) for f in os.listdir(config_dir())} if os.path.isdir(config_dir()) else set()
    for fn in sorted(os.listdir(INBOX_DIR))[:200]:
        p = os.path.join(INBOX_DIR, fn)
        stem = confparse.stem_of(fn) if fn.lower().endswith(EXT_PLAIN) else None
        if not stem or _is_reparse(p) or not os.path.isfile(p):
            continue
        if stem in have:
            out["skipped"].append(fn)
            continue
        try:
            with open(p, "rb") as f:
                raw = f.read(INBOX_MAX + 1)
            if len(raw) > INBOX_MAX:
                raise ValueError("file too large")
            r = import_text(stem, raw.decode("utf-8-sig"), untrusted=True)
        except (OSError, ValueError) as e:
            r = {"ok": False, "error": str(e)}
        (out["imported"] if r.get("ok") else out["errors"]).append(fn if r.get("ok") else f"{fn}: {r.get('error')}")
        have.add(stem)
    return out


def _public_host(host):
    """True if every address `host` resolves to is a public internet address. NOBAD runs as admin, so a link must not
    make it fetch from this PC (its own control server), the local network (router admin pages) or cloud metadata."""
    from . import reach
    ips = reach.system_resolve(host) if host else []
    return bool(ips) and not any(reach.bogus(ip) for ip in ips)


def import_url(url, name=None):
    url = str(url or "").strip()
    u = urllib.parse.urlparse(url)
    if u.scheme != "https" or not u.netloc or not u.hostname:
        return {"ok": False, "error": "only https:// links can be imported"}
    if not _public_host(u.hostname):
        return {"ok": False, "error": "that link points to this PC or a local network address — download the file "
                                      "and import it instead"}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NobadVPN"})
        with urllib.request.urlopen(req, timeout=10) as r:   # redirects to http:// are refused (reach.py)
            final = urllib.parse.urlparse(r.geturl() if hasattr(r, "geturl") else url)
            if final.scheme != "https" or not _public_host(final.hostname):
                return {"ok": False, "error": "the link redirected somewhere NOBAD won't download from"}
            raw = r.read(MAX_BYTES + 1)
    except Exception as e:
        return {"ok": False, "error": f"download failed: {type(e).__name__}"}
    if len(raw) > MAX_BYTES:
        return {"ok": False, "error": "that file is too large to be a WireGuard config"}
    text = raw.decode("utf-8", "replace")
    nm = name or os.path.basename(u.path) or u.hostname or "imported"
    # configs fetched from the network may not carry command hooks
    return import_text(nm, text, untrusted=True)


def delete(name):
    if not _safe(name):
        return {"ok": False, "error": "unknown config"}
    if ctx.tunnel.connected and ctx.tunnel.active == name:
        return {"ok": False, "error": "disconnect from this server before deleting it"}
    removed = False
    for ext in (EXT_ENC, EXT_PLAIN):
        p = os.path.join(config_dir(), name + ext)
        if os.path.exists(p):
            dpapi.wipe_and_remove(p)
            removed = True
    if not removed:
        return {"ok": False, "error": "unknown config"}
    ctx.tunnel.rescan()
    ctx.tunnel.push()
    log(f"deleted {name}", "warn")
    return {"ok": True}


def set_encryption(on):
    """Convert every stored config. Returns counts; never leaves a config half-converted."""
    if on and not dpapi.available():
        return {"ok": False, "error": "Windows DPAPI isn't available on this system"}
    ensure_dirs()
    done = failed = 0
    d = config_dir()
    for fn in sorted(os.listdir(d)):
        stem = confparse.stem_of(fn)
        if not stem:
            continue
        src = os.path.join(d, fn)
        is_enc = confparse.is_encrypted(src)
        if is_enc == bool(on):
            continue
        dst = os.path.join(d, stem + (EXT_ENC if on else EXT_PLAIN))
        try:
            text = confparse.read_conf_text(src)
            confparse.write_conf_text(dst, text, encrypted=bool(on))
            if confparse.read_conf_text(dst) != text.replace("\r\n", "\n").replace("\n", "\r\n") + \
                    ("" if text.endswith(("\n", "\r\n")) else "\r\n"):
                raise OSError("verification failed")
            dpapi.wipe_and_remove(src)
            done += 1
        except Exception as e:
            failed += 1
            log(f"couldn't convert {fn}: {e}", "bad")
            if os.path.exists(dst) and os.path.exists(src):
                dpapi.wipe_and_remove(dst)
    ctx.tunnel.rescan()
    ctx.tunnel.push()
    log(f"config encryption {'on' if on else 'off'}: converted {done}, failed {failed}", "ok" if not failed else "warn")
    return {"ok": failed == 0, "converted": done, "failed": failed}
