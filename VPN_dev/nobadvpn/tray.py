"""System-tray icon (pystray + Pillow, both optional). Left-click opens the compact window."""
from .ctx import ctx
from .lifecycle import request_quit
from .logbus import log
from .syscmd import spawn

COLORS = {"off": (150, 160, 178), "on": (32, 200, 139), "wait": (255, 154, 124), "block": (255, 90, 110)}


def _state_key():
    t = ctx.tunnel
    if t.connecting:
        return "wait"
    if t.connected:
        return "on"
    if t.ks_active:
        return "block"
    return "off"


class Tray:
    def __init__(self):
        self.available = False
        self.icon = None
        self._pystray = None
        self._Image = None
        self._last_key = None
        try:
            import pystray
            from PIL import Image
            self._pystray, self._Image = pystray, Image
            self.available = True
        except Exception:
            self.available = False

    # ---- image
    def _mark(self, size):
        """The NOBAD 'n' mark, cached; None if the brand file is missing."""
        if getattr(self, "_mark_img", None) is None:
            try:
                import os
                from .const import UI_DIR
                src = self._Image.open(os.path.join(UI_DIR, "brand", "nobad-mark.png")).convert("RGBA")
                self._mark_img = src.resize((size, size), self._Image.LANCZOS)
            except Exception:
                self._mark_img = False
        return self._mark_img or None

    def _image(self, key):
        """NOBAD mark with a status dot (green on, amber connecting, red blocked, grey off)."""
        from PIL import ImageDraw
        size = 64
        mark = self._mark(size)
        img = mark.copy() if mark else self._Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        if not mark:  # fallback: plain orange tile
            d.rounded_rectangle((4, 4, size - 4, size - 4), radius=12, fill=(17, 17, 17, 255))
            d.rectangle((20, 22, 28, 46), fill=(246, 80, 0, 255))
            d.arc((20, 20, 44, 44), start=180, end=360, fill=(246, 80, 0, 255), width=8)
            d.rectangle((36, 32, 44, 46), fill=(246, 80, 0, 255))
        r = 13
        box = (size - 2 * r - 1, size - 2 * r - 1, size - 1, size - 1)
        d.ellipse(box, fill=(255, 255, 255, 255))
        d.ellipse((box[0] + 3, box[1] + 3, box[2] - 3, box[3] - 3), fill=COLORS[key] + (255,))
        return img

    def _title(self):
        t = ctx.tunnel
        if t.connecting:
            return f"NOBAD — connecting to {t.connecting}…"
        if t.connected:
            return f"NOBAD — connected · {t.active}"
        return "NOBAD — not connected" + (" (kill switch blocking)" if t.ks_active else "")

    # ---- menu
    def _menu(self):
        P = self._pystray
        Item, Menu = P.MenuItem, P.Menu
        t = ctx.tunnel

        def toggle_text(_i):
            return "Disconnect" if (t.connected or t.connecting) else "Connect (last server)"

        def toggle(_icon, _item):
            if t.connected or t.connecting:
                spawn(t.disconnect)
            else:
                target = ctx.settings.get("last_region") or (t.region_names()[0] if t.region_names() else None)
                if target:
                    spawn(t.connect, target)
                elif ctx.windows:
                    ctx.windows.show_main()

        def servers():
            for r in t._regions:
                n = r["name"]
                yield Item(n, (lambda name: lambda _i, _m: spawn(t.connect, name))(n),
                           checked=(lambda name: lambda _i: t.connected and t.active == name)(n), radio=True)

        def ks_toggle(_i, _m):
            spawn(t.set_kill_switch, not ctx.settings.get("kill_switch"))

        return Menu(
            Item("Quick view", lambda _i, _m: ctx.windows and ctx.windows.toggle_mini(), default=True),
            Item("Open NOBAD", lambda _i, _m: ctx.windows and ctx.windows.show_main()),
            Menu.SEPARATOR,
            Item(toggle_text, toggle),
            Item("Connect to", Menu(servers)),
            Item("Fastest server", lambda _i, _m: spawn(t.fastest)),
            Item("Smart pick", lambda _i, _m: spawn(t.smart_connect)),
            Item("Kill switch", ks_toggle, checked=lambda _i: bool(ctx.settings.get("kill_switch"))),
            Menu.SEPARATOR,
            Item("Restore internet (panic reset)", lambda _i, _m: spawn(t.panic_reset)),
            Item("Repair network (quick)", lambda _i, _m: self._quick_repair()),
            Item("Quit (VPN keeps running)", lambda _i, _m: request_quit(False)),
            Item("Disconnect and quit", lambda _i, _m: request_quit(True)))

    # ---- lifecycle
    def start(self):
        if not self.available or self.icon is not None:
            return self.icon is not None
        try:
            key = _state_key()
            self.icon = self._pystray.Icon("NobadVPN", self._image(key), self._title(), self._menu())
            self._last_key = key
            self.icon.run_detached()
            return True
        except Exception as e:
            log(f"tray icon unavailable: {e}", "warn")
            self.available = False
            self.icon = None
            return False

    def stop(self):
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None

    def apply_setting(self):
        if ctx.settings.get("tray"):
            self.start()
        else:
            self.stop()

    def refresh(self):
        if self.icon is None:
            return
        key = _state_key()
        try:
            if key != self._last_key:
                self.icon.icon = self._image(key)
                self._last_key = key
            self.icon.title = self._title()[:127]
            self.icon.update_menu()
        except Exception:
            pass

    def _quick_repair(self):
        """Tray twin of `--repair-network quick`: reachable even when the window won't open."""
        from . import netrepair
        from .logbus import broadcast
        from .syscmd import run_once

        def work():
            broadcast("net_repair_start", {"level": "quick"})
            res = netrepair.repair("quick", panic=ctx.tunnel.panic_reset)
            broadcast("net_repair_done", res)
            bad = [st["step"] for st in res.get("steps", []) if not st.get("ok")]
            self.notify("Network repaired" if res.get("ok") else "Repair finished with problems",
                        "Open NOBAD for the step-by-step result." if not bad else "Failed: " + ", ".join(bad[:3]))
        if not run_once("net_repair", work):   # same lock as the in-app buttons
            self.notify("Network repair", "A network repair is already running.")

    def notify(self, title, msg):
        if self.icon is None:
            return False
        try:
            self.icon.notify(msg[:250], title[:60])
            return True
        except Exception:
            return False
