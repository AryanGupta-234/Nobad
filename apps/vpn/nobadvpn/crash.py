"""Crash capture. Reports are ALWAYS saved locally; they are only SENT if the user opted in and a server URL is set.
Reports contain: version, OS, a path-scrubbed traceback and the last log lines (key material scrubbed)."""
import json
import os
import platform
import sys
import threading
import time
import traceback

from .const import APP_VER, CRASH_DIR
from .ctx import ctx
from .logbus import log, recent_log, scrub


def _config_secrets():
    """The real key values in the configs, as a second line of defence after the pattern scrub (#18)."""
    try:
        from .diagnostics import _secret_values
        return _secret_values()
    except Exception:
        return set()


def _scrub_paths(text, secrets=()):
    home = os.path.expanduser("~")
    user = os.environ.get("USERNAME") or os.environ.get("USER") or ""
    text = text.replace(home, "<home>")
    if user and len(user) > 2:
        text = text.replace(user, "<user>")
    for s in secrets:
        if s and len(s) >= 20:
            text = text.replace(s, "(hidden)")
    return scrub(text)


def write_report(exc_type, exc, tb, where="main", fatal=True):
    """fatal=True: the app is going down (shown as "closed unexpectedly"). fatal=False: an exception in a
    background thread the app survived — kept as error-*.json for diagnostics, never shown as a crash."""
    try:
        os.makedirs(CRASH_DIR, exist_ok=True)
        sec = _config_secrets()
        rep = {"app_version": APP_VER, "ts": int(time.time()), "where": where, "os": platform.platform(),
               "python": platform.python_version(),
               "traceback": _scrub_paths("".join(traceback.format_exception(exc_type, exc, tb)), sec),
               "log_tail": [_scrub_paths(f"{e['ts']} {e['level']} {e['msg']}", sec) for e in recent_log()[-40:]]}
        rep["fatal"] = bool(fatal)
        path = os.path.join(CRASH_DIR, f"{'crash' if fatal else 'error'}-{rep['ts']}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=1)
        if not fatal:  # keep the newest 20 non-fatal reports
            old = sorted(f for f in os.listdir(CRASH_DIR) if f.startswith("error-") and f.endswith(".json"))
            for f in old[:-20]:
                try:
                    os.remove(os.path.join(CRASH_DIR, f))
                except OSError:
                    pass
        log(f"{'crash' if fatal else 'error'} report saved: {os.path.basename(path)}", "bad" if fatal else "warn")
        return path
    except Exception:
        return None


def install_hooks():
    prev = sys.excepthook

    def hook(t, e, tb):
        if not issubclass(t, KeyboardInterrupt):
            write_report(t, e, tb, "main")
        prev(t, e, tb)

    sys.excepthook = hook

    def thook(args):
        if args.exc_type is not SystemExit:
            write_report(args.exc_type, args.exc_value, args.exc_traceback,
                         f"thread:{getattr(args.thread, 'name', '?')}", fatal=False)

    threading.excepthook = thook


def pending():
    try:
        return sorted(os.path.join(CRASH_DIR, f) for f in os.listdir(CRASH_DIR)
                      if f.startswith("crash-") and f.endswith(".json"))
    except OSError:
        return []


def preview(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _mark(path, suffix):
    try:
        os.replace(path, path[:-5] + suffix)
    except OSError:
        pass


def dismiss(path):
    _mark(path, ".dismissed")


def send(path):
    url = ctx.settings.get("crash_report_url")
    if not url:
        return False, "No crash-report server is configured. Use Export diagnostics instead."
    try:
        data = json.dumps(preview(path)).encode()
        import urllib.request
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json",
                                                              "User-Agent": "NobadVPN/" + APP_VER})
        with urllib.request.urlopen(req, timeout=10) as r:
            ok = 200 <= r.status < 300
    except Exception as e:
        return False, f"send failed: {type(e).__name__}"
    if ok:
        _mark(path, ".sent")
    return ok, "sent" if ok else "server rejected the report"


def auto_send_if_opted_in():
    if not (ctx.settings.get("crash_reporting") and ctx.settings.get("crash_report_url")):
        return 0
    n = 0
    for p in pending():
        if send(p)[0]:
            n += 1
    return n
