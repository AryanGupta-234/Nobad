"""Windows toast notifications (tray balloon when the tray exists, PowerShell toast otherwise)."""
import base64
import os
import threading
import time

from .ctx import ctx
from .logbus import broadcast
from .syscmd import run

_last = {}
_lock = threading.Lock()
_POWERSHELL_APPID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"


def _toast_ps(title, msg):
    t = title.replace("'", "''")
    m = msg.replace("'", "''")
    return (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null;"
        "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        "$x=$t.GetElementsByTagName('text');"
        f"$x.Item(0).AppendChild($t.CreateTextNode('{t}'))|Out-Null;"
        f"$x.Item(1).AppendChild($t.CreateTextNode('{m}'))|Out-Null;"
        "$n=[Windows.UI.Notifications.ToastNotification]::new($t);"
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{_POWERSHELL_APPID}').Show($n)")


def toast(title, msg):
    """Fire-and-forget PowerShell toast with no dependency on app state (used by the watchdog too)."""
    if os.name != "nt":
        return False

    def go():
        enc = base64.b64encode(_toast_ps(title, msg).encode("utf-16-le")).decode()
        run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", enc], timeout=15)

    threading.Thread(target=go, daemon=True).start()
    return True


def notify(title, msg, kind="info", level="info"):
    """Rate-limited (same kind at most once per 5 s). Also pushes an in-app toast."""
    broadcast("notify", {"title": title, "msg": msg, "kind": kind, "level": level})
    s = ctx.settings
    if s is not None and not s.get("notifications"):
        return False
    now = time.time()
    with _lock:
        if now - _last.get(kind, 0) < 5:
            return False
        _last[kind] = now
    tray = ctx.tray
    if tray is not None and tray.available and tray.notify(title, msg):
        return True
    return toast(title, msg)
