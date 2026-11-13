"""Change journal for Windows network settings NOBAD alters OUTSIDE its own tunnel services and firewall rules.

Today that is adapter DNS (and DNS-over-HTTPS registrations) set by the Network Intelligence fix agent, only after
the user switched the agent on. The ORIGINAL value is written here *before* anything is changed, so every reset path
(in-app reset, Start-menu "Restore internet", `--panic`, uninstall) can put Windows back exactly as it was, even if
NOBAD was killed halfway through a change or is not running at all.

The file lives in ProgramData\\NobadVPN (SYSTEM/Administrators only). Writes are atomic (temp file + replace)."""
import ipaddress
import json
import os
import threading
import time
import uuid

from .const import DATA_DIR
from .logbus import log
from .syscmd import run

JOURNAL_PATH = os.path.join(DATA_DIR, "netchanges.json")
_lock = threading.RLock()


def _load():
    try:
        with open(JOURNAL_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _save(items):
    os.makedirs(os.path.dirname(JOURNAL_PATH), exist_ok=True)
    tmp = JOURNAL_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=1)
    os.replace(tmp, JOURNAL_PATH)


def entries():
    with _lock:
        return _load()


def record(kind, target, before, after, reason, **extra):
    """Write the undo information BEFORE the change is made. Returns the entry id."""
    e = {"id": uuid.uuid4().hex[:12], "kind": kind, "target": target, "before": before, "after": after,
         "reason": reason, "ts": time.time(), "state": "pending", **extra}
    with _lock:
        items = _load()
        items.append(e)
        _save(items)
    return e["id"]


def mark(entry_id, state, **extra):
    with _lock:
        items = _load()
        for e in items:
            if e.get("id") == entry_id:
                e["state"] = state
                e.update(extra)
        _save(items)


def forget(entry_id):
    with _lock:
        _save([e for e in _load() if e.get("id") != entry_id])


# ------------------------------------------------------------------ DNS (per adapter)
def _ps(script, timeout=40):
    return run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout=timeout)


def _is_ip(x):
    try:
        ipaddress.ip_address(str(x))
        return True
    except ValueError:
        return False


def _ps_list(xs):
    return "@(" + ",".join("'" + str(x).replace("'", "''") + "'" for x in xs) + ")"


def dns_snapshot(if_index):
    """What Windows has configured on one adapter right now. `static` lists are the manually set servers
    (empty = automatic/DHCP), read from the registry because Get-DnsClientServerAddress can't tell them apart."""
    script = (
        "$ErrorActionPreference='Stop';"
        f"$a=Get-NetAdapter -InterfaceIndex {int(if_index)};$g=$a.InterfaceGuid;"
        "$v4=(Get-ItemProperty -Path ('HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Tcpip\\Parameters\\Interfaces\\'+$g) -Name NameServer -ErrorAction SilentlyContinue).NameServer;"
        "$v6=(Get-ItemProperty -Path ('HKLM:\\SYSTEM\\CurrentControlSet\\Services\\Tcpip6\\Parameters\\Interfaces\\'+$g) -Name NameServer -ErrorAction SilentlyContinue).NameServer;"
        "[pscustomobject]@{alias=$a.Name;guid=\"$g\";v4=\"$v4\";v6=\"$v6\"}|ConvertTo-Json -Compress")
    r = _ps(script)
    if r.returncode != 0:
        return None
    try:
        d = json.loads((r.stdout or "").strip() or "{}")
    except ValueError:
        return None
    split = lambda s: [x for x in str(s or "").replace(",", " ").split() if x]
    return {"if_index": int(if_index), "alias": d.get("alias"), "guid": d.get("guid"),
            "static_v4": split(d.get("v4")), "static_v6": split(d.get("v6"))}


def _set_dns_script(if_index, servers):
    if servers:
        return f"Set-DnsClientServerAddress -InterfaceIndex {int(if_index)} -ServerAddresses {_ps_list(servers)}"
    return f"Set-DnsClientServerAddress -InterfaceIndex {int(if_index)} -ResetServerAddresses"


def restore_entry(e):
    """Undo one journal entry. Returns (ok, detail). Unknown kinds are left in the journal."""
    if e.get("kind") != "dns":
        return False, f"unknown change type {e.get('kind')!r}"
    b = e.get("before") or {}
    # The journal is a file: everything that reaches PowerShell (run as admin, or SYSTEM in the boot guard) must be
    # an adapter number or an IP address, nothing else.
    try:
        idx = int(b.get("if_index"))
    except (TypeError, ValueError):
        return False, "no valid adapter recorded"
    servers = list(b.get("static_v4") or []) + list(b.get("static_v6") or [])
    doh = list(e.get("doh_added") or [])
    if not all(_is_ip(x) for x in servers + doh):
        return False, "journal entry has an invalid DNS address — not restored"
    parts = ["$ErrorActionPreference='Stop'", _set_dns_script(idx, servers)]
    for srv in doh:   # only DoH registrations NOBAD itself added
        parts.append(f"Remove-DnsClientDohServerAddress -ServerAddress '{ipaddress.ip_address(str(srv))}' "
                     "-ErrorAction SilentlyContinue")    # validated above: an IP address can't break out of the quotes
    parts.append("Clear-DnsClientCache")
    r = _ps(";".join(parts))
    if r.returncode != 0:
        # the adapter may be gone (USB / VPN adapter removed): nothing left to restore
        err = r.stderr or ""
        gone = "ObjectNotFound" in err or ("No MSFT_" in err and "objects found" in err)
        return gone, ("adapter no longer present" if gone else (r.stderr or "failed").strip()[:200])
    return True, f"DNS on {b.get('alias') or idx} restored"


def restore_all():
    """Undo every recorded change, newest first. Entries that were restored (or whose adapter is gone) are
    removed; failures stay so a later reset can retry. Returns a list of {id, ok, detail}."""
    out = []
    with _lock:
        items = _load()
        keep = []
        for e in reversed(items):
            try:
                ok, detail = restore_entry(e) if isinstance(e, dict) else (False, "unreadable entry")
            except Exception as ex:          # one bad entry must not stop the rest of the reset
                ok, detail = False, f"{type(ex).__name__}: {ex}"[:200]
                e = e if isinstance(e, dict) else {}
            out.append({"id": e.get("id"), "ok": ok, "detail": detail, "reason": e.get("reason")})
            if not ok:
                keep.append(e)
        _save(list(reversed(keep)))
    if out:
        log(f"network journal: restored {sum(1 for x in out if x['ok'])} of {len(out)} change(s)",
            "info" if all(x["ok"] for x in out) else "warn")
    return out
