"""A global hotkey (default Win+Shift+Space) that brings NOBAD Find to the front."""
import ctypes
import threading
from ctypes import wintypes

from . import winapi
from .log import log

MODS = {"alt": 0x1, "ctrl": 0x2, "shift": 0x4, "win": 0x8}
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012


def parse(spec):
    """'win+shift+space' -> (modifiers, virtual key) or None."""
    parts = spec.lower().split("+")
    mods = 0
    for p in parts[:-1]:
        if p not in MODS:
            return None
        mods |= MODS[p]
    key = parts[-1]
    if key == "space":
        vk = 0x20
    elif len(key) == 1 and key.isalnum():
        vk = ord(key.upper())
    elif key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 12:
        vk = 0x6F + int(key[1:])
    else:
        return None
    return (mods | MOD_NOREPEAT, vk) if mods else None


class Hotkey:
    def __init__(self, spec, callback):
        self.spec = spec
        self.callback = callback
        self.ok = False
        self._tid = None

    def start(self):
        parsed = parse(self.spec)
        if not winapi.WIN or not parsed:
            return False
        ready = threading.Event()
        threading.Thread(target=self._loop, args=(parsed, ready), daemon=True, name="hotkey").start()
        ready.wait(2)
        return self.ok

    def stop(self):
        if self._tid:
            ctypes.windll.user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)

    def _loop(self, parsed, ready):
        user32 = ctypes.windll.user32
        self._tid = ctypes.windll.kernel32.GetCurrentThreadId()
        self.ok = bool(user32.RegisterHotKey(None, 1, parsed[0], parsed[1]))
        ready.set()
        if not self.ok:
            log(f"hotkey {self.spec} is taken by another app", "warn")
            return
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    try:
                        self.callback()
                    except Exception as e:
                        log(f"hotkey action failed: {type(e).__name__}", "warn")
        finally:
            user32.UnregisterHotKey(None, 1)
